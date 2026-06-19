from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opportunity_radar.models import RecipientResult
from opportunity_radar.pipeline import run_digest
from opportunity_radar.state import FileJsonStore


ROOT = Path(__file__).resolve().parents[1]


class FakeSender:
    provider = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str]] = []

    def send(self, recipient: str, message: str) -> RecipientResult:
        self.sent.append((recipient, message))
        return RecipientResult(recipient=recipient, ok=not self.fail, provider=self.provider, error="failed" if self.fail else "")


class PipelineTests(unittest.TestCase):
    def test_dry_run_does_not_mutate_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = FileJsonStore(Path(tmp) / "state.json")
            result = run_digest(
                ROOT,
                sources_path="tests/fixtures/sources.fixture.json",
                deterministic_fallback=True,
                include_seen=True,
                state_store=store,
            )
            self.assertGreaterEqual(result.candidate_count, 3)
            self.assertGreaterEqual(len(result.selected_jobs), 1)
            self.assertFalse((Path(tmp) / "state.json").exists())

    def test_send_mutates_state_once(self) -> None:
        with patch.dict(os.environ, {"OPPORTUNITY_RECIPIENTS": "whatsapp:+15550001111"}, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                store = FileJsonStore(Path(tmp) / "state.json")
                sender = FakeSender()
                result = run_digest(
                    ROOT,
                    send=True,
                    force=True,
                    sources_path="tests/fixtures/sources.fixture.json",
                    deterministic_fallback=True,
                    include_seen=True,
                    state_store=store,
                    sender=sender,
                )
                self.assertTrue(result.state_summary["mutated"])
                state = store.load()
                self.assertIn(result.week_key, state["sent_weeks"])
                self.assertGreaterEqual(len(state["seen_jobs"]), 1)

                second = run_digest(
                    ROOT,
                    send=True,
                    force=False,
                    sources_path="tests/fixtures/sources.fixture.json",
                    deterministic_fallback=True,
                    include_seen=True,
                    state_store=store,
                    sender=sender,
                )
                self.assertIn("week_already_sent", second.errors)
                self.assertFalse(second.state_summary["mutated"])

    def test_ranker_failure_does_not_send_without_fallback(self) -> None:
        with patch.dict(os.environ, {"OPPORTUNITY_RECIPIENTS": "whatsapp:+15550001111", "OPENROUTER_API_KEY": ""}, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                store = FileJsonStore(Path(tmp) / "state.json")
                sender = FakeSender()
                result = run_digest(
                    ROOT,
                    send=True,
                    force=True,
                    sources_path="tests/fixtures/sources.fixture.json",
                    deterministic_fallback=False,
                    include_seen=True,
                    state_store=store,
                    sender=sender,
                )
                self.assertIn("ranker_failed:OpenRouterError", result.errors)
                self.assertEqual(sender.sent, [])
                self.assertFalse(result.state_summary["mutated"])
                self.assertFalse((Path(tmp) / "state.json").exists())
    def test_partial_failure_does_not_mark_sent(self) -> None:
        with patch.dict(os.environ, {"OPPORTUNITY_RECIPIENTS": "whatsapp:+15550001111"}, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                store = FileJsonStore(Path(tmp) / "state.json")
                result = run_digest(
                    ROOT,
                    send=True,
                    force=True,
                    sources_path="tests/fixtures/sources.fixture.json",
                    deterministic_fallback=True,
                    include_seen=True,
                    state_store=store,
                    sender=FakeSender(fail=True),
                )
                self.assertFalse(result.state_summary["mutated"])
                self.assertFalse((Path(tmp) / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
