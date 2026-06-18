from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schwarzman_qa.access_control import access_control_from_env  # noqa: E402
from schwarzman_qa.config import load_env  # noqa: E402


def print_user(user: dict[str, object]) -> None:
    print(
        f"{str(user.get('status', '')):8} "
        f"wa_id={user.get('wa_id', '')} "
        f"phone={user.get('phone_number', '')} "
        f"name={user.get('profile_name', '')} "
        f"feedback={user.get('feedback_count', 0)} "
        f"failed={user.get('failed_question_count', 0)} "
        f"source={user.get('source', '')}"
    )


def print_event(event: dict[str, object]) -> None:
    metadata = event.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    detail = ""
    if metadata:
        response_type = metadata.get("response_type", "")
        top_source = metadata.get("top_source", "")
        if response_type or top_source:
            detail = f" response_type={response_type} top_source={top_source}"
    print(
        f"{event.get('created_at', '')} "
        f"{event.get('kind', '')} "
        f"wa_id={event.get('wa_id', '')} "
        f"phone={event.get('phone_number', '')} "
        f"name={event.get('profile_name', '')}{detail}\n"
        f"  {event.get('text', '')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage WhatsApp Q&A bot access.")
    parser.add_argument(
        "action",
        choices=["list", "summary", "blocked", "feedback", "failures", "approve", "block", "revoke", "remove", "check"],
    )
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--wa-id", default="", help="WhatsApp wa_id/from value")
    parser.add_argument("--phone", default="", help="Phone number, if different from wa_id")
    parser.add_argument("--name", default="", help="Profile/display name")
    parser.add_argument("--notes", default="")
    parser.add_argument("--status", default="", choices=["", "approved", "pending", "blocked"], help="Filter list output")
    parser.add_argument("--limit", type=int, default=25, help="Maximum events to print")
    parser.add_argument("--json", action="store_true", help="Print JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    load_env(root)
    access = access_control_from_env(root)

    if args.action == "list":
        users = access.users(status=args.status)
        if args.json:
            print(json.dumps(users, ensure_ascii=False, indent=2))
            return 0
        if not users:
            print("No stored WhatsApp users.")
            return 0
        for user in users:
            print_user(user)
        return 0

    if args.action == "summary":
        summary = access.summary()
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0
        print(
            f"unique_users={summary['unique_users']} "
            f"approved={summary['approved']} "
            f"pending={summary['pending']} "
            f"blocked={summary['blocked']} "
            f"feedback={summary['feedback_count']} "
            f"failed_questions={summary['failed_question_count']}"
        )
        for user in summary["users"]:
            print_user(user)
        return 0

    if args.action == "blocked":
        users = access.users(status="blocked")
        if args.json:
            print(json.dumps(users, ensure_ascii=False, indent=2))
            return 0
        if not users:
            print("No blocked WhatsApp users.")
            return 0
        for user in users:
            print_user(user)
        return 0

    if args.action in {"feedback", "failures"}:
        kind = "feedback" if args.action == "feedback" else "failed_question"
        events = access.events(kind=kind, limit=args.limit)
        if args.json:
            print(json.dumps(events, ensure_ascii=False, indent=2))
            return 0
        if not events:
            print(f"No {kind.replace('_', ' ')} events.")
            return 0
        for event in events:
            print_event(event)
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
    elif args.action == "remove":
        access.remove(wa_id, phone)
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
