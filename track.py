#!/usr/bin/env python3
"""Track Bluesky followers and record who unfollows, and when.

Uses Bluesky's public API (no login or password needed). Each run:
  1. downloads the current follower list,
  2. compares it with the last saved snapshot (data/followers.json),
  3. appends anyone who has gone to UNFOLLOWS.md and data/events.csv,
  4. saves the new snapshot.

Followers are tracked by their permanent account ID (DID), so someone
changing their handle is not mistaken for an unfollow.
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HANDLE = os.environ.get("BSKY_HANDLE", "sixtytwomike.bsky.social")
API = os.environ.get("BSKY_API", "https://public.api.bsky.app/xrpc")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SNAPSHOT = DATA / "followers.json"
EVENTS = DATA / "events.csv"
LOG = ROOT / "UNFOLLOWS.md"
# The workflow turns this file into a GitHub issue (which emails you).
NOTICE = Path(os.environ.get("NOTICE_FILE", ROOT / "notice.md"))

LOG_HEADER = (
    "# Bluesky unfollows\n\n"
    f"Accounts that stopped following @{HANDLE}, newest at the bottom.\n\n"
    "| Detected (UTC) | Account | Name | Had followed since | What happened |\n"
    "|---|---|---|---|---|\n"
)


def get(endpoint, params, retries=4):
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "follower-tracker"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as err:
            # 400 = the account genuinely can't be found; don't retry that.
            if err.code == 400 or attempt == retries - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
        time.sleep(2 ** attempt * 2)


def fetch_followers():
    followers, cursor = {}, None
    while True:
        params = {"actor": HANDLE, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = get("app.bsky.graph.getFollowers", params)
        for f in page.get("followers", []):
            followers[f["did"]] = {
                "handle": f.get("handle", ""),
                "name": f.get("displayName") or "",
            }
        # Bluesky can return short or even empty pages while more remain,
        # so only stop when the cursor runs out (or stops moving).
        next_cursor = page.get("cursor")
        if not next_cursor or next_cursor == cursor:
            return followers
        cursor = next_cursor


def why_gone(did):
    """Tell a real unfollow apart from an account that no longer exists."""
    try:
        get("app.bsky.actor.getProfile", {"actor": did})
        return "Unfollowed (or blocked you)"
    except urllib.error.HTTPError as err:
        if err.code == 400:
            return "Account deleted, deactivated or suspended"
        return "Unfollowed (account status could not be checked)"
    except Exception:
        return "Unfollowed (account status could not be checked)"


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    DATA.mkdir(exist_ok=True)
    if NOTICE.exists():
        NOTICE.unlink()

    current = fetch_followers()
    try:
        profile = get("app.bsky.actor.getProfile", {"actor": HANDLE})
    except Exception:
        profile = {}
    (DATA / "status.json").write_text(
        json.dumps(
            {
                "checked_utc": now,
                "handle": profile.get("handle", HANDLE),
                "did": profile.get("did"),
                "name": profile.get("displayName"),
                "count_on_profile": profile.get("followersCount"),
                "followers_listed": len(current),
            },
            indent=1,
        )
        + "\n"
    )

    if not SNAPSHOT.exists():
        snapshot = {
            did: {**info, "first_seen": None} for did, info in current.items()
        }
        SNAPSHOT.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")
        if not LOG.exists():
            LOG.write_text(LOG_HEADER)
        print(f"Baseline saved: {len(current)} followers for @{HANDLE}.")
        return

    previous = json.loads(SNAPSHOT.read_text())

    # Safety net: a half-failed download must not look like a mass unfollow.
    if len(previous) >= 20 and len(current) < len(previous) * 0.5:
        sys.exit(
            f"Follower list dropped from {len(previous)} to {len(current)} in one "
            "run - treating this as a bad download and changing nothing."
        )

    lost = [d for d in previous if d not in current]
    gained = [d for d in current if d not in previous]

    rows = []
    for did in lost:
        old = previous[did]
        rows.append(
            {
                "detected_utc": now,
                "event": "unfollow",
                "did": did,
                "handle": old.get("handle", ""),
                "name": old.get("name", ""),
                "since": old.get("first_seen") or "before tracking began",
                "detail": why_gone(did),
            }
        )
    for did in gained:
        rows.append(
            {
                "detected_utc": now,
                "event": "follow",
                "did": did,
                "handle": current[did]["handle"],
                "name": current[did]["name"],
                "since": "",
                "detail": "",
            }
        )

    if rows:
        new_file = not EVENTS.exists()
        with EVENTS.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            if new_file:
                writer.writeheader()
            writer.writerows(rows)

    unfollows = [r for r in rows if r["event"] == "unfollow"]
    if unfollows:
        if not LOG.exists():
            LOG.write_text(LOG_HEADER)
        with LOG.open("a") as fh:
            for r in unfollows:
                fh.write(
                    f"| {r['detected_utc']} "
                    f"| [@{cell(r['handle'])}](https://bsky.app/profile/{r['did']}) "
                    f"| {cell(r['name'])} | {cell(r['since'])} | {cell(r['detail'])} |\n"
                )
        lines = [
            f"- **@{r['handle']}**"
            + (f" ({r['name']})" if r["name"] else "")
            + f" - {r['detail']}. Had followed since: {r['since']}. "
            + f"https://bsky.app/profile/{r['did']}"
            for r in unfollows
        ]
        NOTICE.write_text(
            f"Detected {now} UTC. You now have {len(current)} followers.\n\n"
            + "\n".join(lines)
            + "\n"
        )

    snapshot = {}
    for did, info in current.items():
        first_seen = previous[did].get("first_seen") if did in previous else now
        snapshot[did] = {**info, "first_seen": first_seen}
    SNAPSHOT.write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")

    print(
        f"@{HANDLE}: {len(current)} followers, "
        f"{len(gained)} new, {len(unfollows)} gone."
    )


if __name__ == "__main__":
    main()
