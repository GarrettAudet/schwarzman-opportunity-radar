from __future__ import annotations

from datetime import datetime

from .models import RankedOpportunity


def week_label(week_key: str) -> str:
    return week_key.replace("-W", " week ")


def format_digest(selected: list[RankedOpportunity], *, week_key: str, errors: list[str] | None = None) -> str:
    if not selected:
        return (
            f"*OpportunityRadar - {week_label(week_key)}*\n\n"
            "No new high-signal roles matched the criteria this week."
        )
    lines = [
        f"*OpportunityRadar - {week_label(week_key)}*",
        "",
        "Curated roles for Schwarzman Scholars:",
        "",
    ]
    for item in selected:
        job = item.job
        url = job.apply_url or job.canonical_url
        lines.append(f"{item.rank}. *{job.company} - {job.title}*")
        lines.append(f"   {job.city} | Score {int(round(item.score))}")
        reason = item.why_cool or item.scholar_fit_reason
        if reason:
            lines.append(f"   {reason}")
        if url:
            lines.append(f"   {url}")
        lines.append("")
    if errors and any(error.startswith("source_failed") for error in errors):
        lines.append("Some sources failed this run; the digest used the sources that were available.")
    return "\n".join(lines).strip()


def digest_preview_title() -> str:
    return datetime.now().strftime("OpportunityRadar preview %Y-%m-%d %H:%M")
