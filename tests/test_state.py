from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

from opportunity_radar.state import GithubJsonStore


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class GithubJsonStoreTests(unittest.TestCase):
    def test_load_with_sha_decodes_small_contents_api_file(self) -> None:
        payload = {"version": 1, "seen_jobs": {}}
        encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        item = {"content": encoded, "encoding": "base64", "sha": "abc123"}

        def fake_urlopen(request, timeout=30):
            return FakeResponse(json.dumps(item))

        store = GithubJsonStore("owner/repo", "opportunity-state.json", "token", user_agent="test")
        with patch("urllib.request.urlopen", fake_urlopen):
            loaded, sha = store.load_with_sha()

        self.assertEqual(loaded, payload)
        self.assertEqual(sha, "abc123")

    def test_load_with_sha_uses_download_url_when_contents_api_omits_content(self) -> None:
        payload = {"version": 1, "board_registry": {"greenhouse:coolco": {}}}
        calls: list[str] = []
        item = {
            "content": "",
            "encoding": "none",
            "sha": "large123",
            "download_url": "https://raw.githubusercontent.com/owner/repo/main/opportunity-state.json",
        }

        def fake_urlopen(request, timeout=30):
            calls.append(request.full_url)
            if "api.github.com/repos/owner/repo/contents" in request.full_url:
                return FakeResponse(json.dumps(item))
            if "raw.githubusercontent.com/owner/repo" in request.full_url:
                return FakeResponse(json.dumps(payload))
            raise AssertionError(f"Unexpected URL: {request.full_url}")

        store = GithubJsonStore("owner/repo", "opportunity-state.json", "token", user_agent="test")
        with patch("urllib.request.urlopen", fake_urlopen):
            loaded, sha = store.load_with_sha()

        self.assertEqual(loaded, payload)
        self.assertEqual(sha, "large123")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()