#!/usr/bin/env python3
"""Tilemap-level oracle for the widescreen margins.

The pixel oracle is confounded by sprites and animated tiles. The BG tilemap is
not: a map entry says which tile the engine placed at a world column, and it
only changes when the engine restages that column. So compare the entry the
margin drew against the entry the same world column has once it is native:

    frame i, logical x = margin + 256 + k   (right margin, world cam_i+256+k)
    frame j, logical x = margin + 256 + k - d  (native, same world)  cam_j = cam_i + d

Equal entry  => the margin showed the world column it claimed to.
Different    => the margin drew a different section of the map (the artifact).

Usage: maporacle.py <case-dir>   (a directory produced by oracle.py)
"""
import json
import pathlib
import struct
import sys


def load_frame(case, tag):
    d = case / "dump"
    vram = (d / (tag + ".vram.bin")).read_bytes()
    wram = (d / (tag + ".wram.bin")).read_bytes()
    regs = json.loads((d / (tag + ".regs.json")).read_text())
    return vram, wram, regs


def words(vram):
    return struct.unpack("<32768H", vram)


def layer_setup(regs, layer):
    sc = regs["bgsc"][layer] if isinstance(regs["bgsc"], list) else regs["bgsc"]
    hs = regs["hscroll"][layer] if isinstance(regs["hscroll"], list) else regs["hscroll"]
    base_words = ((sc & 0xFC) << 8) >> 1
    cols = 64 if (sc & 0x01) else 32
    rows = 32
    return base_words, cols, rows, hs


def entry(w, base, cols, rows, hs, screen_x, row):
    col = ((hs + screen_x) >> 3) % cols
    return w[base + ((row % rows) * cols) + col]


def main():
    case = pathlib.Path(sys.argv[1])
    extra = int(sys.argv[2]) if len(sys.argv) > 2 else 71
    frames = []
    for p in sorted((case / "dump").glob("d*.fbwide.bgrx")):
        tag = p.name.split(".")[0]
        vram, wram, regs = load_frame(case, tag)
        cam = struct.unpack_from("<H", wram, 0xC0)[0]
        frames.append((cam, tag, vram, regs))
    frames.sort()
    best = None
    for i in range(len(frames)):
        for j in range(i + 1, len(frames)):
            d = frames[j][0] - frames[i][0]
            if extra + 8 <= d <= 272 and (best is None or d > best[0]):
                best = (d, i, j)
    if best is None:
        print("no usable camera delta")
        return 2
    d, i, j = best
    cam_i, tag_i, vram_i, regs_i = frames[i]
    cam_j, tag_j, vram_j, regs_j = frames[j]
    print("%s(cam=%d) vs %s(cam=%d) delta=%d" % (tag_i, cam_i, tag_j, cam_j, d))
    wi, wj = words(vram_i), words(vram_j)
    for layer in (0, 1):
        bi, ci, ri, hsi = layer_setup(regs_i, layer)
        bj, cj, rj, hsj = layer_setup(regs_j, layer)
        print("BG%d: base=%04x cols=%d hs_i=%d | base=%04x cols=%d hs_j=%d"
              % (layer + 1, bi, ci, hsi, bj, cj, hsj))
        bad_total = 0
        rows = range(6, 28)
        line = []
        for k in range(0, extra, 8):
            xa = extra + 256 + k
            xb = extra + 256 + k - d
            bad = 0
            for row in rows:
                a = entry(wi, bi, ci, ri, hsi, xa, row)
                b = entry(wj, bj, cj, rj, hsj, xb, row)
                if a != b:
                    bad += 1
            bad_total += bad
            line.append("k=%3d %2d/%2d%s" % (k, bad, len(rows),
                                             "  <-- differs" if bad > 2 else ""))
        for s in line:
            print("   " + s)
        print("   total mismatched entries: %d of %d" % (bad_total, len(rows) * (extra // 8)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
