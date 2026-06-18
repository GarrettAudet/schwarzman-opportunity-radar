from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
import urllib.request

from .access_control import WhatsAppAccessControl, access_control_from_env
from .agents import CAPABILITY_BODY, answer_with_agents
from .citations import public_citation_ref
from .config import load_env
from .policy import NOT_FOUND_TEXT, clean_visible_text, format_chat_answer
from .retrieval import latest_file, load_index
from .twilio_whatsapp import (
    extract_message as extract_twilio_message,
    parse_form_body,
    send_text as send_twilio_text,
    should_validate_signature as should_validate_twilio_signature,
    twiml_response,
    validate_signature as validate_twilio_signature,
)
from .whatsapp import extract_messages, send_text, verify_signature, verify_webhook_token


MAX_BODY_BYTES = 131_072
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
API_TOKEN_ENV = "SCHWARZMAN_API_TOKEN"
FAILED_RESPONSE_TYPES = {"not_found", "out_of_scope", "safety_refusal", "agent_error", "server_error"}
HELP_TEXT = (
    CAPABILITY_BODY
)
PASSWORD_PROMPT = (
    f"{HELP_TEXT}\n\n"
    "Please send the group password before asking questions."
)
APPROVED_PROMPT = (
    "You're approved.\n\n"
    f"{HELP_TEXT}"
)
FEEDBACK_EMPTY_PROMPT = "Send feedback like: /feedback add more details about arrival transportation."
FEEDBACK_RECEIVED_PROMPT = "Thanks - I saved that feedback for review."


@dataclass
class ServerState:
    root: Path
    index_path: Path
    index_data: dict[str, Any]
    default_top_k: int
    whatsapp_access: WhatsAppAccessControl
    processed_whatsapp_ids: set[str] = field(default_factory=set)
    processed_lock: threading.Lock = field(default_factory=threading.Lock)


def make_response(result: dict[str, Any], elapsed_ms: int, debug: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": result.get("response_type") != "agent_error",
        "elapsed_ms": elapsed_ms,
        "response_type": result.get("response_type", ""),
        "answer": clean_visible_text(str(result.get("final_answer", ""))),
        "retrieval": {
            "top_score": result.get("retrieval", {}).get("top_score", 0),
            "sources": [
                {
                    "score": item.get("score", 0),
                    "citation_ref": public_citation_ref(item.get("citation_ref", "")),
                    "source_file": public_citation_ref(item.get("source_file", "")),
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


def sse_bytes(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def is_api_authorized(authorization_header: str) -> bool:
    token = os.environ.get(API_TOKEN_ENV, "").strip()
    if not token:
        return True
    return secrets.compare_digest(authorization_header.strip(), f"Bearer {token}")


def external_request_url(headers: Any, path: str) -> str:
    configured = os.environ.get("TWILIO_WEBHOOK_URL", "").strip()
    if configured:
        return configured
    proto = headers.get("X-Forwarded-Proto", "https").split(",", 1)[0].strip() or "https"
    host = headers.get("X-Forwarded-Host") or headers.get("Host", "")
    return f"{proto}://{host}{path}"


def is_help_request(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", text.strip().lower())
    normalized = lowered.replace(" u ", " you ")
    if normalized in {"/help", "help", "/start", "start"}:
        return True
    help_patterns = [
        r"\bwhat (questions|kinds of questions|types of questions|topics) can (you|it|this|this bot|the bot)\b",
        r"\bwhat can (you|it|this bot|the bot) (answer|do|help with|search)\b",
        r"\bwhat (resources|materials|sources|documents|docs) can (you|it|this bot|the bot) (search|use|answer from)\b",
        r"\bwhat (resources|materials|sources|documents|docs) (are there|are available|do you have|can (you|it|this bot|the bot) search)\b",
        r"\bwhat (are you|is this bot) for\b",
        r"\bhow (do|can) i use (you|it|this|this bot|the bot)\b",
        r"\bwhat schwarzman.*questions can (you|it|this|this bot|the bot)\b",
        r"\bwhat tsinghua.*questions can (you|it|this|this bot|the bot)\b",
    ]
    return any(re.search(pattern, normalized) for pattern in help_patterns)


def parse_feedback(text: str) -> str | None:
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered == "/feedback":
        return ""
    if lowered.startswith("/feedback "):
        return stripped[len("/feedback ") :].strip()
    return None


def top_retrieval_source(response: dict[str, Any]) -> tuple[float, str]:
    sources = response.get("retrieval", {}).get("sources", [])
    if not sources:
        return 0.0, ""
    first = sources[0]
    return float(first.get("score", 0) or 0), str(first.get("citation_ref", "") or first.get("source_file", ""))


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

    def send_text_response(self, status: HTTPStatus, body: str) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def send_twiml(self, status: HTTPStatus, body: bytes) -> None:
        self.send_response(status.value)
        self.send_header("Content-Type", "application/xml; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def require_api_auth(self) -> bool:
        if is_api_authorized(self.headers.get("Authorization", "")):
            return True
        status, body = json_bytes({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
        self.send_json(status, body)
        return False

    def send_sse_headers(self) -> None:
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def write_sse(self, event: str, payload: dict[str, Any]) -> None:
        self.wfile.write(sse_bytes(event, payload))
        self.wfile.flush()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/webhooks/whatsapp":
            challenge = verify_webhook_token(
                parse_qs(parsed.query),
                os.environ.get("WHATSAPP_VERIFY_TOKEN", "").strip(),
            )
            if challenge is None:
                self.send_text_response(HTTPStatus.FORBIDDEN, "forbidden")
                return
            self.send_text_response(HTTPStatus.OK, challenge)
            return
        if path in {"/", "/health"}:
            status, body = json_bytes(
                {
                    "ok": True,
                    "service": "schwarzman-qa",
                    "endpoints": [
                        "GET /health",
                        "POST /ask",
                        "POST /ask/stream",
                        "GET /webhooks/whatsapp",
                        "POST /webhooks/whatsapp",
                        "POST /webhooks/twilio/whatsapp",
                    ],
                    "index_path": display_path(self.state.index_path, self.state.root),
                    "chunk_count": self.state.index_data.get("chunk_count", 0),
                }
            )
            self.send_json(status, body)
            return
        status, body = json_bytes({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
        self.send_json(status, body)

    def do_HEAD(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        status = HTTPStatus.OK if path in {"/", "/health"} else HTTPStatus.NOT_FOUND
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/webhooks/twilio/whatsapp":
            self.handle_twilio_whatsapp_webhook()
            return
        if path == "/webhooks/whatsapp":
            self.handle_whatsapp_webhook()
            return
        if path == "/ask/stream":
            if not self.require_api_auth():
                return
            self.handle_streaming_ask()
            return
        if path != "/ask":
            status, body = json_bytes({"ok": False, "error": "not_found"}, HTTPStatus.NOT_FOUND)
            self.send_json(status, body)
            return
        if not self.require_api_auth():
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

    def handle_whatsapp_webhook(self) -> None:
        try:
            raw_body = self.read_raw_body()
            if not verify_signature(
                raw_body,
                self.headers.get("X-Hub-Signature-256", ""),
                os.environ.get("WHATSAPP_APP_SECRET", "").strip(),
            ):
                status, body = json_bytes({"ok": False, "error": "bad_signature"}, HTTPStatus.UNAUTHORIZED)
                self.send_json(status, body)
                return
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            messages = extract_messages(payload)
        except Exception as exc:
            status, body = json_bytes(
                {"ok": False, "error": "bad_request", "detail": type(exc).__name__},
                HTTPStatus.BAD_REQUEST,
            )
            self.send_json(status, body)
            return

        queued = 0
        for message in messages:
            message_key = message.message_id or f"{message.wa_id}:{hash(message.text)}"
            with self.state.processed_lock:
                if message_key in self.state.processed_whatsapp_ids:
                    continue
                self.state.processed_whatsapp_ids.add(message_key)
                if len(self.state.processed_whatsapp_ids) > 1000:
                    self.state.processed_whatsapp_ids = set(list(self.state.processed_whatsapp_ids)[-500:])
            threading.Thread(target=self.process_whatsapp_message, args=(message,), daemon=True).start()
            queued += 1

        status, body = json_bytes({"ok": True, "queued": queued})
        self.send_json(status, body)

    def handle_twilio_whatsapp_webhook(self) -> None:
        try:
            raw_body = self.read_raw_body()
            form = parse_form_body(raw_body)
            if should_validate_twilio_signature():
                callback_url = external_request_url(self.headers, "/webhooks/twilio/whatsapp")
                valid = validate_twilio_signature(
                    callback_url,
                    form,
                    self.headers.get("X-Twilio-Signature", ""),
                    os.environ.get("TWILIO_AUTH_TOKEN", "").strip(),
                )
                if not valid:
                    self.send_twiml(HTTPStatus.FORBIDDEN, twiml_response())
                    return
            message = extract_twilio_message(form)
        except Exception as exc:
            print(f"Twilio webhook parse failed: {type(exc).__name__}", flush=True)
            self.send_twiml(HTTPStatus.BAD_REQUEST, twiml_response())
            return

        message_key = message.message_id or f"{message.wa_id}:{hash(message.body)}"
        with self.state.processed_lock:
            if message_key not in self.state.processed_whatsapp_ids:
                self.state.processed_whatsapp_ids.add(message_key)
                if len(self.state.processed_whatsapp_ids) > 1000:
                    self.state.processed_whatsapp_ids = set(list(self.state.processed_whatsapp_ids)[-500:])
                threading.Thread(target=self.process_twilio_whatsapp_message, args=(message,), daemon=True).start()

        self.send_twiml(HTTPStatus.OK, twiml_response())

    def process_twilio_whatsapp_message(self, message: Any) -> None:
        try:
            access = self.state.whatsapp_access
            text = message.body.strip()
            decision = access.check(message.wa_id, message.phone_number)
            if decision.status == "blocked":
                send_twilio_text(
                    message.from_address,
                    "This number is not approved for the Schwarzman resource bot.",
                    from_address=message.to_address,
                )
                return

            invite_code = access.invite_code
            if invite_code and secrets.compare_digest(text, invite_code):
                invite_decision = access.redeem_invite(
                    text,
                    wa_id=message.wa_id,
                    phone_number=message.phone_number,
                    profile_name=message.profile_name,
                )
                if invite_decision.allowed:
                    access.record_event(
                        "approved",
                        wa_id=message.wa_id,
                        phone_number=message.phone_number,
                        profile_name=message.profile_name,
                        metadata={"source": "password"},
                    )
                    send_twilio_text(
                        message.from_address,
                        APPROVED_PROMPT,
                        from_address=message.to_address,
                    )
                else:
                    send_twilio_text(
                        message.from_address,
                        "That password was not accepted. Please use the password posted in the student group.",
                        from_address=message.to_address,
                    )
                return

            if not decision.allowed:
                access.record_event(
                    "password_prompt",
                    wa_id=message.wa_id,
                    phone_number=message.phone_number,
                    profile_name=message.profile_name,
                    metadata={"reason": decision.reason},
                )
                send_twilio_text(
                    message.from_address,
                    PASSWORD_PROMPT,
                    from_address=message.to_address,
                )
                return

            if is_help_request(text):
                send_twilio_text(message.from_address, HELP_TEXT, from_address=message.to_address)
                return

            feedback = parse_feedback(text)
            if feedback is not None:
                if not feedback:
                    send_twilio_text(message.from_address, FEEDBACK_EMPTY_PROMPT, from_address=message.to_address)
                    return
                access.record_feedback(
                    feedback,
                    wa_id=message.wa_id,
                    phone_number=message.phone_number,
                    profile_name=message.profile_name,
                )
                send_twilio_text(message.from_address, FEEDBACK_RECEIVED_PROMPT, from_address=message.to_address)
                return

            if not text or message.num_media:
                send_twilio_text(
                    message.from_address,
                    "I can only answer text questions right now.",
                    from_address=message.to_address,
                )
                return

            send_twilio_text(message.from_address, "Got it - searching the reviewed resources now.", from_address=message.to_address)
            started = time.perf_counter()
            result = answer_with_agents(
                self.state.root,
                text,
                index_data=self.state.index_data,
                top_k=self.state.default_top_k,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            response = make_response(result, elapsed_ms)
            answer = response.get("answer") or NOT_FOUND_TEXT
            response_type = str(response.get("response_type", ""))
            if response_type in FAILED_RESPONSE_TYPES:
                top_score, top_source = top_retrieval_source(response)
                access.record_failed_question(
                    text,
                    wa_id=message.wa_id,
                    phone_number=message.phone_number,
                    profile_name=message.profile_name,
                    response_type=response_type,
                    top_score=top_score,
                    top_source=top_source,
                )
            send_twilio_text(message.from_address, format_chat_answer(str(answer)), from_address=message.to_address)
        except Exception as exc:
            print(f"Twilio WhatsApp message handling failed: {type(exc).__name__}", flush=True)

    def process_whatsapp_message(self, message: Any) -> None:
        try:
            access = self.state.whatsapp_access
            text = message.text.strip()
            decision = access.check(message.wa_id, message.phone_number)
            if decision.status == "blocked":
                send_text(
                    message.wa_id,
                    "This number is not approved for the Schwarzman resource bot.",
                    reply_to_message_id=message.message_id,
                )
                return

            invite_code = access.invite_code
            if invite_code and secrets.compare_digest(text, invite_code):
                invite_decision = access.redeem_invite(
                    text,
                    wa_id=message.wa_id,
                    phone_number=message.phone_number,
                    profile_name=message.profile_name,
                )
                if invite_decision.allowed:
                    access.record_event(
                        "approved",
                        wa_id=message.wa_id,
                        phone_number=message.phone_number,
                        profile_name=message.profile_name,
                        metadata={"source": "password"},
                    )
                    send_text(
                        message.wa_id,
                        APPROVED_PROMPT,
                        reply_to_message_id=message.message_id,
                    )
                else:
                    send_text(
                        message.wa_id,
                        "That password was not accepted. Please use the password posted in the student group.",
                        reply_to_message_id=message.message_id,
                    )
                return

            if not decision.allowed:
                access.record_event(
                    "password_prompt",
                    wa_id=message.wa_id,
                    phone_number=message.phone_number,
                    profile_name=message.profile_name,
                    metadata={"reason": decision.reason},
                )
                send_text(
                    message.wa_id,
                    PASSWORD_PROMPT,
                    reply_to_message_id=message.message_id,
                )
                return

            if is_help_request(text):
                send_text(message.wa_id, HELP_TEXT, reply_to_message_id=message.message_id)
                return

            feedback = parse_feedback(text)
            if feedback is not None:
                if not feedback:
                    send_text(message.wa_id, FEEDBACK_EMPTY_PROMPT, reply_to_message_id=message.message_id)
                    return
                access.record_feedback(
                    feedback,
                    wa_id=message.wa_id,
                    phone_number=message.phone_number,
                    profile_name=message.profile_name,
                )
                send_text(message.wa_id, FEEDBACK_RECEIVED_PROMPT, reply_to_message_id=message.message_id)
                return

            if message.message_type != "text" or not text:
                send_text(
                    message.wa_id,
                    "I can only answer text questions right now.",
                    reply_to_message_id=message.message_id,
                )
                return

            send_text(message.wa_id, "Got it - searching the reviewed resources now.", reply_to_message_id=message.message_id)
            started = time.perf_counter()
            result = answer_with_agents(
                self.state.root,
                text,
                index_data=self.state.index_data,
                top_k=self.state.default_top_k,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            response = make_response(result, elapsed_ms)
            answer = response.get("answer") or NOT_FOUND_TEXT
            response_type = str(response.get("response_type", ""))
            if response_type in FAILED_RESPONSE_TYPES:
                top_score, top_source = top_retrieval_source(response)
                access.record_failed_question(
                    text,
                    wa_id=message.wa_id,
                    phone_number=message.phone_number,
                    profile_name=message.profile_name,
                    response_type=response_type,
                    top_score=top_score,
                    top_source=top_source,
                )
            send_text(message.wa_id, format_chat_answer(str(answer)))
        except Exception as exc:
            print(f"WhatsApp message handling failed: {type(exc).__name__}", flush=True)

    def handle_streaming_ask(self) -> None:
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
        self.send_sse_headers()
        self.write_sse("connected", {"ok": True, "message": "Request accepted."})

        try:
            result = answer_with_agents(
                self.state.root,
                question,
                index_data=self.state.index_data,
                top_k=top_k,
                retrieval_only=retrieval_only,
                event_callback=self.write_sse,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.write_sse("final", make_response(result, elapsed_ms, debug=debug))
            self.write_sse("done", {"ok": True, "elapsed_ms": elapsed_ms})
        except BrokenPipeError:
            return
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.write_sse(
                "error",
                {
                    "ok": False,
                    "elapsed_ms": elapsed_ms,
                    "response_type": "server_error",
                    "error": type(exc).__name__,
                },
            )

    def read_json_body(self) -> dict[str, Any]:
        raw = self.read_raw_body()
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("json_object_required")
        return payload

    def read_raw_body(self) -> bytes:
        raw_length = self.headers.get("Content-Length", "0")
        length = int(raw_length)
        if length > MAX_BODY_BYTES:
            raise ValueError("request_body_too_large")
        return self.rfile.read(length)


def run_server(root: Path, host: str, port: int, top_k: int = 6, index_path: Path | None = None) -> None:
    root = root.resolve()
    load_env(root)
    if index_path is None:
        index_path = default_index_path(root)
    else:
        index_path = index_path.resolve()
    index_data = load_index(root, index_path)
    state = ServerState(
        root=root,
        index_path=index_path,
        index_data=index_data,
        default_top_k=top_k,
        whatsapp_access=access_control_from_env(root),
    )
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
