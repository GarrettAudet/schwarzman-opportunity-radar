from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schwarzman_qa.corpus import latest_file  # noqa: E402


REVIEW_COLUMNS = [
    "decision",
    "drop_reason",
    "notes",
    "source",
    "path",
    "qa_flags",
    "summary",
    "detected_type",
    "status",
    "text_path",
    "chunks",
    "chars",
    "size_bytes",
    "sha256",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in REVIEW_COLUMNS})


def main() -> int:
    parser = argparse.ArgumentParser(description="Append newly scanned corpus files to corpus-review.csv.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--report", default="", help="Optional corpus-file-report JSON path")
    parser.add_argument("--default-decision", default="review", choices=["review", "include", "needs_fix"])
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report_path = Path(args.report).resolve() if args.report else latest_file(root / "data" / "corpus" / "reports", "corpus-file-report-*.json")
    review_path = root / "data" / "corpus" / "review" / "corpus-review.csv"

    report_rows = json.loads(report_path.read_text(encoding="utf-8"))
    existing_rows = read_csv(review_path)
    existing_paths = {row.get("path", "") for row in existing_rows}

    added = 0
    for report_row in report_rows:
        path = str(report_row.get("path", ""))
        if not path or path in existing_paths:
            continue
        decision = args.default_decision
        if report_row.get("status") != "ok" or "not_ready" in str(report_row.get("qa_flags", "")):
            decision = "needs_fix"
        existing_rows.append(
            {
                "decision": decision,
                "drop_reason": "",
                "notes": "",
                "source": str(report_row.get("source", "")),
                "path": path,
                "qa_flags": str(report_row.get("qa_flags", "")),
                "summary": str(report_row.get("summary", "")),
                "detected_type": str(report_row.get("detected_type", "")),
                "status": str(report_row.get("status", "")),
                "text_path": str(report_row.get("text_path", "")),
                "chunks": str(report_row.get("chunks", "")),
                "chars": str(report_row.get("chars", "")),
                "size_bytes": str(report_row.get("size_bytes", "")),
                "sha256": str(report_row.get("sha256", "")),
            }
        )
        existing_paths.add(path)
        added += 1

    existing_rows.sort(key=lambda row: (row.get("source", ""), row.get("path", "")))
    write_csv(review_path, existing_rows)
    print(f"Loaded report: {report_path}")
    print(f"Updated review CSV: {review_path}")
    print(f"Added rows: {added}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
