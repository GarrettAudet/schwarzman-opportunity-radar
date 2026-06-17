from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request


def auth_headers(api_token: str = "") -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    return headers


def post_json(url: str, payload: dict, timeout: int, api_token: str = "") -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=auth_headers(api_token),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def post_sse(url: str, payload: dict, timeout: int, api_token: str = ""):
    headers = auth_headers(api_token)
    headers["Accept"] = "text/event-stream"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            event = "message"
            data_lines = []
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_lines.append(line.split(":", 1)[1].strip())
                elif line == "" and data_lines:
                    yield event, json.loads("\n".join(data_lines))
                    event = "message"
                    data_lines = []
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def stream_url_for(url: str) -> str:
    if url.endswith("/ask/stream"):
        return url
    return url[:-4] + "/ask/stream" if url.endswith("/ask") else url.rstrip("/") + "/stream"


def progress_line(event: str, payload: dict) -> str:
    if event == "connected":
        return "Connected."
    if event == "guardrail_started":
        return "Checking request safety..."
    if event == "guardrail_done":
        return f"Safety check done. Prompt-injection score: {payload.get('prompt_injection_score', 0)}"
    if event == "retrieval_started":
        return "Searching reviewed corpus..."
    if event == "retrieval_done":
        return f"Found {payload.get('source_count', 0)} candidate sources. Top score: {payload.get('top_score', 0)}"
    if event == "draft_started":
        return f"Drafting answer with {payload.get('model', 'answer model')}..."
    if event == "draft_done":
        return f"Draft ready. Type: {payload.get('response_type', '')}"
    if event == "review_started":
        return f"Reviewing citations and safety with {payload.get('model', 'review model')}..."
    if event == "review_done":
        return f"Review complete. Allowed: {payload.get('allowed', False)}"
    if event == "answer_ready":
        return f"Answer ready. Type: {payload.get('response_type', '')}"
    if event == "done":
        return f"Done in {payload.get('elapsed_ms')} ms."
    if event == "error":
        return f"Error: {payload.get('error', 'unknown')}"
    return event


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask the local Schwarzman QA backend.")
    parser.add_argument("question", nargs="*", help="Question to ask")
    parser.add_argument("--url", default="http://127.0.0.1:8765/ask")
    parser.add_argument("--stream", action="store_true", help="Use the streaming /ask/stream endpoint")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--api-token", default=os.environ.get("SCHWARZMAN_API_TOKEN", ""))
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

    if args.stream:
        final_response = None
        for event, event_payload in post_sse(
            stream_url_for(args.url),
            payload,
            timeout=args.timeout,
            api_token=args.api_token,
        ):
            if args.json:
                print(json.dumps({"event": event, "data": event_payload}, ensure_ascii=False))
            elif event == "final":
                final_response = event_payload
            else:
                print(progress_line(event, event_payload), flush=True)
            if event == "done":
                break
        if final_response is None:
            return 1
        if args.json:
            return 0 if final_response.get("ok", False) else 1
        print()
        print(final_response.get("answer", ""))
        return 0 if final_response.get("ok", False) else 1

    response = post_json(args.url, payload, timeout=args.timeout, api_token=args.api_token)
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
