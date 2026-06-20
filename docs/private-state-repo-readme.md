# OpportunityRadar Private State Repo

This private repo stores runtime configuration and durable send state for the deployed OpportunityRadar service.

## Files

- `sources.json` - job source configuration.
- `conditions.json` - target locations, role groups, exclude terms, and years-of-experience rules.
- `opportunity-state.json` - seen jobs, sent weeks, source cache headers, and recent run summaries.
- `opportunity-criteria.md` - optional private override for the ranking criteria.

## Render Environment

```text
GITHUB_STATE_REPO=<owner/private-repo>
GITHUB_STATE_PATH=opportunity-state.json
GITHUB_STATE_REF=main
GITHUB_STATE_TOKEN=<fine-grained contents read/write token>
GITHUB_SOURCES_PATH=sources.json
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
```

Use `TWILIO_WHATSAPP_CONTENT_SID` for proactive notifications outside the WhatsApp customer-service window.
