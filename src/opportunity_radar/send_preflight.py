from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import load_runtime_config
from .twilio_whatsapp import twilio_send_config_errors


def check_send_ready(root: Path) -> dict[str, Any]:
    config = load_runtime_config(root)
    errors = twilio_send_config_errors(
        recipients=config.recipients,
        content_sid=config.twilio_content_sid,
        messaging_service_sid=config.twilio_messaging_service_sid,
    )
    uses_template = bool(config.twilio_content_sid)
    uses_messaging_service = bool(config.twilio_messaging_service_sid)
    return {
        "ok": not errors,
        "provider": "twilio_whatsapp",
        "recipient_count": len(config.recipients),
        "uses_template": uses_template,
        "uses_messaging_service": uses_messaging_service,
        "requires_from": not (uses_template and uses_messaging_service),
        "errors": errors,
    }
