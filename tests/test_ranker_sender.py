from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from opportunity_radar.microsoft_graph import email_payload, microsoft_graph_send_config_errors
from opportunity_radar.models import JobPosting
from opportunity_radar.ranker import rank_deterministically, rank_with_llm
from opportunity_radar.sender import MicrosoftGraphEmailSender, TwilioWhatsAppSender
from opportunity_radar.twilio_whatsapp import twilio_send_config_errors


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

    @patch("opportunity_radar.twilio_whatsapp.send_message_payload")
    def test_twilio_template_with_messaging_service_does_not_require_from(self, send_message_payload) -> None:  # type: ignore[no-untyped-def]
        send_message_payload.return_value = {"sid": "SM456"}
        env = {"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "token"}
        with patch.dict(os.environ, env, clear=True):
            result = TwilioWhatsAppSender(content_sid="HX123", messaging_service_sid="MG123").send("+15552223333", "Digest")
        self.assertTrue(result.ok)
        payload = send_message_payload.call_args.args[2]
        self.assertEqual(payload["To"], "whatsapp:+15552223333")
        self.assertEqual(payload["MessagingServiceSid"], "MG123")
        self.assertNotIn("From", payload)

    @patch("opportunity_radar.twilio_whatsapp.send_message_payload")
    def test_twilio_template_payload_splits_long_digest(self, send_message_payload) -> None:  # type: ignore[no-untyped-def]
        send_message_payload.side_effect = [{"sid": "SM1"}, {"sid": "SM2"}]
        env = {"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "token"}
        long_digest = "A" * 1700
        with patch.dict(os.environ, env, clear=True):
            result = TwilioWhatsAppSender(content_sid="HX123", messaging_service_sid="MG123").send("+15552223333", long_digest)
        self.assertTrue(result.ok)
        self.assertEqual(result.message_ids, ["SM1", "SM2"])
        self.assertEqual(send_message_payload.call_count, 2)
        first_payload = send_message_payload.call_args_list[0].args[2]
        second_payload = send_message_payload.call_args_list[1].args[2]
        self.assertLessEqual(len(json.loads(first_payload["ContentVariables"])["1"]), 1500)
        self.assertLessEqual(len(json.loads(second_payload["ContentVariables"])["1"]), 1500)

    def test_twilio_preflight_reports_missing_send_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            errors = twilio_send_config_errors(recipients=["whatsapp:+15552223333"])
        self.assertEqual(errors, ["TWILIO_ACCOUNT_SID is not set", "TWILIO_AUTH_TOKEN is not set", "TWILIO_WHATSAPP_FROM is not set"])

    def test_twilio_preflight_allows_messaging_service_without_from(self) -> None:
        env = {"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "token"}
        with patch.dict(os.environ, env, clear=True):
            errors = twilio_send_config_errors(recipients=["whatsapp:+15552223333"], content_sid="HX123", messaging_service_sid="MG123")
        self.assertEqual(errors, [])

    def test_microsoft_graph_preflight_reports_missing_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            errors = microsoft_graph_send_config_errors(recipients=["jobs@example.com"])
        self.assertEqual(errors, ["MICROSOFT_CLIENT_ID is not set", "MICROSOFT_REFRESH_TOKEN is not set"])

    def test_microsoft_graph_email_payload(self) -> None:
        payload = email_payload(recipient="mailto:jobs@example.com", subject="Weekly", body="Digest", save_to_sent_items=False)
        self.assertEqual(payload["message"]["subject"], "Weekly")
        self.assertEqual(payload["message"]["toRecipients"][0]["emailAddress"]["address"], "jobs@example.com")
        self.assertEqual(payload["message"]["body"]["content"], "Digest")
        self.assertFalse(payload["saveToSentItems"])

    @patch("opportunity_radar.sender.send_email")
    def test_microsoft_graph_sender(self, send_email) -> None:  # type: ignore[no-untyped-def]
        send_email.return_value = {"id": "graph:202"}
        result = MicrosoftGraphEmailSender(subject="Weekly").send("jobs@example.com", "Digest")
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "microsoft_graph_email")
        self.assertEqual(result.message_ids, ["graph:202"])
        send_email.assert_called_once_with("jobs@example.com", "Digest", subject="Weekly")


if __name__ == "__main__":
    unittest.main()
