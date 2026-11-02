#!/usr/bin/env python3
"""Map-level (tilemap entry) staleness test for the widescreen leading margin.

The pixel oracle mixes in sprites, the parallax layer and the fade, so a "wrong"
pixel is not proof of a stale BG map. This one compares only BG1 tilemap
entries: the entry displayed for world `w` must be the same no matter whether it
is currently drawn in the margin or, in a later frame, in the native view.

Reads the per-frame dumps probe.py writes (`*.vram.bin`, `*.wram.bin`,
`*.regs.json`), so it needs no new run — point it at an existing probe case.

Usage: mapstale.py <case-dir> [--layer 0] [--margin 71] [--extra-print]
"""
import argparse
import json
import pathlib
import struct
import sys


def cam_of(wram: bytes) -> int:
    return struct.unpack_from("<H", wram, 0xC0)[0]


def vscroll_of(regs: dict) -> int:
    return regs["vscroll"][0]


def base_bytes(regs: dict, layer: int) -> int:
    sc = regs["bgsc"][layer]
    cols = 64 if (sc & 1) else 32
    return ((sc & 0xfc) << 9) & 0xFFFF, cols


def entry(vram: bytes, base: int, cols: int, col: int, row: int) -> int:
    col %= cols
    block = 0x800 if (cols == 64 and col >= 32) else 0
    word = (col & 31) + 32 * (row & 31)
    off = (base + block + 2 * word) & 0xFFFF
    return vram[off] | (vram[(off + 1) & 0xFFFF] << 8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("case")
    ap.add_argument("--layer", type=int, default=0)
    ap.add_argument("--margin", type=int, default=71)
    ap.add_argument("--rows", default="7,27",
                    help="tile rows to sample, inclusive (default skips HUD)")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    case = pathlib.Path(a.case)
    dump = case / "dump"
    r0, r1 = (int(t) for t in a.rows.split(","))

    frames = []
    for p in sorted(dump.glob("d*.wram.bin")):
        tag = p.name[:-len(".wram.bin")]
        v = dump / (tag + ".vram.bin")
        g = dump / (tag + ".regs.json")
        if not (v.is_file() and g.is_file()):
            continue
        regs = json.loads(g.read_text())
        cam = cam_of(p.read_bytes())
        vs = vscroll_of(regs)
        base, cols = base_bytes(regs, a.layer)
        frames.append({"tag": tag, "cam": cam, "vs": vs, "base": base,
                       "cols": cols, "vram": v.read_bytes()})
    if not frames:
        print("no usable dumps in", dump)
        return 1
    print("frames=%d cam %d..%d  base=0x%04x cols=%d" %
          (len(frames), frames[0]["cam"], frames[-1]["cam"],
           frames[0]["base"], frames[0]["cols"]))

    # world -> entry, keyed by the margin sample; compared against the same
    # world seen natively in a later frame (cam_j = cam_i + d, 0 < d <= 256).
    per_k = {}
    pairs = 0
    for i, fi in enumerate(frames):
        for j in range(i + 1, len(frames)):
            fj = frames[j]
            d = fj["cam"] - fi["cam"]
            if d <= a.margin + 8 or d > 256:
                continue
            if fj["base"] != fi["base"] or fj["cols"] != fi["cols"]:
                continue
            pairs += 1
            for k in range(a.margin):
                world = fi["cam"] + 256 + k
                col_i, row_i = world >> 3, (fi["vs"] + 112) >> 3
                e_i = entry(fi["vram"], fi["base"], fi["cols"], col_i, row_i)
                native_x = world - fj["cam"]
                if not (0 <= native_x < 256):
                    continue
                col_j, row_j = (fj["cam"] + native_x) >> 3, (fj["vs"] + 112) >> 3
                e_j = entry(fj["vram"], fj["base"], fj["cols"], col_j, row_j)
                per_k.setdefault(k, []).append((fi["cam"], e_i == e_j))
    if not pairs:
        print("no frame pair with 0 < d <= 256")
        return 2
    print("pairs:", pairs)
    print("k    equal/total   by first-frame camera")
    for k in sorted(per_k):
        v = per_k[k]
        ok = sum(1 for _, e in v if e)
        bycam = {}
        for c, e in v:
            bycam.setdefault(c, []).append(e)
        camps = sorted(bycam)
        line = " ".join("%d:%d%%" % (c, round(100 * sum(bycam[c]) / len(bycam[c])))
                        for c in camps[:10])
        print("k=%2d  %3d/%-3d %5.1f%%   %s" % (k, ok, len(v), 100 * ok / len(v), line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
