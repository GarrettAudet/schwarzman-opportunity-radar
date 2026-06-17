# Eval Runs

Generated eval run outputs live in `runs/` and are ignored by Git.

Use `scripts/run_eval.py --root .` for retrieval-only checks. This confirms
that answerable questions retrieve the expected reviewed source files without
spending OpenRouter tokens.

Use `scripts/run_eval.py --root . --llm` for the full two-agent behavior check.
That mode calls the drafter and reviewer models, so it can evaluate answer type,
citations, prompt-injection handling, and refusal behavior.
