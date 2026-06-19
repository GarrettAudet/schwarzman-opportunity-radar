from __future__ import annotations

import os
from pathlib import Path


DEFAULT_CRITERIA = """# OpportunityRadar Criteria

Audience: Schwarzman Scholars with diverse interests across policy, consulting, technology, startups, investing, operations, global business, public sector, and leadership-track work.

Prefer roles that have at least one of these signals:
- Hot startup or unusually fast-growing company.
- Big brand, elite institution, or respected global platform.
- Strong fit for global leadership, China/global affairs, frontier tech, investing, strategy, operations, public impact, or cross-border business.
- Role gives meaningful ownership, access to senior decision-making, or a differentiated learning curve.
- Explicit years-of-experience requirements are 0-5 years; reject roles requiring more than 5 years.
- Location is one of the configured target cities.

Avoid:
- Generic local roles with no strategic, leadership, brand, mission, or learning signal.
- Roles that look seniority-mismatched for early-career candidates unless they are fellowships, rotational programs, or clearly accessible.
- Roles explicitly requiring more than 5 years of experience.
- Spammy, vague, commission-only, unpaid, or low-information postings.
"""


def load_criteria(root: Path) -> str:
    configured = os.environ.get("OPPORTUNITY_CRITERIA_PATH", "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = root / path
        if path.exists():
            return path.read_text(encoding="utf-8")
    path = root / "docs" / "opportunity-criteria.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return DEFAULT_CRITERIA
