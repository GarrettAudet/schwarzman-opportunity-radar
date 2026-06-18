from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


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

INTAKE_COLUMNS = [
    "intake_status",
    "decision",
    "previous_decision",
    "source",
    "path",
    "qa_status",
    "qa_flags",
    "chunks",
    "chars",
    "sha256",
    "previous_sha256",
    "summary",
    "action",
]

FIX_FLAG_FRAGMENTS = (
    "no_text_extracted",
    "image_needs_ocr",
    "needs_ocr",
    "low_text_review",
    "short_transcript_review",
    "unsupported",
    "legacy",
    "not_ready",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def latest_file(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[0]


def run_step(label: str, command: list[str]) -> None:
    print(f"\n==> {label}", flush=True)
    print(" ".join(command), flush=True)
    subprocess.run(command, check=True)


def needs_fix(report_row: dict[str, Any]) -> bool:
    status = str(report_row.get("status", "")).strip().lower()
    flags = str(report_row.get("qa_flags", "")).strip().lower()
    detected_type = str(report_row.get("detected_type", "")).strip().lower()
    chunks = int_value(report_row.get("chunks"))
    chars = int_value(report_row.get("chars"))
    if status and status != "ok":
        return True
    if chunks <= 0 or chars <= 0:
        return True
    if any(fragment in flags for fragment in FIX_FLAG_FRAGMENTS):
        return True
    if detected_type in {"legacy_office", "image"}:
        return True
    return False


def int_value(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


def default_decision(report_row: dict[str, Any], fallback: str) -> str:
    return "needs_fix" if needs_fix(report_row) else fallback


def review_row_from_report(report_row: dict[str, Any], decision: str, notes: str) -> dict[str, str]:
    return {
        "decision": decision,
        "drop_reason": "",
        "notes": notes,
        "source": str(report_row.get("source", "")),
        "path": str(report_row.get("path", "")),
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


def append_note(existing: str, addition: str) -> str:
    existing = existing.strip()
    if not existing:
        return addition
    if addition in existing:
        return existing
    return f"{existing} | {addition}"


def update_review_from_report(
    root: Path,
    report_rows: list[dict[str, Any]],
    default_ready_decision: str,
    preserve_changed_decisions: bool,
    dry_run: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]], Path]:
    review_path = root / "data" / "corpus" / "review" / "corpus-review.csv"
    existing_rows = read_csv(review_path)
    existing_by_path = {row.get("path", ""): row for row in existing_rows if row.get("path")}
    report_by_path = {str(row.get("path", "")): row for row in report_rows if row.get("path")}
    intake_rows: list[dict[str, str]] = []
    stamp = datetime.now().strftime("%Y-%m-%d")

    for path in sorted(report_by_path):
        report_row = report_by_path[path]
        existing = existing_by_path.get(path)
        if existing is None:
            decision = default_decision(report_row, default_ready_decision)
            action = "Fix extraction before inclusion." if decision == "needs_fix" else "Review row, then set decision to include or summarize_only."
            note = f"Intake {stamp}: new file detected; {action}"
            new_row = review_row_from_report(report_row, decision=decision, notes=note)
            existing_rows.append(new_row)
            existing_by_path[path] = new_row
            intake_rows.append(
                intake_row("new", new_row, previous_decision="", previous_sha="", action=action)
            )
            continue

        old_sha = str(existing.get("sha256", "")).strip()
        new_sha = str(report_row.get("sha256", "")).strip()
        if old_sha and new_sha and old_sha == new_sha:
            continue

        previous_decision = str(existing.get("decision", "")).strip()
        if preserve_changed_decisions:
            decision = previous_decision or default_decision(report_row, default_ready_decision)
            action = "Metadata refreshed; decision preserved."
        else:
            decision = default_decision(report_row, default_ready_decision)
            if previous_decision == "drop":
                decision = "drop"
                action = "Content changed, but previous drop decision was preserved."
            elif decision == "needs_fix":
                action = "Content changed and extraction needs fixing before inclusion."
            else:
                action = "Content changed; review row again before inclusion."

        updated = review_row_from_report(
            report_row,
            decision=decision,
            notes=append_note(
                str(existing.get("notes", "")),
                f"Intake {stamp}: content changed; previous decision was {previous_decision or 'blank'}.",
            ),
        )
        existing.update(updated)
        intake_rows.append(
            intake_row(
                "changed",
                existing,
                previous_decision=previous_decision,
                previous_sha=old_sha,
                action=action,
            )
        )

    missing_paths = sorted(set(existing_by_path) - set(report_by_path))
    for path in missing_paths:
        existing = existing_by_path[path]
        intake_rows.append(
            {
                "intake_status": "missing_from_sources",
                "decision": str(existing.get("decision", "")),
                "previous_decision": str(existing.get("decision", "")),
                "source": str(existing.get("source", "")),
                "path": path,
                "qa_status": str(existing.get("status", "")),
                "qa_flags": str(existing.get("qa_flags", "")),
                "chunks": str(existing.get("chunks", "")),
                "chars": str(existing.get("chars", "")),
                "sha256": "",
                "previous_sha256": str(existing.get("sha256", "")),
                "summary": str(existing.get("summary", "")),
                "action": "Review row if this source was intentionally removed.",
            }
        )

    existing_rows.sort(key=lambda row: (row.get("source", ""), row.get("path", "")))
    if not dry_run:
        write_csv(review_path, existing_rows, REVIEW_COLUMNS)
    return existing_rows, intake_rows, review_path


def intake_row(
    status: str,
    row: dict[str, str],
    previous_decision: str,
    previous_sha: str,
    action: str,
) -> dict[str, str]:
    return {
        "intake_status": status,
        "decision": str(row.get("decision", "")),
        "previous_decision": previous_decision,
        "source": str(row.get("source", "")),
        "path": str(row.get("path", "")),
        "qa_status": str(row.get("status", "")),
        "qa_flags": str(row.get("qa_flags", "")),
        "chunks": str(row.get("chunks", "")),
        "chars": str(row.get("chars", "")),
        "sha256": str(row.get("sha256", "")),
        "previous_sha256": previous_sha,
        "summary": str(row.get("summary", "")),
        "action": action,
    }


def write_intake_report(
    root: Path,
    intake_rows: list[dict[str, str]],
    report_path: Path,
    review_path: Path,
    dry_run: bool,
) -> tuple[Path, Path]:
    reports_dir = root / "data" / "corpus" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    csv_path = reports_dir / f"corpus-intake-{stamp}.csv"
    md_path = reports_dir / f"corpus-intake-{stamp}.md"

    counts = count_by_status(intake_rows)
    lines = [
        "# Corpus Intake Report",
        "",
        f"- Generated: {stamp}",
        f"- Source report: `{report_path}`",
        f"- Review CSV: `{review_path}`",
        f"- Dry run: {'yes' if dry_run else 'no'}",
        "",
        "## Summary",
        "",
    ]
    for status in ("new", "changed", "missing_from_sources"):
        lines.append(f"- {status}: {counts.get(status, 0)}")
    fix_rows = [row for row in intake_rows if row.get("decision") == "needs_fix"]
    review_rows = [row for row in intake_rows if row.get("decision") == "review"]
    lines.extend(
        [
            f"- needs_fix decisions: {len(fix_rows)}",
            f"- review decisions: {len(review_rows)}",
            "",
            "## Action Items",
            "",
        ]
    )
    if not intake_rows:
        lines.append("- No new, changed, or missing source files detected.")
    else:
        for row in intake_rows[:80]:
            lines.append(
                f"- `{row['path']}` - {row['intake_status']}; decision `{row['decision']}`; {row['action']}"
            )
        if len(intake_rows) > 80:
            lines.append(f"- ...and {len(intake_rows) - 80} more rows in the CSV report.")

    write_csv(csv_path, intake_rows, INTAKE_COLUMNS)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def count_by_status(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = row.get("intake_status", "")
        counts[status] = counts.get(status, 0) + 1
    return counts


def load_report(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected list in report: {path}")
    return [row for row in data if isinstance(row, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect new/changed corpus files, rebuild extraction outputs, and prepare review-gated intake reports."
    )
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--skip-build", action="store_true", help="Use the latest corpus-file-report JSON without rebuilding")
    parser.add_argument("--report", default="", help="Specific corpus-file-report JSON to ingest")
    parser.add_argument("--ocr", action="store_true", help="Pass --ocr to build_corpus_qa.py")
    parser.add_argument("--dry-run", action="store_true", help="Write intake report but do not update corpus-review.csv")
    parser.add_argument(
        "--default-ready-decision",
        default="review",
        choices=["review", "include", "needs_fix"],
        help="Decision for new or changed files whose extraction looks healthy",
    )
    parser.add_argument(
        "--preserve-changed-decisions",
        action="store_true",
        help="Keep existing decisions when file content hashes change",
    )
    parser.add_argument("--skip-audit", action="store_true", help="Do not run audit_corpus_quality.py after intake")
    parser.add_argument("--build-index", action="store_true", help="Build a local index after intake")
    parser.add_argument("--run-retrieval-eval", action="store_true", help="Run retrieval eval after index build")
    parser.add_argument("--run-whatsapp-smoke", action="store_true", help="Run WhatsApp smoke test after index build")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    python = sys.executable

    if not args.skip_build and not args.report:
        build_command = [python, str(root / "scripts" / "build_corpus_qa.py"), "--root", str(root)]
        if args.ocr:
            build_command.append("--ocr")
        run_step("Build corpus QA outputs", build_command)

    report_path = (
        Path(args.report).resolve()
        if args.report
        else latest_file(root / "data" / "corpus" / "reports", "corpus-file-report-*.json")
    )
    report_rows = load_report(report_path)
    _review_rows, intake_rows, review_path = update_review_from_report(
        root=root,
        report_rows=report_rows,
        default_ready_decision=args.default_ready_decision,
        preserve_changed_decisions=args.preserve_changed_decisions,
        dry_run=args.dry_run,
    )
    intake_csv, intake_md = write_intake_report(root, intake_rows, report_path, review_path, args.dry_run)

    if not args.skip_audit and not args.dry_run:
        run_step("Audit corpus quality", [python, str(root / "scripts" / "audit_corpus_quality.py"), "--root", str(root)])

    if args.build_index:
        run_step("Build local index", [python, str(root / "scripts" / "build_local_index.py"), "--root", str(root)])
        if args.run_retrieval_eval:
            run_step("Run retrieval eval", [python, str(root / "scripts" / "run_retrieval_eval.py"), "--root", str(root)])
        if args.run_whatsapp_smoke:
            run_step("Run WhatsApp smoke", [python, str(root / "scripts" / "run_whatsapp_smoke.py"), "--root", str(root)])

    counts = count_by_status(intake_rows)
    print("\n==> Intake complete")
    print(f"Source report: {report_path}")
    print(f"Review CSV: {review_path}")
    print(f"New: {counts.get('new', 0)}")
    print(f"Changed: {counts.get('changed', 0)}")
    print(f"Missing from sources: {counts.get('missing_from_sources', 0)}")
    print(f"Wrote {intake_csv}")
    print(f"Wrote {intake_md}")
    if not intake_rows:
        print("No review action needed.")
    else:
        print("Review the intake report and corpus-review.csv before rebuilding/uploading the deploy index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
