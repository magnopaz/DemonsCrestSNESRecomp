#!/usr/bin/env python3
"""Turn a folder of frame_XXXXXX.bmp captures into a GIF (and an MP4).

The debug server's `record_frames` / `record_last` commands write one 256x224 BMP
per frame; this converts that sequence into something shareable. Frames are
upscaled with nearest-neighbour so the pixels stay crisp.

Usage:
  python tools/bmp_sequence.py <frames_dir> [--gif out.gif] [--mp4 out.mp4]
                               [--fps 60] [--scale 3] [--every 2]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image


def load_frames(folder: Path, every: int):
    files = sorted(folder.glob("frame_*.bmp"))
    if not files:
        files = sorted(folder.glob("*.bmp"))
    if not files:
        raise SystemExit(f"no BMP frames in {folder}")
    frames = []
    for path in files[::max(1, every)]:
        frames.append(Image.open(path).convert("RGB"))
    return frames


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--gif", type=Path)
    ap.add_argument("--mp4", type=Path)
    ap.add_argument("--fps", type=int, default=60)
    ap.add_argument("--scale", type=int, default=3)
    ap.add_argument("--every", type=int, default=1,
                    help="keep every Nth frame (2 halves a 60 fps capture)")
    args = ap.parse_args()

    frames = load_frames(args.folder, args.every)
    if args.scale > 1:
        frames = [f.resize((f.width * args.scale, f.height * args.scale),
                           Image.NEAREST) for f in frames]
    print(f"{len(frames)} frame(s) at {frames[0].size}")

    if args.gif or not args.mp4:
        gif = args.gif or (args.folder / "capture.gif")
        delay = max(1, int(round(1000.0 / max(1, args.fps / args.every))))
        frames[0].save(gif, save_all=True, append_images=frames[1:],
                       duration=delay, loop=0)
        print("gif:", gif, f"({gif.stat().st_size // 1024} KiB)")

    if args.mp4:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            print("mp4 skipped: ffmpeg not on PATH", file=sys.stderr)
        else:
            tmp = args.folder / "_seq"
            tmp.mkdir(exist_ok=True)
            for i, frame in enumerate(frames):
                frame.save(tmp / f"{i:05d}.png")
            cmd = [ffmpeg, "-y", "-framerate", str(args.fps // args.every),
                   "-i", str(tmp / "%05d.png"), "-pix_fmt", "yuv420p",
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                   str(args.mp4)]
            subprocess.run(cmd, check=False, capture_output=True)
            if args.mp4.is_file():
                print("mp4:", args.mp4,
                      f"({args.mp4.stat().st_size // 1024} KiB)")
            else:
                print("mp4 failed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
