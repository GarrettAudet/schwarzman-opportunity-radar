from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request


def post_json(url: str, payload: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the local Schwarzman QA backend.")
    parser.add_argument("question", nargs="*", help="Question to ask")
    parser.add_argument("--url", default="http://127.0.0.1:8765/ask")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true", help="Print full JSON response")
    args = parser.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        question = input("Question: ").strip()

    payload = {
        "question": question,
        "retrieval_only": args.retrieval_only,
        "top_k": args.top_k,
    }
    started = time.perf_counter()
    response = post_json(args.url, payload, timeout=args.timeout)
    client_elapsed_ms = int((time.perf_counter() - started) * 1000)

    if args.json:
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return 0 if response.get("ok", False) else 1

    print(f"HTTP client elapsed: {client_elapsed_ms} ms")
    print(f"Backend elapsed: {response.get('elapsed_ms')} ms")
    print(f"Response type: {response.get('response_type')}")
    if response.get("agent_warning"):
        print(f"Warning: {response.get('agent_warning')}")
    if response.get("agent_error"):
        print(f"Error: {response.get('agent_error')}")
    if response.get("response_type") == "retrieval_only":
        print()
        print("Top sources:")
        for source in response.get("retrieval", {}).get("sources", [])[: args.top_k]:
            print(f"- {source.get('score')} {source.get('citation_ref')}")
        return 0 if response.get("ok", False) else 1
    print()
    print(response.get("answer", ""))
    return 0 if response.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
