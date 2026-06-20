from __future__ import annotations

import unittest
from pathlib import Path

from opportunity_radar.fetch import FetchResponse
from opportunity_radar.registry import (
    active_registry_sources,
    common_crawl_cdx_url,
    common_crawl_indexes,
    discover_common_crawl_refs,
    discover_registry_refs,
    merge_board_registry,
    parse_cdx_records,
    parse_greenhouse_job_url,
    record_board_poll_result,
    refs_from_payload,
    stable_poll_bucket,
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

        regional = parse_greenhouse_job_url("https://job-boards.anz.greenhouse.io/dawnaerospace/jobs/4001647201")
        self.assertIsNotNone(regional)
        self.assertEqual(regional.board_token, "dawnaerospace")
        self.assertEqual(regional.job_id, "4001647201")

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

    def test_active_registry_sources_spreads_unpolled_boards_by_hash(self) -> None:
        board_tokens = ["alpha", "bravo", "charlie", "delta", "echo"]
        state = {
            "board_registry": {
                f"greenhouse:{token}": {"ats": "greenhouse", "board_token": token, "active": True, "last_polled": ""}
                for token in board_tokens
            }
        }
        sources = active_registry_sources(
            state,
            {"enabled": True, "max_boards_per_daily_run": 3, "poll_spread_seed": "test-seed"},
            default_cities={"New York"},
            allow_global_remote=False,
        )
        expected = sorted(board_tokens, key=lambda token: stable_poll_bucket(token, "test-seed"))[:3]
        self.assertEqual([source["board_token"] for source in sources], expected)
        self.assertNotEqual([source["board_token"] for source in sources], ["alpha", "bravo", "charlie"])

    def test_parse_cdx_records_handles_json_lines(self) -> None:
        records = parse_cdx_records('{"url":"https://job-boards.greenhouse.io/a/jobs/1"}\n{"url":"https://job-boards.greenhouse.io/b/jobs/2"}')
        self.assertEqual(len(records), 2)

    def test_common_crawl_indexes_prefers_cdx_api_endpoint(self) -> None:
        def fetcher(url: str, **_kwargs: object) -> FetchResponse:
            self.assertEqual(url, "https://index.commoncrawl.org/collinfo.json")
            return FetchResponse(
                status=200,
                url=url,
                body='[{"id":"CC-MAIN-2026-21","cdx-api":"https://index.commoncrawl.org/CC-MAIN-2026-21-index"},{"id":"CC-MAIN-2026-17"}]',
                headers={},
            )

        indexes, errors = common_crawl_indexes({"max_common_crawl_indexes": 2}, fetcher=fetcher)
        self.assertEqual(errors, [])
        self.assertEqual(indexes, ["https://index.commoncrawl.org/CC-MAIN-2026-21-index", "https://index.commoncrawl.org/CC-MAIN-2026-17-index"])

    def test_common_crawl_cdx_url_uses_index_endpoint_and_broad_host_path(self) -> None:
        url = common_crawl_cdx_url("CC-MAIN-2026-21", "job-boards.greenhouse.io", 25)
        self.assertTrue(url.startswith("https://index.commoncrawl.org/CC-MAIN-2026-21-index?"))
        self.assertIn("url=job-boards.greenhouse.io%2F%2A", url)
        self.assertIn("limit=25", url)
        self.assertNotIn("/cdx?", url)

    def test_common_crawl_404_query_is_empty_not_fatal(self) -> None:
        def fetcher(url: str, **_kwargs: object) -> FetchResponse:
            if url.endswith("collinfo.json"):
                return FetchResponse(200, url, '[{"id":"CC-MAIN-2026-21"}]', {})
            raise RuntimeError("HTTP 404 fetching https://index.commoncrawl.org/CC-MAIN-2026-21-index: URL Not Found")

        result = discover_common_crawl_refs(ROOT, {"enabled": True, "ats_hosts": ["job-boards.greenhouse.io"]}, fetcher=fetcher)
        self.assertEqual(result["raw_url_count"], 0)
        self.assertEqual(result["errors"], [])

    def test_google_cse_registry_discovers_greenhouse_refs(self) -> None:
        requested_urls: list[str] = []

        def fetcher(url: str, **_kwargs: object) -> FetchResponse:
            requested_urls.append(url)
            return FetchResponse(
                200,
                url,
                '{"items":[{"link":"https://job-boards.greenhouse.io/coolco/jobs/123"},{"link":"https://www.linkedin.com/jobs/view/456"}]}',
                {},
            )

        config = {
            "provider": "google_cse_registry",
            "google_cse": {
                "enabled": True,
                "api_key": "key",
                "cx": "cx",
                "queries": ["site:job-boards.greenhouse.io New York strategy"],
                "results_per_query": 10,
            },
        }
        result = discover_registry_refs(ROOT, config, {}, fetcher=fetcher)
        self.assertEqual(result["raw_url_count"], 2)
        self.assertEqual(result["accepted_ref_count"], 1)
        self.assertEqual(result["rejected_url_count"], 1)
        self.assertEqual(result["refs"][0]["board_token"], "coolco")
        self.assertIn("customsearch/v1", requested_urls[0])

    def test_google_cse_registry_requires_credentials(self) -> None:
        result = discover_registry_refs(ROOT, {"provider": "google_cse_registry", "google_cse": {"enabled": True}}, {}, fetcher=lambda *_args, **_kwargs: self.fail("fetcher should not be called"))
        self.assertEqual(result["accepted_ref_count"], 0)
        self.assertIn("google_cse_missing_credentials", result["errors"])

    def test_hybrid_registry_combines_common_crawl_and_google_refs(self) -> None:
        def fetcher(url: str, **_kwargs: object) -> FetchResponse:
            if url.endswith("collinfo.json"):
                return FetchResponse(200, url, '[{"id":"CC-MAIN-2026-21"}]', {})
            if "customsearch" in url:
                return FetchResponse(200, url, '{"items":[{"link":"https://job-boards.greenhouse.io/searchco/jobs/777"}]}', {})
            return FetchResponse(200, url, '{"url":"https://job-boards.greenhouse.io/crawlco/jobs/100"}', {})

        config = {
            "provider": "hybrid_registry",
            "ats_hosts": ["job-boards.greenhouse.io"],
            "max_registry_refresh_urls": 10,
            "common_crawl_indexes": ["CC-MAIN-2026-21"],
            "google_cse": {
                "enabled": True,
                "api_key": "key",
                "cx": "cx",
                "queries": ["site:job-boards.greenhouse.io New York operations"],
            },
        }
        result = discover_registry_refs(ROOT, config, {}, fetcher=fetcher)
        self.assertEqual(result["accepted_ref_count"], 2)
        self.assertEqual({ref["board_token"] for ref in result["refs"]}, {"crawlco", "searchco"})


if __name__ == "__main__":
    unittest.main()
