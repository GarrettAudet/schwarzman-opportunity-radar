# Corpus QA Outputs

Generated text, chunks, and reports live here.

- `text/` - extracted text files, grouped by source.
- `chunks/` - JSONL chunks ready for search/RAG indexing. Each chunk
  includes `source_file`, `source_title`, and `citation_ref` for answer
  citations.
- `reports/` - file-level extraction QA, flags, and one-line summaries.
- `review/` - human include/drop decisions for the WhatsApp Q&A corpus.

Run from the repository root:

```powershell
python scripts\build_corpus_qa.py --root .
python scripts\sync_corpus_review.py --root .
```

Generated outputs can contain material copied from student-facing documents, so
they should be reviewed before being committed, hosted, or wired into WhatsApp.

Use `review/corpus-review.csv` as the human decision log. Edit the `decision`
column rather than editing timestamped files in `reports/`.
