# GitHub cloud simulation

This repository runs a simulation-only dual-market research workflow. It does not connect to a broker and cannot place real orders.

## Cloud behavior

- GitHub Actions wakes every 15 minutes on weekdays during the A-share and US market sessions.
- `cloud_schedule.py` runs only the market whose local session is active.
- Stale, missing, test, and high-risk signals cannot create simulated entries.
- Updated ledgers are committed by `github-actions[bot]` so the next run continues the same simulated account.
- A public repository deploys the dashboard with GitHub Pages after each successful market cycle. A private repository skips Pages so publishing cannot interrupt simulation or notification jobs.
- ServerChan sends simulated fills, one close summary per market day, a manual connection test, and a daily-deduplicated failure alert.
- New entries use fresh quotes (35 minutes or newer), minimum provider coverage, restricted entry windows, two confirmations, and position limits.

## Manual check

Set the repository secret `SERVERCHAN_SENDKEY`, then open **Actions > Cloud simulated trading > Run workflow**. Select `auto`; enable `push_test` for the first run. The deployment URL appears in the `github-pages` environment after the job completes.

The schedule is best effort: GitHub may delay scheduled jobs during periods of high load.
