#!/usr/bin/env python3
"""Column content invariance: does every write of a map column agree?

A BG map column covers a fixed 8-px world slice (`column c = world (c*8) mod 512`
for the 64-column ring), so inside one room every write to that column has to
carry the same 32-row content. A second variant means something wrote that
column from the wrong source phase — which is exactly how a widescreen
streaming "fix" corrupts a margin while looking like it wrote more.

Reads a `coltrace.py` capture (`vram_trace.jsonl`) and reports, per column, how
many distinct 32-row contents were written and which frames wrote the minority
ones. With two captures it also answers "did capture B write the same content
for that column as capture A", which is the check that proves the extra columns
a catch-up writes early are byte-identical to what the engine writes later.

usage:
    colcontent.py <case-a> [<case-b>] [--base 0x9000]
"""
import argparse
import collections
import json
import pathlib
import sys

ROWS = 32


def load(path, base):
    """frame -> {column: [(row, byte0, byte1)]} for the 64x32 map."""
    per_frame = collections.defaultdict(lambda: collections.defaultdict(dict))
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        off = int(rec["adr_byte"], 16) - base
        if off < 0 or off >= 0x1000:
            continue
        block, within = divmod(off, 0x800)
        col = block * 32 + (within % 64) // 2
        row = within // 64
        half = off & 1
        slot = per_frame[rec["f"]][col].setdefault(row, [None, None])
        slot[half] = rec["val"]
    return per_frame


def content_map(per_frame):
    """column -> {content-tuple: [frames that wrote it]}"""
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for f, cols in per_frame.items():
        for col, rows in cols.items():
            if len(rows) < ROWS:              # partial write, skip
                continue
            key = tuple(tuple(rows[r]) for r in range(ROWS))
            out[col][key].append(f)
    return out


def describe(cm, label):
    print("== %s: %d columns written" % (label, len(cm)))
    bad = 0
    for col in sorted(cm):
        variants = cm[col]
        if len(variants) == 1:
            continue
        bad += 1
        order = sorted(variants.items(), key=lambda kv: -len(kv[1]))
        print("   column %2d: %d variants -- %s" %
              (col, len(variants),
               ", ".join("%d frame(s) %s" % (len(fr), fr[:3]) for _, fr in order)))
    if not bad:
        print("   every column has exactly one content (no stale/foreign write)")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="+")
    ap.add_argument("--base", default="0x9000")
    a = ap.parse_args()
    base = int(a.base, 16)
    maps = []
    for c in a.cases:
        case = pathlib.Path(c).expanduser()
        trace = case / "vram_trace.jsonl"
        if not trace.exists():
            sys.exit("%s: missing vram_trace.jsonl" % trace)
        cm = content_map(load(trace, base))
        describe(cm, case.name)
        maps.append((case.name, cm))

    if len(maps) == 2:
        (na, a_cm), (nb, b_cm) = maps
        print("\n== cross-capture, per column: %s vs %s" % (na, nb))
        agree = disagree = only = 0
        for col in sorted(set(a_cm) | set(b_cm)):
            ka = set(a_cm.get(col, {}))
            kb = set(b_cm.get(col, {}))
            if not ka or not kb:
                only += 1
                continue
            if ka == kb:
                agree += 1
            else:
                disagree += 1
                print("   column %2d differs (%d vs %d variants)" %
                      (col, len(ka), len(kb)))
        print("   identical: %d, differing: %d, written by one side only: %d" %
              (agree, disagree, only))


if __name__ == "__main__":
    main()
