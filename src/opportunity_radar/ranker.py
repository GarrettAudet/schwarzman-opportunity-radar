from __future__ import annotations

import json
import re
from typing import Any

from .models import JobPosting, RankedOpportunity
from .openrouter_client import OpenRouterClient, parse_json_object


class RankingError(RuntimeError):
    pass


COOL_TERMS = {
    "ai": 18,
    "artificial intelligence": 18,
    "machine learning": 16,
    "strategy": 14,
    "strategic": 14,
    "venture": 18,
    "investment": 16,
    "investor": 16,
    "policy": 14,
    "public policy": 16,
    "global": 12,
    "chief of staff": 18,
    "founder": 14,
    "startup": 12,
    "product": 10,
    "climate": 10,
    "fintech": 10,
    "crypto": 8,
    "frontier": 12,
    "leadership": 10,
}

BRAND_TERMS = {
    "openai": 24,
    "anthropic": 24,
    "google": 22,
    "deepmind": 22,
    "microsoft": 20,
    "meta": 20,
    "apple": 18,
    "stripe": 18,
    "airbnb": 16,
    "mckinsey": 20,
    "bain": 18,
    "bcg": 18,
    "blackstone": 18,
    "goldman": 16,
    "world bank": 18,
    "united nations": 18,
}


def rank_with_llm(
    jobs: list[JobPosting],
    *,
    criteria_text: str,
    model: str,
    max_selected: int,
    client: OpenRouterClient | None = None,
) -> list[RankedOpportunity]:
    if not jobs:
        return []
    client = client or OpenRouterClient()
    payload = [job.compact_for_llm() for job in jobs[:60]]
    prompt = f"""
Return JSON only.

You select a weekly OpportunityRadar job digest for Schwarzman Scholars.

Criteria markdown:
{criteria_text}

Candidate jobs:
{json.dumps(payload, ensure_ascii=False)}

Return:
{{
  "opportunities": [
    {{
      "key": "exact candidate key",
      "score": 0,
      "include": true,
      "scholar_fit_reason": "short reason this fits Schwarzman Scholars",
      "why_cool": "one concise digest-ready line",
      "risk_flags": []
    }}
  ]
}}

Include only jobs that are genuinely high-signal. Prefer fewer strong roles over filling the quota.
"""
    text = client.chat(
        model=model,
        messages=[
            {"role": "system", "content": "You rank jobs for a curated weekly opportunities digest. Return strict JSON only."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=3600,
    )
    data = parse_json_object(text)
    rows = data.get("opportunities", [])
    if not isinstance(rows, list):
        raise RankingError("LLM response missing opportunities list")
    jobs_by_key = {job.stable_key: job for job in jobs}
    ranked: list[RankedOpportunity] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key", "")).strip()
        job = jobs_by_key.get(key)
        if job is None:
            continue
        score = float(row.get("score", 0) or 0)
        include = bool(row.get("include", False)) and score >= 70
        ranked.append(
            RankedOpportunity(
                job=job,
                score=score,
                include=include,
                scholar_fit_reason=str(row.get("scholar_fit_reason", "")).strip()[:400],
                why_cool=str(row.get("why_cool", "")).strip()[:400],
                risk_flags=[str(flag).strip()[:120] for flag in row.get("risk_flags", []) if str(flag).strip()],
            )
        )
    ranked.sort(key=lambda item: item.score, reverse=True)
    selected = [item for item in ranked if item.include][:max_selected]
    return [RankedOpportunity(**{**item.__dict__, "rank": index}) for index, item in enumerate(selected, start=1)]


def rank_deterministically(jobs: list[JobPosting], *, max_selected: int) -> list[RankedOpportunity]:
    ranked: list[RankedOpportunity] = []
    for job in jobs:
        haystack = " ".join([job.company, job.title, job.department, " ".join(job.tags), job.description_text[:1200]]).lower()
        score = 45.0
        reasons = []
        for term, points in COOL_TERMS.items():
            if re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", haystack):
                score += points
                reasons.append(term)
        for term, points in BRAND_TERMS.items():
            if term in haystack:
                score += points
                reasons.append(term)
        if job.city in {"Beijing", "Dubai", "Shenzhen", "New York", "San Francisco"}:
            score += 8
        include = score >= 70
        why = f"{job.company} role in {job.city}: {job.title}"
        if reasons:
            why += f" ({', '.join(reasons[:3])})"
        ranked.append(
            RankedOpportunity(
                job=job,
                score=min(score, 100.0),
                include=include,
                scholar_fit_reason="Deterministic fallback matched curated opportunity signals.",
                why_cool=why,
                risk_flags=["deterministic_fallback"],
            )
        )
    ranked.sort(key=lambda item: item.score, reverse=True)
    selected = [item for item in ranked if item.include][:max_selected]
    return [RankedOpportunity(**{**item.__dict__, "rank": index}) for index, item in enumerate(selected, start=1)]
