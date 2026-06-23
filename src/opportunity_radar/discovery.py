from __future__ import annotations

import secrets
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .adapters import fetch_greenhouse_detail, fetch_greenhouse_index, fetch_source, normalize_job, parse_date
from .cities import canonical_city_set
from .conditions import ConditionMatch, conditions_allowed_cities, load_conditions, match_job_conditions, recency_allowed, role_group_counts
from .config import load_runtime_config
from .criteria import load_criteria
from .fetch import FetchResponse, fetch_url
from .filtering import dedupe_jobs, source_filter_allows
from .models import JobPosting, RankedOpportunity, SourceResult, now_iso
from .pipeline import enabled_sources, load_sources
from .ranker import rank_deterministically, rank_with_llm
from .registry import active_registry_sources, load_discovery_config, record_board_poll_result
from .scheduling import week_key_for
from .state import JsonStore, state_store_from_env


FetchFn = Callable[..., FetchResponse]
RejectedJob = tuple[JobPosting, str, str, dict[str, Any]]


@dataclass(frozen=True)
class DiscoveryBatch:
    jobs: list[JobPosting]
    rejected_jobs: list[RejectedJob]
    result: SourceResult
    cache_update: dict[str, str]
    city_candidates: int
    recent_city_candidates: int
    condition_candidates: int
    condition_matches: dict[str, dict[str, Any]]


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
    if str(entry.get("rejection_reason", "")) == "conditions_filter:no_role_group":
        return False
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
    condition_match: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_payload = job.to_dict()
    if status != "included":
        job_payload["description_text"] = ""
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
        "condition_matches": condition_match or {},
        "job": job_payload,
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


def job_with_condition_tags(job: JobPosting, condition_match: ConditionMatch) -> JobPosting:
    tags = list(job.tags)
    for group_id in condition_match.role_group_ids:
        tag = f"condition:{group_id}"
        if tag not in tags:
            tags.append(tag)
    return replace(job, tags=tags)


def ranked_payload(item: RankedOpportunity, condition_matches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    payload = item.to_dict()
    payload["condition_matches"] = condition_matches.get(item.job.stable_key, {})
    return payload


def greenhouse_discovery_jobs(
    source: dict[str, Any],
    *,
    default_cities: set[str],
    allow_global_remote: bool,
    conditions_config: dict[str, Any],
    state: dict[str, Any],
    force: bool,
    cache: dict[str, Any],
    now: datetime | None,
    fetcher: FetchFn = fetch_url,
) -> DiscoveryBatch:
    raw_index, index_result, cache_update = fetch_greenhouse_index(source, cache=cache, fetcher=fetcher)
    if not index_result.ok:
        return DiscoveryBatch([], [], index_result, cache_update, 0, 0, 0, {})

    max_jobs = int(source.get("max_jobs_per_source", 500))
    max_detail_fetches = int(source.get("max_detail_fetches", source.get("max_jobs_per_source", 25)))
    index_description_chars = int(source.get("index_condition_description_chars", 1200))
    detail_description_chars = int(source.get("detail_condition_description_chars", 8000))
    detail_jobs: list[JobPosting] = []
    rejected_jobs: list[RejectedJob] = []
    condition_matches: dict[str, dict[str, Any]] = {}
    city_candidates = 0
    recent_city_candidates = 0
    condition_candidates = 0
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
        recent_ok, _posted_at, _age_days = recency_allowed(index_job, conditions_config, now=now)
        if recent_ok:
            recent_city_candidates += 1
        index_match = match_job_conditions(index_job, conditions_config, description_chars=index_description_chars, now=now)
        if not index_match.allowed and index_match.rejection_reason != "no_role_group":
            continue
        if should_skip_evaluated(state, index_job, raw, force=force):
            continue
        if detail_fetches >= max_detail_fetches:
            continue
        detail_fetches += 1
        try:
            detail_raw = fetch_greenhouse_detail(source, raw.get("external_id"), fetcher=fetcher)
            detail_raw.setdefault("posted_at", raw.get("posted_at"))
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
        detail_match = match_job_conditions(detail_job, conditions_config, description_chars=detail_description_chars, now=now)
        detail_match_payload = detail_match.to_dict()
        if not detail_match.allowed:
            rejected_jobs.append((detail_job, source_updated_at, f"conditions_filter:{detail_match.rejection_reason}", detail_match_payload))
            continue
        condition_candidates += 1
        if source_filter_allows(detail_job, source):
            tagged_job = job_with_condition_tags(detail_job, detail_match)
            detail_jobs.append(tagged_job)
            condition_matches[tagged_job.stable_key] = detail_match_payload
        else:
            rejected_jobs.append((detail_job, source_updated_at, "hard_filter", detail_match_payload))

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
    return DiscoveryBatch(detail_jobs, rejected_jobs, result, cache_update, city_candidates, recent_city_candidates, condition_candidates, condition_matches)


def generic_discovery_jobs(
    source: dict[str, Any],
    *,
    default_cities: set[str],
    allow_global_remote: bool,
    conditions_config: dict[str, Any],
    cache: dict[str, Any],
    now: datetime | None,
    fetcher: FetchFn = fetch_url,
) -> DiscoveryBatch:
    jobs, result, cache_update = fetch_source(
        source,
        default_cities=default_cities,
        allow_global_remote=allow_global_remote,
        cache=cache,
        fetcher=fetcher,
    )
    detail_description_chars = int(source.get("detail_condition_description_chars", 8000))
    filtered: list[JobPosting] = []
    rejected: list[RejectedJob] = []
    condition_matches: dict[str, dict[str, Any]] = {}
    recent_city_candidates = 0
    condition_candidates = 0
    for job in jobs:
        recent_ok, _posted_at, _age_days = recency_allowed(job, conditions_config, now=now)
        if recent_ok:
            recent_city_candidates += 1
        match = match_job_conditions(job, conditions_config, description_chars=detail_description_chars, now=now)
        match_payload = match.to_dict()
        if not match.allowed:
            rejected.append((job, job.posted_at, f"conditions_filter:{match.rejection_reason}", match_payload))
            continue
        condition_candidates += 1
        if source_filter_allows(job, source):
            tagged_job = job_with_condition_tags(job, match)
            filtered.append(tagged_job)
            condition_matches[tagged_job.stable_key] = match_payload
        else:
            rejected.append((job, job.posted_at, "hard_filter", match_payload))
    return DiscoveryBatch(filtered, rejected, result, cache_update, len(jobs), recent_city_candidates, condition_candidates, condition_matches)


def rank_candidates(
    root: Path,
    jobs: list[JobPosting],
    *,
    model: str,
    max_selected: int,
    min_selected: int,
    deterministic_fallback: bool,
) -> tuple[list[RankedOpportunity], list[str], bool]:
    if not jobs:
        return [], [], False
    criteria_text = load_criteria(root)
    try:
        return (
            rank_with_llm(jobs, criteria_text=criteria_text, model=model, max_selected=max_selected, min_selected=min_selected),
            [],
            False,
        )
    except Exception as exc:
        if deterministic_fallback:
            return (
                rank_deterministically(jobs, max_selected=max_selected, min_selected=min_selected),
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
    conditions_path: str = "",
    discovery_path: str = "",
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
    conditions_config = load_conditions(root, conditions_path)
    discovery_config = load_discovery_config(root, discovery_path)
    defaults = sources_config.get("defaults", {}) if isinstance(sources_config.get("defaults", {}), dict) else {}
    condition_cities = conditions_allowed_cities(conditions_config)
    default_cities = condition_cities or set(config.allowed_cities)
    if defaults.get("cities"):
        source_default_cities = canonical_city_set(defaults.get("cities"))
        default_cities = (source_default_cities & condition_cities) if condition_cities else source_default_cities
        if not default_cities:
            default_cities = source_default_cities
    allow_global_remote = bool(conditions_config.get("allow_global_remote", defaults.get("allow_global_remote", config.allow_global_remote)))
    registry_sources = active_registry_sources(
        state,
        discovery_config,
        default_cities=default_cities,
        allow_global_remote=allow_global_remote,
    )
    state_source_cache = state.get("source_cache", {})

    all_jobs: list[JobPosting] = []
    rejected_jobs: list[RejectedJob] = []
    source_results: list[SourceResult] = []
    source_cache_updates: dict[str, Any] = {}
    condition_matches_by_key: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    city_candidate_count = 0
    recent_city_candidate_count = 0
    condition_candidate_count = 0
    registry_boards_polled = 0
    all_sources = [*registry_sources, *enabled_sources(sources_config)]

    for source in all_sources:
        source_id = str(source.get("id") or source.get("name") or "source")
        adapter = str(source.get("adapter", "")).strip().lower()
        if adapter == "greenhouse":
            batch = greenhouse_discovery_jobs(
                source,
                default_cities=default_cities,
                allow_global_remote=allow_global_remote,
                conditions_config=conditions_config,
                state=state,
                force=force,
                cache={} if force else state_source_cache.get(source_id, {}),
                now=now,
                fetcher=fetcher,
            )
        else:
            batch = generic_discovery_jobs(
                source,
                default_cities=default_cities,
                allow_global_remote=allow_global_remote,
                conditions_config=conditions_config,
                cache={} if force else state_source_cache.get(source_id, {}),
                now=now,
                fetcher=fetcher,
            )
        source_results.append(batch.result)
        all_jobs.extend(batch.jobs)
        rejected_jobs.extend(batch.rejected_jobs)
        condition_matches_by_key.update(batch.condition_matches)
        city_candidate_count += batch.city_candidates
        recent_city_candidate_count += batch.recent_city_candidates
        condition_candidate_count += batch.condition_candidates
        if batch.cache_update:
            source_cache_updates[source_id] = batch.cache_update
        if source.get("_registry_key"):
            registry_boards_polled += 1
            record_board_poll_result(
                state,
                source,
                ok=batch.result.ok,
                error=batch.result.error,
                max_failures=int(discovery_config.get("max_board_failures", 3)),
            )
        if not batch.result.ok:
            errors.append(f"source_failed:{source_id}:{batch.result.error}")

    candidates = dedupe_jobs(all_jobs)
    allow_fallback = config.deterministic_fallback if deterministic_fallback is None else deterministic_fallback
    selected, ranker_errors, ranker_failed = rank_candidates(
        root,
        candidates,
        model=config.rank_model,
        max_selected=max(config.max_jobs, len(candidates)),
        min_selected=min(config.min_jobs, config.max_jobs),
        deterministic_fallback=bool(allow_fallback),
    )
    errors.extend(ranker_errors)
    included_by_key = {item.job.stable_key: item for item in selected if item.include}

    state_updates: dict[str, Any] = {}
    for job, source_updated_at, rejection_reason, condition_match in rejected_jobs:
        state_updates[job.stable_key] = evaluated_entry(
            job,
            status="rejected",
            run_id=run_id,
            week_key=week_key,
            source_updated_at=source_updated_at,
            rejection_reason=rejection_reason,
            condition_match=condition_match,
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
                condition_match=condition_matches_by_key.get(job.stable_key, {}),
            )

    included = [item for item in selected if item.include]
    included.sort(key=lambda item: item.score, reverse=True)
    included = [RankedOpportunity(**{**item.__dict__, "rank": index}) for index, item in enumerate(included, start=1)]
    group_counts = role_group_counts(condition_matches_by_key.values())
    finished_at = now_iso()
    run_payload = {
        "run_id": run_id,
        "kind": "discovery",
        "week_key": week_key,
        "dry_run": not write,
        "started_at": started_at,
        "finished_at": finished_at,
        "source_results": [item.to_dict() for item in source_results],
        "registry_board_count": len(registry_sources),
        "registry_boards_polled": registry_boards_polled,
        "city_candidate_count": city_candidate_count,
        "recent_city_candidate_count": recent_city_candidate_count,
        "condition_candidate_count": condition_candidate_count,
        "candidate_count": len(candidates),
        "included_count": len(included),
        "rejected_count": len([item for item in state_updates.values() if item.get("status") == "rejected"]),
        "role_group_counts": group_counts,
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
            "board_registry": len(state.get("board_registry", {})),
        },
        "included_jobs": [ranked_payload(item, condition_matches_by_key) for item in included],
    }
