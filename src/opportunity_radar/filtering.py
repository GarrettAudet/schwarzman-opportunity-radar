from __future__ import annotations

from collections import OrderedDict
import re
from typing import Any

from .models import JobPosting


MAX_REQUIRED_YEARS = 5


def contains_any(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles if needle.strip())


def explicit_year_requirements(text: str) -> list[tuple[int, int | None]]:
    lowered = re.sub(r"\s+", " ", text.lower())
    requirements: list[tuple[int, int | None]] = []
    range_pattern = re.compile(
        r"(?<![\d$])(\d{1,2})\s*(?:-|to)\s*(\d{1,2})\s*(?:\+?\s*)?(?:years?|yrs?)\b"
        r"(?:\s+of)?(?:\s+(?:relevant|professional|work|industry))?\s+experience"
    )
    for match in range_pattern.finditer(lowered):
        requirements.append((int(match.group(1)), int(match.group(2))))

    min_pattern = re.compile(
        r"(?:minimum|min\.?|at least|requires?|requirement:)?\s*"
        r"(?<![\d$])(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b"
        r"(?:\s+of)?(?:\s+(?:relevant|professional|work|industry))?\s+experience"
    )
    for match in min_pattern.finditer(lowered):
        requirements.append((int(match.group(1)), None))
    return requirements


def years_experience_allowed(text: str, max_required_years: int = MAX_REQUIRED_YEARS) -> bool:
    for minimum, maximum in explicit_year_requirements(text):
        if minimum > max_required_years:
            return False
        if maximum is not None and maximum > max_required_years:
            return False
    return True


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
    if not years_experience_allowed(haystack):
        return False
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
