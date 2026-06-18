# SchwarzmanQnA-Index

Private storage for the deployed Schwarzman Q&A bot.

This repo should stay private because `local-index.json` contains extracted text
from student-facing Blackboard, Rencai, and transcript resources. The public app
repo contains code only.

## Files

- `local-index.json` - reviewed retrieval index consumed by Render.
- `whatsapp-access.json` - optional WhatsApp access store with approved users,
  blocked users, feedback, failed questions, answered questions, and short
  conversation memory.
- `README.md` - this operator runbook.

## Update Corpus

From the public app repo on your machine:

```powershell
cd C:\repos\SchwarzmanScholarResources
python scripts\ingest_corpus_updates.py --root . --build-index --run-retrieval-eval --run-whatsapp-smoke
```

Review:

```powershell
data\corpus\reports\corpus-intake-*.md
data\corpus\review\corpus-review.csv
```

Only rows marked `include` or `summarize_only` are added to the deployable
index. Leave questionable files as `review`, `needs_fix`, or `drop`.

## Production Gate

Run this before deploying code or a new index:

```powershell
python scripts\run_production_gate.py --root .
```

Fast iteration:

```powershell
python scripts\run_production_gate.py --root . --quick
```

Optional live-model subset:

```powershell
python scripts\run_production_gate.py --root . --llm
```

Reports are written under:

```text
data/evals/runs/production-gate-*.md
data/evals/runs/production-gate-*.json
```

## Upload Index

Use a fine-grained GitHub token with Contents read/write access to this private
repo:

```powershell
$env:GITHUB_INDEX_UPLOAD_TOKEN = "<token>"
python scripts\upload_index_to_github.py --root . --upload-readme
```

The script copies the newest generated `data/corpus/index/local-index-*.json`
to `deploy/index/local-index.json`, uploads it here as `local-index.json`, and
optionally uploads this README.

Dry run:

```powershell
python scripts\upload_index_to_github.py --root . --dry-run --upload-readme
```

## Render Environment

The web service reads the index from this repo with:

```text
GITHUB_INDEX_REPO=GarrettAudet/SchwarzmanQnA-Index
GITHUB_INDEX_PATH=local-index.json
GITHUB_INDEX_REF=main
GITHUB_INDEX_TOKEN=<read-only contents token>
```

For the private WhatsApp access store:

```text
GITHUB_ACCESS_REPO=GarrettAudet/SchwarzmanQnA-Index
GITHUB_ACCESS_PATH=whatsapp-access.json
GITHUB_ACCESS_REF=main
GITHUB_ACCESS_TOKEN=<contents read/write token>
```

Admin commands are available only to numbers or WhatsApp IDs listed in:

```text
WHATSAPP_ADMIN_NUMBERS=<comma-separated phone numbers>
WHATSAPP_ADMIN_WA_IDS=<comma-separated wa_ids>
```

## WhatsApp Admin Commands

From an approved admin WhatsApp account:

```text
/status
/users
/failed
/answers
/feedback
/blocked
/approve <number>
/block <number>
/unblock <number>
```

Normal users can still send:

```text
/help
/resources
/feedback <suggestion>
```

## Access Store CLI

Local inspection:

```powershell
python scripts\manage_whatsapp_access.py summary --root .
python scripts\manage_whatsapp_access.py list --root .
python scripts\manage_whatsapp_access.py failures --root . --limit 25
python scripts\manage_whatsapp_access.py answers --root . --limit 25
python scripts\manage_whatsapp_access.py feedback --root . --limit 25
```

Manual moderation:

```powershell
python scripts\manage_whatsapp_access.py approve --root . --phone 15551234567 --name "Student Name"
python scripts\manage_whatsapp_access.py block --root . --phone 15551234567 --notes "Removed from group"
python scripts\manage_whatsapp_access.py revoke --root . --phone 15551234567
python scripts\manage_whatsapp_access.py remove --root . --phone 15551234567
```

## Deploy Checklist

1. Add new files to `data/blackboard`, `data/rencai/raw`, or
   `data/transcripts/raw`.
2. Run corpus intake and review `corpus-review.csv`.
3. Run `python scripts\run_production_gate.py --root .`.
4. Upload the index with `python scripts\upload_index_to_github.py --root .`.
5. Restart or redeploy Render.
6. Test `/health`, `/resources`, one visa question, one webinar comparison, and
   one admin `/status` command.
