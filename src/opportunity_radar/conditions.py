from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .cities import canonical_city_set
from .config import read_json
from .filtering import MAX_REQUIRED_YEARS, years_experience_allowed
from .models import JobPosting
from .state import load_json_from_github


@dataclass(frozen=True)
class ConditionMatch:
    allowed: bool
    city: str
    role_group_ids: list[str]
    role_group_labels: list[str]
    matched_terms: list[str]
    excluded_terms: list[str]
    rejection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "city": self.city,
            "role_group_ids": list(self.role_group_ids),
            "role_group_labels": list(self.role_group_labels),
            "matched_terms": list(self.matched_terms),
            "excluded_terms": list(self.excluded_terms),
            "rejection_reason": self.rejection_reason,
        }


def default_conditions_path(root: Path) -> Path:
    configured = os.environ.get("OPPORTUNITY_CONDITIONS_PATH", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else root / path
    local_path = root / "data" / "config" / "conditions.local.json"
    if local_path.exists():
        return local_path
    return root / "data" / "config" / "conditions.example.json"


def load_conditions(root: Path, explicit_path: str = "") -> dict[str, Any]:
    config_repo = os.environ.get("GITHUB_CONFIG_REPO", os.environ.get("GITHUB_STATE_REPO", "")).strip()
    config_token = os.environ.get("GITHUB_CONFIG_TOKEN", os.environ.get("GITHUB_STATE_TOKEN", "")).strip()
    github_path = os.environ.get("GITHUB_CONDITIONS_PATH", "").strip()
    if not explicit_path and config_repo and config_token and github_path:
        ref = os.environ.get("GITHUB_CONFIG_REF", os.environ.get("GITHUB_STATE_REF", "main"))
        return load_json_from_github(config_repo, github_path, config_token, ref)
    path = Path(explicit_path) if explicit_path else default_conditions_path(root)
    if not path.is_absolute():
        path = root / path
    return read_json(path)


def conditions_allowed_cities(conditions: dict[str, Any]) -> set[str]:
    values = conditions.get("locations") or conditions.get("cities") or []
    return canonical_city_set(values) if values else set()


def keyword_pattern(term: str) -> str:
    normalized = re.sub(r"\s+", " ", term.lower()).strip()
    if not normalized:
        return ""
    return r"(?<![a-z0-9])" + re.escape(normalized) + r"(?![a-z0-9])"


def matched_keywords(text: str, terms: Iterable[object]) -> list[str]:
    lowered = text.lower()
    matches: list[str] = []
    for raw_term in terms:
        term = re.sub(r"\s+", " ", str(raw_term or "").lower()).strip()
        pattern = keyword_pattern(term)
        if pattern and re.search(pattern, lowered) and term not in matches:
            matches.append(term)
    return matches


def condition_text(job: JobPosting, *, description_chars: int) -> str:
    return " ".join(
        [
            job.title,
            job.company,
            job.city,
            job.location_text,
            job.department,
            job.employment_type,
            " ".join(job.tags),
            job.description_text[:description_chars],
        ]
    )


def group_matches(text: str, group: dict[str, Any]) -> tuple[bool, list[str]]:
    include_any = list(group.get("include_any", []) or [])
    include_all = list(group.get("include_all", []) or [])
    exclude_any = list(group.get("exclude_any", []) or [])
    if exclude_any and matched_keywords(text, exclude_any):
        return False, []
    matched_any = matched_keywords(text, include_any)
    matched_all = matched_keywords(text, include_all)
    if include_all and len(matched_all) != len([item for item in include_all if str(item).strip()]):
        return False, []
    if include_any and not matched_any:
        return False, []
    if not include_any and not include_all:
        return False, []
    return True, [*matched_any, *[term for term in matched_all if term not in matched_any]]


def match_job_conditions(
    job: JobPosting,
    conditions: dict[str, Any],
    *,
    description_chars: int = 1200,
) -> ConditionMatch:
    text = condition_text(job, description_chars=description_chars)
    max_years = int(conditions.get("max_years_experience", MAX_REQUIRED_YEARS) or MAX_REQUIRED_YEARS)
    excluded_terms = matched_keywords(text, conditions.get("exclude_any", []) or [])
    if excluded_terms:
        return ConditionMatch(False, job.city, [], [], [], excluded_terms, "excluded_keyword")
    if not years_experience_allowed(text, max_required_years=max_years):
        return ConditionMatch(False, job.city, [], [], [], [], "years_experience")

    role_group_ids: list[str] = []
    role_group_labels: list[str] = []
    matched_terms: list[str] = []
    role_groups = [group for group in conditions.get("role_groups", []) if isinstance(group, dict)]
    for group in role_groups:
        ok, group_terms = group_matches(text, group)
        if not ok:
            continue
        group_id = str(group.get("id") or group.get("label") or "role_group").strip()
        label = str(group.get("label") or group_id).strip()
        if group_id and group_id not in role_group_ids:
            role_group_ids.append(group_id)
            role_group_labels.append(label)
        for term in group_terms:
            if term not in matched_terms:
                matched_terms.append(term)

    if role_groups and not role_group_ids:
        return ConditionMatch(False, job.city, [], [], [], [], "no_role_group")
    return ConditionMatch(True, job.city, role_group_ids, role_group_labels, matched_terms, [], "")


def role_group_counts(matches: Iterable[ConditionMatch | dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        if isinstance(match, ConditionMatch):
            group_ids = match.role_group_ids
        else:
            group_ids = [str(item) for item in match.get("role_group_ids", [])]
        for group_id in group_ids:
            counts[group_id] = counts.get(group_id, 0) + 1
    return dict(sorted(counts.items()))