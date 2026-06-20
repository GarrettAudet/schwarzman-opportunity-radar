from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .cities import city_allowed_for_location, canonical_city_set
from .fetch import FetchResponse, conditional_headers, fetch_url
from .models import JobPosting, SourceResult, clean_text, now_iso


FetchFn = Callable[[str], FetchResponse]


def strip_html(value: object) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<(script|style).*?</\1>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return clean_text(html.unescape(text), max_chars=12000)


def parse_date(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if isinstance(value, (int, float)) or text.isdigit():
        number = int(value)
        if number > 10_000_000_000:
            number = number // 1000
        return datetime.fromtimestamp(number, tz=timezone.utc).isoformat(timespec="seconds")
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        pass
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return text[:80]


def source_cities(source: dict[str, Any], default_cities: set[str]) -> set[str]:
    return canonical_city_set(source.get("cities") or list(default_cities))


def normalize_job(
    source: dict[str, Any],
    raw: dict[str, Any],
    *,
    location_text: str,
    default_cities: set[str],
    allow_global_remote: bool,
) -> JobPosting | None:
    allowed_cities = source_cities(source, default_cities)
    allowed, city, remote = city_allowed_for_location(
        location_text,
        allowed_cities=allowed_cities,
        allow_global_remote=bool(source.get("allow_global_remote", allow_global_remote)),
    )
    if not allowed:
        return None
    company = clean_text(raw.get("company") or source.get("company") or source.get("name") or "", max_chars=180)
    title = clean_text(raw.get("title"), max_chars=220)
    canonical_url = clean_text(raw.get("canonical_url") or raw.get("apply_url") or raw.get("url"), max_chars=1200)
    if not title or not company or not canonical_url:
        return None
    description = strip_html(raw.get("description_text") or raw.get("description") or raw.get("content"))
    return JobPosting(
        source_id=clean_text(source.get("id"), max_chars=120),
        source_name=clean_text(source.get("name") or source.get("id"), max_chars=180),
        external_id=clean_text(raw.get("external_id") or raw.get("id") or canonical_url, max_chars=300),
        title=title,
        company=company,
        location_text=location_text,
        city=city,
        canonical_url=canonical_url,
        apply_url=clean_text(raw.get("apply_url") or canonical_url, max_chars=1200),
        remote=remote,
        department=clean_text(raw.get("department") or raw.get("team"), max_chars=180),
        employment_type=clean_text(raw.get("employment_type") or raw.get("commitment"), max_chars=120),
        posted_at=parse_date(raw.get("posted_at") or raw.get("created_at")),
        description_text=description,
        tags=[clean_text(tag, max_chars=80) for tag in raw.get("tags", []) if clean_text(tag, max_chars=80)],
        salary_text=clean_text(raw.get("salary_text") or raw.get("salary"), max_chars=240),
        fetched_at=now_iso(),
    )


def parse_greenhouse(payload: Any, source: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        jobs = payload.get("jobs")
        if jobs is None and payload.get("id") is not None:
            jobs = [payload]
        elif jobs is None:
            jobs = []
    else:
        jobs = payload
    parsed: list[dict[str, Any]] = []
    for job in jobs or []:
        if not isinstance(job, dict):
            continue
        location = job.get("location") or {}
        departments = job.get("departments") or []
        department = ""
        if departments and isinstance(departments[0], dict):
            department = str(departments[0].get("name", ""))
        parsed.append(
            {
                "external_id": job.get("id"),
                "title": job.get("title"),
                "company": source.get("company"),
                "location": location.get("name") if isinstance(location, dict) else location,
                "canonical_url": job.get("absolute_url"),
                "apply_url": job.get("absolute_url"),
                "department": department,
                "posted_at": job.get("first_published") or job.get("published_at"),
                "updated_at": job.get("updated_at"),
                "description_text": job.get("content"),
                "tags": [department] if department else [],
            }
        )
    return parsed


def greenhouse_board_token(source: dict[str, Any]) -> str:
    explicit = clean_text(source.get("board_token"), max_chars=200)
    if explicit:
        return explicit
    url = clean_text(source.get("url"), max_chars=1200)
    if not url:
        raise ValueError("greenhouse sources require board_token or url")
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    match = re.search(r"(?:^|/)boards/([^/]+)/jobs(?:/|$)", path)
    if match:
        return match.group(1)
    parts = [part for part in path.split("/") if part]
    if parsed.netloc.endswith("greenhouse.io") and parts:
        return parts[0]
    raise ValueError(f"could not derive Greenhouse board token from {url}")


def greenhouse_index_url(source: dict[str, Any]) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{greenhouse_board_token(source)}/jobs"


def greenhouse_detail_url(source: dict[str, Any], job_id: object) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{greenhouse_board_token(source)}/jobs/{job_id}"


def lever_board_token(source: dict[str, Any]) -> str:
    explicit = clean_text(source.get("board_token"), max_chars=200)
    if explicit:
        return explicit
    url = clean_text(source.get("url"), max_chars=1200)
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc == "jobs.lever.co" and parts:
        return parts[0]
    raise ValueError("lever sources require board_token or jobs.lever.co url")


def lever_index_url(source: dict[str, Any]) -> str:
    return f"https://api.lever.co/v0/postings/{lever_board_token(source)}?mode=json"


def ashby_board_token(source: dict[str, Any]) -> str:
    explicit = clean_text(source.get("board_token"), max_chars=200)
    if explicit:
        return explicit
    url = clean_text(source.get("url"), max_chars=1200)
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc == "jobs.ashbyhq.com" and parts:
        return parts[0]
    raise ValueError("ashby sources require board_token or jobs.ashbyhq.com url")


def ashby_index_url(source: dict[str, Any]) -> str:
    return f"https://api.ashbyhq.com/posting-api/job-board/{ashby_board_token(source)}"


def fetch_greenhouse_index(
    source: dict[str, Any],
    *,
    cache: dict[str, Any] | None = None,
    fetcher: Callable[..., FetchResponse] = fetch_url,
) -> tuple[list[dict[str, Any]], SourceResult, dict[str, str]]:
    started = time.perf_counter()
    source_id = str(source.get("id") or source.get("name") or "source").strip()
    source_name = str(source.get("name") or source_id).strip()
    response_headers: dict[str, str] = {}
    try:
        response = fetcher(greenhouse_index_url(source), headers=conditional_headers(cache or {}), timeout=int(source.get("timeout", 30)))
        response_headers = {
            "etag": response.headers.get("etag", ""),
            "last_modified": response.headers.get("last-modified", ""),
        }
        raw_jobs = [] if response.status == 304 else parse_greenhouse(json.loads(response.body), source)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return (
            raw_jobs,
            SourceResult(source_id=source_id, source_name=source_name, ok=True, fetched_count=len(raw_jobs), elapsed_ms=elapsed_ms),
            response_headers,
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ([], SourceResult(source_id=source_id, source_name=source_name, ok=False, elapsed_ms=elapsed_ms, error=type(exc).__name__), response_headers)


def fetch_greenhouse_detail(
    source: dict[str, Any],
    job_id: object,
    *,
    fetcher: Callable[..., FetchResponse] = fetch_url,
) -> dict[str, Any]:
    response = fetcher(greenhouse_detail_url(source, job_id), headers={}, timeout=int(source.get("timeout", 30)))
    parsed = parse_greenhouse(json.loads(response.body), source)
    if not parsed:
        raise ValueError(f"no Greenhouse detail returned for {job_id}")
    return parsed[0]


def parse_lever(payload: Any, source: dict[str, Any]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    for job in payload if isinstance(payload, list) else []:
        categories = job.get("categories") or {}
        parsed.append(
            {
                "external_id": job.get("id"),
                "title": job.get("text"),
                "company": source.get("company"),
                "location": categories.get("location"),
                "canonical_url": job.get("hostedUrl"),
                "apply_url": job.get("applyUrl") or job.get("hostedUrl"),
                "department": categories.get("team"),
                "employment_type": categories.get("commitment"),
                "created_at": job.get("createdAt"),
                "description_text": job.get("descriptionPlain") or job.get("description"),
                "tags": [item for item in [categories.get("team"), categories.get("commitment")] if item],
            }
        )
    return parsed


def parse_ashby(payload: Any, source: dict[str, Any]) -> list[dict[str, Any]]:
    jobs = payload.get("jobs", payload) if isinstance(payload, dict) else payload
    parsed: list[dict[str, Any]] = []
    for job in jobs or []:
        location = job.get("location") or job.get("locationName") or ""
        parsed.append(
            {
                "external_id": job.get("id"),
                "title": job.get("title"),
                "company": source.get("company"),
                "location": location,
                "canonical_url": job.get("jobUrl") or job.get("url"),
                "apply_url": job.get("applyUrl") or job.get("jobUrl") or job.get("url"),
                "department": job.get("department"),
                "employment_type": job.get("employmentType"),
                "posted_at": job.get("publishedAt") or job.get("createdAt"),
                "description_text": job.get("descriptionPlain") or job.get("descriptionHtml") or job.get("description"),
                "tags": [item for item in [job.get("department"), job.get("employmentType")] if item],
            }
        )
    return parsed


def parse_rss(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    parsed: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        description = item.findtext("description") or ""
        location = ""
        match = re.search(r"\b(Beijing|Dubai|Shenzhen|Shenzen|New York City|New York|NYC|San Francisco|SF|Sydney)\b", f"{title} {description}", flags=re.I)
        if match:
            location = match.group(1)
        parsed.append(
            {
                "external_id": item.findtext("guid") or item.findtext("link") or title,
                "title": title,
                "company": source.get("company") or source.get("name"),
                "location": location,
                "canonical_url": item.findtext("link"),
                "apply_url": item.findtext("link"),
                "posted_at": item.findtext("pubDate"),
                "description_text": description,
                "tags": [],
            }
        )
    return parsed


def parse_html_static(text: str, source: dict[str, Any]) -> list[dict[str, Any]]:
    item_pattern = source.get("item_regex")
    if not item_pattern:
        raise ValueError("html_static sources require item_regex")
    parsed = []
    for match in re.finditer(str(item_pattern), text, flags=re.I | re.S):
        block = match.group(0)
        def grab(key: str) -> str:
            pattern = source.get(f"{key}_regex")
            if not pattern:
                return ""
            value_match = re.search(str(pattern), block, flags=re.I | re.S)
            return strip_html(value_match.group(1)) if value_match else ""
        parsed.append(
            {
                "external_id": grab("id") or grab("url") or grab("title"),
                "title": grab("title"),
                "company": source.get("company") or grab("company"),
                "location": grab("location"),
                "canonical_url": grab("url"),
                "apply_url": grab("url"),
                "description_text": grab("description") or block,
                "tags": [],
            }
        )
    return parsed


def parse_fixture(source: dict[str, Any]) -> list[dict[str, Any]]:
    if "jobs" in source:
        return list(source.get("jobs") or [])
    fixture_path = source.get("fixture_path")
    if not fixture_path:
        return []
    path = Path(str(fixture_path))
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return list(payload.get("jobs", payload))


def fetch_source(
    source: dict[str, Any],
    *,
    default_cities: set[str],
    allow_global_remote: bool,
    cache: dict[str, Any] | None = None,
    fetcher: Callable[..., FetchResponse] = fetch_url,
) -> tuple[list[JobPosting], SourceResult, dict[str, str]]:
    started = time.perf_counter()
    source_id = str(source.get("id") or source.get("name") or "source").strip()
    source_name = str(source.get("name") or source_id).strip()
    try:
        adapter = str(source.get("adapter", "")).strip().lower()
        raw_jobs: list[dict[str, Any]]
        response_headers: dict[str, str] = {}
        if adapter == "fixture":
            raw_jobs = parse_fixture(source)
        else:
            url = str(source.get("url", "")).strip()
            if not url and adapter == "greenhouse":
                url = greenhouse_index_url(source)
            elif not url and adapter == "lever":
                url = lever_index_url(source)
            elif not url and adapter == "ashby":
                url = ashby_index_url(source)
            if not url:
                raise ValueError("source url is required")
            response = fetcher(url, headers=conditional_headers(cache or {}), timeout=int(source.get("timeout", 30)))
            response_headers = {
                "etag": response.headers.get("etag", ""),
                "last_modified": response.headers.get("last-modified", ""),
            }
            if response.status == 304:
                raw_jobs = []
            elif adapter == "greenhouse":
                raw_jobs = parse_greenhouse(json.loads(response.body), source)
            elif adapter == "lever":
                raw_jobs = parse_lever(json.loads(response.body), source)
            elif adapter == "ashby":
                raw_jobs = parse_ashby(json.loads(response.body), source)
            elif adapter == "rss":
                raw_jobs = parse_rss(response.body, source)
            elif adapter == "html_static":
                raw_jobs = parse_html_static(response.body, source)
            else:
                raise ValueError(f"unsupported adapter: {adapter}")
        max_jobs = int(source.get("max_jobs_per_source", 250))
        normalized: list[JobPosting] = []
        for raw in raw_jobs[:max_jobs]:
            location_text = clean_text(raw.get("location") or raw.get("location_text"), max_chars=300)
            job = normalize_job(
                source,
                raw,
                location_text=location_text,
                default_cities=default_cities,
                allow_global_remote=allow_global_remote,
            )
            if job is not None:
                normalized.append(job)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return (
            normalized,
            SourceResult(
                source_id=source_id,
                source_name=source_name,
                ok=True,
                fetched_count=len(raw_jobs),
                normalized_count=len(normalized),
                elapsed_ms=elapsed_ms,
                etag=response_headers.get("etag", ""),
                last_modified=response_headers.get("last_modified", ""),
            ),
            response_headers,
        )
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return (
            [],
            SourceResult(source_id=source_id, source_name=source_name, ok=False, elapsed_ms=elapsed_ms, error=type(exc).__name__),
            {},
        )
