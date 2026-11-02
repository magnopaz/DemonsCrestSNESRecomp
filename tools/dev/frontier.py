#!/usr/bin/env python3
"""Streaming frontier, measured from a coltrace capture.

`coltrace.py --cam` writes two files per case:

  vram_trace.jsonl  {"f": frame, "adr_byte": "0x9000", "val": "0x00"}
  cam.jsonl         {"f": frame, "hex": "<32 bytes of WRAM from $00C0>"}

The BG map ring is 64 columns of 8 px (512 px = two 256-px pages). A column
covers world `page*256 + col*8`, so the column a write lands in, measured
against the camera column `cam>>3`, says how far ahead of the camera the engine
keeps the ring filled. That distance is the streaming lookahead — the number
that decides whether a widescreen leading margin shows the current world or the
previous ring revolution (see docs/HANDOFF-widescreen-staging.md §10).

`$00:C840` (room restream) fills 42 columns from 4 columns behind the cursor,
which puts the frontier at camera+304 (the last written pair starts at
camera+288) and leaves only 48 px of headroom past the authentic 256-px view.
The per-frame tracker `$00:CF7D` then advances 2 columns per 16 px of scroll,
so the phase measured here is the phase the whole room keeps.

usage:
    frontier.py <case-dir> [--base 0x9000] [--cols 64] [--min-cols 2]
    frontier.py ~/.hermes/cache/scratch/dcwork/dr_fix/case
"""
import argparse
import collections
import json
import pathlib
import sys


def load_cam(path):
    """frame -> camera word from $00C0.

    `read_ram c0 32` answers a space-separated hex string, so the bytes have to
    be split, not sliced: `hex[2:4]` lands on a space and silently reads 0.
    """
    cams = {}
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        parts = (rec.get("hex") or "").replace(" ", " ").split()
        if len(parts) < 2:
            continue
        cams[rec["f"]] = int(parts[0], 16) | (int(parts[1], 16) << 8)
    return cams


def column_of(off):
    """Map offset (bytes) -> column index in a 64x32 map.

    The ring is 64 columns but the PPU screen layout is two 32-column blocks
    (bytes 0x000..0x7ff and 0x800..0xfff), each 32 columns x 32 rows with a
    64-byte row stride. `off // 8` is NOT a column: it walks rows as if they
    were columns and reports strides of 8 "columns".
    """
    block, within = divmod(off, 0x800)
    return block * 32 + (within % 64) // 2


def load_writes(path, base, cols):
    """frame -> sorted set of map-relative columns written that frame."""
    writes = collections.defaultdict(set)
    span = cols * 32 * 2         # 64 columns x 32 rows x 2 bytes = 4096 bytes
    for line in pathlib.Path(path).read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        off = int(rec["adr_byte"], 16) - base
        if off < 0 or off >= span:
            continue
        writes[rec["f"]].add(column_of(off))
    return writes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case", help="directory holding vram_trace.jsonl + cam.jsonl")
    ap.add_argument("--base", default="0x9000", help="BG map byte base (default 0x9000)")
    ap.add_argument("--cols", type=int, default=64, help="ring width in columns (default 64)")
    ap.add_argument("--min-cols", type=int, default=2,
                    help="ignore frames that wrote fewer columns (default 2)")
    ap.add_argument("--tail", type=int, default=40, help="rows to print (default 40)")
    a = ap.parse_args()

    case = pathlib.Path(a.case).expanduser()
    base = int(a.base, 16) if isinstance(a.base, str) else a.base
    trace, campath = case / "vram_trace.jsonl", case / "cam.jsonl"
    for p in (trace, campath):
        if not p.exists():
            sys.exit("%s: missing (run coltrace.py --cam)" % p)

    cams = load_cam(campath)
    writes = load_writes(trace, base, a.cols)
    if not writes:
        sys.exit("no writes inside the map window 0x%04x..0x%04x" % (base, base + a.cols * 8))

    # Camera at a write frame: the nearest sample at or before that frame.
    cam_frames = sorted(cams)
    rows = []
    for f in sorted(writes):
        cols = sorted(writes[f])
        if len(cols) < a.min_cols or not cam_frames:
            continue
        near = min(cam_frames, key=lambda cf: (abs(cf - f), cf))
        if abs(near - f) > 6:
            continue
        cam = cams[near]
        cam_col = cam >> 3
        # Leading pair = the two columns furthest ahead of the camera column.
        ahead = [c for c in cols if c >= cam_col]
        if not ahead:
            continue
        lead = min(ahead, key=lambda c: ((c - cam_col) % a.cols, c))
        run = [lead]
        nxt = lead + 1
        while nxt in cols and len(run) < 4:
            run.append(nxt)
            nxt += 1
        delta = (lead - cam_col) % a.cols
        rows.append((f, cam, cam_col, run, delta))

    if not rows:
        sys.exit("no frame had camera data and at least %d columns written" % a.min_cols)

    print("%-10s %6s %6s  %-14s %6s %6s" %
          ("frame", "cam", "camcol", "cols written", "dcol", "dpx"))
    for f, cam, cam_col, run, delta in rows[-a.tail:]:
        print("%-10d %6d %6d  %-14s %6d %6d" %
              (f, cam, cam_col, ",".join(map(str, run)), delta, delta * 8))

    deltas = collections.Counter(r[4] for r in rows)
    print("\nframes measured: %d" % len(rows))
    print("leading-pair distance from the camera column (col -> frames):")
    for d, n in sorted(deltas.items()):
        print("  +%-3d (%4d px)  %4d frame(s)" % (d, d * 8, n))
    top = max(deltas)
    print("\nfrontier: camera + %d px (last written pair starts there)" % (top * 8))
    print("headroom past the authentic 256-px view: %d px" % (top * 8 - 256))


if __name__ == "__main__":
    main()
