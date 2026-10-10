#!/usr/bin/env python3
"""Compare two SNESRECOMP_STATE_TRACE files frame by frame.

The desktop host writes one CSV line per simulated frame when
SNESRECOMP_STATE_TRACE is set:

    frame,pbr_pc,a,x,y,sp,dbr,pbr,?,flags

Two runs of the same route on a deterministic build produce byte-identical
files (verified on the Demon's Crest attract route). Comparing a baseline
against a candidate is therefore the strongest cheap equivalence check the
port has: if the guest CPU state matches at every frame boundary, the AOT
promotion or RTL change did not alter behavior on that route.

Usage:
    python3 tools/trace_diff.py baseline.trace candidate.trace [--context N]
                                                          [--max-diffs N]
    python3 tools/trace_diff.py --hash trace.trace

Exit status: 0 when identical, 1 when different, 2 on usage errors.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys


def short_digest(path: pathlib.Path) -> str:
    sha = hashlib.sha256()
    frames = 0
    with path.open("rb") as f:
        for line in f:
            sha.update(line)
            frames += 1
    return f"frames={frames} sha256={sha.hexdigest()[:16]}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", nargs="?", help="first trace")
    parser.add_argument("candidate", nargs="?", help="second trace")
    parser.add_argument("--hash", metavar="TRACE",
                        help="print frame count and digest of one trace")
    parser.add_argument("--max-diffs", type=int, default=10,
                        help="stop after this many differing lines (default 10)")
    parser.add_argument("--context", type=int, default=2,
                        help="lines of context around each difference")
    args = parser.parse_args()

    if args.hash:
        path = pathlib.Path(args.hash)
        if not path.is_file():
            print(f"trace_diff: no such file: {path}", file=sys.stderr)
            return 2
        print(f"{path}: {short_digest(path)}")
        return 0

    if not args.baseline or not args.candidate:
        parser.error("two trace paths are required (or --hash)")

    base_path, cand_path = pathlib.Path(args.baseline), pathlib.Path(args.candidate)
    for path in (base_path, cand_path):
        if not path.is_file():
            print(f"trace_diff: no such file: {path}", file=sys.stderr)
            return 2

    with base_path.open("r", encoding="utf-8", errors="replace") as a, \
         cand_path.open("r", encoding="utf-8", errors="replace") as b:
        a_lines = a.readlines()
        b_lines = b.readlines()

    print(f"baseline  {base_path}: {short_digest(base_path)}")
    print(f"candidate {cand_path}: {short_digest(cand_path)}")

    if a_lines == b_lines:
        print("traces are IDENTICAL")
        return 0

    diffs = 0
    context = max(args.context, 0)
    limit = min(len(a_lines), len(b_lines))
    last_reported = -10 * (context + 1)
    for i in range(limit):
        if a_lines[i] == b_lines[i]:
            continue
        diffs += 1
        if diffs > args.max_diffs:
            break
        if i - last_reported > context + 1:
            print("  ...")
        start = max(0, i - context)
        for j in range(start, i):
            print(f"    base[{j}] {a_lines[j].rstrip()}")
            print(f"    cand[{j}] {b_lines[j].rstrip()}")
        print(f"  difference at line {i + 1}:")
        print(f"    base {a_lines[i].rstrip()}")
        print(f"    cand {b_lines[i].rstrip()}")
        last_reported = i
    if len(a_lines) != len(b_lines):
        print(f"  line counts differ: baseline {len(a_lines)}, "
              f"candidate {len(b_lines)}")
        for j in range(limit, min(len(a_lines), limit + 2)):
            print(f"    base[{j}] {a_lines[j].rstrip()}")
        for j in range(limit, min(len(b_lines), limit + 2)):
            print(f"    cand[{j}] {b_lines[j].rstrip()}")
    print(f"traces DIFFER ({diffs} differing line(s)"
          f"{' shown' if diffs <= args.max_diffs else ', truncated'})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
