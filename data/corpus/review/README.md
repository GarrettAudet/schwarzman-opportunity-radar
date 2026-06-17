# Corpus Review

Edit `corpus-review.csv` when deciding what the WhatsApp Q&A bot should use.

Suggested `decision` values:

- `include` - OK to use in the bot.
- `drop` - exclude entirely.
- `summarize_only` - OK to use for high-level summaries, but avoid verbatim detail.
- `needs_fix` - keep out until OCR, conversion, renaming, or manual cleanup is done.
- `review` - not decided yet.

Use `drop_reason` and `notes` for quick context, such as `not useful`,
`sensitive`, `duplicate`, `bad extraction`, or `image only`.
