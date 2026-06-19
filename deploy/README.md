# Deployment

OpportunityRadar is designed for Render:

- `opportunity-radar-api` exposes `/health`, `/digest/preview`, and `/digest/run`.
- `opportunity-radar-weekly` runs hourly on Mondays and lets the app decide whether the configured local send hour has arrived.

Cron schedules are UTC, so the application-level schedule check avoids DST drift.
