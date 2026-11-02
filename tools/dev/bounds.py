#!/usr/bin/env python3
"""Find the room's right scroll bound in WRAM, empirically.

The camera clamps at the room's right edge, so a word whose value equals that
clamp in every room -- at the same address -- is the bound (or the bound plus a
constant). Walk right in several rooms, record the camera clamp, then look for a
16-bit WRAM word that (a) equals the clamp + k for small k, (b) sits at the same
address in every room, (c) is stable while the camera is clamped.

Usage: bounds.py <fixture.sav> [fixture.sav ...]
"""
import pathlib
import struct
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
FRAMES, CHUNK = 120, 10


def walk(save, case):
    script = pathlib.Path(str(case) + ".txt")
    lines = ["loadstate 0", "wait 20"]
    for i in range(FRAMES):
        lines += ["press right %d" % CHUNK, "dump d%03d" % i]
    lines.append("quit")
    script.write_text("\n".join(lines) + "\n")
    subprocess.run([sys.executable, str(HERE / "probe.py"), "run", "--name", str(case),
                    "--ws", "1", "--extra", "71", "--save", save, "--script", str(script)],
                   capture_output=True, text=True)
    d = case / "dump"
    out = []
    for p in sorted(d.glob("d*.fbwide.bgrx")):
        tag = p.name.split(".")[0]
        w = (d / (tag + ".wram.bin")).read_bytes()
        cam = struct.unpack_from("<H", w, 0xC0)[0]
        out.append((cam, w))
    return out


def main():
    rooms = {}
    for save in sys.argv[1:]:
        name = pathlib.Path(save).stem
        case = pathlib.Path("bounds_" + name.replace("-", "_")[:40])
        frames = walk(save, case)
        if not frames:
            print("%s: no frames" % name)
            continue
        maxcam = max(c for c, _ in frames)
        clamped = [w for c, w in frames if c >= maxcam - 2]
        rooms[name] = (maxcam, clamped[-1], len(clamped))
        print("%-46s max cam %4d  (clamped frames: %d)" % (name[:46], maxcam, len(clamped)))
    if len(rooms) < 2:
        return 1
    # candidate = address whose word equals maxcam+k at the same place in all rooms
    names = list(rooms)
    print("\nscanning %d rooms for a shared address holding each room's own clamp:"
          % len(names))
    hits = []
    for k in range(-256, 257):
        base = None
        ok = True
        for n in names:
            maxcam, wram, _ = rooms[n]
            want = (maxcam + k) & 0xFFFF
            found = set()
            for a in range(0, 0x2000, 1):
                if struct.unpack_from("<H", wram, a)[0] == want:
                    found.add(a)
            base = found if base is None else (base & found)
            if not base:
                ok = False
                break
        if ok and base:
            for a in sorted(base):
                hits.append((a, k))
    seen = {}
    for a, k in hits:
        seen.setdefault(a, []).append(k)
    for a in sorted(seen):
        ks = seen[a]
        if len(ks) > 40:
            continue
        print("  addr $%04X  matches clamp%+d in all rooms  (offsets %s)"
              % (a, ks[0], ks[:6]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
