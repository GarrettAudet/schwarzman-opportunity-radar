from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from opportunity_radar.discovery import run_discovery
from opportunity_radar.pipeline import run_digest
from opportunity_radar.registry import refresh_registry
from opportunity_radar.sender import TwilioWhatsAppSender
from opportunity_radar.state import FileJsonStore
from tests.test_discovery import RegistryGreenhouseFetcher


ROOT = Path(__file__).resolve().parents[1]


def write_empty_sources(path: Path) -> None:
    path.write_text(
        json.dumps({"version": 1, "defaults": {"cities": ["New York", "San Francisco"], "allow_global_remote": False}, "sources": []}),
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
                        "include_any": ["strategy", "operations"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def write_discovery_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "enabled": True,
                "fixture_path": "tests/fixtures/common_crawl_greenhouse.jsonl",
                "max_registry_refresh_urls": 20,
                "max_boards_per_daily_run": 1,
                "max_detail_fetches_per_board": 5,
            }
        ),
        encoding="utf-8",
    )


class EndToEndPipelineTests(unittest.TestCase):
    @patch("opportunity_radar.twilio_whatsapp.send_message_payload")
    def test_detection_to_twilio_whatsapp_template_message(self, send_message_payload) -> None:  # type: ignore[no-untyped-def]
        send_message_payload.return_value = {"sid": "SM123"}
        env = {
            "OPENROUTER_API_KEY": "",
            "OPPORTUNITY_RECIPIENTS": "whatsapp:+15552223333",
            "OPPORTUNITY_MAX_JOBS": "30",
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+15550001111",
        }
        with patch.dict(os.environ, env, clear=False):
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                store = FileJsonStore(tmp_path / "state.json")
                sources_path = tmp_path / "sources.json"
                conditions_path = tmp_path / "conditions.json"
                discovery_path = tmp_path / "discovery.json"
                write_empty_sources(sources_path)
                write_conditions(conditions_path)
                write_discovery_config(discovery_path)

                registry = refresh_registry(
                    ROOT,
                    write=True,
                    discovery_path=str(discovery_path),
                    state_store=store,
                )
                self.assertEqual(registry["accepted_ref_count"], 3)
                self.assertEqual(registry["state_summary"]["board_registry"], 2)

                discovery = run_discovery(
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
                self.assertEqual(discovery["registry_boards_polled"], 1)
                self.assertEqual(discovery["included_count"], 2)

                digest = run_digest(
                    ROOT,
                    send=True,
                    force=True,
                    from_state=True,
                    state_store=store,
                    sender=TwilioWhatsAppSender(content_sid="HX123", messaging_service_sid="MG123"),
                )
                self.assertEqual(digest.candidate_count, 2)
                self.assertEqual(len(digest.selected_jobs), 2)
                self.assertEqual(len(digest.recipient_results), 1)
                self.assertTrue(digest.recipient_results[0].ok)
                self.assertTrue(digest.state_summary["mutated"])
                payload = send_message_payload.call_args.args[2]
                self.assertEqual(payload["To"], "whatsapp:+15552223333")
                self.assertEqual(payload["ContentSid"], "HX123")
                self.assertEqual(payload["MessagingServiceSid"], "MG123")
                content_variables = json.loads(payload["ContentVariables"])
                self.assertIn("Coolco - Strategy and Operations Associate", content_variables["1"])
                self.assertIn("https://job-boards.greenhouse.io/coolco/jobs/100", content_variables["1"])


if __name__ == "__main__":
    unittest.main()
