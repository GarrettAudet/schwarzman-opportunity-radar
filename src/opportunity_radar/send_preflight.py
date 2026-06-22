from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_runtime_config
from .google_workspace import gmail_send_config_errors, load_google_sheet_recipients
from .microsoft_graph import microsoft_graph_send_config_errors
from .sender import normalize_send_provider
from .smtp_email import smtp_send_config_errors
from .twilio_whatsapp import twilio_send_config_errors


def check_send_ready(root: Path) -> dict[str, Any]:
    config = load_runtime_config(root)
    provider = normalize_send_provider(config.send_provider)
    uses_template = False
    uses_messaging_service = False
    requires_from = False
    recipient_source = "env"
    recipients = list(config.recipients)
    recipient_errors: list[str] = []
    if provider == "gmail_email" and config.google_recipients_sheet_id:
        recipient_source = "google_sheet"
        base_errors = gmail_send_config_errors(recipients=[], allow_sheet=True)
        if not base_errors:
            try:
                recipients = load_google_sheet_recipients(
                    spreadsheet_id=config.google_recipients_sheet_id,
                    range_name=config.google_recipients_range,
                )
            except Exception as exc:
                recipients = []
                recipient_errors.append(f"recipient_load_failed:{type(exc).__name__}: {exc}")
    if provider == "gmail_smtp":
        errors = smtp_send_config_errors(recipients=recipients)
    elif provider == "gmail_email":
        errors = gmail_send_config_errors(recipients=recipients, allow_sheet=bool(config.google_recipients_sheet_id)) + recipient_errors
    elif provider == "microsoft_graph_email":
        errors = microsoft_graph_send_config_errors(recipients=recipients)
    elif provider == "twilio_whatsapp":
        errors = twilio_send_config_errors(
            recipients=recipients,
            content_sid=config.twilio_content_sid,
            messaging_service_sid=config.twilio_messaging_service_sid,
        )
        uses_template = bool(config.twilio_content_sid)
        uses_messaging_service = bool(config.twilio_messaging_service_sid)
        requires_from = not (uses_template and uses_messaging_service)
    else:
        errors = [f"unsupported_send_provider:{config.send_provider}"]
    return {
        "ok": not errors,
        "provider": provider,
        "recipient_count": len(recipients),
        "recipient_source": recipient_source,
        "recipient_sheet_id": config.google_recipients_sheet_id if recipient_source == "google_sheet" else "",
        "uses_template": uses_template,
        "uses_messaging_service": uses_messaging_service,
        "requires_from": requires_from,
        "subject": config.email_subject,
        "errors": errors,
    }
