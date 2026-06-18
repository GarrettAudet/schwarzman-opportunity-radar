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

Recommended update workflow:

1. Create a local working branch, especially if you are also changing prompts,
   scripts, or review policy:

   ```powershell
   git checkout -b corpus/update-YYYY-MM-DD
   ```

2. Add new student-facing files to `data/blackboard`,
   `data/rencai/raw`, or `data/transcripts/raw`.
3. Rebuild and sync the local review sheet:

   ```powershell
   python scripts\build_corpus_qa.py --root .
   python scripts\sync_corpus_review.py --root .
   ```

4. Review `data/corpus/review/corpus-review.csv`. Set new trusted rows to
   `include` or `summarize_only`; leave questionable files as `review`,
   `needs_fix`, or `drop`.
5. Audit extraction quality before indexing:

   ```powershell
   python scripts\audit_corpus_quality.py --root .
   ```

   Open the newest report in `data/corpus/reports/`. Fix or exclude files
   flagged for empty extraction, scanned PDFs, unsupported legacy Office
   formats, weak summaries, or obvious text corruption.
6. Rebuild the index and smoke-test retrieval:

   ```powershell
   python scripts\build_local_index.py --root .
   python scripts\ask_corpus.py --root . --retrieval-only "What documents do I need for the X1 visa?"
   ```

7. Run the retrieval and WhatsApp behavior gates:

   ```powershell
   python scripts\run_retrieval_eval.py --root .
   python scripts\run_whatsapp_smoke.py --root .
   ```

   For a smaller live-model check before deploy:

   ```powershell
   python scripts\run_whatsapp_smoke.py --root . --llm --ids international_scholars_webinar,todo_current,x1_visa_docs,residence_permits,mandarin_resources,cover_letter_resources,sector_nonprofit,unsupported_housing,prompt_injection
   ```

8. Upload the latest generated index to the private index repo:

   ```powershell
   $env:GITHUB_INDEX_UPLOAD_TOKEN = "<fine-grained GitHub token with Contents read/write access>"
   python scripts\upload_index_to_github.py --root .
   ```

   The upload script copies the latest `data/corpus/index/local-index-*.json`
   to `deploy/index/local-index.json`, then uploads it to the private
   `GarrettAudet/SchwarzmanQnA-Index` repo as `local-index.json`.
9. Redeploy or restart Render so the service reloads the updated index.

The raw source files, extracted text, chunks, review CSV, and deploy index are
ignored in this app repo. Keep them local or in private storage; do not push
student-resource content to the public app repo.

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

`audit_corpus_quality.py` reads the reviewed corpus sheet and scores each file
for RAG readiness. It is designed to catch problems that make answers bad even
when retrieval code is working: scanned PDFs with no text, legacy `.doc` files
that were not converted, corrupted extraction, duplicated boilerplate, very
thin text, and weak summaries. Its reports are local generated artifacts and
are ignored by git.

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
writes a timestamped index under `data/corpus/index`. For deployment, upload
the latest generated index to the private index repo:

```powershell
$env:GITHUB_INDEX_UPLOAD_TOKEN = "<fine-grained GitHub token with Contents read/write access>"
python scripts\upload_index_to_github.py --root .
```

By default, `upload_index_to_github.py` uploads to
`GarrettAudet/SchwarzmanQnA-Index` as `local-index.json` on `main`. It also
refreshes `deploy/index/local-index.json` from the newest timestamped index.
You can override the destination with `GITHUB_INDEX_REPO`, `GITHUB_INDEX_PATH`,
`GITHUB_INDEX_REF`, or CLI flags. The script does not load `.env`; set the
token in your shell when you run the upload.

User-facing citations are source-relative document paths, such as
`blackboard/OBTAINING YOUR X1 STUDENT VISA 2026.pdf` or
`rencai/Job Search/example.pdf`. Internal `data/` prefixes and `#chunk=`
fragments are not shown in answers.

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

Run the targeted retrieval suite when you want to know whether search is finding
the expected documents:

```powershell
python scripts\run_retrieval_eval.py --root .
```

This suite checks top-1, top-3, and top-5 source matches for diverse questions
across visas, residence permits, To-Do items, webinars, career resources,
language programs, tests, transcripts, and intentionally unsupported questions.
It also records document-summary candidates so weak chunk retrieval can be
diagnosed separately from weak corpus structure.

Run the WhatsApp-style behavior smoke test before deploy:

```powershell
python scripts\run_whatsapp_smoke.py --root .
```

For a representative live-model gate through OpenRouter:

```powershell
python scripts\run_whatsapp_smoke.py --root . --llm --ids international_scholars_webinar,todo_current,x1_visa_docs,residence_permits,mandarin_resources,cover_letter_resources,sector_nonprofit,unsupported_housing,prompt_injection
```

The answer path uses normal RAG first. If chunk search is weak but document
titles, paths, and one-line summaries point strongly to likely files, the
backend uses those document candidates to broaden retrieval and try again. The
model still answers from retrieved chunks with citations; summaries are a
retrieval aid, not standalone evidence.

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
- `POST /ask/stream` - same request shape as `/ask`, but streams progress
  events and a final answer payload as Server-Sent Events.

Test the hosted streaming endpoint:

```powershell
python scripts\query_backend.py --url https://schwarzmanqna.onrender.com/ask --stream "What documents do I need for the X1 student visa?"
```

For WhatsApp, use these stream events as internal progress states. WhatsApp
itself usually sends complete messages rather than token-by-token edits, so the
integration should send the final cited answer when the `final` event arrives.

## WhatsApp Access Control

The recommended group-limited flow is password enrollment:

1. Post a password in the student WhatsApp group.
2. Students DM the bot with that password once.
3. The bot stores their `wa_id`, phone number, display name, and approval status.
4. Future questions are answered only for approved users.
5. Blocked users are denied even if they previously enrolled.

Local access-control data lives in `data/whatsapp/access-control.json`, which is
ignored by git because it contains phone numbers. For Render, do not rely only
on the free instance filesystem for this file. Use static env allow/block lists
for small pilots, or use the private GitHub-backed JSON store described in
`data/whatsapp/README.md`.

For the hosted bot, the private GitHub access store should be the source of
truth for WhatsApp identities, approval status, block status, feedback, and
failed/not-found/out-of-scope question logs. The webhook checks that store
before answering every message.

Useful env vars:

```text
WHATSAPP_PASSWORD=<password posted in the group, preferred user-facing name>
WHATSAPP_INVITE_CODE=<legacy env name; still supported if WHATSAPP_PASSWORD is unset>
WHATSAPP_VERIFY_TOKEN=<random string pasted into Meta webhook setup>
WHATSAPP_ACCESS_TOKEN=<Meta WhatsApp Cloud API access token>
WHATSAPP_PHONE_NUMBER_ID=<Meta WhatsApp phone number ID>
WHATSAPP_APP_SECRET=<optional Meta app secret for webhook signature checks>
WHATSAPP_GRAPH_API_VERSION=v23.0
WHATSAPP_ALLOWED_NUMBERS=<optional comma-separated phone allowlist>
WHATSAPP_BLOCKED_NUMBERS=<optional comma-separated phone blocklist>
WHATSAPP_ALLOWED_WA_IDS=<optional comma-separated WhatsApp ID allowlist>
WHATSAPP_BLOCKED_WA_IDS=<optional comma-separated WhatsApp ID blocklist>
GITHUB_ACCESS_REPO=GarrettAudet/SchwarzmanQnA-Index
GITHUB_ACCESS_PATH=whatsapp-access.json
GITHUB_ACCESS_REF=main
GITHUB_ACCESS_TOKEN=<fine-grained token with contents read/write for the private repo>
SCHWARZMAN_API_TOKEN=<optional bearer token for direct /ask API calls>
```

Manage local access data:

```powershell
python scripts\manage_whatsapp_access.py list --root .
python scripts\manage_whatsapp_access.py summary --root .
python scripts\manage_whatsapp_access.py blocked --root .
python scripts\manage_whatsapp_access.py feedback --root . --limit 25
python scripts\manage_whatsapp_access.py failures --root . --limit 25
python scripts\manage_whatsapp_access.py approve --root . --phone 15551234567 --name "Student Name"
python scripts\manage_whatsapp_access.py block --root . --phone 15551234567 --notes "Removed from group"
python scripts\manage_whatsapp_access.py revoke --root . --phone 15551234567
python scripts\manage_whatsapp_access.py remove --root . --phone 15551234567
```

## WhatsApp Webhook

### Twilio Sandbox Path

For the prototype, Twilio is the easiest WhatsApp transport. In Twilio Console,
use the WhatsApp Sandbox first.

Render env vars:

```text
TWILIO_ACCOUNT_SID=<from Twilio Console>
TWILIO_AUTH_TOKEN=<from Twilio Console>
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_VALIDATE_SIGNATURE=true
TWILIO_WEBHOOK_URL=https://schwarzmanqna.onrender.com/webhooks/twilio/whatsapp
WHATSAPP_PASSWORD=<password students send after joining the sandbox>
```

In Twilio's WhatsApp Sandbox settings, set:

```text
When a message comes in:
https://schwarzmanqna.onrender.com/webhooks/twilio/whatsapp

Method:
POST
```

To test, join your Twilio Sandbox from your personal WhatsApp by sending the
`join ...` message Twilio shows in the Sandbox screen. Then send your
`WHATSAPP_PASSWORD`. Once approved, send a resource question.

Twilio webhook signature validation is enabled by default. Keep
`TWILIO_WEBHOOK_URL` exactly equal to the URL configured in Twilio so signature
checks match.

### Meta Cloud API Path

After adding the WhatsApp env vars and redeploying Render, configure Meta's
WhatsApp webhook with:

```text
Callback URL: https://schwarzmanqna.onrender.com/webhooks/whatsapp
Verify token: the exact value of WHATSAPP_VERIFY_TOKEN
```

Subscribe to WhatsApp message webhooks. Incoming DMs follow this flow:

1. Unknown users are asked for the group password.
2. A correct password approves and stores their WhatsApp identity.
3. Approved users can ask questions, send `/help`, or send `/feedback <text>`.
4. Failed, not-found, out-of-scope, and feedback messages are logged in the
   private access store for admin review.
5. The bot calls the Q&A agent, then sends the final cited answer.
6. Blocked users are denied even if they enrolled earlier.

## Phase 5: Online Backend

For a real public URL, use a private GitHub repo connected to Render.

This repo includes:

- `render.yaml` - Render web service blueprint.
- `requirements.txt` - compatibility file for Render's default Python build command.
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

If you create a Web Service manually instead of using the blueprint, use:

```text
Build Command: python -m pip install -r requirements.txt
Start Command: python scripts/serve_backend.py --root . --host 0.0.0.0
```

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
