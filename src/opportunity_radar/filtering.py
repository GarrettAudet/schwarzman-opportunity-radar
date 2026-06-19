from __future__ import annotations

from collections import OrderedDict
from typing import Any

from .models import JobPosting


def contains_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles if needle.strip())


def source_filter_allows(job: JobPosting, source: dict[str, Any]) -> bool:
    haystack = " ".join(
        [
            job.title,
            job.company,
            job.city,
            job.location_text,
            job.department,
            job.employment_type,
            job.description_text[:2000],
            " ".join(job.tags),
        ]
    )
    exclude = list(source.get("exclude_keywords", []) or [])
    if exclude and contains_any(haystack, exclude):
        return False
    include = list(source.get("include_keywords", []) or [])
    if include and not contains_any(haystack, include):
        return False
    return True


def dedupe_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
    by_key: OrderedDict[str, JobPosting] = OrderedDict()
    for job in jobs:
        by_key.setdefault(job.stable_key, job)
    return list(by_key.values())


def remove_seen_jobs(jobs: list[JobPosting], state: dict[str, Any], *, include_seen: bool = False) -> list[JobPosting]:
    if include_seen:
        return jobs
    seen = state.get("seen_jobs", {})
    return [job for job in jobs if job.stable_key not in seen]
