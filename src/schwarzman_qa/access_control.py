from __future__ import annotations

import base64
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote
import urllib.error
import urllib.request


APPROVED = "approved"
BLOCKED = "blocked"
PENDING = "pending"


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    status: str
    reason: str
    wa_id: str
    phone_number: str


class AccessStore(Protocol):
    def load(self) -> dict[str, Any]:
        ...

    def save(self, payload: dict[str, Any]) -> None:
        ...


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_identifier(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "@" in text:
        text = text.split("@", 1)[0]
    digits = re.sub(r"\D+", "", text)
    return digits or text.lower()


def parse_identifier_set(value: str) -> set[str]:
    return {item for item in (normalize_identifier(part) for part in value.split(",")) if item}


def empty_payload() -> dict[str, Any]:
    return {"version": 1, "updated_at": now_iso(), "users": {}}


class FileAccessStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return empty_payload()
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload["updated_at"] = now_iso()
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class GithubAccessStore:
    def __init__(self, repo: str, path: str, token: str, ref: str = "main") -> None:
        self.repo = repo
        self.path = path.strip("/")
        self.token = token
        self.ref = ref

    def _url(self) -> str:
        return f"https://api.github.com/repos/{self.repo}/contents/{quote(self.path)}?ref={quote(self.ref)}"

    def _request(self, url: str, *, method: str = "GET", data: bytes | None = None) -> urllib.request.Request:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "schwarzman-qna-access-store",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        return urllib.request.Request(url, data=data, headers=headers, method=method)

    def load_with_sha(self) -> tuple[dict[str, Any], str]:
        try:
            with urllib.request.urlopen(self._request(self._url()), timeout=30) as response:
                item = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return empty_payload(), ""
            raise
        content = base64.b64decode(str(item.get("content", "")).encode("utf-8")).decode("utf-8")
        return json.loads(content), str(item.get("sha", ""))

    def load(self) -> dict[str, Any]:
        payload, _sha = self.load_with_sha()
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        _current, sha = self.load_with_sha()
        payload["updated_at"] = now_iso()
        body: dict[str, Any] = {
            "message": "Update WhatsApp access control",
            "content": base64.b64encode(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")).decode("ascii"),
            "branch": self.ref,
        }
        if sha:
            body["sha"] = sha
        put_url = f"https://api.github.com/repos/{self.repo}/contents/{quote(self.path)}"
        with urllib.request.urlopen(
            self._request(put_url, method="PUT", data=json.dumps(body).encode("utf-8")),
            timeout=30,
        ):
            return


class WhatsAppAccessControl:
    def __init__(
        self,
        store: AccessStore,
        *,
        invite_code: str = "",
        allowed_numbers: set[str] | None = None,
        blocked_numbers: set[str] | None = None,
        allowed_wa_ids: set[str] | None = None,
        blocked_wa_ids: set[str] | None = None,
    ) -> None:
        self.store = store
        self.invite_code = invite_code.strip()
        self.allowed_numbers = allowed_numbers or set()
        self.blocked_numbers = blocked_numbers or set()
        self.allowed_wa_ids = allowed_wa_ids or set()
        self.blocked_wa_ids = blocked_wa_ids or set()

    def check(self, wa_id: object, phone_number: object = "") -> AccessDecision:
        wa_id_norm = normalize_identifier(wa_id)
        phone_norm = normalize_identifier(phone_number) or wa_id_norm
        if wa_id_norm in self.blocked_wa_ids or phone_norm in self.blocked_numbers:
            return AccessDecision(False, BLOCKED, "blocked_by_env", wa_id_norm, phone_norm)
        if wa_id_norm in self.allowed_wa_ids or phone_norm in self.allowed_numbers:
            return AccessDecision(True, APPROVED, "allowed_by_env", wa_id_norm, phone_norm)

        user = self._user(wa_id_norm)
        status = str(user.get("status", PENDING))
        if status == BLOCKED:
            return AccessDecision(False, BLOCKED, "blocked", wa_id_norm, phone_norm)
        if status == APPROVED:
            return AccessDecision(True, APPROVED, "approved", wa_id_norm, phone_norm)
        return AccessDecision(False, PENDING, "not_enrolled", wa_id_norm, phone_norm)

    def redeem_invite(
        self,
        code: str,
        *,
        wa_id: object,
        phone_number: object = "",
        profile_name: str = "",
    ) -> AccessDecision:
        wa_id_norm = normalize_identifier(wa_id)
        phone_norm = normalize_identifier(phone_number) or wa_id_norm
        current = self.check(wa_id_norm, phone_norm)
        if current.status == BLOCKED:
            return current
        if not self.invite_code or not secrets.compare_digest(code.strip(), self.invite_code):
            self.record_seen(wa_id_norm, phone_norm, profile_name=profile_name)
            return AccessDecision(False, PENDING, "invalid_invite_code", wa_id_norm, phone_norm)
        self.approve(wa_id_norm, phone_norm, profile_name=profile_name, source="invite_code")
        return AccessDecision(True, APPROVED, "invite_code_redeemed", wa_id_norm, phone_norm)

    def record_seen(self, wa_id: object, phone_number: object = "", *, profile_name: str = "") -> None:
        wa_id_norm = normalize_identifier(wa_id)
        if not wa_id_norm:
            return
        phone_norm = normalize_identifier(phone_number) or wa_id_norm
        payload = self.store.load()
        user = self._ensure_user(payload, wa_id_norm, phone_norm)
        user["last_seen_at"] = now_iso()
        if profile_name:
            user["profile_name"] = profile_name
        self.store.save(payload)

    def approve(
        self,
        wa_id: object,
        phone_number: object = "",
        *,
        profile_name: str = "",
        source: str = "manual",
        notes: str = "",
    ) -> None:
        self._set_status(wa_id, phone_number, APPROVED, profile_name=profile_name, source=source, notes=notes)

    def block(self, wa_id: object, phone_number: object = "", *, profile_name: str = "", notes: str = "") -> None:
        self._set_status(wa_id, phone_number, BLOCKED, profile_name=profile_name, source="manual", notes=notes)

    def revoke(self, wa_id: object, phone_number: object = "", *, notes: str = "") -> None:
        self._set_status(wa_id, phone_number, PENDING, source="manual", notes=notes)

    def users(self) -> list[dict[str, Any]]:
        payload = self.store.load()
        return sorted(payload.get("users", {}).values(), key=lambda item: str(item.get("wa_id", "")))

    def _user(self, wa_id: str) -> dict[str, Any]:
        payload = self.store.load()
        return payload.get("users", {}).get(wa_id, {})

    def _ensure_user(self, payload: dict[str, Any], wa_id: str, phone_number: str) -> dict[str, Any]:
        users = payload.setdefault("users", {})
        user = users.setdefault(
            wa_id,
            {
                "wa_id": wa_id,
                "phone_number": phone_number,
                "status": PENDING,
                "first_seen_at": now_iso(),
                "last_seen_at": now_iso(),
                "profile_name": "",
                "source": "",
                "notes": "",
            },
        )
        if phone_number and not user.get("phone_number"):
            user["phone_number"] = phone_number
        return user

    def _set_status(
        self,
        wa_id: object,
        phone_number: object,
        status: str,
        *,
        profile_name: str = "",
        source: str = "",
        notes: str = "",
    ) -> None:
        wa_id_norm = normalize_identifier(wa_id)
        if not wa_id_norm:
            raise ValueError("wa_id_required")
        phone_norm = normalize_identifier(phone_number) or wa_id_norm
        payload = self.store.load()
        user = self._ensure_user(payload, wa_id_norm, phone_norm)
        user["status"] = status
        user["last_seen_at"] = now_iso()
        if profile_name:
            user["profile_name"] = profile_name
        if source:
            user["source"] = source
        if notes:
            user["notes"] = notes
        if status == APPROVED:
            user["approved_at"] = now_iso()
        elif status == BLOCKED:
            user["blocked_at"] = now_iso()
        self.store.save(payload)


def access_control_from_env(root: Path) -> WhatsAppAccessControl:
    github_repo = os.environ.get("GITHUB_ACCESS_REPO", "").strip()
    github_token = os.environ.get("GITHUB_ACCESS_TOKEN", "").strip()
    if github_repo and github_token:
        store: AccessStore = GithubAccessStore(
            github_repo,
            os.environ.get("GITHUB_ACCESS_PATH", "whatsapp-access.json"),
            github_token,
            os.environ.get("GITHUB_ACCESS_REF", "main"),
        )
    else:
        store_path = Path(os.environ.get("WHATSAPP_ACCESS_STORE_PATH", "data/whatsapp/access-control.json"))
        if not store_path.is_absolute():
            store_path = root / store_path
        store = FileAccessStore(store_path)

    return WhatsAppAccessControl(
        store,
        invite_code=os.environ.get("WHATSAPP_INVITE_CODE", ""),
        allowed_numbers=parse_identifier_set(os.environ.get("WHATSAPP_ALLOWED_NUMBERS", "")),
        blocked_numbers=parse_identifier_set(os.environ.get("WHATSAPP_BLOCKED_NUMBERS", "")),
        allowed_wa_ids=parse_identifier_set(os.environ.get("WHATSAPP_ALLOWED_WA_IDS", "")),
        blocked_wa_ids=parse_identifier_set(os.environ.get("WHATSAPP_BLOCKED_WA_IDS", "")),
    )
