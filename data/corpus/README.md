# Corpus QA Outputs

Generated text, chunks, and reports live here.

- `text/` - extracted text files, grouped by source.
- `chunks/` - JSONL chunks ready for search/RAG indexing. Each chunk
  includes `source_file`, `source_title`, and `citation_ref` for answer
  citations.
- `reports/` - file-level extraction QA, flags, and one-line summaries.
- `review/` - human include/drop decisions for the WhatsApp Q&A corpus.

Source files are read from:

- `../blackboard`
- `../rencai/raw`
- `../transcripts/raw`

Run from the repository root:

```powershell
python scripts\build_corpus_qa.py --root .
python scripts\sync_corpus_review.py --root .
```

`build_corpus_qa.py` scans the source folders recursively and creates fresh,
timestamped outputs in `text/`, `chunks/`, and `reports/`. It does not approve
files for the bot by itself.

`sync_corpus_review.py` reads the latest `reports/corpus-file-report-*.json`
and appends newly discovered files to `review/corpus-review.csv`. Existing rows
and decisions are kept, so you can rerun it after adding more files without
losing prior review work.

Generated outputs can contain material copied from student-facing documents, so
they should be reviewed before being committed, hosted, or wired into WhatsApp.

Use `review/corpus-review.csv` as the human decision log. Edit the `decision`
column rather than editing timestamped files in `reports/`. Rows marked
`include` or `summarize_only` are eligible for the retrieval index; rows left as
`review`, `needs_fix`, or `drop` are excluded.
