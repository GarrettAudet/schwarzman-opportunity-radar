# Video Transcripts

Put video transcript files in `raw/`.

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
```

Then review the new transcript rows in:

```text
data/corpus/review/corpus-review.csv
```

Set `decision` to `include` for transcript files that should be searchable by
the Q&A bot, then rebuild the local index.
