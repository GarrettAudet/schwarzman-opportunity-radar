from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any
from urllib.parse import quote, urlencode


DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
DEFAULT_SHEETS_READ_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
DEFAULT_GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
DEFAULT_SHEETS_API_BASE_URL = "https://sheets.googleapis.com/v4"
DEFAULT_EMAIL_SUBJECT = "OpportunityRadar weekly jobs"
DEFAULT_RECIPIENTS_RANGE = "Recipients!A:C"
INACTIVE_STATUSES = {"0", "false", "inactive", "no", "off", "remove", "removed", "delete", "deleted", "unsubscribe", "unsubscribed"}


class GoogleWorkspaceError(RuntimeError):
    pass


def google_token_uri() -> str:
    return os.environ.get("GOOGLE_TOKEN_URI", DEFAULT_TOKEN_URI).strip() or DEFAULT_TOKEN_URI


def gmail_api_base_url() -> str:
    return os.environ.get("GOOGLE_GMAIL_API_BASE_URL", DEFAULT_GMAIL_API_BASE_URL).strip().rstrip("/") or DEFAULT_GMAIL_API_BASE_URL


def sheets_api_base_url() -> str:
    return os.environ.get("GOOGLE_SHEETS_API_BASE_URL", DEFAULT_SHEETS_API_BASE_URL).strip().rstrip("/") or DEFAULT_SHEETS_API_BASE_URL


def configured_google_scopes(include_sheets: bool = True) -> list[str]:
    configured = os.environ.get("GOOGLE_OAUTH_SCOPES", "").strip()
    if configured:
        return [scope for scope in configured.split() if scope.strip()]
    scopes = [DEFAULT_GMAIL_SEND_SCOPE]
    if include_sheets:
        scopes.append(DEFAULT_SHEETS_READ_SCOPE)
    return scopes


def gmail_send_config_errors(*, recipients: list[str], allow_sheet: bool = False) -> list[str]:
    errors: list[str] = []
    if not recipients and not allow_sheet:
        errors.append("no_recipients_configured")
    if not os.environ.get("GOOGLE_CLIENT_ID", "").strip():
        errors.append("GOOGLE_CLIENT_ID is not set")
    if not os.environ.get("GOOGLE_CLIENT_SECRET", "").strip():
        errors.append("GOOGLE_CLIENT_SECRET is not set")
    if not os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip():
        errors.append("GOOGLE_REFRESH_TOKEN is not set")
    return errors


def post_form(url: str, data: dict[str, str], *, user_agent: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urlencode(data).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": user_agent,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GoogleWorkspaceError(f"Google OAuth request failed: HTTP {exc.code}: {detail[:500]}") from exc


def refresh_google_access_token(
    *,
    client_id: str = "",
    client_secret: str = "",
    refresh_token: str = "",
    token_uri: str = "",
) -> dict[str, Any]:
    resolved_client_id = (client_id or os.environ.get("GOOGLE_CLIENT_ID", "")).strip()
    resolved_client_secret = (client_secret or os.environ.get("GOOGLE_CLIENT_SECRET", "")).strip()
    resolved_refresh_token = (refresh_token or os.environ.get("GOOGLE_REFRESH_TOKEN", "")).strip()
    if not resolved_client_id:
        raise GoogleWorkspaceError("GOOGLE_CLIENT_ID is not set")
    if not resolved_client_secret:
        raise GoogleWorkspaceError("GOOGLE_CLIENT_SECRET is not set")
    if not resolved_refresh_token:
        raise GoogleWorkspaceError("GOOGLE_REFRESH_TOKEN is not set")
    payload = post_form(
        token_uri or google_token_uri(),
        {
            "client_id": resolved_client_id,
            "client_secret": resolved_client_secret,
            "refresh_token": resolved_refresh_token,
            "grant_type": "refresh_token",
        },
        user_agent="opportunity-radar-google-oauth",
    )
    if not payload.get("access_token"):
        raise GoogleWorkspaceError("Google token response did not include access_token")
    return payload


def normalize_email_address(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("mailto:"):
        text = text[7:].strip()
    _, address = parseaddr(text)
    address = address.strip()
    if "@" not in address or address.startswith("@") or address.endswith("@"):
        return ""
    return address


def gmail_message_payload(*, recipient: str, subject: str, body: str, from_address: str = "") -> dict[str, str]:
    address = normalize_email_address(recipient)
    if not address:
        raise GoogleWorkspaceError(f"Invalid email recipient: {recipient!r}")
    message = EmailMessage()
    sender = (from_address or os.environ.get("GOOGLE_GMAIL_FROM", "") or os.environ.get("OPPORTUNITY_EMAIL_FROM", "")).strip()
    if sender:
        message["From"] = sender
    message["To"] = address
    message["Subject"] = subject.strip() or os.environ.get("OPPORTUNITY_EMAIL_SUBJECT", DEFAULT_EMAIL_SUBJECT)
    message.set_content(body.strip() or "No OpportunityRadar digest body was generated.")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return {"raw": raw}


def google_api_json_request(url: str, *, access_token: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "opportunity-radar-google-workspace",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {"status": response.status}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GoogleWorkspaceError(f"Google API request failed: HTTP {exc.code}: {detail[:500]}") from exc


def send_gmail_message(
    to_address: str,
    body: str,
    *,
    access_token: str,
    subject: str = "",
    from_address: str = "",
    api_base_url: str = "",
) -> dict[str, Any]:
    payload = gmail_message_payload(recipient=to_address, subject=subject, body=body, from_address=from_address)
    url = f"{(api_base_url or gmail_api_base_url()).rstrip('/')}/users/me/messages/send"
    return google_api_json_request(url, access_token=access_token, method="POST", payload=payload)


def read_google_sheet_values(
    *,
    spreadsheet_id: str,
    range_name: str,
    access_token: str,
    api_base_url: str = "",
) -> list[list[str]]:
    sheet_id = spreadsheet_id.strip()
    if not sheet_id:
        raise GoogleWorkspaceError("GOOGLE_RECIPIENTS_SHEET_ID is not set")
    selected_range = range_name.strip() or DEFAULT_RECIPIENTS_RANGE
    url = f"{(api_base_url or sheets_api_base_url()).rstrip('/')}/spreadsheets/{quote(sheet_id, safe='')}/values/{quote(selected_range, safe='')}"
    payload = google_api_json_request(url, access_token=access_token)
    values = payload.get("values", [])
    if not isinstance(values, list):
        return []
    return [[str(cell).strip() for cell in row] for row in values if isinstance(row, list)]


def parse_recipient_rows(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    first = [cell.strip().lower().replace(" ", "_") for cell in rows[0]]
    has_header = "email" in first or "email_address" in first or "address" in first
    email_index = 0
    status_index: int | None = None
    start_index = 0
    if has_header:
        start_index = 1
        for candidate in ("email", "email_address", "address"):
            if candidate in first:
                email_index = first.index(candidate)
                break
        if "status" in first:
            status_index = first.index("status")
    recipients: list[str] = []
    seen: set[str] = set()
    for row in rows[start_index:]:
        if email_index >= len(row):
            continue
        if status_index is not None and status_index < len(row) and row[status_index].strip().lower() in INACTIVE_STATUSES:
            continue
        address = normalize_email_address(row[email_index])
        key = address.lower()
        if address and key not in seen:
            recipients.append(address)
            seen.add(key)
    return recipients


def load_google_sheet_recipients(*, spreadsheet_id: str, range_name: str = "") -> list[str]:
    token_payload = refresh_google_access_token()
    rows = read_google_sheet_values(
        spreadsheet_id=spreadsheet_id,
        range_name=range_name or os.environ.get("GOOGLE_RECIPIENTS_RANGE", DEFAULT_RECIPIENTS_RANGE),
        access_token=str(token_payload["access_token"]),
    )
    recipients = parse_recipient_rows(rows)
    if not recipients:
        raise GoogleWorkspaceError("Google recipients sheet did not contain any active email recipients")
    return recipients
