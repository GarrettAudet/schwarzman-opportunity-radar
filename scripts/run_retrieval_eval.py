from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schwarzman_qa.agents import answer_with_agents, retrieval_query_for  # noqa: E402
from schwarzman_qa.retrieval import document_candidates, load_index, retrieve  # noqa: E402


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            case = json.loads(stripped)
            case["_line"] = line_number
            cases.append(case)
    return cases


def matches_expected(ref: str, expected: list[str]) -> bool:
    lowered = ref.lower()
    return any(needle.lower() in lowered for needle in expected)


def first_rank(refs: list[str], expected: list[str]) -> int:
    for index, ref in enumerate(refs, start=1):
        if matches_expected(ref, expected):
            return index
    return 0


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    total = len(rows)
    top1 = sum(1 for row in rows if row["top1"])
    top3 = sum(1 for row in rows if row["top3"])
    top5 = sum(1 for row in rows if row["top5"])
    summary_top5 = sum(1 for row in rows if row["summary_top5"])
    by_category: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        category = row["category"] or "uncategorized"
        by_category[category]["cases"] += 1
        by_category[category]["top1"] += int(bool(row["top1"]))
        by_category[category]["top3"] += int(bool(row["top3"]))
        by_category[category]["top5"] += int(bool(row["top5"]))

    lines = [
        "# Retrieval Eval Summary",
        "",
        f"- Cases: {total}",
        f"- Top-1 source hit: {top1}/{total}",
        f"- Top-3 source hit: {top3}/{total}",
        f"- Top-5 source hit: {top5}/{total}",
        f"- Document-summary top-5 hit: {summary_top5}/{total}",
        "",
        "## By Category",
    ]
    for category, counts in sorted(by_category.items()):
        cases = counts["cases"]
        lines.append(
            f"- {category}: top1 {counts['top1']}/{cases}, top3 {counts['top3']}/{cases}, top5 {counts['top5']}/{cases}"
        )

    failures = [row for row in rows if not row["top5"]]
    lines.extend(["", "## Top-5 Misses"])
    if failures:
        for row in failures:
            lines.append(
                f"- `{row['id']}`: {row['question']} | expected {row['expected']} | top `{row['top_ref']}` | summary rank {row['summary_rank'] or 'miss'}"
            )
    else:
        lines.append("- No top-5 misses.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate_case(root: Path, index: dict[str, Any], case: dict[str, Any], top_k: int) -> dict[str, Any]:
    raw_question = str(case["question"])
    query = retrieval_query_for(raw_question)
    expected = list(case.get("expected_source_contains", []))
    retrieval_mode = str(case.get("retrieval_mode", "direct"))
    if retrieval_mode == "agent":
        agent_result = answer_with_agents(root, raw_question, index_data=index, top_k=top_k, retrieval_only=True)
        results = list(agent_result.get("retrieval", {}).get("results", []))
        docs = list(agent_result.get("retrieval", {}).get("document_candidates", []))
    else:
        results = retrieve(index, query, top_k=top_k)
        docs = document_candidates(index, query, top_k=top_k)
    refs = [str(item.get("citation_ref") or item.get("source_file") or "") for item in results]
    doc_refs = [str(item.get("citation_ref") or item.get("source_file") or "") for item in docs]
    rank = first_rank(refs, expected)
    summary_rank = first_rank(doc_refs, expected)
    return {
        "id": case.get("id", ""),
        "category": case.get("category", ""),
        "question": raw_question,
        "query": query,
        "retrieval_mode": retrieval_mode,
        "expected": " | ".join(expected),
        "rank": rank,
        "top1": rank == 1,
        "top3": bool(rank and rank <= 3),
        "top5": bool(rank and rank <= 5),
        "summary_rank": summary_rank,
        "summary_top5": bool(summary_rank and summary_rank <= 5),
        "top_score": results[0].get("score", 0) if results else 0,
        "top_ref": refs[0] if refs else "",
        "top_sources": " || ".join(refs[:5]),
        "summary_top_ref": doc_refs[0] if doc_refs else "",
        "summary_top_sources": " || ".join(doc_refs[:5]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval source-ranking quality.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--cases", default="data/evals/retrieval_questions.jsonl")
    parser.add_argument("--index", default="", help="Optional local index JSON path")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="Comma-separated case IDs")
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cases = load_cases((root / args.cases).resolve())
    if args.ids:
        wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
        cases = [case for case in cases if case.get("id") in wanted]
    if args.limit:
        cases = cases[: args.limit]
    index = load_index(root, Path(args.index).resolve() if args.index else None)

    rows = []
    for number, case in enumerate(cases, start=1):
        row = evaluate_case(root, index, case, args.top_k)
        rows.append(row)
        status = "PASS" if row["top5"] else "FAIL"
        print(f"[{number}/{len(cases)}] {status} {row['id']} rank={row['rank'] or 'miss'} top={row['top_ref']}")

    out_dir = root / "data" / "evals" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    csv_path = out_dir / f"retrieval-eval-{stamp}.csv"
    md_path = out_dir / f"retrieval-eval-{stamp}.md"
    json_path = out_dir / f"retrieval-eval-{stamp}.json"
    write_csv(csv_path, rows)
    write_markdown(md_path, rows)
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    total = len(rows)
    top5 = sum(1 for row in rows if row["top5"])
    top1 = sum(1 for row in rows if row["top1"])
    print()
    print(f"Top-1: {top1}/{total}")
    print(f"Top-5: {top5}/{total}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {md_path}")
    print(f"Wrote {json_path}")
    return 0 if top5 == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
