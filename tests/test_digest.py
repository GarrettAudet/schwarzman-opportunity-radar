from __future__ import annotations

import unittest

from opportunity_radar.digest import format_digest
from opportunity_radar.models import JobPosting, RankedOpportunity


def ranked(index: int, title: str, group_id: str) -> RankedOpportunity:
    job = JobPosting(
        source_id="fixture",
        source_name="Fixture",
        external_id=str(index),
        title=title,
        company="Example",
        location_text="New York",
        city="New York",
        canonical_url=f"https://example.com/{index}",
        tags=[f"condition:{group_id}"],
    )
    return RankedOpportunity(job, 90, True, "", f"Why {title}", rank=index)


class DigestTests(unittest.TestCase):
    def test_digest_groups_by_condition_tags(self) -> None:
        text = format_digest(
            [ranked(1, "Legal Engineer", "legal_regulatory"), ranked(2, "Strategy Associate", "strategy_operations")],
            week_key="2026-W25",
        )
        self.assertIn("Hello everyone,", text)
        self.assertIn("week of June 15-21, 2026", text)
        self.assertIn("Strategy / Operations", text)
        self.assertIn("Legal / Regulatory", text)
        self.assertIn("Best,\nGarrett", text)
        self.assertLess(text.index("Strategy / Operations"), text.index("Legal / Regulatory"))


if __name__ == "__main__":
    unittest.main()
