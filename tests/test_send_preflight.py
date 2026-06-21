from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opportunity_radar.send_preflight import check_send_ready


class SendPreflightTests(unittest.TestCase):
    def test_reports_missing_send_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=True):
                result = check_send_ready(Path(tmp))
        self.assertFalse(result["ok"])
        self.assertEqual(result["recipient_count"], 0)
        self.assertTrue(result["requires_from"])
        self.assertEqual(
            result["errors"],
            [
                "no_recipients_configured",
                "TWILIO_ACCOUNT_SID is not set",
                "TWILIO_AUTH_TOKEN is not set",
                "TWILIO_WHATSAPP_FROM is not set",
            ],
        )

    def test_template_messaging_service_is_ready_without_from(self) -> None:
        env = {
            "OPPORTUNITY_RECIPIENTS": "whatsapp:+15550001111",
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_CONTENT_SID": "HX123",
            "TWILIO_MESSAGING_SERVICE_SID": "MG123",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, env, clear=True):
                result = check_send_ready(Path(tmp))
        self.assertTrue(result["ok"])
        self.assertTrue(result["uses_template"])
        self.assertTrue(result["uses_messaging_service"])
        self.assertFalse(result["requires_from"])
        self.assertEqual(result["errors"], [])

    def test_direct_whatsapp_send_requires_from(self) -> None:
        env = {
            "OPPORTUNITY_RECIPIENTS": "whatsapp:+15550001111",
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, env, clear=True):
                result = check_send_ready(Path(tmp))
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"], ["TWILIO_WHATSAPP_FROM is not set"])

    def test_microsoft_graph_email_provider_is_ready(self) -> None:
        env = {
            "OPPORTUNITY_SEND_PROVIDER": "microsoft_graph_email",
            "OPPORTUNITY_RECIPIENTS": "jobs@example.com",
            "OPPORTUNITY_EMAIL_SUBJECT": "OpportunityRadar test",
            "MICROSOFT_CLIENT_ID": "client-id",
            "MICROSOFT_REFRESH_TOKEN": "refresh-token",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, env, clear=True):
                result = check_send_ready(Path(tmp))
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "microsoft_graph_email")
        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(result["subject"], "OpportunityRadar test")
        self.assertFalse(result["requires_from"])
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
