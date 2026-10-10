#!/usr/bin/env python3
"""Report byte-identical runs between two SNES ROM images.

Used during Demon's Crest port bring-up to quantify shared Capcom library
code with Mega Man X: the two titles are the same cartridge class, and an
identical region in both images is a routine worth identifying once and
naming in `recomp/symbols.toml` for both projects.

Usage:
    python3 tools/rom_similarity.py <base.sfc> <other.sfc> [--min 24]

Both files are read as-is; a 512-byte copier header is stripped when
present. Offsets are reported as LoROM logical addresses (`bank:addr`) and
as raw file offsets, since the two images map the same bytes differently.
Nothing is written and no ROM data is copied into the project.
"""

from __future__ import annotations

import argparse
import hashlib
import struct


def load(path: str) -> bytes:
    data = open(path, "rb").read()
    if len(data) % 1024 == 512:
        data = data[512:]
    return data


def lorom(offset: int) -> str:
    bank = offset // 0x8000
    return f"{bank:02X}:{0x8000 + (offset % 0x8000):04X}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", help="ROM to index (e.g. Mega Man X)")
    parser.add_argument("other", help="ROM to scan (e.g. Demon's Crest)")
    parser.add_argument("--min", type=int, default=24,
                        help="minimum run length in bytes (default 24)")
    parser.add_argument("--top", type=int, default=20,
                        help="how many runs to print (default 20)")
    args = parser.parse_args()

    base = load(args.base)
    other = load(args.other)
    window = 24
    index: dict[bytes, list[int]] = {}
    for i in range(len(base) - window):
        chunk = base[i:i + window]
        if len(set(chunk)) <= 2:  # uniform filler: not evidence of shared code
            continue
        index.setdefault(hashlib.md5(chunk).digest(), []).append(i)

    runs: list[tuple[int, int, int]] = []
    pos = 0
    while pos <= len(other) - window:
        chunk = other[pos:pos + window]
        if len(set(chunk)) <= 2:
            pos += 1
            continue
        candidates = index.get(hashlib.md5(chunk).digest())
        best = 0
        best_base = -1
        for j in candidates or ():
            length = window
            while (pos + length < len(other) and j + length < len(base)
                   and other[pos + length] == base[j + length]):
                length += 1
            if length > best:
                best, best_base = length, j
        if best >= args.min:
            runs.append((best, pos, best_base))
            pos += best
            continue
        pos += 1

    runs.sort(reverse=True)
    total = sum(length for length, _, _ in runs)
    print(f"base  {args.base}: {len(base)} bytes")
    print(f"other {args.other}: {len(other)} bytes")
    print(f"runs >= {args.min} bytes: {len(runs)}, "
          f"{total} bytes ({100.0 * total / max(len(other), 1):.2f}% of other)")
    print()
    print(f"{'length':>8}  {'other':>12}  {'base':>12}  file offsets")
    for length, o, b in runs[:args.top]:
        print(f"{length:8d}  {lorom(o):>12}  {lorom(b):>12}  "
              f"other=${o:06X} base=${b:06X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
