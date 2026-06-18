# Video Transcripts

Put video transcript files in `raw/`.

Files placed in `raw/` are tagged as video transcript resources in the local
index. That lets the bot answer resource-catalog questions such as "what videos
do we have?" while keeping video transcripts distinct from ordinary Blackboard
or Rencai PDFs/docs.

Supported formats:

- `.txt`
- `.md`
- `.srt`
- `.vtt`
- `.docx`
- `.pdf`

Recommended naming pattern:

```text
YYYY-MM-DD - Session Title - Speaker or Source.vtt
```

After adding transcripts, run:

```powershell
python scripts\build_corpus_qa.py --root .
python scripts\sync_corpus_review.py --root .
```

Then review the new transcript rows in:

```text
data/corpus/review/corpus-review.csv
```

Set `decision` to `include` for transcript files that should be searchable by
the Q&A bot, then rebuild the local index:

```powershell
python scripts\build_local_index.py --root .
```
