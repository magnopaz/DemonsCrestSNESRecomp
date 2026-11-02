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

3. BG1 map restream lookahead (bank $00, `StreamRestream` at $C840):

       lda #$14 / sta $14        ; fixed 21-call, 42-column (336 px) budget

   $14 -> $14 + DcWsStreamAheadIters(). The restream starts 4 columns behind the
   ring cursor, so its budget is what puts the frontier 304 px past the camera
   (48 px past the authentic view). The per-frame tracker at $00:CF7D advances
   the cursor 2 columns per 16 px of scroll afterwards, so one wider budget per
   room load shifts the frontier permanently; measured margin staleness starts
   at k ~= 50 and a 16:9 margin is 71 px (see docs/HANDOFF-widescreen-staging.md
   §10). 0 extras reproduces the authentic immediate exactly, so 4:3 and any
   margin <= 48 px stay bit-identical.

The generated code is re-derived by tools/regen.sh; this script is idempotent
(injected lines carry a /*DCWS4*/, /*DCWS5*/ or /*DCWS6*/ marker).

Drift safety: the injector is the only thing standing between a generator
change and a silently narrower game, so it counts what it patched and fails
loudly (a) when an anchor is missing, (b) when fewer sites are patched than
this project expects, and (c) in --check mode, when any anchor is still
unpatched. A generator change that legitimately adds or removes a variant must
update EXPECTED_MIN below -- deliberately, in the same commit.

Usage:
    tools/dc_apply_widescreen_hooks.py [--gen-dir src/gen] [--check]
                                       [--expect key=count ...] [--no-strict]
    tools/dc_apply_widescreen_hooks.py --check      # verify, never write

Exit codes: 0 ok / nothing to do, 1 drift or unexpected anchor shape,
2 usage error.
"""

import argparse
import pathlib
import re
import sys

MARK = "/*DCWS4*/"
MARK5 = "/*DCWS5*/"
MARK6 = "/*DCWS6*/"
PROTO = ("%s extern int DcWsObjectCullMargin(void); "
         "/* widescreen object cull margin (src/dc_widescreen.c) */" % MARK)
PROTO_STREAM = ("%s extern int DcWsStreamCatchUpTake(int layer); "
                "/* widescreen BG1 streaming catch-up (src/dc_widescreen.c) */"
                % MARK6)

X_CONST = re.compile(r"^(\s*)uint16 (_v\d+) = 0x1c0;$")
Y_CONST = re.compile(r"^(\s*)uint16 (_v\d+) = 0x1a0;$")
SLACK_CONST = re.compile(r"^(\s*)uint16 (_v\d+) = 0x60;$")
EMIT_LIMIT = re.compile(r"^(\s*)uint16 (_v\d+) = 0xf3;$")
# The "on-screen?" helper at $82:E6AC: mask the camera-relative coordinate's
# high byte (keep only [0,255]) and branch on Z. Two sites, X then Y.
SCREEN_MASK = re.compile(r"^(\s*)uint16 (_v\d+) = 0xff00;$")

# Patched forms, counted after injection (and by --check against an existing
# tree). Keep these in step with the injected text below.
PATCHED_CULL_X = re.compile(
    r"^\s*uint16 _v\d+ = \(uint16\)\(0x1c0 \+ 2 \* DcWsObjectCullMargin\(\)\);",
    re.MULTILINE)
PATCHED_CULL_Y = re.compile(
    r"^\s*uint16 _v\d+ = \(uint16\)\(0x1a0 \+ 2 \* DcWsObjectCullMargin\(\)\);",
    re.MULTILINE)
PATCHED_SLACK = re.compile(
    r"^\s*uint16 _v\d+ = \(uint16\)\(0x60 \+ DcWsObjectCullMargin\(\)\);",
    re.MULTILINE)
PATCHED_EMITTER = re.compile(
    r"^\s*uint16 _v\d+ = \(uint16\)\(0x00F3 - DcWsObjectCullMargin\(\)\);",
    re.MULTILINE)
PATCHED_SCREEN = re.compile(
    r"^\s*const uint16 _ws_m = \(uint16\)DcWsObjectCullMargin\(\);",
    re.MULTILINE)
PATCHED_PROTO = re.compile(re.escape(PROTO))
PATCHED_PROTO_STREAM = re.compile(re.escape(PROTO_STREAM))

# The AOT per-frame BG map tracker $00:CF7D is where the streaming catch-up is
# paid. The room restream itself ($00:C840) runs on the interpreter tier (it
# yields to the scheduler in-line) and the analyzer refuses to emit it in any
# M/X variant, so its fixed 42-column budget cannot be patched; the tracker it
# leaves behind is AOT and drives the same $D57F map writer. The injected
# preamble pays the debt the port arms when it sees a room restream, then the
# authentic body maintains the phase. See docs/HANDOFF-widescreen-staging.md §10.
STREAM_FUNC = re.compile(r"^RecompReturn bank_00_CF7D_M\dX\d\(CpuState \*cpu\) \{",
                         re.MULTILINE)
STREAM_ENTRY_LABEL = re.compile(r"^(\s*)L_CF7D_M\dX\d\s*:\s*;?\s*$")

EXPECTED_MIN = {
    "cull_x": 5,
    "cull_y": 5,
    "emitter": 1,
    "screen": 6,
    "stream_ahead": 1,
    "prototype_files": 3,
}


class Drift(Exception):
    """An anchor disappeared or changed shape: refuse to touch the tree."""


def inject_prototype(lines, protos=(PROTO,)):
    if all(any(p in line for line in lines) for p in protos):
        return
    for i, line in enumerate(lines):
        if line.startswith('#include "funcs.h"'):
            for j, p in enumerate(protos):
                if not any(p in line for line in lines):
                    lines.insert(i + 1 + j, p)
            return
    raise Drift('no #include "funcs.h" anchor for the injected prototype')


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
            raise Drift("%s: no slack constant before line %d" % (path, i + 1))
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
                raise Drift("%s: unexpected line %d: %s" %
                            (path, idx + 1, lines[idx]))
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
        raise Drift("%s: emitter block end not found at line %d" %
                    (path, start + 1))

    indent = re.match(r"^(\s*)", lines[start]).group(1)
    hide_label = re.search(r"goto (L_F788_\w+)", "\n".join(lines[start:end + 1]))
    keep_label = re.search(r"goto (L_F762_\w+)", lines[end])
    if not hide_label or not keep_label:
        raise Drift("%s: emitter labels not found at line %d" %
                    (path, start + 1))
    hide, keep = hide_label.group(1), keep_label.group(1)
    var = EMIT_LIMIT.match(lines[start]).group(2)

    injected = [
        "%s%s /* Widescreen: keep the widened right margin (low < margin) and the" % (indent, MARK),
        "%s     * widened left-edge window (low >= 0xF3 - margin); 0 = authentic. */" % indent,
        "%suint16 %s = (uint16)(0x00F3 - DcWsObjectCullMargin()); %s" %
        (indent, var, MARK),
        "%suint16 _ws_low = (uint16)(cpu->A & 0x00FF); %s" % (indent, MARK),
        "%sif (_ws_low >= DcWsObjectCullMargin() && _ws_low < %s) { %s" %
        (indent, var, MARK),
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
    sites = []
    for i, line in enumerate(lines):
        if not SCREEN_MASK.match(line):
            continue
        after = "\n".join(lines[i:i + 8])
        if "L_E6C4_" not in after and "L_E6C8_" not in after:
            continue
        # The injected block sits right after the masked value; its `_ws_m`
        # local is how an already-patched site is recognised (the mask line
        # itself is authentic and stays untouched).
        if "_ws_m" in "\n".join(lines[i:i + 16]):
            continue
        sites.append(i)
    if not sites:
        return 0

    changed = 0
    for i in sorted(sites, reverse=True):
        m = SCREEN_MASK.match(lines[i])
        mask_var = m.group(2)
        read_i = i + 1
        if "cpu_read_a16(cpu)" not in lines[read_i]:
            raise Drift("%s: unexpected line %d: %s" %
                        (path, read_i + 1, lines[read_i]))
        raw_var = re.search(r"uint16 (_v\d+) = cpu_read_a16", lines[read_i])
        if not raw_var:
            raise Drift("%s: raw read not found at line %d" % (path, read_i + 1))
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
            raise Drift("%s: mask value not found after line %d" %
                        (path, i + 1))
        a_write = None
        for j in range(value_i + 1, min(value_i + 6, len(lines))):
            if "cpu_write_a_m" in lines[j]:
                a_write = j
                break
        if a_write is None:
            raise Drift("%s: A write not found after line %d" %
                        (path, value_i + 1))
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


def patch_stream_budget(path, lines):
    """Pay the widescreen streaming debt from the AOT BG map tracker. Returns
    lines changed.

    The room restream ($00:C840) fills 42 columns (336 px) from 4 columns behind
    the ring cursor, parking the frontier 304 px past the camera - 48 px past
    the authentic view. Everything wider than that in the leading margin reads
    the previous ring revolution (measured: staged to k=45, stale from k=50;
    docs/HANDOFF-widescreen-staging.md §10). The restream runs on the
    interpreter tier and cannot be hooked, so the extra columns are paid here,
    at the entry of the AOT tracker that owns the same writer: the port arms a
    debt when it sees a restream, and this preamble spends it exactly the way
    the restream loop does (write the pair at the cursor, then advance it).
    """
    text = "\n".join(lines)
    fn = STREAM_FUNC.search(text)
    if not fn:
        return 0
    start = text.count("\n", 0, fn.start()) + 1
    tail = text[fn.end():]
    nxt = re.search(r"^RecompReturn bank_", tail, re.MULTILINE)
    end = start + tail.count("\n", 0, nxt.start() if nxt else len(tail))
    body = "\n".join(lines[start:end + 1])
    if MARK6 in body:
        return 0                       # already injected
    label_i = None
    for i in range(start, min(end + 1, len(lines))):
        if STREAM_ENTRY_LABEL.match(lines[i]):
            label_i = i
            break
    if label_i is None:
        raise Drift("%s: bank_00_CF7D entry label not found" % path)
    indent = "    "
    injected = [
        "%s{ %s /* Widescreen: pay the room restream's streaming debt." % (indent, MARK6),
        "%s   * The engine's restream stops 304 px ahead of the camera, so a leading" % indent,
        "%s   * margin wider than 48 px draws the previous ring revolution. The extra" % indent,
        "%s   * pairs are written by the engine's own map writer, with the source phase" % indent,
        "%s   * the restream left behind; the authentic body below then keeps the new" % indent,
        "%s   * phase (+2 columns per 16 px of scroll). Debt 0 = nothing happens." % indent,
        "%s   * The call frame mirrors the authentic JSR site at $00:CFCF (Option-1" % indent,
        "%s   * cpu->S frame + host_return_valid = 2) and propagates a non-local" % indent,
        "%s   * return exactly as that site does. */" % indent,
        "%s  int _ws_pairs = DcWsStreamCatchUpTake((int)cpu_read8(cpu, 0x00, (uint16)(cpu->D + 0x0010))); %s"
        % (indent, MARK6),
        "%s  if (_ws_pairs > 0) {" % indent,
        "%s    CpuState _ws_saved = *cpu; %s" % (indent, MARK6),
        "%s    while (_ws_pairs-- > 0) {" % indent,
        "%s      extern RecompReturn bank_00_D57F_M1X1(CpuState *cpu);" % indent,
        "%s      RecompReturn _ws_r;" % indent,
        "%s      cpu_write8(cpu, 0x00, cpu->S, 0xcf); cpu->S = (uint16)(cpu->S - 1);" % indent,
        "%s      cpu_write8(cpu, 0x00, cpu->S, 0xd1); cpu->S = (uint16)(cpu->S - 1);" % indent,
        "%s      cpu->host_return_valid = 2; %s" % (indent, MARK6),
        "%s      _ws_r = bank_00_D57F_M1X1(cpu); %s" % (indent, MARK6),
        "%s      if (_ws_r != RECOMP_RETURN_NORMAL) { %s" % (indent, MARK6),
        "%s        cpu_trace_event(cpu, 0, CPU_TR_NLR_PROPAGATE, (uint8)_ws_r, 0);" % indent,
        "%s        cpu_trace_mark_nlr_exit(BD_EXIT_KIND_SKIP_PROPAGATION);" % indent,
        "%s        RecompStackPop();" % indent,
        "%s        return (RecompReturn)((int)_ws_r - 1);" % indent,
        "%s      }" % indent,
        "%s      uint16 _ws_cd = (uint16)(cpu->D + 0x00d0 + cpu_read8(cpu, 0x00, (uint16)(cpu->D + 0x0010))); %s"
        % (indent, MARK6),
        "%s      uint8 _ws_cur = (uint8)((cpu_read8(cpu, 0x00, _ws_cd) + 2u) & 0x3fu);" % indent,
        "%s      cpu_write8(cpu, 0x00, _ws_cd, _ws_cur);" % indent,
        "%s      if ((_ws_cur & 0x1fu) == 0u) { %s" % (indent, MARK6),
        "%s        uint16 _ws_pg = (uint16)(_ws_cd + 8u);" % indent,
        "%s        cpu_write8(cpu, 0x00, _ws_pg, (uint8)(cpu_read8(cpu, 0x00, _ws_pg) + 1u));" % indent,
        "%s      }" % indent,
        "%s      *cpu = _ws_saved; %s" % (indent, MARK6),
        "%s    }" % indent,
        "%s  }" % indent,
        "%s} %s" % (indent, MARK6),
    ]
    lines[label_i:label_i] = injected
    return len(injected)


def count_patched(text):
    """Hook sites present in `text` as already-injected code."""
    return {
        "cull_x": len(PATCHED_CULL_X.findall(text)),
        "cull_y": len(PATCHED_CULL_Y.findall(text)),
        "slack": len(PATCHED_SLACK.findall(text)),
        "emitter": len(PATCHED_EMITTER.findall(text)),
        "screen": len(PATCHED_SCREEN.findall(text)),
        "stream_ahead": text.count("int _ws_pairs = DcWsStreamCatchUpTake("),
        "prototype_files": 1 if PATCHED_PROTO.search(text) else 0,
    }


def merge_counts(total, add):
    for k, v in add.items():
        total[k] = total.get(k, 0) + v


def check_counts(counts, expected):
    """Return a list of human-readable shortfalls (empty when the tree is ok)."""
    short = []
    for key, want in sorted(expected.items()):
        got = counts.get(key, 0)
        if got < want:
            short.append("%s: %d patched, expected at least %d" % (key, got, want))
    return short


def write_atomic(path, text):
    """Write via a sibling temp file so a crash cannot leave a half-patched TU."""
    tmp = path.with_name(path.name + ".dchooks.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    tmp.replace(path)


def parse_expectations(pairs):
    expected = dict(EXPECTED_MIN)
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit("--expect wants key=count, got %r" % pair)
        key, _, value = pair.partition("=")
        key = key.strip()
        if key not in EXPECTED_MIN:
            raise SystemExit("--expect: unknown key %r (known: %s)" %
                             (key, ", ".join(sorted(EXPECTED_MIN))))
        try:
            expected[key] = int(value)
        except ValueError:
            raise SystemExit("--expect %s: not an integer: %r" % (key, value))
    return expected


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gen-dir", default="src/gen",
                    help="generated-code directory (default: src/gen)")
    ap.add_argument("--check", action="store_true",
                    help="verify only: fail if any anchor is unpatched or a "
                         "hook site is missing; never write")
    ap.add_argument("--expect", action="append", default=[], metavar="KEY=COUNT",
                    help="override an expected minimum (repeatable; known keys: "
                         + ", ".join(sorted(EXPECTED_MIN)) + ")")
    ap.add_argument("--no-strict", action="store_true",
                    help="report the counts but do not fail on a shortfall "
                         "(for investigating a generator change)")
    args = ap.parse_args()

    expected = parse_expectations(args.expect)
    gen = pathlib.Path(args.gen_dir)
    if not gen.is_dir():
        print("dc_apply_widescreen_hooks: gen dir not found: %s" % gen,
              file=sys.stderr)
        return 2
    files = sorted(gen.glob("bank*.c"))
    if not files:
        print("dc_apply_widescreen_hooks: no generated bank files in %s" % gen,
              file=sys.stderr)
        return 2

    total_changed = 0
    counts = {}
    changed_files = []
    try:
        for path in files:
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines()
            cull = patch_cull(path, lines)
            emit = patch_emitter(path, lines)
            screen = patch_screen_test(path, lines)
            stream = patch_stream_budget(path, lines)
            changed = cull + emit + screen + stream
            if changed:
                protos = [PROTO] + ([PROTO_STREAM] if stream else [])
                inject_prototype(lines, tuple(protos))
            text = "\n".join(lines) + "\n" if changed else original

            if changed and not args.check:
                write_atomic(path, text)

            counts_file = count_patched(text)
            merge_counts(counts, counts_file)
            if changed:
                changed_files.append("%s: cull %d, emitter %d, screen %d, "
                                     "stream %d" %
                                     (path.name, cull, emit, screen, stream))
                total_changed += changed
    except Drift as exc:
        print("dc_apply_widescreen_hooks: DRIFT: %s" % exc, file=sys.stderr)
        return 1

    for line in changed_files:
        print("dc_apply_widescreen_hooks: %s" % line)

    if args.check and total_changed:
        # In check mode the patcher ran on an in-memory copy: anything it had
        # to change means the tree on disk is not fully injected.
        print("dc_apply_widescreen_hooks: --check FAILED: %d hook line(s) "
              "still unpatched; run the injector" % total_changed,
              file=sys.stderr)
        return 1

    short = check_counts(counts, expected)
    if short and not args.no_strict:
        print("dc_apply_widescreen_hooks: FAILED: hook sites are missing "
              "(anchors changed shape?):", file=sys.stderr)
        for line in short:
            print("  - %s" % line, file=sys.stderr)
        print("  measured: %s" % ", ".join("%s=%d" % (k, counts.get(k, 0))
                                           for k in sorted(expected)),
              file=sys.stderr)
        print("  If the generator deliberately changed the hook set, update "
              "EXPECTED_MIN in this script in the same commit.", file=sys.stderr)
        return 1
    if short:
        print("dc_apply_widescreen_hooks: WARNING (--no-strict): %s" %
              "; ".join(short), file=sys.stderr)

    print("dc_apply_widescreen_hooks: %s (cull_x %d, cull_y %d, slack %d, "
          "emitter %d, screen %d, stream_ahead %d, prototype files %d)" %
          ("check ok" if args.check else "done",
           counts.get("cull_x", 0), counts.get("cull_y", 0),
           counts.get("slack", 0), counts.get("emitter", 0),
           counts.get("screen", 0), counts.get("stream_ahead", 0),
           counts.get("prototype_files", 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
