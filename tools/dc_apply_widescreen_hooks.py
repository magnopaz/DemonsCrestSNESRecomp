#!/usr/bin/env python3
"""Inject the Demon's Crest widescreen hooks into generated code (Fase 4).

Two guest-side tests keep objects and their sprites inside the authentic
256-px window. Both are widened by the live widescreen margin here; at margin
0 every injected expression evaluates to the authentic constant, so the 4:3
path stays bit-identical.

1. Object cull (bank $82 update loop, three emitted variants):

       dx = objX - camX;  keep if (dx + 0x60) < 0x1C0     (X, cmp $1C0)
       dy = objY - camY;  keep if (dy + 0x60) < 0x1A0     (Y, cmp $1A0)

   0x60 -> 0x60 + margin, 0x1C0/0x1A0 -> 0x1C0/0x1A0 + 2*margin: the window
   widens by `margin` on BOTH sides without moving its base.

2. Sprite emitter X test (bank $00/$80 function at $F689, AOT):

       bit #$0100 / beq keep                 ; x < 256: native, no 9th bit
       and #$00FF / cmp #$00F3 / bcc hide    ; 9-bit x with low < $F3: hidden

   Replaced by: keep when the low byte is < margin (right margin) or
   >= 0xF3 - margin (widened left-edge window); the authentic hide stays for
   everything else. The framework decodes 256..256+extra as the right margin
   and >= that as the wrapped left margin (PpuDecodeOamX).

The generated code is re-derived by tools/regen.sh; this script is idempotent
(injected lines carry a /*DCWS4*/ marker) and fails loudly when an anchor is
missing, so a generator change cannot silently drop a hook.

Usage: tools/dc_apply_widescreen_hooks.py [--gen-dir src/gen]
"""

import argparse
import pathlib
import re
import sys

MARK = "/*DCWS4*/"
PROTO = ("%s extern int DcWsObjectCullMargin(void); "
         "/* widescreen object cull margin (src/dc_widescreen.c) */" % MARK)

X_CONST = re.compile(r"^(\s*)uint16 (_v\d+) = 0x1c0;$")
Y_CONST = re.compile(r"^(\s*)uint16 (_v\d+) = 0x1a0;$")
SLACK_CONST = re.compile(r"^(\s*)uint16 (_v\d+) = 0x60;$")
EMIT_LIMIT = re.compile(r"^(\s*)uint16 (_v\d+) = 0xf3;$")
# The "on-screen?" helper at $82:E6AC: mask the camera-relative coordinate's
# high byte (keep only [0,255]) and branch on Z. Two sites, X then Y.
SCREEN_MASK = re.compile(r"^(\s*)uint16 (_v\d+) = 0xff00;$")


def inject_prototype(lines):
    if any(PROTO in line for line in lines):
        return
    for i, line in enumerate(lines):
        if line.startswith('#include "funcs.h"'):
            lines.insert(i + 1, PROTO)
            return
    sys.exit('no #include "funcs.h" anchor for the injected prototype')


def patch_cull(path, lines):
    """Widen the bank $82 object loop's cull window. Returns lines changed."""
    tests = []
    for i, line in enumerate(lines):
        m = X_CONST.match(line)
        kind = "X"
        if not m:
            m = Y_CONST.match(line)
            kind = "Y"
        if not m:
            continue
        label = "L_86F0_" if kind == "X" else "L_8704_"
        if label not in "\n".join(lines[i:i + 9]):
            continue  # an unrelated 0x1c0/0x1a0 compare
        slack = None
        for j in range(i - 1, max(-1, i - 40), -1):
            if SLACK_CONST.match(lines[j]):
                slack = j
                break
        if slack is None:
            sys.exit("%s: no slack constant before line %d" % (path, i + 1))
        tests.append((kind, i, slack))

    if not tests:
        return 0

    changed = 0
    for kind, const_i, slack_i in sorted(tests, key=lambda t: -t[1]):
        limit = "0x1c0" if kind == "X" else "0x1a0"
        for idx, old, new in (
            (const_i, "= %s;" % limit,
             "= (uint16)(%s + 2 * DcWsObjectCullMargin());" % limit),
            (slack_i, "= 0x60;",
             "= (uint16)(0x60 + DcWsObjectCullMargin());"),
        ):
            if MARK in lines[idx]:
                continue
            if old not in lines[idx]:
                sys.exit("%s: unexpected line %d: %s" % (path, idx + 1, lines[idx]))
            lines[idx] = lines[idx].replace(old, new) + " " + MARK
            changed += 1
    return changed


def patch_emitter(path, lines):
    """Widen the sprite emitter's X test. Returns lines changed."""
    start = None
    for i, line in enumerate(lines):
        if not EMIT_LIMIT.match(line):
            continue
        before = "\n".join(lines[max(0, i - 8):i])
        after = "\n".join(lines[i:i + 10])
        if "0xff;" in before and "goto L_F788_" in after:
            start = i
            break
    if start is None:
        return 0
    if MARK in lines[start]:
        return 0  # already injected

    # Find the end of the replaced block: the fall-through goto after the
    # hide branch.
    end = None
    for j in range(start, min(start + 12, len(lines))):
        if "goto L_F762_" in lines[j]:
            end = j
            break
    if end is None:
        sys.exit("%s: emitter block end not found at line %d" % (path, start + 1))

    indent = re.match(r"^(\s*)", lines[start]).group(1)
    hide_label = re.search(r"goto (L_F788_\w+)", "\n".join(lines[start:end + 1]))
    keep_label = re.search(r"goto (L_F762_\w+)", lines[end])
    if not hide_label or not keep_label:
        sys.exit("%s: emitter labels not found at line %d" % (path, start + 1))
    hide, keep = hide_label.group(1), keep_label.group(1)

    injected = [
        "%s%s /* Widescreen: keep the widened right margin (low < margin) and the" % (indent, MARK),
        "%s     * widened left-edge window (low >= 0xF3 - margin); 0 = authentic. */" % indent,
        "%suint16 %s = (uint16)(0x00F3 - DcWsObjectCullMargin()); %s" %
        (indent, EMIT_LIMIT.match(lines[start]).group(2), MARK),
        "%suint16 _ws_low = (uint16)(cpu->A & 0x00FF); %s" % (indent, MARK),
        "%sif (_ws_low >= DcWsObjectCullMargin() && _ws_low < %s) { %s" %
        (indent, EMIT_LIMIT.match(lines[start]).group(2), MARK),
        "%s  cpu->cycles += 1; cpu->master_cycles += ((g_memsel && (cpu->PB & 0x80)) ? 6 : 8); %s"
        % (indent, MARK),
        "%s  goto %s; %s" % (indent, hide, MARK),
        "%s} %s" % (indent, MARK),
        "%sgoto %s; /* fall-through */ %s" % (indent, keep, MARK),
    ]
    lines[start:end + 1] = injected
    return len(injected)


def patch_screen_test(path, lines):
    """Widen the $82:E6AC on-screen test (shot/object despawn) by the margin.

    The authentic test keeps a coordinate only while its high byte is zero
    (i.e. in [0,255]); the injected version keeps [-margin, 255+margin). The
    branch that follows reads Z, so Z must mean "on screen" at both sites.
    """
    MARK5 = "/*DCWS5*/"
    sites = []
    for i, line in enumerate(lines):
        if not SCREEN_MASK.match(line):
            continue
        after = "\n".join(lines[i:i + 8])
        if "L_E6C4_" in after or "L_E6C8_" in after:
            sites.append(i)
    if not sites:
        return 0

    changed = 0
    for i in sorted(sites, reverse=True):
        if MARK5 in lines[i]:
            continue
        m = SCREEN_MASK.match(lines[i])
        mask_var = m.group(2)
        read_i = i + 1
        if "cpu_read_a16(cpu)" not in lines[read_i]:
            sys.exit("%s: unexpected line %d: %s" % (path, read_i + 1, lines[read_i]))
        raw_var = re.search(r"uint16 (_v\d+) = cpu_read_a16", lines[read_i])
        if not raw_var:
            sys.exit("%s: raw read not found at line %d" % (path, read_i + 1))
        raw_var = raw_var.group(1)
        value_var = None
        value_i = None
        for j in range(read_i + 1, min(read_i + 4, len(lines))):
            mm = re.match(r"^\s*uint16 (_v\d+) = \(uint16\)\((_v\d+) & (_v\d+)\);$", lines[j])
            if mm and mm.group(3) == mask_var:
                value_var = mm.group(1)
                value_i = j
                break
        if value_var is None:
            sys.exit("%s: mask value not found after line %d" % (path, i + 1))
        a_write = None
        for j in range(value_i + 1, min(value_i + 6, len(lines))):
            if "cpu_write_a_m" in lines[j]:
                a_write = j
                break
        if a_write is None:
            sys.exit("%s: A write not found after line %d" % (path, value_i + 1))
        indent = re.match(r"^(\s*)", lines[value_i]).group(1)
        injected = [
            "%s%s /* Widescreen: authentic keeps a screen coordinate only while its" % (indent, MARK5),
            "%s     * high byte is zero (0..255); keep [-margin, 255+margin). Z = on" % indent,
            "%s     * screen; margin 0 evaluates to the authentic test. */" % indent,
            "%s{" % indent,
            "%s  const uint16 _ws_m = (uint16)DcWsObjectCullMargin(); %s" % (indent, MARK5),
            "%s  const uint16 _ws_c = (uint16)(%s & 0xFFFF); %s" % (indent, raw_var, MARK5),
            "%s  cpu->_flag_Z = ((uint16)(_ws_c + _ws_m) < (uint16)(0x0100u + 2u * _ws_m)) ? 1 : 0; %s" % (indent, MARK5),
            "%s  cpu->_flag_N = 0; %s" % (indent, MARK5),
            "%s}" % indent,
        ]
        lines[value_i + 1:a_write] = injected
        changed += 1
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gen-dir", default="src/gen",
                    help="generated-code directory (default: src/gen)")
    args = ap.parse_args()

    gen = pathlib.Path(args.gen_dir)
    if not gen.is_dir():
        sys.exit("gen dir not found: %s" % gen)
    files = sorted(gen.glob("bank*.c"))
    if not files:
        sys.exit("no generated bank files in %s" % gen)

    total_cull = 0
    total_emit = 0
    total_screen = 0
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        cull = patch_cull(path, lines)
        emit = patch_emitter(path, lines)
        screen = patch_screen_test(path, lines)
        if not (cull or emit or screen):
            continue
        inject_prototype(lines)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("dc_apply_widescreen_hooks: %s: cull %d, emitter %d, screen %d" %
              (path.name, cull, emit, screen))
        total_cull += cull
        total_emit += emit
        total_screen += screen

    if total_cull == 0 and total_emit == 0 and total_screen == 0:
        # Either everything is already patched or the anchors vanished.
        patched = any(MARK in p.read_text(encoding="utf-8") for p in files)
        if not patched:
            sys.exit("no widescreen anchors found in %s" % gen)
    print("dc_apply_widescreen_hooks: done (cull %d, emitter %d, screen %d)" %
          (total_cull, total_emit, total_screen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
