# Schwarzman Scholar Resources

A small local toolkit for inventorying and saving authenticated Schwarzman/Rencai/Blackboard resources into a local reviewable corpus.

It does not ask for credentials, run a backend, or upload data. The scan runs locally in the extension side panel using your existing browser session.

## Load It

1. Open Chrome and go to `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select this folder: `C:\repos\SchwarzmanScholarResources`.
5. Open one of your Rencai or Blackboard tabs and make sure you are logged in.
6. Click the extension icon, then click **Use Active Tab** and **Start Scan**.

## Suggested Scans

- **Blackboard**: use **Same host** scope with a higher max page count.
- **Rencai / one section only**: use **URL prefix** scope, set **Scan method** to **Rendered active tab**, paste the section root as the allowed prefix, and use a lower max page count.

## Outputs

- **CSV**: spreadsheet-friendly inventory of discovered resources.
- **JSON**: full inventory plus crawl metadata and scanned page log.
- **Save Corpus**: writes authenticated Rencai downloads into `data/rencai/raw`, plus manifests and a review CSV.

For Rencai, click **Save Corpus** after a successful scan and choose the repo root:

`C:\repos\SchwarzmanScholarResources`

The extension creates:

- `data/rencai/raw/...` - downloaded files grouped by source folder.
- `data/rencai/manifests/...` - inventory and download manifests.
- `data/rencai/review/...` - allowlist review CSV.
- `data/rencai/text/...` - extracted text output from the Python script.

## Adding Resources To The Corpus

Put source files in one of these folders:

- `data/blackboard` - Blackboard PDFs, docs, spreadsheets, and other manually downloaded files.
- `data/rencai/raw` - files saved by the extension's **Save Corpus** button.
- `data/transcripts/raw` - video transcripts, including `.txt`, `.md`, `.srt`, `.vtt`, `.docx`, and `.pdf`.

Then run from the repo root:

```powershell
python -m pip install -r requirements-corpus.txt
python scripts\build_corpus_qa.py --root .
python scripts\sync_corpus_review.py --root .
```

`build_corpus_qa.py` recursively scans the source folders, extracts normalized
text, creates search chunks, writes one-line file summaries, and flags files
that may need manual attention. It writes generated outputs under:

- `data/corpus/text` - extracted text grouped by source.
- `data/corpus/chunks` - timestamped chunk JSONL files for search/RAG.
- `data/corpus/reports` - timestamped QA reports and file summaries.

`sync_corpus_review.py` reads the latest QA report and appends newly discovered
files to `data/corpus/review/corpus-review.csv`. It preserves existing review
decisions. New rows default to `review`, while files with extraction problems
default to `needs_fix`.

Review `data/corpus/review/corpus-review.csv` before indexing. Set `decision`
to `include` for files the Q&A bot can answer from, or `summarize_only` for
files that should be available as context but treated cautiously. Rows left as
`review`, `needs_fix`, or `drop` are excluded from the searchable index.

After review, rebuild the local retrieval index:

```powershell
python scripts\build_local_index.py --root .
```

The index builder uses the latest chunk file plus your review CSV decisions and
writes a timestamped index under `data/corpus/index`. For deployment, copy the
latest generated index to the fixed Render filename:

```powershell
Copy-Item (Get-ChildItem data\corpus\index\local-index-*.json | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName deploy\index\local-index.json -Force
```

Answering rules for the eventual WhatsApp bot live in
`docs/answering-policy.md`.
The broader agent architecture and rollout plan live in
`docs/whatsapp-qa-agent-design.md`.

## Phase 2: Local Q&A Prototype

Build a reviewed local retrieval index:

```powershell
python scripts\build_local_index.py --root .
```

Ask a retrieval-only question without calling OpenRouter:

```powershell
python scripts\ask_corpus.py --root . --retrieval-only "What documents do I need for the X1 student visa?"
```

Ask with the two-agent OpenRouter flow:

```powershell
python scripts\ask_corpus.py --root . "What documents do I need for the X1 student visa?"
```

The default drafter model is `deepseek/deepseek-v4-flash`.
The default reviewer model is `google/gemini-3.5-flash`.
Set `OPENROUTER_API_KEY` in `.env`, and optionally override models with:

```powershell
$env:OPENROUTER_ANSWER_MODEL = "deepseek/deepseek-v4-flash"
$env:OPENROUTER_REVIEW_MODEL = "google/gemini-3.5-flash"
```

## Phase 3: Eval Harness

Run retrieval-only evals:

```powershell
python scripts\run_eval.py --root .
```

Run full two-agent evals through OpenRouter:

```powershell
python scripts\run_eval.py --root . --llm
```

Eval outputs are written to `data/evals/runs/`. Retrieval-only mode checks
whether the right sources are found. Full `--llm` mode also checks answer type,
prompt-injection handling, refusal behavior, and citation formatting.

## Phase 4: Local Backend

Run a free local HTTP backend:

```powershell
python scripts\serve_backend.py --root . --host 127.0.0.1 --port 8765
```

Check health:

```powershell
Invoke-RestMethod http://127.0.0.1:8765/health
```

Ask through the backend from the terminal:

```powershell
python scripts\query_backend.py "Can internships in China be paid?"
```

Fast retrieval-only test:

```powershell
python scripts\query_backend.py --retrieval-only "What documents do I need for the X1 visa?"
```

The backend exposes:

- `GET /health` - confirms the loaded index and chunk count.
- `POST /ask` - accepts JSON with `question`, optional `top_k`, optional
  `retrieval_only`, and returns the answer, response type, latency, guardrail
  summary, and cited source refs.

## Phase 5: Online Backend

For a real public URL, use a private GitHub repo connected to Render.

This repo includes:

- `render.yaml` - Render web service blueprint.
- `requirements-backend.txt` - backend build requirements.

Important: the reviewed corpus index contains extracted student-resource text,
so it is intentionally not committed to the code repo. Keep `.env` private too.
The recommended setup is a separate private GitHub repo named
`SchwarzmanQnA-Index` that contains only `local-index.json`.

Render setup:

1. Create a private GitHub repo.
2. Push this project.
3. In Render, create a new Blueprint or Web Service from that private repo.
4. Use the included `render.yaml`.
5. Create private repo `GarrettAudet/SchwarzmanQnA-Index` and upload
   `deploy/index/local-index.json` there as `local-index.json`.
6. Create a fine-grained GitHub token with read-only Contents access to that
   private index repo.
7. Add `OPENROUTER_API_KEY` and `GITHUB_INDEX_TOKEN` in Render's environment
   variables.
8. Test `https://<service>.onrender.com/health`.

The older Rencai-only extractor is still available:

```powershell
python scripts\extract_rencai_text.py --root .
```

## Notes

- The crawler stays on the same host as the seed URL.
- URL prefix scope limits what pages are crawled, while still inventorying resources linked from those pages.
- Rendered active tab mode is for JavaScript-heavy sites like 12twenty/Rencai. It navigates the active tab through nested folder links and reads the rendered DOM.
- It skips obvious logout, gradebook, submit, delete, quiz/attempt, and API URLs.
- Rencai downloads are saved only when you click **Save Corpus** and approve a local folder.
- Keep exports private until you have reviewed them for sensitive or restricted material.
