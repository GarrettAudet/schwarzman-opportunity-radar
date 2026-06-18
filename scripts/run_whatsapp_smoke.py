from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schwarzman_qa.agents import answer_with_agents  # noqa: E402
from schwarzman_qa.policy import format_chat_answer  # noqa: E402

GLOBAL_ANSWER_MUST_NOT_CONTAIN = [
    "downloaded",
    "Got it",
    "reviewed resources now",
    "in,,",
    "in, ,",
    "â",
    "ã",
    "Ã",
    "æ",
    "å",
]


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            case = json.loads(stripped)
            case["_line"] = line_number
            cases.append(case)
    return cases


def contains_any(haystack: str, needles: list[str]) -> bool:
    if not needles:
        return True
    lowered = haystack.lower()
    return any(needle.lower() in lowered for needle in needles)


def contains_none(haystack: str, needles: list[str]) -> bool:
    lowered = haystack.lower()
    return all(needle.lower() not in lowered for needle in needles)


def source_hit(result: dict[str, Any], expected_sources: list[str]) -> bool:
    if not expected_sources:
        return True
    refs = []
    for item in result.get("retrieval", {}).get("results", []):
        refs.append(str(item.get("citation_ref", "")))
        refs.append(str(item.get("source_file", "")))
        refs.append(str(item.get("source_title", "")))
    source_text = "\n".join(refs)
    return contains_any(source_text, expected_sources)


def expected_type_ok(response_type: str, expected: str, llm: bool) -> bool:
    if response_type == expected:
        return True
    if not llm and expected == "answer" and response_type == "retrieval_only":
        return True
    return False


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = [
        "id",
        "category",
        "passed",
        "response_type",
        "expected_response_type",
        "top_score",
        "top_source",
        "type_ok",
        "source_ok",
        "must_contain_ok",
        "must_not_contain_ok",
        "elapsed_ms",
        "question",
        "answer_preview",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run WhatsApp bot smoke questions against the local agent.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--cases", default="data/evals/whatsapp_smoke_questions.jsonl")
    parser.add_argument("--index", default="", help="Optional local index JSON path")
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
        wanted_ids = {case_id.strip() for case_id in args.ids.split(",") if case_id.strip()}
        cases = [case for case in cases if case.get("id") in wanted_ids]
    if args.limit:
        cases = cases[: args.limit]

    out_dir = root / "data" / "evals" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    csv_path = out_dir / f"whatsapp-smoke-{stamp}.csv"
    json_path = out_dir / f"whatsapp-smoke-{stamp}.json"

    rows: list[dict[str, Any]] = []
    full_results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']} - {case['question']}", flush=True)
        started = time.perf_counter()
        result = answer_with_agents(
            root,
            str(case["question"]),
            index_path=index_path,
            top_k=args.top_k,
            retrieval_only=not args.llm,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        answer = format_chat_answer(str(result.get("final_answer", "")))
        response_type = str(result.get("response_type", ""))
        expected_response_type = str(case.get("expected_response_type", "answer"))
        top_results = result.get("retrieval", {}).get("results", [])
        top_source = ""
        if top_results:
            first = top_results[0]
            top_source = str(first.get("citation_ref") or first.get("source_file") or first.get("source_title") or "")

        type_ok = expected_type_ok(response_type, expected_response_type, args.llm)
        source_ok = source_hit(result, list(case.get("expected_source_contains", [])))
        check_answer_text = args.llm or response_type != "retrieval_only"
        must_contain_ok = True
        must_not_contain_ok = True
        if check_answer_text:
            must_contain_ok = contains_any(answer, list(case.get("answer_must_contain", [])))
            forbidden_strings = GLOBAL_ANSWER_MUST_NOT_CONTAIN + list(case.get("answer_must_not_contain", []))
            must_not_contain_ok = contains_none(answer, forbidden_strings)
        passed = type_ok and source_ok and must_contain_ok and must_not_contain_ok

        row = {
            "id": case["id"],
            "category": case.get("category", ""),
            "passed": passed,
            "response_type": response_type,
            "expected_response_type": expected_response_type,
            "top_score": result.get("retrieval", {}).get("top_score", 0),
            "top_source": top_source,
            "type_ok": type_ok,
            "source_ok": source_ok,
            "must_contain_ok": must_contain_ok,
            "must_not_contain_ok": must_not_contain_ok,
            "elapsed_ms": elapsed_ms,
            "question": case["question"],
            "answer_preview": answer[:500].replace("\n", " "),
        }
        rows.append(row)
        full_results.append({"case": case, "result": result, "formatted_answer": answer, "row": row})
        write_csv(csv_path, rows)
        json_path.write_text(json.dumps(full_results, ensure_ascii=False, indent=2), encoding="utf-8")

        status = "PASS" if passed else "FAIL"
        print(f"  {status} type={response_type} score={row['top_score']} top={top_source}", flush=True)

    passed_count = sum(1 for row in rows if row["passed"])
    print()
    print(f"Passed {passed_count}/{len(rows)}")
    failures = [row for row in rows if not row["passed"]]
    if failures:
        print("Failures:")
        for row in failures:
            reasons = []
            if not row["type_ok"]:
                reasons.append("type")
            if not row["source_ok"]:
                reasons.append("source")
            if not row["must_contain_ok"]:
                reasons.append("must_contain")
            if not row["must_not_contain_ok"]:
                reasons.append("must_not_contain")
            print(f"- {row['id']}: {', '.join(reasons)} | type={row['response_type']} | top={row['top_source']}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {json_path}")
    return 0 if passed_count == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
