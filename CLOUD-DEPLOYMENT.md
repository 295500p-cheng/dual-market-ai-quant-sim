# GitHub cloud simulation

This repository runs a simulation-only dual-market research workflow. It does not connect to a broker and cannot place real orders.

## Cloud behavior

- GitHub Actions wakes every 15 minutes on weekdays during the broad A-share and US market window.
- `cloud_schedule.py` runs only the market whose local session is active.
- Stale, missing, test, and high-risk signals cannot create simulated entries.
- Updated ledgers are committed by `github-actions[bot]` so the next run continues the same simulated account.
- The dashboard is deployed with GitHub Pages after each successful market cycle.

## Manual check

Open **Actions > Cloud simulated trading > Run workflow**, leave `auto` selected, and run it. The deployment URL appears in the `github-pages` environment after the job completes.

The schedule is best effort: GitHub may delay scheduled jobs during periods of high load.
