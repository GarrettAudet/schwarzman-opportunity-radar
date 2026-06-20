from __future__ import annotations

import json
import unittest

from opportunity_radar.adapters import ashby_index_url, fetch_source, lever_index_url, parse_ashby, parse_greenhouse, parse_lever, strip_html
from opportunity_radar.cities import canonical_city_set
from opportunity_radar.fetch import FetchResponse


class AdapterTests(unittest.TestCase):
    def test_fixture_adapter_filters_city(self) -> None:
        source = {
            "id": "fixture",
            "name": "Fixture",
            "adapter": "fixture",
            "company": "FixtureCo",
            "jobs": [
                {"external_id": "1", "title": "AI Strategy", "location": "San Francisco", "canonical_url": "https://x/1"},
                {"external_id": "2", "title": "Ops", "location": "London", "canonical_url": "https://x/2"},
            ],
        }
        jobs, result, _cache = fetch_source(
            source,
            default_cities=canonical_city_set(["San Francisco"]),
            allow_global_remote=False,
        )
        self.assertTrue(result.ok)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].city, "San Francisco")

    def test_greenhouse_and_lever_parse_shapes(self) -> None:
        greenhouse = parse_greenhouse(
            {
                "jobs": [
                    {
                        "id": 123,
                        "title": "Policy Lead",
                        "absolute_url": "https://jobs/123",
                        "location": {"name": "Beijing"},
                        "departments": [{"name": "Policy"}],
                    }
                ]
            },
            {"company": "Example"},
        )
        self.assertEqual(greenhouse[0]["location"], "Beijing")
        self.assertEqual(greenhouse[0]["department"], "Policy")

        lever = parse_lever(
            [
                {
                    "id": "abc",
                    "text": "Venture Analyst",
                    "hostedUrl": "https://jobs/abc",
                    "categories": {"location": "Dubai", "team": "Investing", "commitment": "Full-time"},
                }
            ],
            {"company": "Example"},
        )
        self.assertEqual(lever[0]["location"], "Dubai")
        self.assertEqual(lever[0]["department"], "Investing")

        ashby = parse_ashby(
            {
                "jobs": [
                    {
                        "id": "xyz",
                        "title": "Operations Associate",
                        "jobUrl": "https://jobs/xyz",
                        "locationName": "Sydney",
                        "department": "Operations",
                        "employmentType": "Full-time",
                    }
                ]
            },
            {"company": "Example"},
        )
        self.assertEqual(ashby[0]["location"], "Sydney")
        self.assertEqual(ashby[0]["department"], "Operations")

    def test_lever_and_ashby_default_index_urls(self) -> None:
        self.assertEqual(lever_index_url({"board_token": "coolco"}), "https://api.lever.co/v0/postings/coolco?mode=json")
        self.assertEqual(ashby_index_url({"board_token": "ashbyco"}), "https://api.ashbyhq.com/posting-api/job-board/ashbyco")

        calls: list[str] = []

        def fake_fetch(url: str, *, headers: dict[str, str], timeout: int) -> FetchResponse:
            calls.append(url)
            if "lever.co" in url:
                body = json.dumps(
                    [
                        {
                            "id": "lever-1",
                            "text": "Operations Associate",
                            "hostedUrl": "https://jobs.lever.co/coolco/lever-1",
                            "createdAt": "2026-06-20T00:00:00Z",
                            "categories": {"location": "New York", "team": "Operations", "commitment": "Full-time"},
                        }
                    ]
                )
            else:
                body = json.dumps(
                    {
                        "jobs": [
                            {
                                "id": "ashby-1",
                                "title": "Strategy Associate",
                                "jobUrl": "https://jobs.ashbyhq.com/ashbyco/ashby-1",
                                "locationName": "San Francisco",
                                "publishedAt": "2026-06-20T00:00:00Z",
                            }
                        ]
                    }
                )
            return FetchResponse(status=200, url=url, headers={}, body=body)

        lever_jobs, lever_result, _cache = fetch_source(
            {"id": "lever", "name": "Lever", "adapter": "lever", "company": "LeverCo", "board_token": "coolco"},
            default_cities=canonical_city_set(["New York", "San Francisco"]),
            allow_global_remote=False,
            fetcher=fake_fetch,
        )
        ashby_jobs, ashby_result, _cache = fetch_source(
            {"id": "ashby", "name": "Ashby", "adapter": "ashby", "company": "AshbyCo", "board_token": "ashbyco"},
            default_cities=canonical_city_set(["New York", "San Francisco"]),
            allow_global_remote=False,
            fetcher=fake_fetch,
        )
        self.assertTrue(lever_result.ok)
        self.assertTrue(ashby_result.ok)
        self.assertEqual(len(lever_jobs), 1)
        self.assertEqual(len(ashby_jobs), 1)
        self.assertEqual(calls, [
            "https://api.lever.co/v0/postings/coolco?mode=json",
            "https://api.ashbyhq.com/posting-api/job-board/ashbyco",
        ])

    def test_strip_html_handles_escaped_tags(self) -> None:
        text = strip_html("&lt;div&gt;&lt;h2&gt;About&lt;/h2&gt;&lt;p&gt;Hello&amp;nbsp;world&lt;/p&gt;&lt;/div&gt;")
        self.assertEqual(text, "About Hello world")
        self.assertNotIn("<div>", text)
    def test_fetcher_receives_conditional_headers(self) -> None:
        calls = []

        def fake_fetch(url: str, *, headers: dict[str, str], timeout: int) -> FetchResponse:
            calls.append(headers)
            return FetchResponse(
                status=200,
                url=url,
                headers={"etag": "next", "last-modified": "today"},
                body=json.dumps(
                    {
                        "jobs": [
                            {
                                "id": 1,
                                "title": "AI Strategy",
                                "absolute_url": "https://jobs/1",
                                "location": {"name": "New York"},
                            }
                        ]
                    }
                ),
            )

        jobs, result, cache = fetch_source(
            {"id": "gh", "name": "GH", "adapter": "greenhouse", "company": "GHCo", "url": "https://example.com"},
            default_cities=canonical_city_set(["New York"]),
            allow_global_remote=False,
            cache={"etag": "old"},
            fetcher=fake_fetch,
        )
        self.assertEqual(calls[0]["If-None-Match"], "old")
        self.assertEqual(cache["etag"], "next")
        self.assertEqual(len(jobs), 1)
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
