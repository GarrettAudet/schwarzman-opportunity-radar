from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .adapters import fetch_greenhouse_detail, fetch_greenhouse_index, fetch_source, normalize_job, parse_date
from .cities import canonical_city_set
from .config import load_runtime_config
from .criteria import load_criteria
from .fetch import FetchResponse, fetch_url
from .filtering import dedupe_jobs, source_filter_allows
from .models import JobPosting, RankedOpportunity, SourceResult, now_iso
from .pipeline import enabled_sources, load_sources
from .ranker import rank_deterministically, rank_with_llm
from .scheduling import week_key_for
from .state import JsonStore, state_store_from_env


FetchFn = Callable[..., FetchResponse]


def job_source_updated_at(raw: dict[str, Any]) -> str:
    return parse_date(raw.get("updated_at") or raw.get("posted_at") or raw.get("created_at"))


def should_skip_evaluated(
    state: dict[str, Any],
    job: JobPosting,
    raw: dict[str, Any],
    *,
    force: bool,
) -> bool:
    if force:
        return False
    entry = state.get("evaluated_jobs", {}).get(job.stable_key)
    if not isinstance(entry, dict):
        return False
    source_updated_at = job_source_updated_at(raw)
    if not source_updated_at:
        return False
    return str(entry.get("source_updated_at", "")) == source_updated_at


def evaluated_entry(
    job: JobPosting,
    *,
    status: str,
    run_id: str,
    week_key: str,
    source_updated_at: str,
    ranked: RankedOpportunity | None = None,
    rejection_reason: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "run_id": run_id,
        "week_key": week_key,
        "evaluated_at": now_iso(),
        "source_updated_at": source_updated_at,
        "score": ranked.score if ranked else 0.0,
        "scholar_fit_reason": ranked.scholar_fit_reason if ranked else "",
        "why_cool": ranked.why_cool if ranked else "",
        "risk_flags": list(ranked.risk_flags) if ranked else [],
        "rejection_reason": rejection_reason,
        "job": job.to_dict(),
    }


def normalize_raw_job(
    source: dict[str, Any],
    raw: dict[str, Any],
    *,
    default_cities: set[str],
    allow_global_remote: bool,
) -> JobPosting | None:
    return normalize_job(
        source,
        raw,
        location_text=str(raw.get("location") or raw.get("location_text") or ""),
        default_cities=default_cities,
        allow_global_remote=allow_global_remote,
    )


def greenhouse_discovery_jobs(
    source: dict[str, Any],
    *,
    default_cities: set[str],
    allow_global_remote: bool,
    state: dict[str, Any],
    force: bool,
    cache: dict[str, Any],
    fetcher: FetchFn = fetch_url,
) -> tuple[list[JobPosting], list[tuple[JobPosting, str, str]], SourceResult, dict[str, str], int]:
    raw_index, index_result, cache_update = fetch_greenhouse_index(source, cache=cache, fetcher=fetcher)
    if not index_result.ok:
        return [], [], index_result, cache_update, 0

    max_jobs = int(source.get("max_jobs_per_source", 500))
    max_detail_fetches = int(source.get("max_detail_fetches", source.get("max_jobs_per_source", 25)))
    detail_jobs: list[JobPosting] = []
    rejected_jobs: list[tuple[JobPosting, str, str]] = []
    city_candidates = 0
    detail_fetches = 0

    for raw in raw_index[:max_jobs]:
        index_job = normalize_raw_job(
            source,
            raw,
            default_cities=default_cities,
            allow_global_remote=allow_global_remote,
        )
        if index_job is None:
            continue
        city_candidates += 1
        if should_skip_evaluated(state, index_job, raw, force=force):
            continue
        if detail_fetches >= max_detail_fetches:
            break
        detail_fetches += 1
        try:
            detail_raw = fetch_greenhouse_detail(source, raw.get("external_id"), fetcher=fetcher)
            detail_raw.setdefault("updated_at", raw.get("updated_at"))
            detail_raw.setdefault("location", raw.get("location"))
            detail_raw.setdefault("canonical_url", raw.get("canonical_url"))
        except Exception:
            detail_raw = raw
        detail_job = normalize_raw_job(
            source,
            detail_raw,
            default_cities=default_cities,
            allow_global_remote=allow_global_remote,
        )
        if detail_job is None:
            continue
        source_updated_at = job_source_updated_at(detail_raw) or job_source_updated_at(raw)
        if source_filter_allows(detail_job, source):
            detail_jobs.append(detail_job)
        else:
            rejected_jobs.append((detail_job, source_updated_at, "hard_filter"))

    result = SourceResult(
        source_id=index_result.source_id,
        source_name=index_result.source_name,
        ok=index_result.ok,
        fetched_count=index_result.fetched_count,
        normalized_count=len(detail_jobs),
        elapsed_ms=index_result.elapsed_ms,
        error=index_result.error,
        etag=index_result.etag,
        last_modified=index_result.last_modified,
    )
    return detail_jobs, rejected_jobs, result, cache_update, city_candidates


def generic_discovery_jobs(
    source: dict[str, Any],
    *,
    default_cities: set[str],
    allow_global_remote: bool,
    cache: dict[str, Any],
    fetcher: FetchFn = fetch_url,
) -> tuple[list[JobPosting], list[tuple[JobPosting, str, str]], SourceResult, dict[str, str], int]:
    jobs, result, cache_update = fetch_source(
        source,
        default_cities=default_cities,
        allow_global_remote=allow_global_remote,
        cache=cache,
        fetcher=fetcher,
    )
    filtered = [job for job in jobs if source_filter_allows(job, source)]
    rejected = [(job, "", "hard_filter") for job in jobs if job not in filtered]
    return filtered, rejected, result, cache_update, len(jobs)


def rank_candidates(
    root: Path,
    jobs: list[JobPosting],
    *,
    model: str,
    max_selected: int,
    deterministic_fallback: bool,
) -> tuple[list[RankedOpportunity], list[str], bool]:
    if not jobs:
        return [], [], False
    criteria_text = load_criteria(root)
    try:
        return (
            rank_with_llm(jobs, criteria_text=criteria_text, model=model, max_selected=max_selected),
            [],
            False,
        )
    except Exception as exc:
        if deterministic_fallback:
            return (
                rank_deterministically(jobs, max_selected=max_selected),
                [f"ranker_fallback:{type(exc).__name__}"],
                False,
            )
        return [], [f"ranker_failed:{type(exc).__name__}"], True


def run_discovery(
    root: Path,
    *,
    write: bool = False,
    force: bool = False,
    sources_path: str = "",
    deterministic_fallback: bool | None = None,
    now: datetime | None = None,
    state_store: JsonStore | None = None,
    fetcher: FetchFn = fetch_url,
) -> dict[str, Any]:
    root = root.resolve()
    started_at = now_iso()
    run_id = secrets.token_hex(8)
    config = load_runtime_config(root)
    week_key = week_key_for(now, config.timezone)
    store = state_store or state_store_from_env(root)
    state = store.load()
    sources_config = load_sources(root, sources_path)
    defaults = sources_config.get("defaults", {}) if isinstance(sources_config.get("defaults", {}), dict) else {}
    default_cities = set(config.allowed_cities)
    if defaults.get("cities"):
        default_cities = canonical_city_set(defaults.get("cities"))
    allow_global_remote = bool(defaults.get("allow_global_remote", config.allow_global_remote))
    state_source_cache = state.get("source_cache", {})

    all_jobs: list[JobPosting] = []
    rejected_jobs: list[tuple[JobPosting, str, str]] = []
    source_results: list[SourceResult] = []
    source_cache_updates: dict[str, Any] = {}
    errors: list[str] = []
    city_candidate_count = 0

    for source in enabled_sources(sources_config):
        source_id = str(source.get("id") or source.get("name") or "source")
        adapter = str(source.get("adapter", "")).strip().lower()
        if adapter == "greenhouse":
            jobs, rejected, result, cache_update, city_candidates = greenhouse_discovery_jobs(
                source,
                default_cities=default_cities,
                allow_global_remote=allow_global_remote,
                state=state,
                force=force,
                cache=state_source_cache.get(source_id, {}),
                fetcher=fetcher,
            )
        else:
            jobs, rejected, result, cache_update, city_candidates = generic_discovery_jobs(
                source,
                default_cities=default_cities,
                allow_global_remote=allow_global_remote,
                cache=state_source_cache.get(source_id, {}),
                fetcher=fetcher,
            )
        source_results.append(result)
        all_jobs.extend(jobs)
        rejected_jobs.extend(rejected)
        city_candidate_count += city_candidates
        if cache_update:
            source_cache_updates[source_id] = cache_update
        if not result.ok:
            errors.append(f"source_failed:{source_id}:{result.error}")

    candidates = dedupe_jobs(all_jobs)
    allow_fallback = config.deterministic_fallback if deterministic_fallback is None else deterministic_fallback
    selected, ranker_errors, ranker_failed = rank_candidates(
        root,
        candidates,
        model=config.rank_model,
        max_selected=max(config.max_jobs, len(candidates)),
        deterministic_fallback=bool(allow_fallback),
    )
    errors.extend(ranker_errors)
    included_by_key = {item.job.stable_key: item for item in selected if item.include}

    state_updates: dict[str, Any] = {}
    for job, source_updated_at, rejection_reason in rejected_jobs:
        state_updates[job.stable_key] = evaluated_entry(
            job,
            status="rejected",
            run_id=run_id,
            week_key=week_key,
            source_updated_at=source_updated_at,
            rejection_reason=rejection_reason,
        )
    if not ranker_failed:
        for job in candidates:
            ranked = included_by_key.get(job.stable_key)
            state_updates[job.stable_key] = evaluated_entry(
                job,
                status="included" if ranked else "rejected",
                run_id=run_id,
                week_key=week_key,
                source_updated_at=job.posted_at,
                ranked=ranked,
                rejection_reason="" if ranked else "not_selected",
            )

    included = [item for item in selected if item.include]
    included.sort(key=lambda item: item.score, reverse=True)
    included = [RankedOpportunity(**{**item.__dict__, "rank": index}) for index, item in enumerate(included, start=1)]
    finished_at = now_iso()
    run_payload = {
        "run_id": run_id,
        "kind": "discovery",
        "week_key": week_key,
        "dry_run": not write,
        "started_at": started_at,
        "finished_at": finished_at,
        "source_results": [item.to_dict() for item in source_results],
        "city_candidate_count": city_candidate_count,
        "candidate_count": len(candidates),
        "included_count": len(included),
        "rejected_count": len([item for item in state_updates.values() if item.get("status") == "rejected"]),
        "errors": errors,
    }

    mutated = False
    if write:
        if state_updates:
            state.setdefault("evaluated_jobs", {}).update(state_updates)
        if source_cache_updates and not ranker_failed:
            state.setdefault("source_cache", {}).update(source_cache_updates)
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
            "evaluated_updates": len(state_updates),
            "evaluated_jobs": len(state.get("evaluated_jobs", {})),
        },
        "included_jobs": [item.to_dict() for item in included],
    }
