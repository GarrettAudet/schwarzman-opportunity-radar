from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opportunity_radar.send_preflight import check_send_ready  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether OpportunityRadar is configured for Twilio WhatsApp sending.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    args = parser.parse_args()

    result = check_send_ready(Path(args.root))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Send ready: {'yes' if result['ok'] else 'no'}")
        print(f"Provider: {result['provider']}")
        print(f"Recipients: {result['recipient_count']}")
        print(f"Template: {'yes' if result['uses_template'] else 'no'}")
        print(f"Messaging service: {'yes' if result['uses_messaging_service'] else 'no'}")
        print(f"Requires TWILIO_WHATSAPP_FROM: {'yes' if result['requires_from'] else 'no'}")
        print(f"Errors: {', '.join(result['errors']) if result['errors'] else 'none'}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
