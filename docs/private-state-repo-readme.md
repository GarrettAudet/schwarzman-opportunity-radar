# OpportunityRadar Private State Repo

This private repo stores runtime configuration and durable send state for the deployed OpportunityRadar service.

## Files

- `discovery.json` - Common Crawl registry and board-polling limits.
- `sources.json` - optional configured source fallback.
- `conditions.json` - posting recency, target locations, role groups, exclude terms, and years-of-experience rules.
- `opportunity-state.json` - board registry, seen jobs, sent weeks, source cache headers, and recent run summaries.
- `opportunity-criteria.md` - optional private override for the ranking criteria.

## Runtime Environment

```text
GITHUB_STATE_REPO=<owner/private-repo>
GITHUB_STATE_PATH=opportunity-state.json
GITHUB_STATE_REF=main
GITHUB_STATE_TOKEN=<fine-grained contents read/write token>
GITHUB_DISCOVERY_PATH=discovery.json
GITHUB_SOURCES_PATH=<optional sources.json>
GITHUB_CONDITIONS_PATH=conditions.json
OPPORTUNITY_RECIPIENTS=whatsapp:+15551234567
OPPORTUNITY_TIMEZONE=America/Edmonton
OPPORTUNITY_SEND_DOW=MON
OPPORTUNITY_SEND_HOUR=9
OPENROUTER_API_KEY=<openrouter key>
TWILIO_ACCOUNT_SID=<twilio sid>
TWILIO_AUTH_TOKEN=<twilio token>
TWILIO_WHATSAPP_FROM=whatsapp:+15551234567
TWILIO_WHATSAPP_CONTENT_SID=<optional approved template content sid>
TWILIO_MESSAGING_SERVICE_SID=<optional messaging service sid>
```

Use `TWILIO_WHATSAPP_CONTENT_SID` for proactive notifications outside the WhatsApp customer-service window. If `TWILIO_MESSAGING_SERVICE_SID` is set with the template SID, `TWILIO_WHATSAPP_FROM` is optional; otherwise configure `TWILIO_WHATSAPP_FROM` with the approved WhatsApp sender.

## GitHub Actions Scheduler

The scheduler workflow maps GitHub secrets and variables into the runtime environment above. Use these repository secrets:

```text
OPPORTUNITY_STATE_REPO=<owner/private-state-repo>
OPPORTUNITY_STATE_TOKEN=<fine-grained contents read/write token>
OPPORTUNITY_RECIPIENTS=whatsapp:+15551234567
OPENROUTER_API_KEY=<capped OpenRouter key>
TWILIO_ACCOUNT_SID=<twilio sid>
TWILIO_AUTH_TOKEN=<twilio token>
TWILIO_WHATSAPP_FROM=whatsapp:+15551234567
TWILIO_WHATSAPP_CONTENT_SID=<optional approved template content sid>
TWILIO_MESSAGING_SERVICE_SID=<optional messaging service sid>
```

Use these repository variables for non-secret settings:

```text
OPPORTUNITY_SCHEDULER_ENABLED=false
OPPORTUNITY_TIMEZONE=America/Edmonton
OPPORTUNITY_SEND_DOW=MON
OPPORTUNITY_SEND_HOUR=9
OPPORTUNITY_MAX_JOBS=10
```

Before enabling the weekly sender, run:

```powershell
python scripts\check_send_ready.py --root .
```
