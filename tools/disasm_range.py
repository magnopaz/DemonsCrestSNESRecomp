#!/usr/bin/env python3
"""Disassemble a range of the project ROM with the framework's decoder.

Small development aid for porting: decode a linear range of 65816 code using
the same opcode table the recompiler uses (snesrecomp/recompiler/snes65816.py),
tracking SEP/REP width changes so immediates decode at the right size.

Usage:
    python3 tools/disasm_range.py <bank:addr> [<end addr>] [--rom PATH]
                                  [--m 1|0] [--x 1|0]

    python3 tools/disasm_range.py 80:8183 80:81A6
    python3 tools/disasm_range.py 00:FFA4 00:FFE0 --m 1 --x 1

Addresses are hex bank:addr (LoROM). The end address may include the bank
(80:81A6) or be a plain 16-bit address (81A6); decoding stops at the second.
Reads the ROM path from --rom, SNESRECOMP_ROM, or rom.cfg, in that order.
No ROM bytes are printed beyond the instruction stream.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "snesrecomp"))

from recompiler import snes65816 as s  # noqa: E402


def parse_addr(text: str, default_bank: int = 0) -> tuple[int, int]:
    if ":" in text:
        bank, addr = text.split(":", 1)
        return int(bank, 16), int(addr, 16)
    return default_bank, int(text, 16)


def find_rom(explicit: str | None) -> str:
    if explicit:
        return explicit
    import os
    env = os.environ.get("SNESRECOMP_ROM")
    if env:
        return env
    cfg = ROOT / "rom.cfg"
    if cfg.is_file():
        path = cfg.read_text(encoding="utf-8").strip().splitlines()
        if path:
            return path[0]
    raise SystemExit("disasm_range: pass --rom, set SNESRECOMP_ROM, or write rom.cfg")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start", help="bank:addr (hex), e.g. 80:8183")
    parser.add_argument("end", nargs="?", help="end bank:addr or addr (hex)")
    parser.add_argument("--rom", help="ROM path (default: SNESRECOMP_ROM / rom.cfg)")
    parser.add_argument("--m", type=int, default=1, choices=(0, 1),
                        help="initial M (accumulator width) flag")
    parser.add_argument("--x", type=int, default=1, choices=(0, 1),
                        help="initial X (index width) flag")
    parser.add_argument("--bytes", type=int, default=64,
                        help="instructions to print when no end is given")
    args = parser.parse_args()

    rom = s.load_rom(find_rom(args.rom))
    s.set_rom_mapping(s.detect_rom_mapping(rom))

    bank, pc = parse_addr(args.start)
    if args.end:
        _end_bank, end = parse_addr(args.end, bank)
    else:
        end = None
    m, x = args.m, args.x

    count = 0
    while pc < 0x10000 and count < args.bytes:
        offset = s.rom_offset(bank, pc)
        insn = s.decode_insn(rom, offset, pc, bank, m, x)
        if insn is None:
            print(f"{bank:02X}:{pc:04X}  .byte ${rom[offset]:02X}")
            pc += 1
            count += 1
            continue
        operand = ""
        if insn.length > 1:
            if insn.mode in (s.IMM,):
                operand = f" #${insn.operand:0{2 * (insn.length - 1)}X}"
            elif insn.mode in (s.REL,):
                operand = f" ${insn.operand:04X}"
            elif insn.mode in (s.REL16,):
                operand = f" ${insn.operand:04X}"
            elif insn.length == 4:
                operand = f" ${insn.operand:06X}"
            elif insn.length == 3:
                operand = f" ${insn.operand:04X}"
            else:
                operand = f" ${insn.operand:02X}"
        print(f"{bank:02X}:{pc:04X}  {rom[offset:offset + insn.length].hex(' '):<11} "
              f"{insn.mnem.lower():<6}{operand}")
        if insn.mnem.upper() == "SEP" and insn.length == 2:
            if insn.operand & 0x20:
                m = 1
            if insn.operand & 0x10:
                x = 1
        elif insn.mnem.upper() == "REP" and insn.length == 2:
            if insn.operand & 0x20:
                m = 0
            if insn.operand & 0x10:
                x = 0
        pc += insn.length
        count += 1
        if end is not None and pc >= end:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
