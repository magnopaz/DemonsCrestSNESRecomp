#!/usr/bin/env python3
"""Turn a slice of snesrecomp generated C back into readable pseudo-65816.

The generated code is one flat function of per-instruction blocks separated by
labels, with the silicon-accurate ops spelled out. That is unreadable for
pattern hunting, but the mechanical translation back to mnemonics is exact.
Blocks are printed in source order with the operands that matter.

Usage: asmview.py <gen-file> <start-line> <end-line> [--only C0,D0]
"""
import argparse
import re
import sys

DP = re.compile(r'cpu->D \+ 0x([0-9a-f]{4})( \+ cpu->X)?', re.I)
ABS = re.compile(r'cpu_write(8|16)\(cpu, (?:cpu->DB|0x00), \(uint16\)\(0x([0-9a-f]{4})\)')
LABEL = re.compile(r'^\s*(L_[0-9A-F]+_\w+):')


def op_of(line):
    s = line.strip()
    if not s:
        return None
    if LABEL.match(line):
        return ("LABEL", LABEL.match(line).group(1))
    if re.match(r'^(cpu->cycles|WatchdogCheck|cpu_trace_block|cpu_dbg_funcname|'
                r'RecompStackPush|cpu_trace_func_entry|if \(interp_bridge|'
                r'return interp_bridge|\(void\)|uint16 _entry_s|uint8 _hrv|'
                r'uint32 _host_return_pc24|if \(_hrv|if \(cpu_take_tail|'
                r'if \(g_recomp_stack_top|RecompReturn|g_last_recomp_func|'
                r'extern |\} *$)', s):
        return None
    m = re.search(r'uint8 _v\d+ = 0x([0-9a-f]{1,2});', s, re.I)
    if m:
        return ("LDA #$%s" % m.group(1).upper(),)
    m = re.search(r'uint16 _v\d+ = 0x([0-9a-f]{1,4});', s, re.I)
    if m:
        return ("LD16 #$%s" % m.group(1).upper(),)
    if 'cpu_read8(cpu, 0x00, (uint16)(cpu->D + 0x0010))' in s:
        return ("LDX $10",)
    m = re.search(r'uint8 _v\d+ = cpu_read8\(cpu, 0x00, \(uint16\)\(cpu->D \+ 0x([0-9a-f]{4})( \+ cpu->X)?\)\)', s, re.I)
    if m:
        return ("LDA $%s%s" % (m.group(1).upper(), ",X" if m.group(2) else ""),)
    m = re.search(r'cpu_read8\(cpu, \(uint8\)\(.*?0x([0-9a-f]{4}).*?\)', s, re.I)
    if m:
        return ("LDA $%s,X (long)" % m.group(1).upper(),)
    m = re.search(r'cpu_write8\(cpu, 0x00, \(uint16\)\(cpu->D \+ 0x([0-9a-f]{4})( \+ cpu->X)?\), _(\w+)\)', s, re.I)
    if m:
        return ("STA $%s%s" % (m.group(1).upper(), ",X" if m.group(2) else ""),)
    m = ABS.search(s)
    if m:
        return ("STA $%s (reg)" % m.group(2).upper(),)
    m = re.search(r'cpu_read16\(cpu, 0x00, \(uint16\)\(cpu->D \+ 0x([0-9a-f]{4})( \+ cpu->X)?\)\)', s, re.I)
    if m:
        return ("LDA16 $%s%s" % (m.group(1).upper(), ",X" if m.group(2) else ""),)
    if 'cpu->A = (uint16)((cpu->A) + (0x' in s:
        v = re.search(r'\(0x([0-9a-f]+)\)', s, re.I)
        return ("ADC #$%s" % v.group(1).upper() if v else "ADC",)
    if 'cpu->A = (uint16)((cpu->A) + (cpu->X));' in s:
        return ("ADC $X",)
    if 'cpu->A = (uint16)((cpu->A) + (cpu->Y));' in s:
        return ("ADC $Y",)
    if 'cpu->A = (uint16)((cpu->A) + (-1));' in s or ')+ (-1)' in s:
        return ("DEC A",)
    if 'cpu->A) + (1)' in s:
        return ("INC A",)
    if 'cpu->X = (uint16)((cpu->X) + (-1));' in s or 'cpu->X) + (-1)' in s:
        return ("DEX",)
    if 'cpu->X = (uint16)((cpu->X) + (1));' in s:
        return ("INX",)
    if 'cpu->Y = (uint16)((cpu->Y) + (-1));' in s:
        return ("DEY",)
    if 'cpu->Y = (uint16)((cpu->Y) + (1));' in s:
        return ("INY",)
    if 'cpu->A = (uint16)((cpu->A) + (cpu->X));' in s:
        return ("ADC X",)
    if 'cpu->A = (uint16)((_old & 0xFF) << 8)' in s:
        return ("XBA",)
    if 'cpu->A = (uint16)((_old >> 8)' in s:
        return ("XBA(lo)",)
    if '>> 1);' in s:
        return ("LSR A",)
    if '<< 1);' in s:
        return ("ASL A",)
    if 'cpu->A = (uint16)((_old & 0xFF) << 8)' in s:
        return ("XBA",)
    if 'cpu->A = (uint16)(((_old & 0xFF00) >> 8)' in s:
        return ("XBA",)
    if 'cpu->A = (uint16)(_old >> 8)' in s:
        return ("XBA",)
    m = re.search(r'cpu->A = \(uint16\)\(\(\(uint16\)\(cpu->A & 0x([0-9a-f]+)\) >> (\d)\)', s, re.I)
    if m:
        return ("SHR A &$%s >>%s" % (m.group(1).upper(), m.group(2)),)
    if 'cpu->_flag_C = 1;' in s:
        return ("SEC",)
    if 'cpu->_flag_C = 0;' in s:
        return ("CLC",)
    if 'cpu->_flag_C = (' in s or 'cpu->_flag_C = (((' in s:
        return ("(C=cmp)",)
    if 'cpu->_flag_Z = ((cpu->A & 0xFF) == 0)' in s or 'cpu->_flag_Z = ((cpu->A) == 0)' in s:
        return None
    if 'goto L_' in s:
        tgt = re.search(r'goto (L_\w+);', s)
        cond = ''
        if 'if (cpu->_flag_C == 0)' in s:
            cond = 'BCC '
        elif 'if (cpu->_flag_C != 0)' in s:
            cond = 'BCS '
        elif 'if (cpu->_flag_Z != 0)' in s:
            cond = 'BEQ '
        elif 'if (cpu->_flag_Z == 0)' in s:
            cond = 'BNE '
        elif 'if (cpu->_flag_N != 0)' in s:
            cond = 'BMI '
        elif 'if (cpu->_flag_N == 0)' in s:
            cond = 'BPL '
        return (cond + "BRA " + tgt.group(1),) if tgt else None
    if 'cpu->A = (uint16)((_v' in s or 'cpu->A = (uint16)(_v' in s:
        return ("LDA tmp",)
    if 'cpu_write_a_m(cpu' in s:
        return ("(A->mem txn)",)
    if 'uint16 _v' in s and 'cpu_read_a16' in s:
        return ("LDA (stack/idx)",)
    if 'cpu_read_a16' in s:
        return ("LDA ($)",)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("start", type=int)
    ap.add_argument("end", type=int)
    ap.add_argument("--only", default=None,
                    help="comma list of DP addresses (hex, no 0x) to filter blocks")
    a = ap.parse_args()
    lines = open(a.path).read().split("\n")
    want = set(x.upper() for x in a.only.split(",")) if a.only else None
    block = []
    label = "(entry)"
    out = []

    def flush():
        if not block:
            return
        joined = " ".join(block)
        if want and not any(("%s" % w) in joined for w in want):
            return
        print("%-22s %s" % (label, "  ".join(block[:14]) +
                            ("  ..." if len(block) > 14 else "")))

    for i in range(a.start - 1, min(a.end, len(lines))):
        t = op_of(lines[i])
        if t is None:
            continue
        if t[0] == "LABEL":
            flush()
            block = []
            label = t[1]
            continue
        block.append(t[0])
    flush()


if __name__ == "__main__":
    sys.exit(main())
