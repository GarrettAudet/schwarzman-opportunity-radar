from __future__ import annotations

import unittest

from opportunity_radar.filtering import contains_any, explicit_year_requirements, source_filter_allows, years_experience_allowed
from opportunity_radar.models import JobPosting


class FilteringTests(unittest.TestCase):
    def test_years_experience_filter_allows_zero_to_five(self) -> None:
        self.assertTrue(years_experience_allowed("0-2 years of experience in operations"))
        self.assertTrue(years_experience_allowed("3 to 5 years of professional experience"))
        self.assertTrue(years_experience_allowed("5+ years of experience preferred"))

    def test_years_experience_filter_rejects_more_than_five(self) -> None:
        self.assertFalse(years_experience_allowed("6+ years of experience required"))
        self.assertFalse(years_experience_allowed("4-7 years of relevant experience"))
        self.assertFalse(years_experience_allowed("Requires 8 years of experience leading operations teams."))
        self.assertFalse(years_experience_allowed("Preferred qualifications: 8+ years of enterprise sales or business development experience."))
        self.assertFalse(years_experience_allowed("Experience requirement: 6+ years in operations."))
        self.assertFalse(years_experience_allowed("Who You Are 6+ years in client marketing, communications, or events."))

    def test_keyword_filters_use_boundaries(self) -> None:
        self.assertFalse(contains_any("internal mobility program", ["intern"]))
        self.assertTrue(contains_any("summer intern program", ["intern"]))
        self.assertTrue(contains_any("chief of staff role", ["chief of staff"]))

    def test_source_filter_scans_long_descriptions_for_experience(self) -> None:
        long_intro = "context " * 350
        job = JobPosting(
            source_id="fixture",
            source_name="Fixture",
            external_id="long-years",
            title="Operations Lead",
            company="Example",
            location_text="New York",
            city="New York",
            canonical_url="https://example.com/long-years",
            description_text=long_intro + "Preferred qualifications: 8+ years of enterprise sales or business development experience.",
        )
        self.assertFalse(source_filter_allows(job, {}))

    def test_source_filter_scans_full_description_for_years(self) -> None:
        long_intro = "context " * 1400
        job = JobPosting(
            source_id="fixture",
            source_name="Fixture",
            external_id="long-years",
            title="Strategic Events Program Manager",
            company="Example",
            location_text="New York",
            city="New York",
            canonical_url="https://example.com/long-years",
            description_text=long_intro + "Who You Are 6+ years in client marketing, communications, or events.",
        )
        self.assertFalse(source_filter_allows(job, {}))

    def test_years_parser_ignores_unrelated_numbers(self) -> None:
        self.assertEqual(explicit_year_requirements("Join a Fortune 500 company in 2026."), [])
        self.assertTrue(years_experience_allowed("Work with 100 teams across 5 markets."))


if __name__ == "__main__":
    unittest.main()
