# Rencai Corpus

Local corpus area for the Rencai / 12twenty Resource Library.

Recommended layout:

- `raw/` - authenticated downloaded files, grouped by resource-library folder.
- `manifests/` - inventory, download manifest, and text extraction manifest exports.
- `review/` - allowlist CSVs for deciding what can be used in student-facing tools.
- `text/` - extracted text output, generated from files in `raw/`.

Raw files and generated text are ignored by Git so private/course materials do not get accidentally committed.

## Workflow

1. Run the Chrome extension Rencai scan.
2. Click **Save Corpus** and choose the repository root: `C:\repos\SchwarzmanScholarResources`.
3. Review `data/rencai/review/allowlist-review-*.csv`.
4. Run text extraction after downloads complete:

```powershell
python scripts\extract_rencai_text.py --root .
```
