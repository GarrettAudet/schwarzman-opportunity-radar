from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from opportunity_radar.discovery import run_discovery  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpportunityRadar daily job discovery.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--write", action="store_true", help="Persist evaluated jobs to state")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing; this is the default")
    parser.add_argument("--force", action="store_true", help="Re-evaluate unchanged jobs")
    parser.add_argument("--sources", default="", help="Optional sources JSON path")
    parser.add_argument("--conditions", default="", help="Optional conditions JSON path")
    parser.add_argument("--discovery-config", default="", help="Optional discovery JSON path")
    parser.add_argument("--deterministic-fallback", action="store_true", help="Use deterministic ranking if OpenRouter is unavailable")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    args = parser.parse_args()

    result = run_discovery(
        Path(args.root),
        write=bool(args.write),
        force=bool(args.force),
        sources_path=args.sources,
        conditions_path=args.conditions,
        discovery_path=args.discovery_config,
        deterministic_fallback=True if args.deterministic_fallback else None,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Discovery run: {result['run_id']}")
        print(f"Registry boards: {result.get('registry_boards_polled', 0)}/{result.get('registry_board_count', 0)} polled")
        print(f"City candidates: {result['city_candidate_count']} total, {result.get('recent_city_candidate_count', 0)} recent")
        print(f"Recent condition matches: {result['condition_candidate_count']}")
        print(f"Ranked candidates: {result['candidate_count']}")
        print(f"Included: {result['included_count']}")
        if result.get("role_group_counts"):
            groups = ", ".join(f"{key}={value}" for key, value in result["role_group_counts"].items())
            print(f"Role groups: {groups}")
        print(f"Evaluated updates: {result['state_summary']['evaluated_updates']}")
        print(f"State mutated: {result['state_summary']['mutated']}")
        print(f"Errors: {', '.join(result['errors']) if result['errors'] else 'none'}")
        for item in result["included_jobs"][:10]:
            job = item["job"]
            groups = item.get("condition_matches", {}).get("role_group_ids", [])
            group_text = f" [{', '.join(groups)}]" if groups else ""
            print(f"- {job['company']} - {job['title']} ({job['city']}) score={int(round(item['score']))}{group_text}")
    if any(error.startswith("ranker_failed") for error in result["errors"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())