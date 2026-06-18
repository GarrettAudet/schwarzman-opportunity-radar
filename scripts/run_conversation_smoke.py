from __future__ import annotations

import argparse
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


GLOBAL_MUST_NOT_CONTAIN = ["downloaded resources", "reviewed resources now"]


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def expected_type_ok(actual: str, expected: str, llm: bool) -> bool:
    if actual == expected:
        return True
    return not llm and expected == "answer" and actual == "retrieval_only"


def contains_all(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return all(needle.lower() in lowered for needle in needles)


def contains_none(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return not any(needle.lower() in lowered for needle in needles)


def source_hit(result: dict[str, Any], expected: list[str]) -> bool:
    if not expected:
        return True
    refs: list[str] = []
    for item in result.get("retrieval", {}).get("results", []):
        refs.append(str(item.get("citation_ref", "")))
        refs.append(str(item.get("source_file", "")))
        refs.append(str(item.get("source_title", "")))
    haystack = "\n".join(refs).lower()
    return all(fragment.lower() in haystack for fragment in expected)


def memory_from_result(question: str, result: dict[str, Any]) -> dict[str, Any]:
    sources: list[dict[str, str]] = []
    seen_refs: set[str] = set()
    for item in result.get("retrieval", {}).get("results", []):
        ref = str(item.get("citation_ref") or item.get("source_file") or "").strip()
        if not ref or ref in seen_refs:
            continue
        seen_refs.add(ref)
        sources.append(
            {
                "citation_ref": ref,
                "source_file": str(item.get("source_file") or ref),
                "source_title": str(item.get("source_title") or ""),
                "resource_kind": str(item.get("resource_kind") or ""),
            }
        )
        if len(sources) >= 6:
            break
    if not sources:
        return {}
    return {
        "last_question": question,
        "last_response_type": str(result.get("response_type", "")),
        "last_topic": sources[0].get("source_title") or sources[0].get("citation_ref", ""),
        "last_sources": sources,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-turn conversation smoke tests.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--cases", default="data/evals/conversation_smoke.jsonl")
    parser.add_argument("--ids", default="", help="Comma-separated case IDs to run")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cases = load_cases((root / args.cases).resolve())
    if args.ids:
        wanted = {case_id.strip() for case_id in args.ids.split(",") if case_id.strip()}
        cases = [case for case in cases if case.get("id") in wanted]

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for case in cases:
        print(f"[case] {case['id']}", flush=True)
        memory: dict[str, Any] = {}
        for turn_index, turn in enumerate(case.get("turns", []), start=1):
            question = str(turn.get("question", ""))
            started = time.perf_counter()
            result = answer_with_agents(
                root,
                question,
                conversation_memory=memory,
                retrieval_only=bool(turn.get("retrieval_only", False)),
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            answer = format_chat_answer(str(result.get("final_answer", "")))
            response_type = str(result.get("response_type", ""))
            expected_response_type = str(turn.get("expected_response_type", "answer"))
            type_ok = expected_type_ok(response_type, expected_response_type, llm=True)
            source_ok = source_hit(result, list(turn.get("expected_source_contains", [])))
            check_answer_text = response_type != "retrieval_only"
            must_contain_ok = True
            must_not_contain_ok = True
            if check_answer_text:
                must_contain_ok = contains_all(answer, list(turn.get("answer_must_contain", [])))
                must_not_contain_ok = contains_none(
                    answer,
                    GLOBAL_MUST_NOT_CONTAIN + list(turn.get("answer_must_not_contain", [])),
                )
            passed = type_ok and source_ok and must_contain_ok and must_not_contain_ok
            status = "PASS" if passed else "FAIL"
            print(f"  [{turn_index}] {status} type={response_type} elapsed={elapsed_ms}ms", flush=True)
            if not passed:
                failures.append(f"{case['id']} turn {turn_index}")
            rows.append(
                {
                    "case_id": case.get("id", ""),
                    "turn": turn_index,
                    "passed": passed,
                    "response_type": response_type,
                    "question": question,
                    "elapsed_ms": elapsed_ms,
                    "answer_preview": answer[:500],
                    "retrieval": result.get("retrieval", {}),
                }
            )
            next_memory = memory_from_result(question, result)
            if next_memory:
                memory = next_memory

    out_dir = root / "data" / "evals" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"conversation-smoke-{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    if failures:
        print("Failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Passed {len(rows)}/{len(rows)} turns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
