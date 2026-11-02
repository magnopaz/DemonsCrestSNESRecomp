#!/usr/bin/env python3
"""Oracle test for the widescreen right margin.

The authentic 256-px view is the engine's ground truth: whatever a world region
looks like once it scrolls into the native view is what it *should* have looked
like in the margin. This walks right, dumps every frame with the camera, and
then compares

    frame_i [margin+256+k]        (world w = cam_i+256+k, in the right margin)
    frame_j [margin+k]            (same world w, now native)   where cam_j = cam_i+256

so a mismatch is proven bad margin content, not a policy artifact.

Usage: oracle.py <fixture.sav> [--extra N] [--frames N] [--env K=V ...]
"""
import argparse
import json
import pathlib
import struct
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PROBE = HERE / "probe.py"


def make_script(frames, save, chunk):
    lines = ["loadstate 0", "wait 20"]
    for i in range(frames):
        lines.append("press right %d" % chunk)
        lines.append("dump d%03d" % i)
    lines.append("quit")
    return "\n".join(lines) + "\n"


def camera(wram: bytes) -> int:
    """Game camera X ($C0, 16-bit LE) -- the mirror dc_widescreen.c reads."""
    return struct.unpack_from("<H", wram, 0xC0)[0]


def run(save, extra, frames, envs, case, chunk):
    script = case.with_suffix(".txt")
    script.write_text(make_script(frames, save, chunk))
    cmd = [sys.executable, str(PROBE), "run", "--name", str(case), "--ws", "1",
           "--extra", str(extra), "--save", save, "--script", str(script)]
    for e in envs:
        cmd += ["--env", e]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("save")
    ap.add_argument("--extra", type=int, default=71)
    ap.add_argument("--frames", type=int, default=160)
    ap.add_argument("--env", action="append", default=[])
    ap.add_argument("--chunk", type=int, default=8)
    ap.add_argument("--case", default="oracle")
    a = ap.parse_args()

    case = pathlib.Path(a.case)
    rc, out, err = run(a.save, a.extra, a.frames, a.env, case, a.chunk)
    dump = case / "dump"
    frames = []
    for p in sorted(dump.glob("d*.fbwide.bgrx")):
        w = p.with_suffix(".wram.bin")
        if not w.is_file():
            w = pathlib.Path(str(p).replace(".fbwide.bgrx", ".wram.bin"))
        if not w.is_file():
            continue
        frames.append((camera(w.read_bytes()), p))
    if not frames:
        print("no frames", rc, err[-500:])
        return 1
    print("frames=%d cam %d -> %d" % (len(frames), frames[0][0], frames[-1][0]))

    W = 256 + 2 * a.extra
    best = None
    for i in range(len(frames)):
        for j in range(i + 1, len(frames)):
            d = frames[j][0] - frames[i][0]
            # The margin column k (world cam_i+256+k) is native in frame j
            # whenever 0 <= 256+k-d < 256, i.e. k < d <= 256+k. Any d above
            # k works, so a room that clamps its camera at 150 px is usable.
            if d < a.extra + 8 or d > 272:
                continue
            score = -d  # prefer the largest usable delta
            if best is None or score < best[0]:
                best = (score, i, j, d)
    if best is None:
        print("no frame pair with a ~256 px camera delta")
        return 2
    score, i, j, d = best
    cam_i, fi = frames[i]
    cam_j, fj = frames[j]
    A = fi.read_bytes()
    B = fj.read_bytes()
    print("pair d%03d(cam=%d) -> d%03d(cam=%d) delta=%d" % (i, cam_i, j, cam_j, d))

    def px(buf, x, y):
        o = (y * W + x) * 4
        return buf[o:o + 3]

    # world w = cam_i + 256 + k  ->  A[margin+256+k]  vs  B[margin+256+k-d]
    rows = range(48, 224)  # skip the HUD band
    bad = []
    for k in range(a.extra):
        xa = a.extra + 256 + k
        xb = a.extra + k - (d - 256)
        if not (0 <= xb < W):
            continue
        diff = sum(1 for y in rows if px(A, xa, y) != px(B, xb, y))
        bad.append((k, diff))
    total = len(rows)
    print("k = pixels into the right margin; diff = rows whose colour changed "
          "once that column became native (of %d)" % total)
    for k, diff in bad:
        bar = "#" * int(60 * diff / total)
        print("  k=%3d  %4d  %s" % (k, diff, bar))
    good = [k for k, diff in bad if diff <= total // 10]
    print("clean prefix: %d/%d px (k< %d)" % (len(good), a.extra, max(good) + 1 if good else 0))
    json.dump({"extra": a.extra, "delta": d, "rows": total,
               "per_pixel": bad}, open(case / "oracle.json", "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
