from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: object, max_chars: int = 5000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_chars]


def stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_key_part(value: object) -> str:
    text = clean_text(value, max_chars=300).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


@dataclass(frozen=True)
class JobPosting:
    source_id: str
    source_name: str
    external_id: str
    title: str
    company: str
    location_text: str
    city: str
    canonical_url: str
    apply_url: str = ""
    remote: bool = False
    department: str = ""
    employment_type: str = ""
    posted_at: str = ""
    description_text: str = ""
    tags: list[str] = field(default_factory=list)
    salary_text: str = ""
    content_hash: str = ""
    fetched_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        if self.content_hash:
            return
        payload = {
            "source_id": self.source_id,
            "external_id": self.external_id,
            "title": self.title,
            "company": self.company,
            "location_text": self.location_text,
            "canonical_url": self.canonical_url,
            "description_text": clean_text(self.description_text, max_chars=2000),
        }
        object.__setattr__(self, "content_hash", stable_hash(payload))

    @property
    def stable_key(self) -> str:
        if self.source_id and self.external_id:
            return f"{normalized_key_part(self.source_id)}:{normalized_key_part(self.external_id)}"
        if self.canonical_url:
            return f"url:{stable_hash({'url': self.canonical_url})[:24]}"
        fallback = "|".join([self.company, self.title, self.city or self.location_text])
        return f"job:{stable_hash({'fallback': fallback.lower()})[:24]}"

    def compact_for_llm(self) -> dict[str, Any]:
        return {
            "key": self.stable_key,
            "title": self.title,
            "company": self.company,
            "city": self.city,
            "location": self.location_text,
            "department": self.department,
            "employment_type": self.employment_type,
            "posted_at": self.posted_at,
            "tags": self.tags[:12],
            "salary": self.salary_text,
            "description": clean_text(self.description_text, max_chars=1200),
            "url": self.canonical_url or self.apply_url,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RankedOpportunity:
    job: JobPosting
    score: float
    include: bool
    scholar_fit_reason: str
    why_cool: str
    risk_flags: list[str] = field(default_factory=list)
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["job"] = self.job.to_dict()
        return payload


@dataclass(frozen=True)
class SourceResult:
    source_id: str
    source_name: str
    ok: bool
    fetched_count: int = 0
    normalized_count: int = 0
    elapsed_ms: int = 0
    error: str = ""
    etag: str = ""
    last_modified: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecipientResult:
    recipient: str
    ok: bool
    provider: str
    message_ids: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DigestRun:
    run_id: str
    week_key: str
    dry_run: bool
    send_requested: bool
    started_at: str
    finished_at: str
    source_results: list[SourceResult]
    candidate_count: int
    selected_jobs: list[RankedOpportunity]
    recipient_results: list[RecipientResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    state_summary: dict[str, Any] = field(default_factory=dict)
    digest_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "week_key": self.week_key,
            "dry_run": self.dry_run,
            "send_requested": self.send_requested,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "source_results": [item.to_dict() for item in self.source_results],
            "candidate_count": self.candidate_count,
            "selected_jobs": [item.to_dict() for item in self.selected_jobs],
            "recipient_results": [item.to_dict() for item in self.recipient_results],
            "errors": list(self.errors),
            "state_summary": dict(self.state_summary),
            "digest_text": self.digest_text,
        }
