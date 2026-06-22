from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Any


DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
DEFAULT_EMAIL_SUBJECT = "OpportunityRadar weekly jobs"


class SmtpEmailError(RuntimeError):
    pass


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value not in {"0", "false", "no", "off"}


def smtp_host() -> str:
    return os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST).strip() or DEFAULT_SMTP_HOST


def smtp_port() -> int:
    return int(os.environ.get("SMTP_PORT", str(DEFAULT_SMTP_PORT)))


def smtp_username() -> str:
    return os.environ.get("SMTP_USERNAME", os.environ.get("GMAIL_SMTP_USERNAME", "")).strip()


def smtp_password() -> str:
    return os.environ.get("SMTP_APP_PASSWORD", os.environ.get("SMTP_PASSWORD", os.environ.get("GMAIL_APP_PASSWORD", ""))).strip()


def smtp_from_address(value: str = "") -> str:
    return (
        value
        or os.environ.get("SMTP_FROM", "")
        or os.environ.get("GOOGLE_GMAIL_FROM", "")
        or os.environ.get("OPPORTUNITY_EMAIL_FROM", "")
        or smtp_username()
    ).strip()


def smtp_send_config_errors(*, recipients: list[str]) -> list[str]:
    errors: list[str] = []
    if not recipients:
        errors.append("no_recipients_configured")
    if not smtp_username():
        errors.append("SMTP_USERNAME is not set")
    if not smtp_password():
        errors.append("SMTP_APP_PASSWORD is not set")
    if not smtp_from_address():
        errors.append("SMTP_FROM is not set")
    return errors


def normalize_email_address(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("mailto:"):
        text = text[7:].strip()
    _, address = parseaddr(text)
    address = address.strip()
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        return ""
    return address


def smtp_message(
    *,
    recipient: str,
    subject: str,
    body: str,
    from_address: str = "",
) -> EmailMessage:
    address = normalize_email_address(recipient)
    if not address:
        raise SmtpEmailError(f"Invalid email recipient: {recipient!r}")
    sender = smtp_from_address(from_address)
    if not sender:
        raise SmtpEmailError("SMTP_FROM is not set")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = address
    message["Subject"] = subject.strip() or os.environ.get("OPPORTUNITY_EMAIL_SUBJECT", DEFAULT_EMAIL_SUBJECT)
    message["Message-ID"] = make_msgid(domain="opportunity-radar.local")
    message.set_content(body.strip() or "No OpportunityRadar digest body was generated.")
    return message


def send_smtp_email(
    to_address: str,
    body: str,
    *,
    subject: str = "",
    from_address: str = "",
    host: str = "",
    port: int | None = None,
) -> dict[str, Any]:
    username = smtp_username()
    password = smtp_password()
    if not username:
        raise SmtpEmailError("SMTP_USERNAME is not set")
    if not password:
        raise SmtpEmailError("SMTP_APP_PASSWORD is not set")
    message = smtp_message(recipient=to_address, subject=subject, body=body, from_address=from_address)
    resolved_host = host or smtp_host()
    resolved_port = port if port is not None else smtp_port()
    use_ssl = env_bool("SMTP_USE_SSL", False)
    use_starttls = env_bool("SMTP_USE_STARTTLS", True)
    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(resolved_host, resolved_port, timeout=30, context=context) as client:
            client.login(username, password)
            client.send_message(message)
    else:
        with smtplib.SMTP(resolved_host, resolved_port, timeout=30) as client:
            if use_starttls:
                client.starttls(context=context)
            client.login(username, password)
            client.send_message(message)
    return {"id": str(message["Message-ID"]), "to": message["To"]}
