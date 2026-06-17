from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_DECISIONS = {"include", "summarize_only"}


@dataclass(frozen=True)
class ReviewDecision:
    decision: str
    drop_reason: str = ""
    notes: str = ""
    qa_flags: str = ""
    summary: str = ""


def latest_file(directory: Path, pattern: str) -> Path:
    files = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"No files matching {pattern} in {directory}")
    return files[0]


def load_review_decisions(root: Path) -> dict[str, ReviewDecision]:
    path = root / "data" / "corpus" / "review" / "corpus-review.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing review file: {path}")

    decisions: dict[str, ReviewDecision] = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            decision = (row.get("decision") or "").strip().lower()
            corpus_path = (row.get("path") or "").strip()
            if not corpus_path:
                continue
            decisions[corpus_path] = ReviewDecision(
                decision=decision,
                drop_reason=row.get("drop_reason", ""),
                notes=row.get("notes", ""),
                qa_flags=row.get("qa_flags", ""),
                summary=row.get("summary", ""),
            )
    return decisions


def load_chunks(root: Path, chunks_path: Path | None = None) -> list[dict[str, Any]]:
    if chunks_path is None:
        chunks_path = latest_file(root / "data" / "corpus" / "chunks", "corpus-chunks-*.jsonl")
    decisions = load_review_decisions(root)

    chunks: list[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunk = json.loads(line)
            path = chunk.get("source_file") or chunk.get("path")
            review = decisions.get(path)
            if not review or review.decision not in ALLOWED_DECISIONS:
                continue
            enriched = dict(chunk)
            enriched["review_decision"] = review.decision
            enriched["review_notes"] = review.notes
            enriched["qa_flags"] = review.qa_flags
            enriched["file_summary"] = review.summary
            chunks.append(enriched)
    return chunks
