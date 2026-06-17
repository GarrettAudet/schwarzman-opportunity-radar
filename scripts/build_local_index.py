from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from schwarzman_qa.retrieval import build_index, save_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local reviewed-corpus retrieval index.")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--chunks", default="", help="Optional corpus chunks JSONL")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    chunks_path = Path(args.chunks).resolve() if args.chunks else None
    index = build_index(root, chunks_path=chunks_path)
    out_path = save_index(root, index)
    print(f"Indexed {index['chunk_count']} reviewed chunks.")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
