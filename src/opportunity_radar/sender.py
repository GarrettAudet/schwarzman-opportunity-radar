from __future__ import annotations

from typing import Protocol

from .microsoft_graph import send_email
from .models import RecipientResult
from .twilio_whatsapp import send_template, send_text


DEFAULT_SEND_PROVIDER = "twilio_whatsapp"


def normalize_send_provider(value: str) -> str:
    text = value.strip().lower()
    if not text:
        return DEFAULT_SEND_PROVIDER
    aliases = {
        "email": "microsoft_graph_email",
        "graph_email": "microsoft_graph_email",
        "microsoft_graph": "microsoft_graph_email",
        "outlook": "microsoft_graph_email",
        "outlook_email": "microsoft_graph_email",
        "twilio": "twilio_whatsapp",
        "whatsapp": "twilio_whatsapp",
    }
    return aliases.get(text, text)


class Sender(Protocol):
    provider: str

    def send(self, recipient: str, message: str) -> RecipientResult:
        ...


class DryRunSender:
    provider = "dry_run"

    def send(self, recipient: str, message: str) -> RecipientResult:
        return RecipientResult(recipient=recipient, ok=True, provider=self.provider, message_ids=["dry-run"])


class TwilioWhatsAppSender:
    provider = "twilio_whatsapp"

    def __init__(self, *, content_sid: str = "", messaging_service_sid: str = "") -> None:
        self.content_sid = content_sid
        self.messaging_service_sid = messaging_service_sid

    def send(self, recipient: str, message: str) -> RecipientResult:
        try:
            if self.content_sid:
                responses = send_template(
                    recipient,
                    content_sid=self.content_sid,
                    content_variables={"1": message},
                    messaging_service_sid=self.messaging_service_sid,
                )
            else:
                responses = send_text(recipient, message)
            ids = [str(response.get("sid", "")) for response in responses if response.get("sid")]
            return RecipientResult(recipient=recipient, ok=True, provider=self.provider, message_ids=ids)
        except Exception as exc:
            return RecipientResult(recipient=recipient, ok=False, provider=self.provider, error=f"{type(exc).__name__}: {exc}")


class MicrosoftGraphEmailSender:
    provider = "microsoft_graph_email"

    def __init__(self, *, subject: str = "") -> None:
        self.subject = subject

    def send(self, recipient: str, message: str) -> RecipientResult:
        try:
            response = send_email(recipient, message, subject=self.subject)
            message_id = str(response.get("id", "")) if isinstance(response, dict) else ""
            ids = [message_id] if message_id else []
            return RecipientResult(recipient=recipient, ok=True, provider=self.provider, message_ids=ids)
        except Exception as exc:
            return RecipientResult(recipient=recipient, ok=False, provider=self.provider, error=f"{type(exc).__name__}: {exc}")
