from __future__ import annotations

import unittest

from opportunity_radar.filtering import explicit_year_requirements, years_experience_allowed


class FilteringTests(unittest.TestCase):
    def test_years_experience_filter_allows_zero_to_five(self) -> None:
        self.assertTrue(years_experience_allowed("0-2 years of experience in operations"))
        self.assertTrue(years_experience_allowed("3 to 5 years of professional experience"))
        self.assertTrue(years_experience_allowed("5+ years of experience preferred"))

    def test_years_experience_filter_rejects_more_than_five(self) -> None:
        self.assertFalse(years_experience_allowed("6+ years of experience required"))
        self.assertFalse(years_experience_allowed("4-7 years of relevant experience"))
        self.assertFalse(years_experience_allowed("Requires 8 years of experience leading operations teams."))

    def test_years_parser_ignores_unrelated_numbers(self) -> None:
        self.assertEqual(explicit_year_requirements("Join a Fortune 500 company in 2026."), [])
        self.assertTrue(years_experience_allowed("Work with 100 teams across 5 markets."))


if __name__ == "__main__":
    unittest.main()
