# Deployment

OpportunityRadar's default deployment is free/spend-capped first:

- Render runs only the free `opportunity-radar-api` web service from `render.yaml`.
- GitHub Actions runs the registry refresh, daily discovery, and weekly digest schedule from `.github/workflows/opportunity-radar-schedule.yml`.
- Scheduled GitHub Actions runs are disabled until `OPPORTUNITY_SCHEDULER_ENABLED=true` is set as a repository variable.

The weekly schedule is UTC, so the application-level `--respect-schedule` check avoids DST drift.

Manual GitHub workflow tasks:

- `all-preview` refreshes registry, runs discovery, and previews the weekly digest without sending.
- `weekly-send` sends from evaluated state and should be used first with a test recipient.

See `docs/cost-controls.md` before enabling scheduled sends.
