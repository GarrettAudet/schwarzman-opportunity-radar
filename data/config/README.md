# OpportunityRadar Config

Use `discovery.example.json` for the Common Crawl board registry settings, `conditions.example.json` for opportunity filters, and `sources.example.json` only for optional configured-source fallbacks.

For local private work, create `discovery.local.json`, `conditions.local.json`, or `sources.local.json`; they are ignored by Git. In production, store those JSON files in the private state/config repo and point Render at them with `GITHUB_DISCOVERY_PATH`, `GITHUB_CONDITIONS_PATH`, and optionally `GITHUB_SOURCES_PATH`.
