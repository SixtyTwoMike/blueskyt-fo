# Bluesky follower tracker

Checks who follows `sixtytwomike.bsky.social` every 6 hours and records anyone who stops.

- **UNFOLLOWS.md** - readable log of who left and when it was detected.
- **data/events.csv** - every follow and unfollow, for sorting or filtering.
- **data/followers.json** - the latest snapshot the next run compares against.
- When someone unfollows, the workflow opens a GitHub issue, so GitHub emails you (and notifies the GitHub mobile app).

## Things to know

- No Bluesky password is used; the follower list is public.
- "When" is accurate to the check interval: an unfollow is dated to the run that first noticed it.
- An account that was deleted, deactivated or suspended is labelled as such rather than as an unfollow.
- A block looks the same as an unfollow from the outside.
- To change the handle or the frequency, edit `.github/workflows/track.yml`.
- To run a check immediately: Actions tab > Track Bluesky followers > Run workflow.
