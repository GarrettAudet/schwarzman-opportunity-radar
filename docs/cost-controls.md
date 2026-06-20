# Cost Controls

OpportunityRadar defaults to services that are free, have explicit budget controls, or are disabled until you opt in. Do not enable a live sender or scheduled LLM ranking until each account-level control below is configured.

## Default Cost Posture

- Render runs only the free `opportunity-radar-api` web service from `render.yaml`.
- Render cron jobs are not part of the default Blueprint because Render cron services have a minimum monthly charge.
- GitHub Actions owns scheduled registry refresh, daily discovery, and weekly digest runs in `.github/workflows/opportunity-radar-schedule.yml`.
- Scheduled GitHub Actions runs are disabled until the repository variable `OPPORTUNITY_SCHEDULER_ENABLED` is set to `true`.
- Common Crawl registry lookups and public Greenhouse board APIs are free public data sources.
- Google CSE is optional. Leave it disabled unless you intentionally configure its free quota and caps.

## Service Controls

### Render

Use the default `render.yaml` only. It creates a free web service for manual previews and protected `/digest/*` routes.

Do not add Render cron services unless you are intentionally accepting Render cron billing. The GitHub Actions scheduler exists so the normal path does not need them.

### GitHub Actions

Use standard Linux GitHub-hosted runners only. Public repositories have free standard runner usage; private repositories consume included monthly minutes and can be governed by GitHub budgets.

Set `OPPORTUNITY_SCHEDULER_ENABLED=false` or leave it unset until secrets, budget settings, and Twilio/OpenRouter controls are ready. Manual workflow dispatch still works for previews and smoke tests.

### OpenRouter

Use an OpenRouter API key with a credit limit. OpportunityRadar filters by date, city, role signals, and years of experience before calling the ranker, but the API key limit is the hard account-side backstop.

Recommended starting point:

- Use a low-cost model such as `openai/gpt-4.1-mini` or another approved capped model.
- Set the key limit low for the first month.
- Keep `OPPORTUNITY_MAX_JOBS` small until the registry size and ranking volume look stable.

### Twilio

Twilio is the only live outbound messaging provider in the current setup. Before setting `OPPORTUNITY_SCHEDULER_ENABLED=true`, configure Twilio-side billing protection available on the account and keep recipient lists explicit.

OpportunityRadar also limits blast radius in-app:

- It sends only to `OPPORTUNITY_RECIPIENTS`.
- It sends from evaluated state and marks sent weeks idempotently.
- It checks Twilio send readiness before live scheduled sends.
- It limits digest size with `OPPORTUNITY_MAX_JOBS`.

If Twilio account-level controls are not acceptable for your budget policy, keep the weekly job in preview mode and add a different sender behind the existing sender interface.

## Go-Live Checklist

1. Deploy the default free Render web service from `render.yaml`.
2. Configure GitHub Actions budgets or rely on free public-repo standard runner usage.
3. Create a capped OpenRouter API key and store it as `OPENROUTER_API_KEY`.
4. Configure Twilio billing controls, approved WhatsApp template settings, and a small explicit `OPPORTUNITY_RECIPIENTS` list.
5. Run the GitHub workflow manually with `all-preview`.
6. Run the GitHub workflow manually with `weekly-send` to a test recipient.
7. Set repository variable `OPPORTUNITY_SCHEDULER_ENABLED=true` only after the test send works.
