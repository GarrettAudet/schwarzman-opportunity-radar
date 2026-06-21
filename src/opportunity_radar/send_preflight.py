from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_runtime_config
from .microsoft_graph import microsoft_graph_send_config_errors
from .sender import normalize_send_provider
from .twilio_whatsapp import twilio_send_config_errors


def check_send_ready(root: Path) -> dict[str, Any]:
    config = load_runtime_config(root)
    provider = normalize_send_provider(config.send_provider)
    uses_template = False
    uses_messaging_service = False
    requires_from = False
    if provider == "microsoft_graph_email":
        errors = microsoft_graph_send_config_errors(recipients=config.recipients)
    elif provider == "twilio_whatsapp":
        errors = twilio_send_config_errors(
            recipients=config.recipients,
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
        "recipient_count": len(config.recipients),
        "uses_template": uses_template,
        "uses_messaging_service": uses_messaging_service,
        "requires_from": requires_from,
        "subject": config.email_subject,
        "errors": errors,
    }
