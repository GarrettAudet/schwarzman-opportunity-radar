from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode
import urllib.error
import urllib.request


MAX_TWILIO_WHATSAPP_TEXT_CHARS = 1500


class TwilioWhatsAppError(RuntimeError):
    pass


@dataclass(frozen=True)
class IncomingTwilioWhatsAppMessage:
    message_id: str
    wa_id: str
    phone_number: str
    from_address: str
    to_address: str
    profile_name: str
    body: str
    num_media: int


def parse_form_body(raw_body: bytes) -> dict[str, str]:
    parsed = parse_qs(raw_body.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def extract_message(form: dict[str, str]) -> IncomingTwilioWhatsAppMessage:
    from_address = form.get("From", "").strip()
    to_address = form.get("To", "").strip()
    wa_id = form.get("WaId", "").strip() or strip_whatsapp_prefix(from_address)
    return IncomingTwilioWhatsAppMessage(
        message_id=form.get("MessageSid", "").strip() or form.get("SmsMessageSid", "").strip(),
        wa_id=wa_id,
        phone_number=strip_whatsapp_prefix(from_address) or wa_id,
        from_address=from_address,
        to_address=to_address,
        profile_name=form.get("ProfileName", "").strip(),
        body=form.get("Body", "").strip(),
        num_media=int(form.get("NumMedia", "0") or 0),
    )


def strip_whatsapp_prefix(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("whatsapp:"):
        text = text.split(":", 1)[1]
    return text


def twiml_response(message: str = "") -> bytes:
    escaped = (
        message.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    body = f'<?xml version="1.0" encoding="UTF-8"?><Response>'
    if escaped:
        body += f"<Message>{escaped}</Message>"
    body += "</Response>"
    return body.encode("utf-8")


def validate_signature(url: str, form: dict[str, str], signature: str, auth_token: str) -> bool:
    if not auth_token:
        return True
    if not signature:
        return False
    signed = url + "".join(f"{key}{form[key]}" for key in sorted(form))
    digest = hmac.new(auth_token.encode("utf-8"), signed.encode("utf-8"), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature)


def should_validate_signature() -> bool:
    value = os.environ.get("TWILIO_VALIDATE_SIGNATURE", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def send_text(to_address: str, body: str, *, from_address: str = "") -> list[dict[str, Any]]:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    sender = (from_address or os.environ.get("TWILIO_WHATSAPP_FROM", "")).strip()
    if not account_sid:
        raise TwilioWhatsAppError("TWILIO_ACCOUNT_SID is not set")
    if not auth_token:
        raise TwilioWhatsAppError("TWILIO_AUTH_TOKEN is not set")
    if not sender:
        raise TwilioWhatsAppError("TWILIO_WHATSAPP_FROM is not set")

    responses = []
    for chunk in split_message(body):
        responses.append(send_message_payload(account_sid, auth_token, sender, to_address, chunk))
    return responses


def send_message_payload(
    account_sid: str,
    auth_token: str,
    from_address: str,
    to_address: str,
    body: str,
) -> dict[str, Any]:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    data = urlencode({"From": from_address, "To": to_address, "Body": body}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "schwarzman-qna-twilio-whatsapp",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TwilioWhatsAppError(f"Twilio send failed: HTTP {exc.code}: {detail[:500]}") from exc


def split_message(body: str) -> list[str]:
    text = body.strip() or "I don't have an answer to send."
    if len(text) <= MAX_TWILIO_WHATSAPP_TEXT_CHARS:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= MAX_TWILIO_WHATSAPP_TEXT_CHARS:
            chunks.append(remaining)
            break
        split_at = max(
            remaining.rfind("\n\n", 0, MAX_TWILIO_WHATSAPP_TEXT_CHARS),
            remaining.rfind("\n", 0, MAX_TWILIO_WHATSAPP_TEXT_CHARS),
            remaining.rfind(" ", 0, MAX_TWILIO_WHATSAPP_TEXT_CHARS),
        )
        if split_at < MAX_TWILIO_WHATSAPP_TEXT_CHARS // 2:
            split_at = MAX_TWILIO_WHATSAPP_TEXT_CHARS
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    return chunks
