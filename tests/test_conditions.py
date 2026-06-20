from __future__ import annotations

import unittest

from opportunity_radar.conditions import match_job_conditions, role_group_counts
from opportunity_radar.models import JobPosting


CONDITIONS = {
    "locations": ["New York", "San Francisco"],
    "max_years_experience": 5,
    "exclude_any": ["intern"],
    "role_groups": [
        {"id": "strategy_operations", "label": "Strategy / Operations", "include_any": ["strategy", "operations", "chief of staff"]},
        {"id": "policy_ai", "label": "Policy / AI", "include_any": ["policy", "ai governance"]},
    ],
}


def job(title: str, description: str = "") -> JobPosting:
    return JobPosting(
        source_id="fixture",
        source_name="Fixture",
        external_id=title.lower().replace(" ", "-"),
        title=title,
        company="Example",
        location_text="New York, NY",
        city="New York",
        canonical_url=f"https://example.com/{title.lower().replace(' ', '-')}",
        description_text=description,
    )


class ConditionTests(unittest.TestCase):
    def test_matches_role_group(self) -> None:
        match = match_job_conditions(job("Chief of Staff, AI Strategy"), CONDITIONS)
        self.assertTrue(match.allowed)
        self.assertIn("strategy_operations", match.role_group_ids)
        self.assertIn("strategy", match.matched_terms)

    def test_rejects_no_role_group(self) -> None:
        match = match_job_conditions(job("Account Executive"), CONDITIONS)
        self.assertFalse(match.allowed)
        self.assertEqual(match.rejection_reason, "no_role_group")

    def test_rejects_excluded_keyword_with_boundaries(self) -> None:
        self.assertTrue(match_job_conditions(job("Internal Operations Associate"), CONDITIONS).allowed)
        match = match_job_conditions(job("Operations Intern"), CONDITIONS)
        self.assertFalse(match.allowed)
        self.assertEqual(match.rejection_reason, "excluded_keyword")

    def test_rejects_more_than_five_years(self) -> None:
        match = match_job_conditions(job("Operations Lead", "Requires 8+ years of operations experience."), CONDITIONS)
        self.assertFalse(match.allowed)
        self.assertEqual(match.rejection_reason, "years_experience")

    def test_role_group_counts(self) -> None:
        counts = role_group_counts([
            {"role_group_ids": ["strategy_operations", "policy_ai"]},
            {"role_group_ids": ["strategy_operations"]},
        ])
        self.assertEqual(counts, {"policy_ai": 1, "strategy_operations": 2})


if __name__ == "__main__":
    unittest.main()