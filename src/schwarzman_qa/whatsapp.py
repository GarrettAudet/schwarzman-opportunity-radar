from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any
import urllib.error
import urllib.request


MAX_WHATSAPP_TEXT_CHARS = 3900
DEFAULT_GRAPH_API_VERSION = "v23.0"


class WhatsAppError(RuntimeError):
    pass


@dataclass(frozen=True)
class IncomingWhatsAppMessage:
    message_id: str
    wa_id: str
    phone_number: str
    profile_name: str
    message_type: str
    text: str


def verify_webhook_token(query: dict[str, list[str]], expected_token: str) -> str | None:
    mode = first_query_value(query, "hub.mode")
    token = first_query_value(query, "hub.verify_token")
    challenge = first_query_value(query, "hub.challenge")
    if mode == "subscribe" and expected_token and hmac.compare_digest(token, expected_token):
        return challenge
    return None


def first_query_value(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return values[0] if values else ""


def verify_signature(raw_body: bytes, signature_header: str, app_secret: str) -> bool:
    if not app_secret:
        return True
    if not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header, expected)


def extract_messages(payload: dict[str, Any]) -> list[IncomingWhatsAppMessage]:
    extracted: list[IncomingWhatsAppMessage] = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            contacts_by_wa_id = {
                str(contact.get("wa_id", "")): contact
                for contact in value.get("contacts", []) or []
                if contact.get("wa_id")
            }
            for message in value.get("messages", []) or []:
                wa_id = str(message.get("from", "")).strip()
                if not wa_id:
                    continue
                contact = contacts_by_wa_id.get(wa_id, {})
                message_type = str(message.get("type", "")).strip()
                text = ""
                if message_type == "text":
                    text = str((message.get("text") or {}).get("body", "")).strip()
                extracted.append(
                    IncomingWhatsAppMessage(
                        message_id=str(message.get("id", "")).strip(),
                        wa_id=wa_id,
                        phone_number=str(contact.get("wa_id") or wa_id).strip(),
                        profile_name=str((contact.get("profile") or {}).get("name", "")).strip(),
                        message_type=message_type,
                        text=text,
                    )
                )
    return extracted


def send_text(to_wa_id: str, body: str, *, reply_to_message_id: str = "") -> list[dict[str, Any]]:
    token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not token:
        raise WhatsAppError("WHATSAPP_ACCESS_TOKEN is not set")
    if not phone_number_id:
        raise WhatsAppError("WHATSAPP_PHONE_NUMBER_ID is not set")

    responses = []
    for index, chunk in enumerate(split_message(body)):
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_wa_id,
            "type": "text",
            "text": {"preview_url": False, "body": chunk},
        }
        if reply_to_message_id and index == 0:
            payload["context"] = {"message_id": reply_to_message_id}
        responses.append(send_message_payload(payload, token, phone_number_id))
    return responses


def send_message_payload(payload: dict[str, Any], token: str, phone_number_id: str) -> dict[str, Any]:
    api_version = os.environ.get("WHATSAPP_GRAPH_API_VERSION", DEFAULT_GRAPH_API_VERSION).strip() or DEFAULT_GRAPH_API_VERSION
    url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "schwarzman-qna-whatsapp",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WhatsAppError(f"WhatsApp send failed: HTTP {exc.code}: {detail[:500]}") from exc


def split_message(body: str) -> list[str]:
    text = body.strip() or "I don't have an answer to send."
    if len(text) <= MAX_WHATSAPP_TEXT_CHARS:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_WHATSAPP_TEXT_CHARS:
            chunks.append(remaining)
            break
        split_at = max(
            remaining.rfind("\n\n", 0, MAX_WHATSAPP_TEXT_CHARS),
            remaining.rfind("\n", 0, MAX_WHATSAPP_TEXT_CHARS),
            remaining.rfind(" ", 0, MAX_WHATSAPP_TEXT_CHARS),
        )
        if split_at < MAX_WHATSAPP_TEXT_CHARS // 2:
            split_at = MAX_WHATSAPP_TEXT_CHARS
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return chunks
