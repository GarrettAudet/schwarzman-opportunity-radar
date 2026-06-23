from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from opportunity_radar.discovery import run_discovery
from opportunity_radar.fetch import FetchResponse
from opportunity_radar.pipeline import run_digest
from opportunity_radar.state import FileJsonStore


ROOT = Path(__file__).resolve().parents[1]


class FakeGreenhouseFetcher:
    def __init__(self) -> None:
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def __call__(self, url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> FetchResponse:
        self.urls.append(url)
        self.headers.append(dict(headers or {}))
        if url.endswith("/jobs"):
            return FetchResponse(
                status=200,
                url=url,
                headers={"etag": "index-v1"},
                body=json.dumps(
                    {
                        "jobs": [
                            {
                                "id": 100,
                                "title": "Strategy and Operations Analyst, Frontier AI",
                                "absolute_url": "https://example.com/jobs/100",
                                "location": {"name": "San Francisco, CA"},
                                "first_published": "2026-06-15T10:00:00-04:00",
                                "updated_at": "2026-06-15T10:00:00-04:00",
                                "departments": [{"name": "Strategy"}],
                            },
                            {
                                "id": 200,
                                "title": "Director of Operations",
                                "absolute_url": "https://example.com/jobs/200",
                                "location": {"name": "New York City, NY"},
                                "first_published": "2026-06-15T11:00:00-04:00",
                                "updated_at": "2026-06-15T11:00:00-04:00",
                                "departments": [{"name": "Operations"}],
                            },
                            {
                                "id": 500,
                                "title": "Associate",
                                "absolute_url": "https://example.com/jobs/500",
                                "location": {"name": "New York City, NY"},
                                "first_published": "2026-06-16T11:00:00-04:00",
                                "updated_at": "2026-06-16T11:00:00-04:00",
                                "departments": [{"name": "General"}],
                            },
                            {
                                "id": 300,
                                "title": "Operations Associate",
                                "absolute_url": "https://example.com/jobs/300",
                                "location": {"name": "London"},
                                "first_published": "2026-06-15T12:00:00-04:00",
                                "updated_at": "2026-06-15T12:00:00-04:00",
                                "departments": [{"name": "Operations"}],
                            },
                            {
                                "id": 400,
                                "title": "Account Executive, Enterprise Sales",
                                "absolute_url": "https://example.com/jobs/400",
                                "location": {"name": "New York City, NY"},
                                "first_published": "2026-05-01T13:00:00-04:00",
                                "updated_at": "2026-06-15T13:00:00-04:00",
                                "departments": [{"name": "Sales"}],
                            },
                        ]
                    }
                ),
            )
        if url.endswith("/jobs/100"):
            return FetchResponse(
                status=200,
                url=url,
                headers={},
                body=json.dumps(
                    {
                        "id": 100,
                        "title": "Strategy and Operations Analyst, Frontier AI",
                        "absolute_url": "https://example.com/jobs/100",
                        "location": {"name": "San Francisco, CA"},
                        "first_published": "2026-06-15T10:00:00-04:00",
                        "updated_at": "2026-06-15T10:00:00-04:00",
                        "departments": [{"name": "Strategy"}],
                        "content": "Work on AI strategy, product, and operations. 3 years of experience preferred.",
                    }
                ),
            )
        if url.endswith("/jobs/200"):
            return FetchResponse(
                status=200,
                url=url,
                headers={},
                body=json.dumps(
                    {
                        "id": 200,
                        "title": "Director of Operations",
                        "absolute_url": "https://example.com/jobs/200",
                        "location": {"name": "New York City, NY"},
                        "first_published": "2026-06-15T11:00:00-04:00",
                        "updated_at": "2026-06-15T11:00:00-04:00",
                        "departments": [{"name": "Operations"}],
                        "content": "Requires 8+ years of experience leading operations teams.",
                    }
                ),
            )
        if url.endswith("/jobs/500"):
            return FetchResponse(
                status=200,
                url=url,
                headers={},
                body=json.dumps(
                    {
                        "id": 500,
                        "title": "Associate",
                        "absolute_url": "https://example.com/jobs/500",
                        "location": {"name": "New York City, NY"},
                        "first_published": "2026-06-16T11:00:00-04:00",
                        "updated_at": "2026-06-16T11:00:00-04:00",
                        "departments": [{"name": "General"}],
                        "content": "Work on product strategy and special projects. 2 years of experience preferred.",
                    }
                ),
            )
        raise AssertionError(f"unexpected URL {url}")


def write_sources(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "defaults": {"cities": ["New York", "San Francisco"], "allow_global_remote": False},
                "sources": [
                    {
                        "id": "fake-greenhouse",
                        "name": "Fake Greenhouse",
                        "adapter": "greenhouse",
                        "enabled": True,
                        "company": "Anthropic",
                        "board_token": "fake",
                        "cities": ["New York", "San Francisco"],
                        "max_detail_fetches": 5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def write_conditions(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "locations": ["New York", "San Francisco"],
                "posted_within_days": 8,
                "max_years_experience": 5,
                "exclude_any": ["intern"],
                "role_groups": [
                    {
                        "id": "strategy_operations",
                        "label": "Strategy / Operations",
                        "include_any": ["strategy", "operations", "product"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


class DiscoveryTests(unittest.TestCase):
    def test_greenhouse_discovery_prefilters_details_and_weekly_digest_reads_state(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                sources_path = Path(tmp) / "sources.json"
                conditions_path = Path(tmp) / "conditions.json"
                write_sources(sources_path)
                write_conditions(conditions_path)
                store = FileJsonStore(Path(tmp) / "state.json")
                fetcher = FakeGreenhouseFetcher()

                dry_run = run_discovery(
                    ROOT,
                    sources_path=str(sources_path),
                    conditions_path=str(conditions_path),
                    deterministic_fallback=True,
                    state_store=store,
                    now=datetime(2026, 6, 20, tzinfo=timezone.utc),
                    fetcher=fetcher,
                )
                self.assertEqual(dry_run["city_candidate_count"], 4)
                self.assertEqual(dry_run["recent_city_candidate_count"], 3)
                self.assertEqual(dry_run["condition_candidate_count"], 2)
                self.assertEqual(dry_run["candidate_count"], 2)
                self.assertEqual(dry_run["included_count"], 2)
                self.assertEqual(dry_run["included_jobs"][0]["condition_matches"]["role_group_ids"], ["strategy_operations"])
                self.assertFalse((Path(tmp) / "state.json").exists())
                self.assertTrue(any(url.endswith("/jobs/100") for url in fetcher.urls))
                self.assertTrue(any(url.endswith("/jobs/200") for url in fetcher.urls))
                self.assertTrue(any(url.endswith("/jobs/500") for url in fetcher.urls))
                self.assertFalse(any(url.endswith("/jobs/300") for url in fetcher.urls))
                self.assertFalse(any(url.endswith("/jobs/400") for url in fetcher.urls))

                write_run = run_discovery(
                    ROOT,
                    write=True,
                    sources_path=str(sources_path),
                    conditions_path=str(conditions_path),
                    deterministic_fallback=True,
                    state_store=store,
                    now=datetime(2026, 6, 20, tzinfo=timezone.utc),
                    fetcher=FakeGreenhouseFetcher(),
                )
                self.assertTrue(write_run["state_summary"]["mutated"])
                state = store.load()
                statuses = {entry["job"]["external_id"]: entry["status"] for entry in state["evaluated_jobs"].values()}
                self.assertEqual(statuses["100"], "included")
                self.assertEqual(statuses["200"], "rejected")
                self.assertEqual(statuses["500"], "included")
                rejected = next(entry for entry in state["evaluated_jobs"].values() if entry["job"]["external_id"] == "200")
                self.assertEqual(rejected["rejection_reason"], "conditions_filter:years_experience")
                self.assertEqual(rejected["job"]["description_text"], "")

                digest = run_digest(ROOT, from_state=True, state_store=store)
                self.assertEqual(digest.candidate_count, 2)
                self.assertEqual(len(digest.selected_jobs), 2)
                self.assertEqual(digest.selected_jobs[0].job.external_id, "100")

                force_fetcher = FakeGreenhouseFetcher()
                forced = run_discovery(
                    ROOT,
                    write=True,
                    force=True,
                    sources_path=str(sources_path),
                    conditions_path=str(conditions_path),
                    deterministic_fallback=True,
                    state_store=store,
                    now=datetime(2026, 6, 20, tzinfo=timezone.utc),
                    fetcher=force_fetcher,
                )
                self.assertEqual(forced["city_candidate_count"], 4)
                self.assertNotIn("If-None-Match", force_fetcher.headers[0])



class RegistryGreenhouseFetcher:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> FetchResponse:
        self.urls.append(url)
        if url.endswith("/boards/coolco/jobs"):
            return FetchResponse(
                status=200,
                url=url,
                headers={"etag": "coolco-index-v1"},
                body=json.dumps(
                    {
                        "jobs": [
                            {
                                "id": 100,
                                "title": "Strategy and Operations Associate",
                                "absolute_url": "https://job-boards.greenhouse.io/coolco/jobs/100",
                                "location": {"name": "San Francisco, CA"},
                                "first_published": "2026-06-15T10:00:00-04:00",
                                "updated_at": "2026-06-15T10:00:00-04:00",
                            },
                            {
                                "id": 101,
                                "title": "Operations Lead",
                                "absolute_url": "https://job-boards.greenhouse.io/coolco/jobs/101",
                                "location": {"name": "New York City, NY"},
                                "first_published": "2026-06-16T10:00:00-04:00",
                                "updated_at": "2026-06-16T10:00:00-04:00",
                            },
                            {
                                "id": 104,
                                "title": "Associate",
                                "absolute_url": "https://job-boards.greenhouse.io/coolco/jobs/104",
                                "location": {"name": "New York City, NY"},
                                "first_published": "2026-06-17T10:00:00-04:00",
                                "updated_at": "2026-06-17T10:00:00-04:00",
                            },
                            {
                                "id": 102,
                                "title": "Strategy Associate",
                                "absolute_url": "https://job-boards.greenhouse.io/coolco/jobs/102",
                                "location": {"name": "San Francisco, CA"},
                                "first_published": "2026-05-01T10:00:00-04:00",
                                "updated_at": "2026-06-16T10:00:00-04:00",
                            },
                            {
                                "id": 103,
                                "title": "Operations Associate",
                                "absolute_url": "https://job-boards.greenhouse.io/coolco/jobs/103",
                                "location": {"name": "London"},
                                "first_published": "2026-06-16T10:00:00-04:00",
                                "updated_at": "2026-06-16T10:00:00-04:00",
                            },
                        ]
                    }
                ),
            )
        if url.endswith("/boards/coolco/jobs/100"):
            return FetchResponse(
                status=200,
                url=url,
                headers={},
                body=json.dumps(
                    {
                        "id": 100,
                        "title": "Strategy and Operations Associate",
                        "absolute_url": "https://job-boards.greenhouse.io/coolco/jobs/100",
                        "location": {"name": "San Francisco, CA"},
                        "first_published": "2026-06-15T10:00:00-04:00",
                        "updated_at": "2026-06-15T10:00:00-04:00",
                        "content": "Work on AI strategy and business operations. 3 years of experience preferred.",
                    }
                ),
            )
        if url.endswith("/boards/coolco/jobs/101"):
            return FetchResponse(
                status=200,
                url=url,
                headers={},
                body=json.dumps(
                    {
                        "id": 101,
                        "title": "Operations Lead",
                        "absolute_url": "https://job-boards.greenhouse.io/coolco/jobs/101",
                        "location": {"name": "New York City, NY"},
                        "first_published": "2026-06-16T10:00:00-04:00",
                        "updated_at": "2026-06-16T10:00:00-04:00",
                        "content": "Requires 8+ years of operations experience.",
                    }
                ),
            )
        if url.endswith("/boards/coolco/jobs/104"):
            return FetchResponse(
                status=200,
                url=url,
                headers={},
                body=json.dumps(
                    {
                        "id": 104,
                        "title": "Associate",
                        "absolute_url": "https://job-boards.greenhouse.io/coolco/jobs/104",
                        "location": {"name": "New York City, NY"},
                        "first_published": "2026-06-17T10:00:00-04:00",
                        "updated_at": "2026-06-17T10:00:00-04:00",
                        "content": "Work on product strategy and special projects. 2 years of experience preferred.",
                    }
                ),
            )
        raise AssertionError(f"unexpected URL {url}")


class RegistryDiscoveryTests(unittest.TestCase):
    def test_daily_discovery_polls_registry_without_configured_companies(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                sources_path = tmp_path / "sources.json"
                sources_path.write_text(
                    json.dumps({"version": 1, "defaults": {"cities": ["New York", "San Francisco"], "allow_global_remote": False}, "sources": []}),
                    encoding="utf-8",
                )
                conditions_path = tmp_path / "conditions.json"
                conditions_path.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "locations": ["New York", "San Francisco"],
                            "posted_within_days": 8,
                            "max_years_experience": 5,
                            "exclude_any": ["intern"],
                            "role_groups": [
                                {
                                    "id": "strategy_operations",
                                    "label": "Strategy / Operations",
                                    "include_any": ["strategy", "operations"],
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                discovery_path = tmp_path / "discovery.json"
                discovery_path.write_text(
                    json.dumps({"version": 1, "enabled": True, "max_boards_per_daily_run": 5, "max_detail_fetches_per_board": 5}),
                    encoding="utf-8",
                )
                store = FileJsonStore(tmp_path / "state.json")
                store.save(
                    {
                        "version": 1,
                        "seen_jobs": {},
                        "sent_jobs": {},
                        "sent_weeks": {},
                        "evaluated_jobs": {},
                        "source_cache": {},
                        "board_registry": {
                            "greenhouse:coolco": {
                                "ats": "greenhouse",
                                "board_token": "coolco",
                                "active": True,
                                "first_seen": "2026-06-18T00:00:00+00:00",
                                "last_seen": "2026-06-18T00:00:00+00:00",
                                "last_polled": "",
                                "failure_count": 0,
                            }
                        },
                        "runs": [],
                    }
                )
                fetcher = RegistryGreenhouseFetcher()
                dry_run = run_discovery(
                    ROOT,
                    sources_path=str(sources_path),
                    conditions_path=str(conditions_path),
                    discovery_path=str(discovery_path),
                    deterministic_fallback=True,
                    state_store=store,
                    now=datetime(2026, 6, 20, tzinfo=timezone.utc),
                    fetcher=fetcher,
                )
                self.assertEqual(dry_run["registry_board_count"], 1)
                self.assertEqual(dry_run["registry_boards_polled"], 1)
                self.assertEqual(dry_run["city_candidate_count"], 4)
                self.assertEqual(dry_run["recent_city_candidate_count"], 3)
                self.assertEqual(dry_run["condition_candidate_count"], 2)
                self.assertEqual(dry_run["candidate_count"], 2)
                self.assertEqual(dry_run["included_count"], 2)
                self.assertEqual(dry_run["included_jobs"][0]["job"]["company"], "Coolco")
                self.assertTrue(any(url.endswith("/boards/coolco/jobs/100") for url in fetcher.urls))
                self.assertTrue(any(url.endswith("/boards/coolco/jobs/101") for url in fetcher.urls))
                self.assertFalse(any(url.endswith("/boards/coolco/jobs/102") for url in fetcher.urls))

                write_run = run_discovery(
                    ROOT,
                    write=True,
                    sources_path=str(sources_path),
                    conditions_path=str(conditions_path),
                    discovery_path=str(discovery_path),
                    deterministic_fallback=True,
                    state_store=store,
                    now=datetime(2026, 6, 20, tzinfo=timezone.utc),
                    fetcher=RegistryGreenhouseFetcher(),
                )
                self.assertTrue(write_run["state_summary"]["mutated"])
                state = store.load()
                self.assertTrue(state["board_registry"]["greenhouse:coolco"]["last_polled"])
                statuses = {entry["job"]["external_id"]: entry["status"] for entry in state["evaluated_jobs"].values()}
                self.assertEqual(statuses["100"], "included")
                self.assertEqual(statuses["101"], "rejected")

if __name__ == "__main__":
    unittest.main()
