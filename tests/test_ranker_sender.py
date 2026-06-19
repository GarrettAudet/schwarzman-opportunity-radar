from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from opportunity_radar.models import JobPosting
from opportunity_radar.ranker import rank_deterministically, rank_with_llm
from opportunity_radar.sender import TwilioWhatsAppSender


class FakeClient:
    def chat(self, **_kwargs: object) -> str:
        return """
        {
          "opportunities": [
            {
              "key": "fixture:1",
              "score": 91,
              "include": true,
              "scholar_fit_reason": "Strong global AI strategy fit.",
              "why_cool": "Frontier AI strategy role with leadership exposure.",
              "risk_flags": []
            }
          ]
        }
        """


class RankerSenderTests(unittest.TestCase):
    def test_llm_json_maps_to_job(self) -> None:
        job = JobPosting(
            source_id="fixture",
            source_name="Fixture",
            external_id="1",
            title="AI Strategy Lead",
            company="OpenAI",
            location_text="San Francisco",
            city="San Francisco",
            canonical_url="https://example.com",
        )
        ranked = rank_with_llm([job], criteria_text="Prefer AI strategy.", model="test", max_selected=5, client=FakeClient())  # type: ignore[arg-type]
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].rank, 1)
        self.assertEqual(ranked[0].score, 91)

    def test_deterministic_fallback_selects_signal(self) -> None:
        job = JobPosting(
            source_id="fixture",
            source_name="Fixture",
            external_id="1",
            title="AI Venture Strategy Lead",
            company="OpenAI",
            location_text="San Francisco",
            city="San Francisco",
            canonical_url="https://example.com",
            description_text="Frontier artificial intelligence and venture strategy.",
        )
        ranked = rank_deterministically([job], max_selected=5)
        self.assertEqual(len(ranked), 1)
        self.assertTrue(ranked[0].include)

    @patch("opportunity_radar.twilio_whatsapp.send_message_payload")
    def test_twilio_template_payload(self, send_message_payload) -> None:  # type: ignore[no-untyped-def]
        send_message_payload.return_value = {"sid": "SM123"}
        env = {
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "whatsapp:+15550001111",
        }
        with patch.dict(os.environ, env, clear=False):
            result = TwilioWhatsAppSender(content_sid="HX123", messaging_service_sid="MG123").send("whatsapp:+15552223333", "Digest")
        self.assertTrue(result.ok)
        payload = send_message_payload.call_args.args[2]
        self.assertEqual(payload["ContentSid"], "HX123")
        self.assertEqual(payload["MessagingServiceSid"], "MG123")


if __name__ == "__main__":
    unittest.main()
