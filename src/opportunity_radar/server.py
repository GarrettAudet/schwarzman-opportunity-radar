from __future__ import annotations

import argparse
import json
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import load_env, load_runtime_config
from .pipeline import load_sources, run_digest
from .state import state_store_from_env


MAX_BODY_BYTES = 131_072
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def json_bytes(payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> tuple[int, bytes]:
    return status.value, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def is_authorized(authorization_header: str, token: str) -> bool:
    if not token:
        return True
    return secrets.compare_digest(authorization_header.strip(), f"Bearer {token}")


class OpportunityRequestHandler(BaseHTTPRequestHandler):
    server_version = "OpportunityRadar/0.1"

    @property
    def root(self) -> Path:
        return self.server.root  # type: ignore[attr-defined,no-any-return]

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.log_date_time_string()} - {format % args}", flush=True)

    def send_json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def require_auth(self) -> bool:
        config = load_runtime_config(self.root)
        if is_authorized(self.headers.get("Authorization", ""), config.api_token):
            return True
        status, body = json_bytes({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        self.send_json(status, body)
        return False

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/", "/health"}:
            status, body = json_bytes({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
            self.send_json(status, body)
            return
        config = load_runtime_config(self.root)
        state = state_store_from_env(self.root).load()
        try:
            source_count = len(load_sources(self.root).get("sources", []))
        except Exception:
            source_count = 0
        status, body = json_bytes(
            {
                "ok": True,
                "service": "opportunity-radar",
                "endpoints": ["GET /health", "POST /digest/preview", "POST /digest/run"],
                "configured_sources": source_count,
                "recipients_configured": len(config.recipients),
                "last_run": (state.get("runs") or [])[-1] if state.get("runs") else {},
            }
        )
        self.send_json(status, body)

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        status = HTTPStatus.OK if path in {"/", "/health"} else HTTPStatus.NOT_FOUND
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {"/digest/preview", "/digest/run"}:
            status, body = json_bytes({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
            self.send_json(status, body)
            return
        if not self.require_auth():
            return
        try:
            request = self.read_json_body()
            send = path == "/digest/run" and bool(request.get("send", True))
            result = run_digest(
                self.root,
                send=send,
                force=bool(request.get("force", False)),
                respect_schedule=bool(request.get("respect_schedule", False)),
                sources_path=str(request.get("sources_path", "")),
                deterministic_fallback=request.get("deterministic_fallback"),
                include_seen=bool(request.get("include_seen", False)),
                from_state=bool(request.get("from_state", False)),
            )
            status, body = json_bytes({"ok": not any(error.startswith("ranker_failed") for error in result.errors), "run": result.to_dict()})
        except Exception as exc:
            status, body = json_bytes(
                {"ok": False, "error": "server_error", "detail": type(exc).__name__},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
        self.send_json(status, body)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_BODY_BYTES:
            raise ValueError("request_body_too_large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("json_object_required")
        return payload


def run_server(root: Path, host: str, port: int) -> None:
    root = root.resolve()
    load_env(root)
    server = ThreadingHTTPServer((host, port), OpportunityRequestHandler)
    server.root = root  # type: ignore[attr-defined]
    print(f"OpportunityRadar backend listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping OpportunityRadar backend.", flush=True)
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the OpportunityRadar backend.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--host", default=os.environ.get("HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    args = parser.parse_args()
    run_server(Path(args.root), args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
