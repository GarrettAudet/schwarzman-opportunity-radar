from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opportunity_radar.registry import refresh_registry  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the OpportunityRadar public ATS board registry.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--write", action="store_true", help="Persist discovered boards to state")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing; this is the default")
    parser.add_argument("--discovery-config", default="", help="Optional discovery JSON path")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    args = parser.parse_args()

    result = refresh_registry(
        Path(args.root),
        write=bool(args.write),
        discovery_path=args.discovery_config,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Registry refresh: {result['run_id']}")
        print(f"Raw URLs: {result['raw_url_count']}")
        print(f"Accepted refs: {result['accepted_ref_count']}")
        print(f"Rejected URLs: {result['rejected_url_count']}")
        summary = result.get("registry_summary", {})
        print(f"Boards: {summary.get('boards_before', 0)} -> {summary.get('boards_after', 0)}")
        print(f"Added: {summary.get('boards_added', 0)}")
        print(f"Updated: {summary.get('boards_updated', 0)}")
        print(f"State mutated: {result['state_summary']['mutated']}")
        print(f"Errors: {', '.join(result['errors']) if result['errors'] else 'none'}")
        for ref in result.get("discovered_refs", [])[:10]:
            print(f"- {ref['ats']}:{ref['board_token']} job={ref['job_id']} {ref['url']}")
    return 0 if not result.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
