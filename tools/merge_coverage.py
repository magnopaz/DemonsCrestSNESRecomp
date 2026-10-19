#!/usr/bin/env python3
"""Merge Tier-2 coverage checkpoints into one slim seed manifest.

The committed recomp/tier2_coverage.json is the seed baseline for
tools/regen.sh: a small checkpoint whose `discoveries` seed optional AOT
roots from proven interpreter call landings. This tool folds one or more
captures (attract, gameplay routes, ...) into a single checkpoint the
emitter accepts as `--profile-manifest`.

Rules, per snesrecomp/docs/COVERAGE_FEEDBACK.md:

  * rows are unioned by transfer identity and their counters summed;
  * only `discoveries` survive: `costs` and `ram_routines` are evidence for
    the exact build that produced them and are never carried across builds;
  * the merged file carries the LAST input's `identity`, so it is a valid
    profile for the current build. Every candidate is re-validated by the
    analyzer on its own; identity here is a guardrail, not a promotion.

Usage:
    python3 tools/merge_coverage.py <out.json> <capture.json> [capture.json ...]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

COUNTERS = ("observed_hits", "completed_hits", "yielded_hits", "pending_hits",
            "bail_hits")


def records(path: pathlib.Path):
    """Yield checkpoint records, unpacking bundle files."""
    data = json.loads(path.read_text(encoding="utf-8"))

    def unpack(record, depth=0):
        if depth > 8:
            raise SystemExit(f"{path}: coverage bundle nesting too deep")
        if isinstance(record, dict) and \
                record.get("schema") == "snesrecomp tier2 bundle v2":
            for child in record.get("records", []):
                yield from unpack(child, depth + 1)
        else:
            yield record

    yield from unpack(data)


def row_key(row: dict) -> tuple:
    return (row.get("processor", "snes_cpu"),
            row.get("record_kind", "transfer"),
            row.get("site_pc24"), row.get("target_pc24"),
            row.get("entry_mx", "unknown"), row.get("emulation"),
            row.get("site_kind", "unknown"),
            row.get("fallback_reason", "unknown"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", help="merged checkpoint to write")
    parser.add_argument("captures", nargs="+", help="checkpoint JSON files")
    args = parser.parse_args()

    merged: dict[tuple, dict] = {}
    identity = None
    rom_title = "demonscrest"
    roms, modules, mappers = set(), set(), set()
    max_sequence = 0

    for name in args.captures:
        path = pathlib.Path(name)
        for record in records(path):
            ident = record.get("identity", {})
            if not ident.get("rom_sha256"):
                raise SystemExit(f"{path}: capture lacks ROM identity")
            roms.add(ident["rom_sha256"])
            modules.add(ident.get("module_id"))
            mappers.add(ident.get("mapper"))
            rom_title = record.get("rom_title", rom_title)
            max_sequence = max(max_sequence, int(record.get("sequence", 0)))
            for row in record.get("discoveries", []):
                if row.get("record_kind", "transfer") != "transfer":
                    continue
                key = row_key(row)
                if key not in merged:
                    merged[key] = dict(row)
                    for counter in COUNTERS:
                        merged[key][counter] = int(row.get(counter, 0))
                else:
                    out = merged[key]
                    for counter in COUNTERS:
                        out[counter] += int(row.get(counter, 0))
                    out["first_frame"] = min(out.get("first_frame", 0),
                                             row.get("first_frame", 0))
                    out["last_frame"] = max(out.get("last_frame", 0),
                                            row.get("last_frame", 0))
        # The last capture on the command line is the newest build.
        for record in records(path):
            identity = record.get("identity", identity)
            break

    if len(roms) != 1 or len(modules) != 1 or len(mappers) != 1:
        raise SystemExit("refusing to merge captures from different "
                         "ROMs/modules/mappers")
    rows = [merged[k] for k in sorted(merged, key=lambda k: str(k))]
    out = {
        "schema": "snesrecomp tier2 coverage v2",
        "capture_id": f"{rom_title}_merged_{len(args.captures)}routes",
        "rom_title": rom_title,
        "sequence": max_sequence,
        "identity": identity,
        "total_tier_hits": 0,
        "distinct_sites": len(rows),
        "overflowed_tuples": 0,
        "journal_write_failures": 0,
        "discoveries": rows,
        "ram_routines_overflow": 0,
        "ram_routines": [],
        "dropped_cost_samples": 0,
        "checkpoint_complete": True,
    }
    # Compact single-line JSON, matching the committed baseline's style.
    pathlib.Path(args.out).write_text(json.dumps(out) + "\n", encoding="utf-8")
    print(f"merge_coverage: {len(rows)} rows from {len(args.captures)} "
          f"capture(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
