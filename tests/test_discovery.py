from __future__ import annotations

import json
import os
import tempfile
import unittest
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

    def __call__(self, url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> FetchResponse:
        self.urls.append(url)
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
                                "updated_at": "2026-06-15T10:00:00-04:00",
                                "departments": [{"name": "Strategy"}],
                            },
                            {
                                "id": 200,
                                "title": "Director of Operations",
                                "absolute_url": "https://example.com/jobs/200",
                                "location": {"name": "New York City, NY"},
                                "updated_at": "2026-06-15T11:00:00-04:00",
                                "departments": [{"name": "Operations"}],
                            },
                            {
                                "id": 300,
                                "title": "Operations Associate",
                                "absolute_url": "https://example.com/jobs/300",
                                "location": {"name": "London"},
                                "updated_at": "2026-06-15T12:00:00-04:00",
                                "departments": [{"name": "Operations"}],
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
                        "updated_at": "2026-06-15T11:00:00-04:00",
                        "departments": [{"name": "Operations"}],
                        "content": "Requires 8+ years of experience leading operations teams.",
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


class DiscoveryTests(unittest.TestCase):
    def test_greenhouse_discovery_prefilters_details_and_weekly_digest_reads_state(self) -> None:
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                sources_path = Path(tmp) / "sources.json"
                write_sources(sources_path)
                store = FileJsonStore(Path(tmp) / "state.json")
                fetcher = FakeGreenhouseFetcher()

                dry_run = run_discovery(
                    ROOT,
                    sources_path=str(sources_path),
                    deterministic_fallback=True,
                    state_store=store,
                    fetcher=fetcher,
                )
                self.assertEqual(dry_run["candidate_count"], 1)
                self.assertEqual(dry_run["included_count"], 1)
                self.assertFalse((Path(tmp) / "state.json").exists())
                self.assertTrue(any(url.endswith("/jobs/100") for url in fetcher.urls))
                self.assertTrue(any(url.endswith("/jobs/200") for url in fetcher.urls))
                self.assertFalse(any(url.endswith("/jobs/300") for url in fetcher.urls))

                write_run = run_discovery(
                    ROOT,
                    write=True,
                    sources_path=str(sources_path),
                    deterministic_fallback=True,
                    state_store=store,
                    fetcher=FakeGreenhouseFetcher(),
                )
                self.assertTrue(write_run["state_summary"]["mutated"])
                state = store.load()
                statuses = {entry["job"]["external_id"]: entry["status"] for entry in state["evaluated_jobs"].values()}
                self.assertEqual(statuses["100"], "included")
                self.assertEqual(statuses["200"], "rejected")

                digest = run_digest(ROOT, from_state=True, state_store=store)
                self.assertEqual(digest.candidate_count, 1)
                self.assertEqual(len(digest.selected_jobs), 1)
                self.assertEqual(digest.selected_jobs[0].job.external_id, "100")


if __name__ == "__main__":
    unittest.main()