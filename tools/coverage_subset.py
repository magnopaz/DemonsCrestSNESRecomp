#!/usr/bin/env python3
"""Write a copy of a Tier-2 coverage checkpoint with a subset of discoveries.

Development aid for bisecting a coverage-driven promotion: takes a session
checkpoint JSON and keeps only `discoveries[a:b]`, preserving every other
field. The emitted program seeds only the kept landing observations, which
makes a multi-build bisection (regen + build + replay) practical.

Usage:
    python3 tools/coverage_subset.py <src.json> <out.json> <start> <end>

Indices are into the `discoveries` array; `end` is exclusive (Python slice).
"""

from __future__ import annotations

import argparse
import json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("src")
    parser.add_argument("out")
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()

    with open(args.src, "r", encoding="utf-8") as f:
        checkpoint = json.load(f)
    discoveries = checkpoint.get("discoveries", [])
    keep = discoveries[args.start:args.end]
    checkpoint["discoveries"] = keep
    # The slice is a development artifact, not a capture: mark the identity
    # so an accidental commit or manifest use is visible.
    checkpoint["capture_id"] = (
        f"{checkpoint.get('capture_id', 'capture')}"
        f"_subset_{args.start}_{args.end}")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f)
    print(f"coverage_subset: kept {len(keep)} of {len(discoveries)} discoveries "
          f"[{args.start}:{args.end}] -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
