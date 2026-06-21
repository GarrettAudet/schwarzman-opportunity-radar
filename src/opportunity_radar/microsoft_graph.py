from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode


DEFAULT_LOGIN_BASE_URL = "https://login.microsoftonline.com"
DEFAULT_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_TENANT_ID = "common"
DEFAULT_SUBJECT = "OpportunityRadar weekly jobs"


class MicrosoftGraphError(RuntimeError):
    pass


def graph_base_url() -> str:
    return os.environ.get("MICROSOFT_GRAPH_BASE_URL", DEFAULT_GRAPH_BASE_URL).strip().rstrip("/") or DEFAULT_GRAPH_BASE_URL


def login_base_url() -> str:
    return os.environ.get("MICROSOFT_LOGIN_BASE_URL", DEFAULT_LOGIN_BASE_URL).strip().rstrip("/") or DEFAULT_LOGIN_BASE_URL


def tenant_id(value: str = "") -> str:
    return (value or os.environ.get("MICROSOFT_TENANT_ID", DEFAULT_TENANT_ID)).strip() or DEFAULT_TENANT_ID


def graph_resource_root(base_url: str = "") -> str:
    base = (base_url or graph_base_url()).rstrip("/")
    if base.endswith("/v1.0"):
        return base[: -len("/v1.0")]
    if base.endswith("/beta"):
        return base[: -len("/beta")]
    return base


def default_scope(base_url: str = "") -> str:
    return f"{graph_resource_root(base_url)}/Mail.Send offline_access"


def configured_scope(base_url: str = "") -> str:
    return os.environ.get("MICROSOFT_SCOPE", "").strip() or default_scope(base_url)


def token_url(*, tenant: str = "", login_base: str = "") -> str:
    return f"{(login_base or login_base_url()).rstrip('/')}/{tenant_id(tenant)}/oauth2/v2.0/token"


def device_code_url(*, tenant: str = "", login_base: str = "") -> str:
    return f"{(login_base or login_base_url()).rstrip('/')}/{tenant_id(tenant)}/oauth2/v2.0/devicecode"


def microsoft_graph_send_config_errors(*, recipients: list[str]) -> list[str]:
    errors: list[str] = []
    if not recipients:
        errors.append("no_recipients_configured")
    if not os.environ.get("MICROSOFT_CLIENT_ID", "").strip():
        errors.append("MICROSOFT_CLIENT_ID is not set")
    if not os.environ.get("MICROSOFT_REFRESH_TOKEN", "").strip():
        errors.append("MICROSOFT_REFRESH_TOKEN is not set")
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
        raise MicrosoftGraphError(f"Microsoft OAuth request failed: HTTP {exc.code}: {detail[:500]}") from exc


def refresh_access_token(
    *,
    client_id: str = "",
    client_secret: str = "",
    refresh_token: str = "",
    tenant: str = "",
    scope: str = "",
    login_base: str = "",
) -> dict[str, Any]:
    resolved_client_id = (client_id or os.environ.get("MICROSOFT_CLIENT_ID", "")).strip()
    resolved_refresh_token = (refresh_token or os.environ.get("MICROSOFT_REFRESH_TOKEN", "")).strip()
    if not resolved_client_id:
        raise MicrosoftGraphError("MICROSOFT_CLIENT_ID is not set")
    if not resolved_refresh_token:
        raise MicrosoftGraphError("MICROSOFT_REFRESH_TOKEN is not set")

    data = {
        "client_id": resolved_client_id,
        "grant_type": "refresh_token",
        "refresh_token": resolved_refresh_token,
        "scope": scope or configured_scope(),
    }
    secret = (client_secret or os.environ.get("MICROSOFT_CLIENT_SECRET", "")).strip()
    if secret:
        data["client_secret"] = secret
    payload = post_form(token_url(tenant=tenant, login_base=login_base), data, user_agent="opportunity-radar-microsoft-graph")
    if not payload.get("access_token"):
        raise MicrosoftGraphError("Microsoft token response did not include access_token")
    return payload


def request_device_code(
    *,
    client_id: str,
    tenant: str = "",
    scope: str = "",
    login_base: str = "",
    graph_base: str = "",
) -> dict[str, Any]:
    if not client_id.strip():
        raise MicrosoftGraphError("client_id is required")
    return post_form(
        device_code_url(tenant=tenant, login_base=login_base),
        {
            "client_id": client_id.strip(),
            "scope": scope or configured_scope(graph_base),
        },
        user_agent="opportunity-radar-microsoft-auth",
    )


def poll_device_code(
    *,
    client_id: str,
    device_code: str,
    tenant: str = "",
    interval: int = 5,
    expires_in: int = 900,
    login_base: str = "",
) -> dict[str, Any]:
    deadline = time.monotonic() + max(1, expires_in)
    wait_seconds = max(1, interval)
    while time.monotonic() < deadline:
        time.sleep(wait_seconds)
        try:
            payload = post_form(
                token_url(tenant=tenant, login_base=login_base),
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id.strip(),
                    "device_code": device_code,
                },
                user_agent="opportunity-radar-microsoft-auth",
            )
            if payload.get("refresh_token"):
                return payload
            raise MicrosoftGraphError("Microsoft token response did not include refresh_token")
        except MicrosoftGraphError as exc:
            message = str(exc)
            if "authorization_pending" in message:
                continue
            if "slow_down" in message:
                wait_seconds += 5
                continue
            if "authorization_declined" in message or "expired_token" in message or "bad_verification_code" in message:
                raise
            raise
    raise MicrosoftGraphError("Device-code authorization expired before login completed")


def email_payload(*, recipient: str, subject: str, body: str, save_to_sent_items: bool = True) -> dict[str, Any]:
    address = recipient.strip()
    if address.lower().startswith("mailto:"):
        address = address[7:]
    if not address or "@" not in address:
        raise MicrosoftGraphError(f"Invalid email recipient: {recipient!r}")
    return {
        "message": {
            "subject": subject.strip() or DEFAULT_SUBJECT,
            "body": {
                "contentType": "Text",
                "content": body.strip() or "No OpportunityRadar digest body was generated.",
            },
            "toRecipients": [{"emailAddress": {"address": address}}],
        },
        "saveToSentItems": bool(save_to_sent_items),
    }


def send_mail_payload(*, access_token: str, payload: dict[str, Any], graph_base: str = "", user_id: str = "") -> dict[str, Any]:
    if not access_token:
        raise MicrosoftGraphError("access_token is required")
    base = (graph_base or graph_base_url()).rstrip("/")
    actor = user_id.strip() or os.environ.get("MICROSOFT_USER_ID", "").strip()
    endpoint = f"{base}/users/{actor}/sendMail" if actor else f"{base}/me/sendMail"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "opportunity-radar-microsoft-graph",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return {"status": response.status, "id": f"graph:{response.status}"}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MicrosoftGraphError(f"Microsoft Graph sendMail failed: HTTP {exc.code}: {detail[:500]}") from exc


def send_email(to_address: str, body: str, *, subject: str = "") -> dict[str, Any]:
    token_payload = refresh_access_token()
    save_to_sent = os.environ.get("MICROSOFT_SAVE_TO_SENT_ITEMS", "true").strip().lower() not in {"0", "false", "no", "off"}
    payload = email_payload(
        recipient=to_address,
        subject=subject or os.environ.get("OPPORTUNITY_EMAIL_SUBJECT", DEFAULT_SUBJECT),
        body=body,
        save_to_sent_items=save_to_sent,
    )
    return send_mail_payload(access_token=str(token_payload["access_token"]), payload=payload)
