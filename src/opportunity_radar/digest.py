from __future__ import annotations

from datetime import datetime

from .models import RankedOpportunity


GROUP_ORDER = [
    ("strategy_operations", "Strategy / Operations"),
    ("legal_regulatory", "Legal / Regulatory"),
    ("policy_ai", "Policy / AI Governance"),
    ("investing_venture", "Investing / Venture"),
    ("product_growth_partnerships", "Product / Growth / Partnerships"),
    ("frontier_tech_startups", "Frontier Tech / Startups"),
]
GROUP_LABELS = dict(GROUP_ORDER)
OTHER_GROUP = "Other Strong Matches"


def week_label(week_key: str) -> str:
    return week_key.replace("-W", " week ")


def condition_group_ids(item: RankedOpportunity) -> list[str]:
    ids: list[str] = []
    for tag in item.job.tags:
        if not tag.startswith("condition:"):
            continue
        group_id = tag.split(":", 1)[1].strip()
        if group_id and group_id not in ids:
            ids.append(group_id)
    return ids


def digest_group_label(item: RankedOpportunity) -> str:
    ids = condition_group_ids(item)
    for group_id, label in GROUP_ORDER:
        if group_id in ids:
            return label
    if ids:
        return GROUP_LABELS.get(ids[0], ids[0].replace("_", " ").title())
    return OTHER_GROUP


def grouped_opportunities(selected: list[RankedOpportunity]) -> list[tuple[str, list[RankedOpportunity]]]:
    buckets: dict[str, list[RankedOpportunity]] = {}
    for item in selected:
        buckets.setdefault(digest_group_label(item), []).append(item)
    labels = [label for _group_id, label in GROUP_ORDER if label in buckets]
    labels.extend(label for label in buckets if label not in labels)
    return [(label, buckets[label]) for label in labels]


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
    for group_label, items in grouped_opportunities(selected):
        lines.append(f"*{group_label}*")
        for item in items:
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
