from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
import urllib.request

from .agents import answer_with_agents
from .retrieval import latest_file, load_index


MAX_BODY_BYTES = 16_384
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclass
class ServerState:
    root: Path
    index_path: Path
    index_data: dict[str, Any]
    default_top_k: int


def make_response(result: dict[str, Any], elapsed_ms: int, debug: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": result.get("response_type") != "agent_error",
        "elapsed_ms": elapsed_ms,
        "response_type": result.get("response_type", ""),
        "answer": result.get("final_answer", ""),
        "retrieval": {
            "top_score": result.get("retrieval", {}).get("top_score", 0),
            "sources": [
                {
                    "score": item.get("score", 0),
                    "citation_ref": item.get("citation_ref", ""),
                    "source_file": item.get("source_file", ""),
                    "source_title": item.get("source_title", ""),
                }
                for item in result.get("retrieval", {}).get("results", [])
            ],
        },
        "guardrail": {
            "blocked": result.get("guardrail", {}).get("blocked", False),
            "block_reason": result.get("guardrail", {}).get("block_reason", ""),
            "prompt_injection_score": result.get("guardrail", {}).get("prompt_injection_score", 0),
        },
    }
    for key in ("answer_model", "review_model", "agent_warning", "agent_error"):
        if key in result:
            payload[key] = result[key]
    if debug:
        payload["debug"] = result
    return payload


def json_bytes(payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> tuple[int, bytes]:
    return status.value, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def default_index_path(root: Path) -> Path:
    index_url = os.environ.get("SCHWARZMAN_INDEX_URL", "").strip()
    if index_url:
        return download_index(index_url)

    github_repo = os.environ.get("GITHUB_INDEX_REPO", "").strip()
    if github_repo:
        github_path = os.environ.get("GITHUB_INDEX_PATH", "local-index.json").strip()
        github_ref = os.environ.get("GITHUB_INDEX_REF", "main").strip()
        return download_github_index(github_repo, github_path, github_ref)

    local_index_dir = root / "data" / "corpus" / "index"
    if local_index_dir.exists():
        try:
            return latest_file(local_index_dir, "local-index-*.json")
        except FileNotFoundError:
            pass

    deploy_index = root / "deploy" / "index" / "local-index.json"
    if deploy_index.exists():
        return deploy_index

    raise FileNotFoundError(
        "No local retrieval index found. Run scripts/build_local_index.py locally "
        "or provide SCHWARZMAN_INDEX_PATH, SCHWARZMAN_INDEX_URL, or GITHUB_INDEX_REPO."
    )


def download_index(index_url: str) -> Path:
    target = Path(tempfile.gettempdir()) / "schwarzman-local-index.json"
    if target.exists() and target.stat().st_size > 0:
        return target

    request = urllib.request.Request(index_url, method="GET")
    bearer_token = os.environ.get("SCHWARZMAN_INDEX_BEARER_TOKEN", "").strip()
    if bearer_token:
        request.add_header("Authorization", f"Bearer {bearer_token}")

    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())
    return target


def download_github_index(repo: str, path: str, ref: str) -> Path:
    target = Path(tempfile.gettempdir()) / "schwarzman-github-index.json"
    if target.exists() and target.stat().st_size > 0:
        return target

    token = os.environ.get("GITHUB_INDEX_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GITHUB_INDEX_TOKEN is required when GITHUB_INDEX_REPO is set")

    encoded_path = quote(path.strip("/"))
    encoded_ref = quote(ref)
    url = f"https://api.github.com/repos/{repo}/contents/{encoded_path}?ref={encoded_ref}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.raw",
            "Authorization": f"Bearer {token}",
            "User-Agent": "schwarzman-qna-render",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        target.write_bytes(response.read())
    return target


class QaRequestHandler(BaseHTTPRequestHandler):
    server_version = "SchwarzmanQAServer/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.log_date_time_string()} - {format % args}", flush=True)

    @property
    def state(self) -> ServerState:
        return self.server.state  # type: ignore[attr-defined,no-any-return]

    def send_json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in {"/", "/health"}:
            status, body = json_bytes(
                {
                    "ok": True,
                    "service": "schwarzman-qa",
                    "endpoints": ["GET /health", "POST /ask"],
                    "index_path": str(self.state.index_path.relative_to(self.state.root)).replace("\\", "/"),
                    "chunk_count": self.state.index_data.get("chunk_count", 0),
                }
            )
            self.send_json(status, body)
            return
        status, body = json_bytes({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
        self.send_json(status, body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/ask":
            status, body = json_bytes({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
            self.send_json(status, body)
            return

        try:
            request = self.read_json_body()
            question = str(request.get("question", "")).strip()
            if not question:
                status, body = json_bytes({"ok": False, "error": "question_required"}, HTTPStatus.BAD_REQUEST)
                self.send_json(status, body)
                return
            top_k = min(12, max(1, int(request.get("top_k", self.state.default_top_k))))
            retrieval_only = bool(request.get("retrieval_only", False))
            debug = bool(request.get("debug", False))
        except Exception as exc:
            status, body = json_bytes(
                {"ok": False, "error": "bad_request", "detail": str(exc)},
                HTTPStatus.BAD_REQUEST,
            )
            self.send_json(status, body)
            return

        started = time.perf_counter()
        try:
            result = answer_with_agents(
                self.state.root,
                question,
                index_data=self.state.index_data,
                top_k=top_k,
                retrieval_only=retrieval_only,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            status, body = json_bytes(make_response(result, elapsed_ms, debug=debug))
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            status, body = json_bytes(
                {
                    "ok": False,
                    "elapsed_ms": elapsed_ms,
                    "response_type": "server_error",
                    "error": type(exc).__name__,
                },
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        self.send_json(status, body)

    def read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        length = int(raw_length)
        if length > MAX_BODY_BYTES:
            raise ValueError("request_body_too_large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("json_object_required")
        return payload


def run_server(root: Path, host: str, port: int, top_k: int = 6, index_path: Path | None = None) -> None:
    root = root.resolve()
    if index_path is None:
        index_path = default_index_path(root)
    else:
        index_path = index_path.resolve()
    index_data = load_index(root, index_path)
    state = ServerState(root=root, index_path=index_path, index_data=index_data, default_top_k=top_k)
    server = ThreadingHTTPServer((host, port), QaRequestHandler)
    server.state = state  # type: ignore[attr-defined]
    print(
        f"Schwarzman QA backend listening on http://{host}:{port} "
        f"with {index_data.get('chunk_count', 0)} chunks",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Schwarzman QA backend.", flush=True)
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Schwarzman QA backend.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--host", default=os.environ.get("HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--index", default=os.environ.get("SCHWARZMAN_INDEX_PATH", ""), help="Optional local index JSON")
    args = parser.parse_args()

    root = Path(args.root)
    index_path = Path(args.index) if args.index else None
    run_server(root=root, host=args.host, port=args.port, top_k=args.top_k, index_path=index_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
