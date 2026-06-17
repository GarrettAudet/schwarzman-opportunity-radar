from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schwarzman_qa.access_control import access_control_from_env  # noqa: E402
from schwarzman_qa.config import load_env  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage WhatsApp Q&A bot access.")
    parser.add_argument("action", choices=["list", "approve", "block", "revoke", "check"])
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--wa-id", default="", help="WhatsApp wa_id/from value")
    parser.add_argument("--phone", default="", help="Phone number, if different from wa_id")
    parser.add_argument("--name", default="", help="Profile/display name")
    parser.add_argument("--notes", default="")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    load_env(root)
    access = access_control_from_env(root)

    if args.action == "list":
        users = access.users()
        if args.json:
            print(json.dumps(users, ensure_ascii=False, indent=2))
            return 0
        if not users:
            print("No stored WhatsApp users.")
            return 0
        for user in users:
            print(
                f"{user.get('status', ''):8} "
                f"wa_id={user.get('wa_id', '')} "
                f"phone={user.get('phone_number', '')} "
                f"name={user.get('profile_name', '')} "
                f"source={user.get('source', '')}"
            )
        return 0

    if not args.wa_id and not args.phone:
        parser.error("--wa-id or --phone is required for this action")

    wa_id = args.wa_id or args.phone
    phone = args.phone or wa_id
    if args.action == "approve":
        access.approve(wa_id, phone, profile_name=args.name, notes=args.notes)
    elif args.action == "block":
        access.block(wa_id, phone, profile_name=args.name, notes=args.notes)
    elif args.action == "revoke":
        access.revoke(wa_id, phone, notes=args.notes)
    elif args.action == "check":
        decision = access.check(wa_id, phone)
        print(json.dumps(decision.__dict__, ensure_ascii=False, indent=2) if args.json else decision)
        return 0 if decision.allowed else 1

    decision = access.check(wa_id, phone)
    if args.json:
        print(json.dumps(decision.__dict__, ensure_ascii=False, indent=2))
    else:
        print(f"{decision.status}: {decision.reason} wa_id={decision.wa_id} phone={decision.phone_number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
