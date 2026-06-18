from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


MOJIBAKE_MARKERS = ("Ã", "Â", "â", "ã", "æ", "å", "ï", "�")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")
HEADING_RE = re.compile(r"^(#{1,4}\s+|[A-Z][A-Z0-9 ,/&()'-]{8,}|[0-9]+[.)]\s+[A-Z])")


def read_review_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def read_text(root: Path, row: dict[str, str]) -> str:
    text_path = row.get("text_path", "").strip()
    if not text_path:
        return ""
    path = root / text_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def ratio(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 6)


def line_stats(text: str) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return {
            "line_count": 0,
            "avg_line_chars": 0,
            "duplicate_line_ratio": 0.0,
            "long_line_count": 0,
            "heading_count": 0,
            "table_like_line_count": 0,
        }
    counts = Counter(lines)
    duplicate_lines = sum(count - 1 for count in counts.values() if count > 1)
    return {
        "line_count": len(lines),
        "avg_line_chars": round(sum(len(line) for line in lines) / len(lines), 1),
        "duplicate_line_ratio": ratio(duplicate_lines, len(lines)),
        "long_line_count": sum(1 for line in lines if len(line) > 240),
        "heading_count": sum(1 for line in lines if HEADING_RE.search(line)),
        "table_like_line_count": sum(1 for line in lines if line.count("|") >= 2 or line.count("\t") >= 2),
    }


def text_metrics(text: str) -> dict[str, Any]:
    chars = len(text)
    words = WORD_RE.findall(text)
    mojibake_hits = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    replacement_hits = text.count("\ufffd")
    non_ascii = sum(1 for char in text if ord(char) > 127)
    alpha = sum(1 for char in text if char.isalpha())
    digits = sum(1 for char in text if char.isdigit())
    urls = len(re.findall(r"https?://|www\.", text, flags=re.I))
    emails = len(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text))
    metrics = {
        "text_chars": chars,
        "word_count": len(words),
        "unique_word_count": len({word.lower() for word in words}),
        "alpha_ratio": ratio(alpha, chars),
        "digit_ratio": ratio(digits, chars),
        "non_ascii_ratio": ratio(non_ascii, chars),
        "mojibake_hits": mojibake_hits,
        "mojibake_rate": ratio(mojibake_hits + replacement_hits, max(1, chars / 1000)),
        "url_count": urls,
        "email_count": emails,
    }
    metrics.update(line_stats(text))
    return metrics


def quality_flags(row: dict[str, str], metrics: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    detected_type = row.get("detected_type", "")
    status = row.get("status", "")
    qa_flags = row.get("qa_flags", "")
    chars = safe_int(row.get("chars"))
    chunks = safe_int(row.get("chunks"))
    size_bytes = safe_int(row.get("size_bytes"))
    summary = row.get("summary", "").strip()

    if row.get("decision") != "include":
        flags.append("not_included")
    if status != "ok":
        flags.append(f"extract_status_{status or 'unknown'}")
    if "ready" not in qa_flags:
        flags.append("review_flagged")
    if not metrics["text_chars"]:
        flags.append("missing_extracted_text")
    if detected_type == "pdf" and size_bytes > 100_000 and metrics["text_chars"] < 800:
        flags.append("likely_scanned_pdf_or_bad_pdf_extract")
    if detected_type in {"image", "legacy_office"}:
        flags.append(f"manual_review_{detected_type}")
    if chars and abs(chars - metrics["text_chars"]) > max(500, chars * 0.1):
        flags.append("review_char_count_mismatch")
    if metrics["text_chars"] and metrics["word_count"] < 80:
        flags.append("low_word_count")
    if metrics["mojibake_rate"] >= 4:
        flags.append("high_mojibake")
    if metrics["duplicate_line_ratio"] >= 0.25:
        flags.append("high_duplicate_lines")
    if metrics["avg_line_chars"] > 180:
        flags.append("very_long_lines")
    if chunks >= 40:
        flags.append("very_many_chunks")
    if summary_needs_work(summary, row.get("path", "")):
        flags.append("weak_summary")
    return flags


def summary_needs_work(summary: str, path: str) -> bool:
    if len(summary) < 35:
        return True
    lowered = summary.lower()
    weak_markers = [
        "and i just wanted",
        "speaking in foreign language",
        "student-facing material titled",
        "student-facing material about",
        "contents 1.",
    ]
    if any(marker in lowered for marker in weak_markers):
        return True
    title_words = {word.lower() for word in WORD_RE.findall(Path(path).stem)}
    summary_words = {word.lower() for word in WORD_RE.findall(summary)}
    return bool(title_words and len(title_words & summary_words) == 0 and len(summary_words) < 14)


def quality_score(flags: list[str], metrics: dict[str, Any]) -> int:
    score = 100
    penalties = {
        "missing_extracted_text": 60,
        "likely_scanned_pdf_or_bad_pdf_extract": 45,
        "extract_status_": 35,
        "manual_review_": 25,
        "high_mojibake": 25,
        "low_word_count": 20,
        "high_duplicate_lines": 12,
        "very_long_lines": 10,
        "weak_summary": 10,
        "review_flagged": 8,
        "very_many_chunks": 5,
    }
    for flag in flags:
        for prefix, penalty in penalties.items():
            if flag.startswith(prefix):
                score -= penalty
                break
    if metrics.get("heading_count", 0) == 0 and metrics.get("text_chars", 0) > 5000:
        score -= 5
    return max(0, min(100, score))


def audit_row(root: Path, row: dict[str, str]) -> dict[str, Any]:
    text = read_text(root, row)
    metrics = text_metrics(text)
    flags = quality_flags(row, metrics)
    score = quality_score(flags, metrics)
    return {
        "quality_score": score,
        "flags": ";".join(flags) or "ready",
        "decision": row.get("decision", ""),
        "source": row.get("source", ""),
        "path": row.get("path", ""),
        "detected_type": row.get("detected_type", ""),
        "status": row.get("status", ""),
        "qa_flags": row.get("qa_flags", ""),
        "summary": row.get("summary", ""),
        "chunks": row.get("chunks", ""),
        "chars": row.get("chars", ""),
        "size_bytes": row.get("size_bytes", ""),
        "text_path": row.get("text_path", ""),
        **metrics,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    total = len(rows)
    included = sum(1 for row in rows if row["decision"] == "include")
    weak = [row for row in rows if int(row["quality_score"]) < 75]
    flag_counts = Counter(
        flag
        for row in rows
        for flag in str(row["flags"]).split(";")
        if flag and flag != "ready"
    )
    lines = [
        "# Corpus Health Report",
        "",
        f"- Files reviewed: {total}",
        f"- Included files: {included}",
        f"- Files scoring below 75: {len(weak)}",
        f"- Average quality score: {round(sum(int(row['quality_score']) for row in rows) / max(1, total), 1)}",
        "",
        "## Top Flags",
    ]
    if flag_counts:
        for flag, count in flag_counts.most_common(12):
            lines.append(f"- {flag}: {count}")
    else:
        lines.append("- No quality flags found.")

    lines.extend(["", "## Lowest Scoring Files"])
    for row in sorted(rows, key=lambda item: int(item["quality_score"]))[:15]:
        lines.append(f"- `{row['path']}` - score {row['quality_score']} - {row['flags']}")

    lines.extend(["", "## Weak Or Missing Summaries"])
    summary_rows = [row for row in rows if "weak_summary" in str(row["flags"]).split(";")]
    if summary_rows:
        for row in summary_rows[:20]:
            lines.append(f"- `{row['path']}` - {row['summary']}")
    else:
        lines.append("- No weak summaries flagged.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit extracted corpus text for RAG readiness.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--review", default="data/corpus/review/corpus-review.csv")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    review_path = (root / args.review).resolve()
    rows = [audit_row(root, row) for row in read_review_rows(review_path)]
    rows.sort(key=lambda row: (int(row["quality_score"]), row["path"]))

    out_dir = root / "data" / "corpus" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    csv_path = out_dir / f"corpus-health-{stamp}.csv"
    md_path = out_dir / f"corpus-health-{stamp}.md"
    write_csv(csv_path, rows)
    write_markdown(md_path, rows)

    print(f"Files audited: {len(rows)}")
    print(f"Average score: {round(sum(int(row['quality_score']) for row in rows) / max(1, len(rows)), 1)}")
    print(f"Below 75: {sum(1 for row in rows if int(row['quality_score']) < 75)}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
