from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opportunity_radar.discovery import run_discovery  # noqa: E402
from opportunity_radar.pipeline import run_digest  # noqa: E402
from opportunity_radar.registry import refresh_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpportunityRadar from registry detection through weekly WhatsApp digest.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--send", action="store_true", help="Send through Twilio WhatsApp after discovery")
    parser.add_argument("--dry-run", action="store_true", help="Refresh/detect/write state, but preview the digest without sending")
    parser.add_argument("--force", action="store_true", help="Re-evaluate jobs and ignore sent-week suppression")
    parser.add_argument("--respect-schedule", action="store_true", help="Only send inside the configured local send hour")
    parser.add_argument("--skip-registry-refresh", action="store_true", help="Use the existing board registry in state")
    parser.add_argument("--sources", default="", help="Optional configured sources JSON path")
    parser.add_argument("--conditions", default="", help="Optional conditions JSON path")
    parser.add_argument("--discovery-config", default="", help="Optional discovery JSON path")
    parser.add_argument("--deterministic-fallback", action="store_true", help="Use deterministic ranking if OpenRouter is unavailable")
    parser.add_argument("--include-seen", action="store_true", help="Include jobs already sent/seen in state")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    args = parser.parse_args()

    root = Path(args.root)
    registry_result = None
    if not args.skip_registry_refresh:
        registry_result = refresh_registry(
            root,
            write=True,
            discovery_path=args.discovery_config,
            conditions_path=args.conditions,
        )
    discovery_result = run_discovery(
        root,
        write=True,
        force=bool(args.force),
        sources_path=args.sources,
        conditions_path=args.conditions,
        discovery_path=args.discovery_config,
        deterministic_fallback=True if args.deterministic_fallback else None,
    )
    digest_result = run_digest(
        root,
        send=bool(args.send),
        force=bool(args.force),
        respect_schedule=bool(args.respect_schedule),
        deterministic_fallback=True if args.deterministic_fallback else None,
        include_seen=bool(args.include_seen),
        from_state=True,
    )
    payload = {
        "registry_refresh": registry_result,
        "discovery": discovery_result,
        "digest": digest_result.to_dict(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if registry_result:
            print(f"Registry refs: {registry_result['accepted_ref_count']} accepted, boards={registry_result['state_summary']['board_registry']}")
            print(f"Registry errors: {', '.join(registry_result['errors']) if registry_result['errors'] else 'none'}")
        print(f"Discovery included: {discovery_result['included_count']} of {discovery_result['candidate_count']} candidates")
        print(f"Registry boards polled: {discovery_result.get('registry_boards_polled', 0)}/{discovery_result.get('registry_board_count', 0)}")
        print(f"Discovery errors: {', '.join(discovery_result['errors']) if discovery_result['errors'] else 'none'}")
        print()
        print(digest_result.digest_text)
        print()
        print(f"Digest candidates: {digest_result.candidate_count}")
        print(f"Selected: {len(digest_result.selected_jobs)}")
        print(f"Digest errors: {', '.join(digest_result.errors) if digest_result.errors else 'none'}")
        if digest_result.recipient_results:
            ok = sum(1 for item in digest_result.recipient_results if item.ok)
            print(f"Twilio recipients sent: {ok}/{len(digest_result.recipient_results)}")
    failed_send = digest_result.send_requested and digest_result.recipient_results and not all(item.ok for item in digest_result.recipient_results)
    ranker_failed = any(error.startswith("ranker_failed") for error in [*discovery_result.get("errors", []), *digest_result.errors])
    return 1 if failed_send or ranker_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
