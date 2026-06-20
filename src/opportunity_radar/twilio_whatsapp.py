from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
import urllib.error
import urllib.request


MAX_TWILIO_WHATSAPP_TEXT_CHARS = 1500


class TwilioWhatsAppError(RuntimeError):
    pass


@dataclass(frozen=True)
class TwilioMessageResult:
    sid: str
    status: str
    to: str


def strip_whatsapp_prefix(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("whatsapp:"):
        return text
    if text.startswith("+"):
        return f"whatsapp:{text}"
    return text


def split_message(body: str) -> list[str]:
    text = body.strip() or "No OpportunityRadar message body was generated."
    if len(text) <= MAX_TWILIO_WHATSAPP_TEXT_CHARS:
        return [text]
    chunks = []
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


def twilio_auth_credentials() -> tuple[str, str]:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid:
        raise TwilioWhatsAppError("TWILIO_ACCOUNT_SID is not set")
    if not auth_token:
        raise TwilioWhatsAppError("TWILIO_AUTH_TOKEN is not set")
    return account_sid, auth_token


def twilio_from_address(value: str = "") -> str:
    sender = (value or os.environ.get("TWILIO_WHATSAPP_FROM", "")).strip()
    if not sender:
        raise TwilioWhatsAppError("TWILIO_WHATSAPP_FROM is not set")
    return strip_whatsapp_prefix(sender)


def twilio_credentials() -> tuple[str, str, str]:
    account_sid, auth_token = twilio_auth_credentials()
    return account_sid, auth_token, twilio_from_address()


def twilio_send_config_errors(*, recipients: list[str], content_sid: str = "", messaging_service_sid: str = "") -> list[str]:
    errors: list[str] = []
    if not recipients:
        errors.append("no_recipients_configured")
    if not os.environ.get("TWILIO_ACCOUNT_SID", "").strip():
        errors.append("TWILIO_ACCOUNT_SID is not set")
    if not os.environ.get("TWILIO_AUTH_TOKEN", "").strip():
        errors.append("TWILIO_AUTH_TOKEN is not set")
    sender_required = not (content_sid and messaging_service_sid)
    if sender_required and not os.environ.get("TWILIO_WHATSAPP_FROM", "").strip():
        errors.append("TWILIO_WHATSAPP_FROM is not set")
    return errors


def send_message_payload(account_sid: str, auth_token: str, data: dict[str, str]) -> dict[str, Any]:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        url,
        data=urlencode(data).encode("utf-8"),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "opportunity-radar-twilio-whatsapp",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TwilioWhatsAppError(f"Twilio send failed: HTTP {exc.code}: {detail[:500]}") from exc


def send_text(to_address: str, body: str, *, from_address: str = "") -> list[dict[str, Any]]:
    account_sid, auth_token, default_sender = twilio_credentials()
    sender = strip_whatsapp_prefix(from_address or default_sender)
    responses = []
    for chunk in split_message(body):
        responses.append(
            send_message_payload(
                account_sid,
                auth_token,
                {"From": sender, "To": strip_whatsapp_prefix(to_address), "Body": chunk},
            )
        )
    return responses


def send_template(
    to_address: str,
    *,
    content_sid: str,
    content_variables: dict[str, Any],
    messaging_service_sid: str = "",
    from_address: str = "",
) -> list[dict[str, Any]]:
    account_sid, auth_token = twilio_auth_credentials()
    original_body = str(content_variables.get("1", ""))
    chunks = split_message(original_body) if original_body else [""]
    responses = []
    for chunk in chunks:
        variables = dict(content_variables)
        if original_body:
            variables["1"] = chunk
        data = {
            "To": strip_whatsapp_prefix(to_address),
            "ContentSid": content_sid,
            "ContentVariables": json.dumps(variables, ensure_ascii=False),
        }
        if messaging_service_sid:
            data["MessagingServiceSid"] = messaging_service_sid
        else:
            data["From"] = twilio_from_address(from_address)
        responses.append(send_message_payload(account_sid, auth_token, data))
    return responses
