from __future__ import annotations

import json
import unittest

from opportunity_radar.adapters import fetch_source, parse_greenhouse, parse_lever, strip_html
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
