from __future__ import annotations

import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from .adapters import fetch_source
from .config import default_sources_path, load_runtime_config, read_json
from .criteria import load_criteria
from .digest import format_digest
from .filtering import dedupe_jobs, remove_seen_jobs, source_filter_allows
from .models import DigestRun, JobPosting, RankedOpportunity, SourceResult, now_iso
from .ranker import RankingError, rank_deterministically, rank_with_llm
from .scheduling import should_send_now, week_key_for
from .sender import DryRunSender, Sender, TwilioWhatsAppSender
from .state import JsonStore, load_json_from_github, state_store_from_env


def load_sources(root: Path, explicit_path: str = "") -> dict[str, Any]:
    config_repo = os.environ.get("GITHUB_CONFIG_REPO", os.environ.get("GITHUB_STATE_REPO", "")).strip()
    config_token = os.environ.get("GITHUB_CONFIG_TOKEN", os.environ.get("GITHUB_STATE_TOKEN", "")).strip()
    github_path = os.environ.get("GITHUB_SOURCES_PATH", "").strip()
    if not explicit_path and config_repo and config_token and github_path:
        return load_json_from_github(config_repo, github_path, config_token, os.environ.get("GITHUB_CONFIG_REF", os.environ.get("GITHUB_STATE_REF", "main")))
    path = Path(explicit_path) if explicit_path else default_sources_path(root)
    if not path.is_absolute():
        path = root / path
    return read_json(path)


def enabled_sources(sources_config: dict[str, Any]) -> list[dict[str, Any]]:
    return [source for source in sources_config.get("sources", []) if source.get("enabled", True)]


def apply_source_filters(jobs: list[JobPosting], source_by_id: dict[str, dict[str, Any]]) -> list[JobPosting]:
    filtered = []
    for job in jobs:
        source = source_by_id.get(job.source_id, {})
        if source_filter_allows(job, source):
            filtered.append(job)
    return filtered


def update_state_after_send(state: dict[str, Any], *, week_key: str, selected: list[RankedOpportunity], run_payload: dict[str, Any]) -> dict[str, Any]:
    seen_jobs = state.setdefault("seen_jobs", {})
    for item in selected:
        seen_jobs[item.job.stable_key] = {
            "first_sent_at": now_iso(),
            "company": item.job.company,
            "title": item.job.title,
            "city": item.job.city,
            "url": item.job.canonical_url,
            "content_hash": item.job.content_hash,
        }
    state.setdefault("sent_weeks", {})[week_key] = {"sent_at": now_iso(), "run_id": run_payload.get("run_id", "")}
    runs = state.setdefault("runs", [])
    runs.append(run_payload)
    state["runs"] = runs[-50:]
    state["updated_at"] = now_iso()
    return state




def sender_for_run(config: Any, *, dry_run: bool, sender: Sender | None = None) -> Sender:
    if sender is not None:
        return sender
    if dry_run:
        return DryRunSender()
    return TwilioWhatsAppSender(content_sid=config.twilio_content_sid, messaging_service_sid=config.twilio_messaging_service_sid)


def run_digest(
    root: Path,
    *,
    send: bool = False,
    force: bool = False,
    respect_schedule: bool = False,
    sources_path: str = "",
    deterministic_fallback: bool | None = None,
    include_seen: bool = False,
    now: datetime | None = None,
    state_store: JsonStore | None = None,
    sender: Sender | None = None,
) -> DigestRun:
    root = root.resolve()
    started_at = now_iso()
    run_id = secrets.token_hex(8)
    config = load_runtime_config(root)
    week_key = week_key_for(now, config.timezone)
    errors: list[str] = []
    dry_run = not send
    state_store = state_store or state_store_from_env(root)
    state = state_store.load()

    if respect_schedule and send and not should_send_now(now, timezone_name=config.timezone, send_dow=config.send_dow, send_hour=config.send_hour):
        errors.append("outside_configured_send_window")
        return DigestRun(
            run_id=run_id,
            week_key=week_key,
            dry_run=dry_run,
            send_requested=send,
            started_at=started_at,
            finished_at=now_iso(),
            source_results=[],
            candidate_count=0,
            selected_jobs=[],
            errors=errors,
            state_summary={"mutated": False},
        )
    if send and not force and week_key in state.get("sent_weeks", {}):
        errors.append("week_already_sent")
        return DigestRun(
            run_id=run_id,
            week_key=week_key,
            dry_run=dry_run,
            send_requested=send,
            started_at=started_at,
            finished_at=now_iso(),
            source_results=[],
            candidate_count=0,
            selected_jobs=[],
            errors=errors,
            state_summary={"mutated": False},
        )

    sources_config = load_sources(root, sources_path)
    default_cities = set(config.allowed_cities)
    source_by_id = {str(source.get("id")): source for source in enabled_sources(sources_config)}
    all_jobs: list[JobPosting] = []
    source_results: list[SourceResult] = []
    source_cache_updates: dict[str, Any] = {}
    state_source_cache = state.get("source_cache", {})
    defaults = sources_config.get("defaults", {}) if isinstance(sources_config.get("defaults", {}), dict) else {}
    allow_global_remote = bool(defaults.get("allow_global_remote", config.allow_global_remote))
    if defaults.get("cities"):
        from .cities import canonical_city_set
        default_cities = canonical_city_set(defaults.get("cities"))

    for source in enabled_sources(sources_config):
        source_id = str(source.get("id") or source.get("name") or "source")
        jobs, result, cache_update = fetch_source(
            source,
            default_cities=default_cities,
            allow_global_remote=allow_global_remote,
            cache=state_source_cache.get(source_id, {}),
        )
        source_results.append(result)
        all_jobs.extend(jobs)
        if cache_update:
            source_cache_updates[source_id] = cache_update
        if not result.ok:
            errors.append(f"source_failed:{source_id}:{result.error}")

    filtered = apply_source_filters(all_jobs, source_by_id)
    candidates = remove_seen_jobs(dedupe_jobs(filtered), state, include_seen=include_seen or force)
    criteria_text = load_criteria(root)
    allow_fallback = config.deterministic_fallback if deterministic_fallback is None else deterministic_fallback
    try:
        selected = rank_with_llm(
            candidates,
            criteria_text=criteria_text,
            model=config.rank_model,
            max_selected=config.max_jobs,
        )
    except Exception as exc:
        if allow_fallback:
            errors.append(f"ranker_fallback:{type(exc).__name__}")
            selected = rank_deterministically(candidates, max_selected=config.max_jobs)
        else:
            errors.append(f"ranker_failed:{type(exc).__name__}")
            selected = []

    digest_text = format_digest(selected, week_key=week_key, errors=errors)
    recipient_results = []
    ranker_failed = any(error.startswith("ranker_failed") for error in errors)
    if send and not ranker_failed and (selected or config.send_empty_digest):
        recipients = config.recipients
        if not recipients:
            errors.append("no_recipients_configured")
        active_sender = sender_for_run(config, dry_run=False, sender=sender)
        for recipient in recipients:
            recipient_results.append(active_sender.send(recipient, digest_text))

    finished_at = now_iso()
    digest_run = DigestRun(
        run_id=run_id,
        week_key=week_key,
        dry_run=dry_run,
        send_requested=send,
        started_at=started_at,
        finished_at=finished_at,
        source_results=source_results,
        candidate_count=len(candidates),
        selected_jobs=selected,
        recipient_results=recipient_results,
        errors=errors,
        state_summary={"mutated": False, "seen_jobs": len(state.get("seen_jobs", {}))},
        digest_text=digest_text,
    )
    run_payload = digest_run.to_dict()

    if source_cache_updates:
        state.setdefault("source_cache", {}).update(source_cache_updates)

    if send:
        all_recipient_ok = bool(recipient_results) and all(result.ok for result in recipient_results)
        if all_recipient_ok:
            update_state_after_send(state, week_key=week_key, selected=selected, run_payload=run_payload)
            state_store.save(state)
            digest_run = DigestRun(**{**digest_run.__dict__, "state_summary": {"mutated": True, "seen_jobs": len(state.get("seen_jobs", {}))}})
    return digest_run
