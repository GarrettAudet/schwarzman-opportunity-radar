from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schwarzman_qa.agents import answer_with_agents  # noqa: E402


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def source_hit(result: dict, expected: list[str]) -> bool:
    if not expected:
        return True
    refs = [
        str(item.get("citation_ref", "")).lower()
        for item in result.get("retrieval", {}).get("results", [])
    ]
    return any(any(needle.lower() in ref for ref in refs) for needle in expected)


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def classify_pass(
    *,
    llm_enabled: bool,
    response_type: str,
    expected_type: str,
    source_hit_ok: bool,
) -> tuple[bool | None, bool | None, bool]:
    if llm_enabled:
        type_ok = response_type == expected_type
        return source_hit_ok and type_ok, type_ok, True
    if expected_type == "answer":
        type_ok = response_type == "retrieval_only"
        return source_hit_ok and type_ok, type_ok, True
    return None, None, False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 3 eval cases.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--cases", default="evals/resource_qa_eval.jsonl")
    parser.add_argument("--index", default="", help="Optional local index JSON")
    parser.add_argument("--llm", action="store_true", help="Call OpenRouter answer/review agents")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--ids", default="", help="Comma-separated case IDs to run")
    parser.add_argument("--top-k", type=int, default=6)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cases_path = (root / args.cases).resolve()
    index_path = Path(args.index).resolve() if args.index else None
    cases = load_cases(cases_path)
    if args.ids:
        wanted_ids = {item.strip() for item in args.ids.split(",") if item.strip()}
        cases = [case for case in cases if case.get("id") in wanted_ids]
    if args.limit:
        cases = cases[: args.limit]

    out_dir = root / "data" / "evals" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    csv_path = out_dir / f"eval-run-{stamp}.csv"
    json_path = out_dir / f"eval-run-{stamp}.json"

    rows = []
    full_results = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']} {case.get('category', '')}", flush=True)
        result = answer_with_agents(
            root,
            case["question"],
            index_path=index_path,
            top_k=args.top_k,
            retrieval_only=not args.llm,
        )
        expected_sources = case.get("expected_source_contains", [])
        hit = source_hit(result, expected_sources)
        response_type = result.get("response_type", "")
        expected_type = case.get("expected_response_type", "answer")
        passed, type_ok, behavior_checked = classify_pass(
            llm_enabled=args.llm,
            response_type=response_type,
            expected_type=expected_type,
            source_hit_ok=hit,
        )
        rows.append(
            {
                "id": case["id"],
                "category": case.get("category", ""),
                "expected_response_type": expected_type,
                "response_type": response_type,
                "top_score": result.get("retrieval", {}).get("top_score", 0),
                "source_hit": hit,
                "type_ok": "" if type_ok is None else type_ok,
                "behavior_checked": behavior_checked,
                "passed": "" if passed is None else passed,
                "question": case["question"],
                "top_ref": (result.get("retrieval", {}).get("results") or [{}])[0].get("citation_ref", ""),
            }
        )
        full_results.append({"case": case, "result": result, "passed": passed})
        write_csv(csv_path, rows)
        json_path.write_text(json.dumps(full_results, ensure_ascii=False, indent=2), encoding="utf-8")

    source_hits = sum(1 for row in rows if row["source_hit"])
    scored_rows = [row for row in rows if row["passed"] != ""]
    passed_count = sum(1 for row in scored_rows if row["passed"])
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"cases": 0, "source_hits": 0, "scored": 0, "passed": 0})
    for row in rows:
        category = row["category"] or "uncategorized"
        by_category[category]["cases"] += 1
        by_category[category]["source_hits"] += 1 if row["source_hit"] else 0
        if row["passed"] != "":
            by_category[category]["scored"] += 1
            by_category[category]["passed"] += 1 if row["passed"] else 0

    print(f"Cases: {len(rows)}")
    print(f"Retrieval source hits: {source_hits}")
    print(f"Behavior-scored cases: {len(scored_rows)}")
    print(f"Passed: {passed_count}")
    for category, stats in sorted(by_category.items()):
        print(
            f"- {category}: {stats['source_hits']}/{stats['cases']} source hits, "
            f"{stats['passed']}/{stats['scored']} scored passed"
        )
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    return 0 if passed_count == len(scored_rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
