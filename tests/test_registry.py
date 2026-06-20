from __future__ import annotations

import unittest
from pathlib import Path

from opportunity_radar.fetch import FetchResponse
from opportunity_radar.registry import (
    active_registry_sources,
    discover_common_crawl_refs,
    merge_board_registry,
    parse_cdx_records,
    parse_greenhouse_job_url,
    record_board_poll_result,
    refs_from_payload,
)


ROOT = Path(__file__).resolve().parents[1]


class RegistryTests(unittest.TestCase):
    def test_parses_greenhouse_job_urls(self) -> None:
        modern = parse_greenhouse_job_url("https://job-boards.greenhouse.io/openai/jobs/123456")
        self.assertIsNotNone(modern)
        self.assertEqual(modern.board_token, "openai")
        self.assertEqual(modern.job_id, "123456")

        legacy = parse_greenhouse_job_url("https://boards.greenhouse.io/frontierops/jobs/abc_123")
        self.assertIsNotNone(legacy)
        self.assertEqual(legacy.board_token, "frontierops")
        self.assertEqual(legacy.job_id, "abc_123")

        api = parse_greenhouse_job_url("https://boards-api.greenhouse.io/v1/boards/coolco/jobs/777")
        self.assertIsNotNone(api)
        self.assertEqual(api.board_token, "coolco")

    def test_rejects_non_greenhouse_and_excluded_domains(self) -> None:
        self.assertIsNone(parse_greenhouse_job_url("https://www.linkedin.com/jobs/view/123"))
        self.assertIsNone(parse_greenhouse_job_url("https://example.com/openai/jobs/123"))
        self.assertIsNone(parse_greenhouse_job_url("https://job-boards.greenhouse.io/openai/about"))

    def test_common_crawl_fixture_discovers_and_merges_boards(self) -> None:
        config = {
            "enabled": True,
            "provider": "common_crawl_registry",
            "fixture_path": "tests/fixtures/common_crawl_greenhouse.jsonl",
            "max_registry_refresh_urls": 20,
        }
        result = discover_common_crawl_refs(ROOT, config)
        self.assertEqual(result["raw_url_count"], 5)
        self.assertEqual(result["accepted_ref_count"], 3)
        self.assertEqual(result["rejected_url_count"], 2)

        state: dict[str, object] = {}
        summary = merge_board_registry(state, refs_from_payload(result), seen_at="2026-06-20T00:00:00+00:00")
        self.assertEqual(summary["boards_added"], 2)
        self.assertEqual(summary["boards_after"], 2)
        registry = state["board_registry"]
        self.assertIn("greenhouse:coolco", registry)
        self.assertIn("greenhouse:frontierops", registry)
        self.assertEqual(registry["greenhouse:coolco"]["sample_job_ids"], ["100", "101"])

    def test_record_board_poll_deactivates_after_failures(self) -> None:
        state = {
            "board_registry": {
                "greenhouse:broken": {
                    "ats": "greenhouse",
                    "board_token": "broken",
                    "active": True,
                    "failure_count": 2,
                }
            }
        }
        source = {"_registry_key": "greenhouse:broken"}
        record_board_poll_result(state, source, ok=False, error="RuntimeError", max_failures=3)
        entry = state["board_registry"]["greenhouse:broken"]
        self.assertFalse(entry["active"])
        self.assertEqual(entry["failure_count"], 3)
        self.assertEqual(entry["last_error"], "RuntimeError")

    def test_active_registry_sources_limit_and_shape(self) -> None:
        state = {
            "board_registry": {
                "greenhouse:coolco": {"ats": "greenhouse", "board_token": "coolco", "active": True, "last_polled": ""},
                "greenhouse:inactive": {"ats": "greenhouse", "board_token": "inactive", "active": False, "last_polled": ""},
            }
        }
        sources = active_registry_sources(
            state,
            {"enabled": True, "max_boards_per_daily_run": 5, "max_detail_fetches_per_board": 7},
            default_cities={"New York", "San Francisco"},
            allow_global_remote=False,
        )
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["adapter"], "greenhouse")
        self.assertEqual(sources[0]["board_token"], "coolco")
        self.assertEqual(sources[0]["max_detail_fetches"], 7)

    def test_parse_cdx_records_handles_json_lines(self) -> None:
        records = parse_cdx_records('{"url":"https://job-boards.greenhouse.io/a/jobs/1"}\n{"url":"https://job-boards.greenhouse.io/b/jobs/2"}')
        self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
