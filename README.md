# OpportunityRadar

OpportunityRadar finds high-signal early-career opportunities for Schwarzman Scholars, ranks them against a human-editable criteria file, and sends a weekly digest by email or WhatsApp.

The production path is intentionally simple: GitHub Actions runs discovery and digest jobs, a private state repo stores durable JSON state, and the public repo keeps the application code, workflow, tests, and docs.

## What It Does

- Discovers public Greenhouse boards from Common Crawl and stores reusable board tokens in state.
- Polls active ATS boards daily, normalizes target-city postings, and filters out noisy roles before ranking.
- Uses `docs/opportunity-criteria.md` plus an LLM ranker to decide which roles belong in the digest.
- Stores evaluated jobs in durable JSON state so the weekly digest can send only unsent included opportunities.
- Sends through Twilio WhatsApp, Gmail SMTP, Gmail API, or Microsoft Graph email.
- Supports Google Groups and Google Sheets-backed recipient lists.
- Provides local scripts, fixture-backed smoke runs, and protected API endpoints for manual checks.

## How It Runs

The app has three scheduled jobs in `.github/workflows/opportunity-radar-schedule.yml`:

| Job | Purpose | Sends messages |
| --- | --- | --- |
| Registry refresh | Finds and stores public ATS board tokens. | No |
| Daily discovery | Polls boards, filters/ranks jobs, and writes evaluated state. | No |
| Weekly digest | Reads unsent included jobs from state and delivers the digest. | Yes, when configured |

Manual workflow tasks behave differently:

| Task | What it does |
| --- | --- |
| `all-preview` | Runs registry, discovery, and a digest preview. It never sends messages. |
| `registry` | Runs only the registry refresh. |
| `discovery` | Runs only daily discovery. |
| `weekly-preview` | Builds the weekly digest from state without sending. |
| `weekly-send` | Checks send readiness, then sends the digest from state. |

A scheduled weekly run sends only when `OPPORTUNITY_SCHEDULER_ENABLED=true` and the runtime schedule guard matches `OPPORTUNITY_TIMEZONE`, `OPPORTUNITY_SEND_DOW`, and `OPPORTUNITY_SEND_HOUR`.

## Architecture

```mermaid
flowchart LR
    A[Weekly/Manual Registry Refresh] --> B[Common Crawl Board Registry]
    B --> C[Private JSON State]
    D[Daily GitHub Actions Scheduler] --> E[Poll Active Greenhouse Boards]
    C <--> E
    E --> F[City + Condition Filters]
    F --> G[LLM Ranker]
    G --> H[Evaluated Jobs in State]
    H <--> C
    I[Weekly GitHub Actions Scheduler] --> J[Digest From Unsent Winners]
    J <--> C
    J --> K[Delivery Sender]
    L[Protected API] --> J
    M[Criteria Markdown] --> G
```

## Production Setup

Use GitHub repository secrets for sensitive values:

```text
OPPORTUNITY_STATE_REPO=<owner/private-state-repo>
OPPORTUNITY_STATE_TOKEN=<fine-grained contents read/write token>
OPPORTUNITY_RECIPIENTS=<destination email, group, or WhatsApp numbers>
OPENROUTER_API_KEY=<capped OpenRouter key>
SMTP_USERNAME=<Gmail SMTP account>
SMTP_APP_PASSWORD=<Gmail app password>
```

Use GitHub repository variables for non-secret settings. This example sends to a Google Group by Gmail SMTP every Wednesday at 09:00 Beijing time:

```text
OPPORTUNITY_SCHEDULER_ENABLED=true
OPPORTUNITY_TIMEZONE=Asia/Shanghai
OPPORTUNITY_SEND_DOW=WED
OPPORTUNITY_SEND_HOUR=9
OPPORTUNITY_SEND_PROVIDER=gmail_smtp
OPPORTUNITY_EMAIL_SUBJECT=Weekly Job Newsletter
OPPORTUNITY_MAX_JOBS=30
OPPORTUNITY_MIN_JOBS=15
OPPORTUNITY_MAX_JOBS_PER_COMPANY=2
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_FROM=Schwarzman Job Updates <schwarzmanjobupdates@gmail.com>
SMTP_USE_STARTTLS=true
```

Keep the GitHub Actions cron aligned with the runtime guard. For Wednesday 09:00 Beijing time, the weekly cron should be:

```yaml
- cron: "0 1 * * WED" # 09:00 Asia/Shanghai
```

and the weekly digest step checks should compare `github.event.schedule` to the same cron string.

## Delivery Providers

### Gmail SMTP to a Google Group

This is the simplest email path when the audience is managed by Google Groups:

```text
OPPORTUNITY_SEND_PROVIDER=gmail_smtp
OPPORTUNITY_RECIPIENTS=schwarzman-job-updates@googlegroups.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=schwarzmanjobupdates@gmail.com
SMTP_APP_PASSWORD=<Google app password>
SMTP_FROM=Schwarzman Job Updates <schwarzmanjobupdates@gmail.com>
SMTP_USE_STARTTLS=true
```

OpportunityRadar sends one email to the group address; Google Groups handles membership.

### Gmail API with a Google Sheet

Use this when a Google Sheet is the recipient source of truth:

```text
OPPORTUNITY_SEND_PROVIDER=gmail_email
GOOGLE_GMAIL_FROM=Schwarzman Job Updates <schwarzmanjobupdates@gmail.com>
GOOGLE_CLIENT_ID=<Google OAuth client id>
GOOGLE_CLIENT_SECRET=<Google OAuth client secret>
GOOGLE_REFRESH_TOKEN=<one-time refresh token>
GOOGLE_RECIPIENTS_SHEET_ID=<spreadsheet id>
GOOGLE_RECIPIENTS_RANGE=Recipients!A:C
```

Run the one-time OAuth flow locally:

```powershell
python scripts\google_auth.py --client-id <client-id> --client-secret <client-secret>
```

The sheet should include `email`, `name`, and optional `status` columns. Rows marked `unsubscribed`, `inactive`, `removed`, or `deleted` are skipped.

### Microsoft Graph Email

```text
OPPORTUNITY_SEND_PROVIDER=microsoft_graph_email
OPPORTUNITY_RECIPIENTS=jobs-list@example.com
MICROSOFT_CLIENT_ID=<app registration client id>
MICROSOFT_REFRESH_TOKEN=<one-time delegated refresh token>
MICROSOFT_TENANT_ID=common
MICROSOFT_GRAPH_BASE_URL=https://graph.microsoft.com/v1.0
MICROSOFT_LOGIN_BASE_URL=https://login.microsoftonline.com
MICROSOFT_USER_ID=<optional user id or email for /users/{id}/sendMail>
MICROSOFT_SAVE_TO_SENT_ITEMS=true
```

Run the one-time OAuth flow locally:

```powershell
python scripts\microsoft_auth.py --client-id <client-id> --tenant common
```

### Twilio WhatsApp

```text
OPPORTUNITY_SEND_PROVIDER=twilio_whatsapp
OPPORTUNITY_RECIPIENTS=whatsapp:+15551234567,whatsapp:+15557654321
TWILIO_ACCOUNT_SID=<sid>
TWILIO_AUTH_TOKEN=<token>
TWILIO_WHATSAPP_FROM=whatsapp:+15551234567
TWILIO_WHATSAPP_CONTENT_SID=<optional approved template sid>
TWILIO_MESSAGING_SERVICE_SID=<optional messaging service sid>
```

For proactive WhatsApp sends, prefer an approved `TWILIO_WHATSAPP_CONTENT_SID` template.

## State And Config Files

Local development reads from files under `data/` by default. Production can read runtime files from a private GitHub state repo.

| File | Purpose |
| --- | --- |
| `data/config/discovery.example.json` | Common Crawl registry and board-polling limits. |
| `data/config/conditions.example.json` | Posting recency, target locations, role groups, exclude terms, and years-of-experience filters. |
| `data/config/sources.example.json` | Optional explicitly configured sources. |
| `docs/opportunity-criteria.md` | Ranking criteria used by the LLM. |
| `data/state/opportunity-state.json` | Local durable state for development runs. |

Production state repo variables can point to private equivalents with `GITHUB_DISCOVERY_PATH`, `GITHUB_CONDITIONS_PATH`, `GITHUB_SOURCES_PATH`, and `GITHUB_STATE_PATH`.

## Local Development

Install dependencies:

```powershell
python -m pip install -r requirements-backend.txt
```

Run fixture-backed discovery without writing state:

```powershell
python scripts\run_discovery.py --root . --sources tests\fixtures\sources.fixture.json --conditions tests\fixtures\conditions.fixture.json --deterministic-fallback --json
```

Preview a fixture-backed weekly digest without spending model tokens:

```powershell
python scripts\run_weekly_digest.py --root . --sources tests\fixtures\sources.fixture.json --deterministic-fallback --include-seen
```

Write evaluated jobs to local state, then preview the digest from state:

```powershell
python scripts\run_discovery.py --root . --sources data\config\sources.greenhouse-smoke.json --conditions data\config\conditions.example.json --deterministic-fallback --write
python scripts\run_weekly_digest.py --root . --from-state
```

Send from evaluated state to configured recipients:

```powershell
python scripts\check_send_ready.py --root .
python scripts\run_weekly_digest.py --root . --send --from-state
```

Run the protected API locally:

```powershell
python scripts\serve_backend.py --root . --host 127.0.0.1 --port 8765
```

Preview through HTTP:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/digest/preview -Headers @{ Authorization = "Bearer $env:OPPORTUNITY_API_TOKEN" } -Body '{"from_state":true}' -ContentType 'application/json'
```

## Verification

Run the production gate before changing scheduling, delivery, or ranking behavior:

```powershell
python scripts\run_production_gate.py --root .
```

The gate compiles Python, runs unit/integration tests, performs fixture-backed registry refresh, exercises dynamic discovery, and runs digest smoke checks.

## Deployment Notes

`render.yaml` defines only the optional free Render web service. It does not create Render cron services because those can require paid cron billing.

Scheduled work is owned by GitHub Actions. Before enabling live sends, run `weekly-send` manually with a test recipient and confirm the delivery provider is ready.

See `docs/cost-controls.md` for budget controls and `docs/private-state-repo-readme.md` for the private state repo layout.
