from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlencode, urlparse

from .cities import ALIASES
from .conditions import conditions_allowed_cities, load_conditions
from .config import read_json
from .fetch import FetchResponse, fetch_url
from .models import now_iso
from .state import JsonStore, load_json_from_github, state_store_from_env


FetchFn = Callable[..., FetchResponse]
DEFAULT_COMMON_CRAWL_INDEX_LIST_URL = "https://index.commoncrawl.org/collinfo.json"
DEFAULT_ATS_HOSTS = [
    "job-boards.greenhouse.io",
    "boards.greenhouse.io",
    "*.greenhouse.io/*/jobs/*",
    "jobs.lever.co/*",
    "jobs.ashbyhq.com/*",
]
DEFAULT_GREENHOUSE_HOSTS = DEFAULT_ATS_HOSTS
SUPPORTED_REGISTRY_ATS = {"greenhouse", "lever", "ashby"}
DEFAULT_EXCLUDE_DOMAINS = ["linkedin.com", "www.linkedin.com", "m.linkedin.com"]
DEFAULT_COMMON_CRAWL_INDEX_COUNT = 4
DEFAULT_MAX_REGISTRY_REFRESH_URLS = 5000
DEFAULT_MAX_BOARDS_PER_DAILY_RUN = 300
DEFAULT_MAX_BOARD_FAILURES = 3


@dataclass(frozen=True)
class DiscoveredPostingRef:
    ats: str
    board_token: str
    job_id: str
    url: str
    source: str = "common_crawl_registry"

    @property
    def board_key(self) -> str:
        return f"{self.ats}:{self.board_token}"

    @property
    def ref_key(self) -> str:
        return f"{self.ats}:{self.board_token}:{self.job_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_discovery_path(root: Path) -> Path:
    configured = os.environ.get("OPPORTUNITY_DISCOVERY_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else root / path
    local_path = root / "data" / "config" / "discovery.local.json"
    if local_path.exists():
        return local_path
    return root / "data" / "config" / "discovery.example.json"


def load_discovery_config(root: Path, explicit_path: str = "") -> dict[str, Any]:
    config_repo = os.environ.get("GITHUB_CONFIG_REPO", os.environ.get("GITHUB_STATE_REPO", "")).strip()
    config_token = os.environ.get("GITHUB_CONFIG_TOKEN", os.environ.get("GITHUB_STATE_TOKEN", "")).strip()
    github_path = os.environ.get("GITHUB_DISCOVERY_PATH", "").strip()
    if not explicit_path and config_repo and config_token and github_path:
        ref = os.environ.get("GITHUB_CONFIG_REF", os.environ.get("GITHUB_STATE_REF", "main"))
        return load_json_from_github(config_repo, github_path, config_token, ref)
    path = Path(explicit_path) if explicit_path else default_discovery_path(root)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        return {"enabled": False}
    return read_json(path)


def normalized_host(value: str) -> str:
    return value.lower().strip().split(":", 1)[0]


def domain_excluded(host: str, excluded_domains: list[str]) -> bool:
    normalized = normalized_host(host)
    for domain in excluded_domains:
        item = normalized_host(str(domain))
        if item and (normalized == item or normalized.endswith(f".{item}")):
            return True
    return False


def display_company_from_token(board_token: str) -> str:
    parts = [part for part in re.split(r"[-_]+", board_token) if part]
    if not parts:
        return board_token
    special = {"ai": "AI", "io": "IO", "usa": "USA", "uk": "UK"}
    return " ".join(special.get(part.lower(), part.capitalize()) for part in parts)


def parse_greenhouse_job_url(url: str, *, excluded_domains: list[str] | None = None) -> DiscoveredPostingRef | None:
    excluded = excluded_domains or DEFAULT_EXCLUDE_DOMAINS
    parsed = urlparse(str(url).strip())
    host = normalized_host(parsed.netloc)
    if not host or domain_excluded(host, excluded):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    board_token = ""
    job_id = ""
    greenhouse_job_board_host = host in {"job-boards.greenhouse.io", "boards.greenhouse.io"} or (
        host.startswith("job-boards.") and host.endswith(".greenhouse.io")
    )
    if greenhouse_job_board_host and len(parts) >= 3 and parts[1] == "jobs":
        board_token = parts[0]
        job_id = parts[2]
    elif host == "boards-api.greenhouse.io" and len(parts) >= 5 and parts[:2] == ["v1", "boards"] and parts[3] == "jobs":
        board_token = parts[2]
        job_id = parts[4]
    if not board_token or not job_id:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", board_token):
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        return None
    return DiscoveredPostingRef(
        ats="greenhouse",
        board_token=board_token.lower(),
        job_id=job_id,
        url=url,
    )


def valid_registry_token(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", value or ""))


def parse_lever_job_url(url: str, *, excluded_domains: list[str] | None = None) -> DiscoveredPostingRef | None:
    excluded = excluded_domains or DEFAULT_EXCLUDE_DOMAINS
    parsed = urlparse(str(url).strip())
    host = normalized_host(parsed.netloc)
    if host != "jobs.lever.co" or domain_excluded(host, excluded):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    board_token = parts[0]
    job_id = parts[1]
    if not valid_registry_token(board_token) or not valid_registry_token(job_id):
        return None
    return DiscoveredPostingRef(
        ats="lever",
        board_token=board_token.lower(),
        job_id=job_id,
        url=url,
    )


def parse_ashby_job_url(url: str, *, excluded_domains: list[str] | None = None) -> DiscoveredPostingRef | None:
    excluded = excluded_domains or DEFAULT_EXCLUDE_DOMAINS
    parsed = urlparse(str(url).strip())
    host = normalized_host(parsed.netloc)
    if host != "jobs.ashbyhq.com" or domain_excluded(host, excluded):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    board_token = parts[0] if parts else ""
    job_id = ""
    if len(parts) >= 2 and parts[1].lower() not in {"application", "department", "teams"}:
        job_id = parts[1]
    elif len(parts) >= 2 and parts[1].lower() == "application":
        job_id = (parse_qs(parsed.query).get("jobId") or [""])[0]
    if not valid_registry_token(board_token) or not valid_registry_token(job_id):
        return None
    return DiscoveredPostingRef(
        ats="ashby",
        board_token=board_token.lower(),
        job_id=job_id,
        url=url,
    )


def parse_ats_job_url(url: str, *, excluded_domains: list[str] | None = None) -> DiscoveredPostingRef | None:
    return (
        parse_greenhouse_job_url(url, excluded_domains=excluded_domains)
        or parse_lever_job_url(url, excluded_domains=excluded_domains)
        or parse_ashby_job_url(url, excluded_domains=excluded_domains)
    )


def parse_cdx_records(text: str) -> list[dict[str, Any]]:
    payload = text.strip()
    if not payload:
        return []
    try:
        parsed = json.loads(payload)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            records = parsed.get("records")
            if isinstance(records, list):
                return [item for item in records if isinstance(item, dict)]
            return [parsed]
    except json.JSONDecodeError:
        pass
    records: list[dict[str, Any]] = []
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def records_from_fixture(root: Path, fixture_path: str) -> list[dict[str, Any]]:
    path = Path(fixture_path)
    if not path.is_absolute():
        path = root / path
    return parse_cdx_records(path.read_text(encoding="utf-8-sig"))


def common_crawl_index_endpoint(value: object) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    if text.startswith(("http://", "https://")):
        return text
    collection_id = text[: -len("-index")] if text.endswith("-index") else text
    return f"https://index.commoncrawl.org/{quote(collection_id, safe='')}-index"


def common_crawl_indexes(config: dict[str, Any], *, fetcher: FetchFn = fetch_url) -> tuple[list[str], list[str]]:
    index_count = max(1, int(config.get("max_common_crawl_indexes", config.get("common_crawl_index_count", DEFAULT_COMMON_CRAWL_INDEX_COUNT))))
    configured = config.get("common_crawl_indexes") or config.get("common_crawl_index")
    if isinstance(configured, str) and configured.strip():
        endpoint = common_crawl_index_endpoint(configured)
        return ([endpoint] if endpoint else []), []
    if isinstance(configured, list):
        indexes = [common_crawl_index_endpoint(item) for item in configured if str(item).strip()]
        indexes = [item for item in indexes if item]
        if indexes:
            return indexes[:index_count], []
    try:
        response = fetcher(str(config.get("common_crawl_index_list_url") or DEFAULT_COMMON_CRAWL_INDEX_LIST_URL), headers={}, timeout=int(config.get("timeout", 30)))
        payload = json.loads(response.body)
        if isinstance(payload, list):
            indexes: list[str] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                endpoint = str(item.get("cdx-api") or "").strip() or common_crawl_index_endpoint(item.get("id"))
                if endpoint:
                    indexes.append(endpoint)
            return indexes[:index_count], []
    except Exception as exc:
        return [], [f"common_crawl_index_list_failed:{type(exc).__name__}:{str(exc)[:160]}"]
    return [], ["common_crawl_index_list_empty"]


def common_crawl_query_pattern(host_or_pattern: str) -> str:
    text = str(host_or_pattern or "").strip()
    if not text:
        return ""
    return text if "/" in text else f"{text}/*"


def common_crawl_cdx_url(index: str, host: str, limit: int) -> str:
    url_pattern = common_crawl_query_pattern(host)
    params = {
        "url": url_pattern,
        "output": "json",
        "fl": "url,timestamp,status,mime",
        "filter": "status:200",
        "collapse": "urlkey",
        "limit": str(max(1, limit)),
    }
    query = "&".join(f"{quote(key)}={quote(value, safe='')}" for key, value in params.items())
    endpoint = common_crawl_index_endpoint(index)
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}{query}"


def common_crawl_error_is_empty(exc: Exception) -> bool:
    text = str(exc)
    return "HTTP 404" in text and ("URL Not Found" in text or "No Captures found" in text)


def google_cse_config(config: dict[str, Any]) -> dict[str, Any]:
    value = config.get("google_cse", {})
    return value if isinstance(value, dict) else {}


def google_cse_enabled(config: dict[str, Any]) -> bool:
    provider = str(config.get("provider") or "common_crawl_registry").strip().lower()
    return provider == "google_cse_registry" or bool(google_cse_config(config).get("enabled", False))


def registry_provider_runs_common_crawl(config: dict[str, Any]) -> bool:
    provider = str(config.get("provider") or "common_crawl_registry").strip().lower()
    if provider == "google_cse_registry":
        return False
    return bool(config.get("common_crawl_enabled", True))


def google_query_term(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    escaped = text.replace('"', "")
    return f'"{escaped}"' if re.search(r"\s", escaped) else escaped


def google_or_expression(terms: list[str]) -> str:
    quoted = [google_query_term(term) for term in terms if google_query_term(term)]
    if not quoted:
        return ""
    if len(quoted) == 1:
        return quoted[0]
    return "(" + " OR ".join(quoted) + ")"


def google_city_terms(city: str, *, max_aliases: int) -> list[str]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in [city, *[alias for alias, canonical in ALIASES.items() if canonical == city]]:
        normalized = re.sub(r"\s+", " ", str(term or "").strip()).lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            terms.append(str(term).strip())
    return terms[:max_aliases]


def build_google_cse_queries(config: dict[str, Any], conditions: dict[str, Any]) -> list[str]:
    google_config = google_cse_config(config)
    explicit = google_config.get("queries") or config.get("google_cse_queries")
    if isinstance(explicit, list):
        return [str(query).strip() for query in explicit if str(query).strip()]
    if isinstance(explicit, str) and explicit.strip():
        return [explicit.strip()]

    sites = [
        str(site).strip()
        for site in google_config.get(
            "sites",
            [
                "job-boards.greenhouse.io",
                "boards.greenhouse.io",
                "job-boards.eu.greenhouse.io",
                "job-boards.anz.greenhouse.io",
                "jobs.lever.co",
                "jobs.ashbyhq.com",
            ],
        )
        if str(site).strip()
    ]
    site_expr = google_or_expression([f"site:{site}" for site in sites])
    if not site_expr:
        return []
    cities = sorted(conditions_allowed_cities(conditions))
    role_groups = [group for group in conditions.get("role_groups", []) if isinstance(group, dict)]
    max_city_aliases = max(1, int(google_config.get("max_city_aliases", 3)))
    max_role_terms = max(1, int(google_config.get("max_role_terms_per_group", 6)))
    max_queries = max(1, int(google_config.get("max_queries", 30)))
    queries: list[str] = []
    for city in cities:
        city_expr = google_or_expression(google_city_terms(city, max_aliases=max_city_aliases))
        if not city_expr:
            continue
        for group in role_groups:
            role_terms = [str(term).strip() for term in [*list(group.get("include_any", []) or []), *list(group.get("include_all", []) or [])] if str(term).strip()]
            role_expr = google_or_expression(role_terms[:max_role_terms])
            if not role_expr:
                continue
            queries.append(f"{site_expr} {city_expr} {role_expr}")
            if len(queries) >= max_queries:
                return queries
    return queries


def google_cse_api_url(api_key: str, cx: str, query: str, *, num: int, start: int, date_restrict: str) -> str:
    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": str(max(1, min(10, num))),
        "start": str(max(1, start)),
    }
    if date_restrict:
        params["dateRestrict"] = date_restrict
    return "https://www.googleapis.com/customsearch/v1?" + urlencode(params)


def google_cse_urls_from_response(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    urls: list[str] = []
    for item in payload.get("items", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("link") or item.get("formattedUrl") or "").strip()
        if url:
            urls.append(url)
    return urls


def discover_google_cse_refs(root: Path, config: dict[str, Any], conditions: dict[str, Any], *, fetcher: FetchFn = fetch_url) -> dict[str, Any]:
    del root
    google_config = google_cse_config(config)
    api_key = str(google_config.get("api_key") or os.environ.get(str(google_config.get("api_key_env") or "GOOGLE_CSE_API_KEY"), "")).strip()
    cx = str(google_config.get("cx") or os.environ.get(str(google_config.get("cx_env") or "GOOGLE_CSE_CX"), "")).strip()
    if not api_key or not cx:
        return {"provider": "google_cse_registry", "raw_url_count": 0, "accepted_ref_count": 0, "rejected_url_count": 0, "refs": [], "errors": ["google_cse_missing_credentials"]}

    queries = build_google_cse_queries(config, conditions)
    if not queries:
        return {"provider": "google_cse_registry", "raw_url_count": 0, "accepted_ref_count": 0, "rejected_url_count": 0, "refs": [], "errors": ["google_cse_no_queries"]}

    excluded_domains = [str(item) for item in config.get("exclude_domains", DEFAULT_EXCLUDE_DOMAINS)]
    results_per_query = max(1, min(10, int(google_config.get("results_per_query", 10))))
    max_pages = max(1, int(google_config.get("max_pages_per_query", 1)))
    max_results = max(1, int(google_config.get("max_results", google_config.get("max_queries", 30) * results_per_query * max_pages)))
    date_restrict = str(google_config.get("date_restrict", "d14") or "").strip()
    errors: list[str] = []
    raw_urls: list[str] = []
    for query in queries[: max(1, int(google_config.get("max_queries", len(queries))))]:
        for page in range(max_pages):
            if len(raw_urls) >= max_results:
                break
            start = 1 + page * results_per_query
            try:
                response = fetcher(google_cse_api_url(api_key, cx, query, num=results_per_query, start=start, date_restrict=date_restrict), headers={}, timeout=int(config.get("timeout", 30)))
                raw_urls.extend(google_cse_urls_from_response(response.body))
            except Exception as exc:
                errors.append(f"google_cse_query_failed:{type(exc).__name__}:{str(exc)[:160]}")
        if len(raw_urls) >= max_results:
            break

    refs_by_key: dict[str, DiscoveredPostingRef] = {}
    rejected = 0
    for url in raw_urls[:max_results]:
        ref = parse_ats_job_url(url, excluded_domains=excluded_domains)
        if ref is None:
            rejected += 1
            continue
        refs_by_key.setdefault(ref.ref_key, DiscoveredPostingRef(ref.ats, ref.board_token, ref.job_id, ref.url, "google_cse_registry"))
    refs = list(refs_by_key.values())
    return {
        "provider": "google_cse_registry",
        "raw_url_count": len(raw_urls[:max_results]),
        "accepted_ref_count": len(refs),
        "rejected_url_count": rejected,
        "refs": [ref.to_dict() for ref in refs],
        "errors": errors,
        "queries_run": len(queries),
    }


def combine_registry_discovery_results(provider: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    refs_by_key: dict[str, DiscoveredPostingRef] = {}
    errors: list[str] = []
    raw_url_count = 0
    rejected_url_count = 0
    for result in results:
        raw_url_count += int(result.get("raw_url_count", 0) or 0)
        rejected_url_count += int(result.get("rejected_url_count", 0) or 0)
        errors.extend(str(error) for error in result.get("errors", []) if str(error))
        for ref in refs_from_payload(result):
            refs_by_key.setdefault(ref.ref_key, ref)
    refs = list(refs_by_key.values())
    return {
        "provider": provider,
        "raw_url_count": raw_url_count,
        "accepted_ref_count": len(refs),
        "rejected_url_count": rejected_url_count,
        "refs": [ref.to_dict() for ref in refs],
        "errors": errors,
    }


def discover_registry_refs(root: Path, config: dict[str, Any], conditions: dict[str, Any] | None = None, *, fetcher: FetchFn = fetch_url) -> dict[str, Any]:
    provider = str(config.get("provider") or "common_crawl_registry").strip().lower()
    results: list[dict[str, Any]] = []
    if registry_provider_runs_common_crawl(config):
        results.append(discover_common_crawl_refs(root, config, fetcher=fetcher))
    if google_cse_enabled(config):
        results.append(discover_google_cse_refs(root, config, conditions or {}, fetcher=fetcher))
    if not results:
        results.append(discover_common_crawl_refs(root, config, fetcher=fetcher))
    if len(results) == 1:
        result = dict(results[0])
        result["provider"] = provider or str(result.get("provider") or "common_crawl_registry")
        return result
    return combine_registry_discovery_results(provider or "hybrid_registry", results)


def discover_common_crawl_refs(root: Path, config: dict[str, Any], *, fetcher: FetchFn = fetch_url) -> dict[str, Any]:
    if not bool(config.get("enabled", True)):
        return {"provider": config.get("provider", "common_crawl_registry"), "raw_url_count": 0, "accepted_ref_count": 0, "rejected_url_count": 0, "refs": [], "errors": ["discovery_disabled"]}
    excluded_domains = [str(item) for item in config.get("exclude_domains", DEFAULT_EXCLUDE_DOMAINS)]
    max_urls = max(1, int(config.get("max_registry_refresh_urls", DEFAULT_MAX_REGISTRY_REFRESH_URLS)))
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    fixture_path = str(config.get("fixture_path", "")).strip()
    if fixture_path:
        try:
            records = records_from_fixture(root, fixture_path)[:max_urls]
        except Exception as exc:
            errors.append(f"fixture_load_failed:{type(exc).__name__}")
    else:
        ats_hosts = [str(item).strip() for item in config.get("ats_hosts", DEFAULT_ATS_HOSTS) if str(item).strip()]
        indexes, index_errors = common_crawl_indexes(config, fetcher=fetcher)
        errors.extend(index_errors)
        remaining = max_urls
        per_query_limit = max(1, int(config.get("per_host_limit", max_urls)))
        for index in indexes:
            for host in ats_hosts:
                if remaining <= 0:
                    break
                limit = min(remaining, per_query_limit)
                try:
                    response = fetcher(common_crawl_cdx_url(index, host, limit), headers={}, timeout=int(config.get("timeout", 30)))
                    host_records = parse_cdx_records(response.body)
                    records.extend(host_records[:remaining])
                    remaining = max_urls - len(records)
                except Exception as exc:
                    if common_crawl_error_is_empty(exc):
                        continue
                    errors.append(f"common_crawl_query_failed:{host}:{type(exc).__name__}:{str(exc)[:160]}")
            if remaining <= 0:
                break
    refs_by_key: dict[str, DiscoveredPostingRef] = {}
    rejected = 0
    for record in records[:max_urls]:
        url = str(record.get("url") or "").strip()
        ref = parse_ats_job_url(url, excluded_domains=excluded_domains)
        if ref is None:
            rejected += 1
            continue
        refs_by_key.setdefault(ref.ref_key, ref)
    refs = list(refs_by_key.values())
    return {
        "provider": str(config.get("provider") or "common_crawl_registry"),
        "raw_url_count": len(records[:max_urls]),
        "accepted_ref_count": len(refs),
        "rejected_url_count": rejected,
        "refs": [ref.to_dict() for ref in refs],
        "errors": errors,
    }


def merge_board_registry(state: dict[str, Any], refs: list[DiscoveredPostingRef], *, seen_at: str | None = None, max_sample_urls: int = 5) -> dict[str, Any]:
    timestamp = seen_at or now_iso()
    registry = state.setdefault("board_registry", {})
    before = len(registry)
    added = 0
    updated = 0
    for ref in refs:
        key = ref.board_key
        existing = registry.get(key, {}) if isinstance(registry.get(key, {}), dict) else {}
        if key in registry:
            updated += 1
        else:
            added += 1
        sample_urls = [str(item) for item in existing.get("sample_urls", []) if str(item).strip()]
        if ref.url not in sample_urls:
            sample_urls.append(ref.url)
        sample_urls = sample_urls[-max_sample_urls:]
        job_ids = [str(item) for item in existing.get("sample_job_ids", []) if str(item).strip()]
        if ref.job_id not in job_ids:
            job_ids.append(ref.job_id)
        job_ids = job_ids[-25:]
        registry[key] = {
            "ats": ref.ats,
            "board_token": ref.board_token,
            "active": True,
            "first_seen": existing.get("first_seen") or timestamp,
            "last_seen": timestamp,
            "last_polled": existing.get("last_polled", ""),
            "failure_count": int(existing.get("failure_count", 0) or 0),
            "last_error": existing.get("last_error", ""),
            "sample_urls": sample_urls,
            "sample_job_ids": job_ids,
            "source": ref.source,
        }
    return {
        "boards_before": before,
        "boards_after": len(registry),
        "boards_added": added,
        "boards_updated": updated,
    }


def refs_from_payload(payload: dict[str, Any]) -> list[DiscoveredPostingRef]:
    refs = []
    for item in payload.get("refs", []):
        if not isinstance(item, dict):
            continue
        try:
            refs.append(
                DiscoveredPostingRef(
                    ats=str(item.get("ats", "")),
                    board_token=str(item.get("board_token", "")),
                    job_id=str(item.get("job_id", "")),
                    url=str(item.get("url", "")),
                    source=str(item.get("source", "common_crawl_registry")),
                )
            )
        except Exception:
            continue
    return refs


def stable_poll_bucket(value: str, seed: str) -> str:
    payload = f"{seed}:{value}".encode("utf-8", errors="ignore")
    return hashlib.sha256(payload).hexdigest()


def active_registry_sources(state: dict[str, Any], discovery_config: dict[str, Any], *, default_cities: set[str], allow_global_remote: bool) -> list[dict[str, Any]]:
    if not bool(discovery_config.get("enabled", True)):
        return []
    registry = state.get("board_registry", {})
    if not isinstance(registry, dict):
        return []
    max_boards = max(0, int(discovery_config.get("max_boards_per_daily_run", DEFAULT_MAX_BOARDS_PER_DAILY_RUN)))
    entries: list[tuple[str, dict[str, Any]]] = []
    for key, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        ats = str(entry.get("ats", "")).lower()
        if ats not in SUPPORTED_REGISTRY_ATS:
            continue
        if not bool(entry.get("active", True)):
            continue
        token = str(entry.get("board_token", "")).strip()
        if not token:
            continue
        entries.append((str(key), entry))
    seed = str(discovery_config.get("poll_spread_seed", "opportunity-radar-v1"))
    entries.sort(key=lambda item: (str(item[1].get("last_polled", "")), stable_poll_bucket(str(item[1].get("board_token", "")), seed)))
    sources: list[dict[str, Any]] = []
    cities = sorted(default_cities)
    for key, entry in entries[:max_boards]:
        token = str(entry.get("board_token", "")).strip()
        ats = str(entry.get("ats", "")).lower()
        company = display_company_from_token(token)
        ats_label = ats.capitalize()
        source = {
            "id": f"registry-{ats}-{token}",
            "name": f"Discovered {ats_label}: {company}",
            "adapter": ats,
            "enabled": True,
            "company": company,
            "board_token": token,
            "cities": cities,
            "allow_global_remote": allow_global_remote,
            "max_jobs_per_source": int(discovery_config.get("max_jobs_per_source", 500)),
            "_registry_key": key,
        }
        if ats == "greenhouse":
            source["max_detail_fetches"] = int(discovery_config.get("max_detail_fetches_per_board", 12))
        sources.append(source)
    return sources


def record_board_poll_result(state: dict[str, Any], source: dict[str, Any], *, ok: bool, error: str = "", max_failures: int = DEFAULT_MAX_BOARD_FAILURES) -> None:
    key = str(source.get("_registry_key") or "").strip()
    if not key:
        return
    registry = state.setdefault("board_registry", {})
    entry = registry.get(key)
    if not isinstance(entry, dict):
        return
    entry["last_polled"] = now_iso()
    if ok:
        entry["failure_count"] = 0
        entry["last_error"] = ""
        entry["active"] = True
    else:
        failure_count = int(entry.get("failure_count", 0) or 0) + 1
        entry["failure_count"] = failure_count
        entry["last_error"] = error or "poll_failed"
        if failure_count >= max_failures:
            entry["active"] = False


def refresh_registry(
    root: Path,
    *,
    write: bool = False,
    discovery_path: str = "",
    conditions_path: str = "",
    state_store: JsonStore | None = None,
    fetcher: FetchFn = fetch_url,
) -> dict[str, Any]:
    root = root.resolve()
    started_at = now_iso()
    run_id = secrets.token_hex(8)
    config = load_discovery_config(root, discovery_path)
    conditions = load_conditions(root, conditions_path or str(config.get("conditions_path", "")))
    store = state_store or state_store_from_env(root)
    state = store.load()
    discovery_result = discover_registry_refs(root, config, conditions, fetcher=fetcher)
    registry_summary = merge_board_registry(
        state,
        refs_from_payload(discovery_result),
        max_sample_urls=int(config.get("max_sample_urls_per_board", 5)),
    )
    finished_at = now_iso()
    run_payload = {
        "run_id": run_id,
        "kind": "registry_refresh",
        "dry_run": not write,
        "started_at": started_at,
        "finished_at": finished_at,
        "provider": discovery_result.get("provider", "common_crawl_registry"),
        "raw_url_count": discovery_result.get("raw_url_count", 0),
        "accepted_ref_count": discovery_result.get("accepted_ref_count", 0),
        "rejected_url_count": discovery_result.get("rejected_url_count", 0),
        "registry_summary": registry_summary,
        "errors": list(discovery_result.get("errors", [])),
    }
    mutated = False
    if write:
        runs = state.setdefault("runs", [])
        runs.append(run_payload)
        state["runs"] = runs[-50:]
        state["updated_at"] = now_iso()
        store.save(state)
        mutated = True
    return {
        **run_payload,
        "write_requested": write,
        "state_summary": {
            "mutated": mutated,
            "board_registry": len(state.get("board_registry", {})),
        },
        "discovered_refs": discovery_result.get("refs", [])[:25],
    }
