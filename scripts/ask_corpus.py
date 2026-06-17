from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schwarzman_qa.agents import answer_with_agents  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the local Schwarzman corpus Q&A prototype.")
    parser.add_argument("question", nargs="*", help="Question to ask")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--index", default="", help="Optional local index JSON")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--retrieval-only", action="store_true", help="Do not call OpenRouter")
    parser.add_argument("--answer-model", default="")
    parser.add_argument("--review-model", default="")
    parser.add_argument("--json", action="store_true", help="Print full JSON output")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        question = input("Question: ").strip()

    root = Path(args.root).resolve()
    index_path = Path(args.index).resolve() if args.index else None
    result = answer_with_agents(
        root,
        question,
        index_path=index_path,
        top_k=args.top_k,
        retrieval_only=args.retrieval_only,
        answer_model_name=args.answer_model or None,
        review_model_name=args.review_model or None,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.retrieval_only:
        print(f"Top score: {result['retrieval']['top_score']}")
        for item in result["retrieval"]["results"]:
            print(f"- {item['score']} {item['citation_ref']}")
            print(f"  {item['text'][:220].replace(chr(10), ' ')}")
    else:
        print(result["final_answer"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
