from __future__ import annotations

from typing import Protocol

from .models import RecipientResult
from .twilio_whatsapp import send_template, send_text


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
