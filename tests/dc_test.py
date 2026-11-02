#!/usr/bin/env python3
"""Headless regression tests for Demon's Crest Recompiled.

Runs the real executable through the framework's script driver, so the tests
exercise the same frame model the player gets. Two classes:

  unit        no ROM needed: the generated-code injector (synthetic anchors,
              idempotency, drift detection) and the injector's --check against
              the current src/gen.
  integration need a ROM; skipped (exit 77) when none is found:
              boot, widescreen geometry + center identity, determinism, and the
              far-right staging-band repair (that last one also needs a save
              state, see SNESRECOMP_TEST_SAVE).

Prerequisites
  ROM          $SNESRECOMP_ROM, else the path in <repo>/rom.cfg, else a known
               filename at the repo root.
  Save state   only for ``staging-band``: $SNESRECOMP_TEST_SAVE (any .sav the
               game can load into slot 0, e.g. one made during stage play).

Exit codes: 0 pass, 1 failure, 77 skipped (CTest SKIP_RETURN_CODE).

Usage:
  python tests/dc_test.py all [--exe build/DemonsCrestSNESRecomp.exe]
  python tests/dc_test.py injector
  python tests/dc_test.py boot --exe ...
  python tests/dc_test.py geometry --exe ...
  python tests/dc_test.py determinism --exe ...
  python tests/dc_test.py staging-band --exe ... --save path.sav
"""

import argparse
import array
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

SKIP = 77
FRAME_HEIGHT = 224
FRAME_WIDTH = 256
MARGIN = 48  # the widened-field margin these tests use (KEEP in step with
             # SNESRECOMP_WS_EXTRA below and the staging model in
             # src/dc_widescreen.c)

CONFIG_TEMPLATE = """\
[General]
Autosave = 0
DisableFrameDelay = 1
SkipLauncher = 0
RunAhead = 0
[Graphics]
WindowSize = Auto
Fullscreen = 0
WindowScale = 3
NewRenderer = 1
IgnoreAspectRatio = 0
NoSpriteLimits = 1
DisplayAspect = 4:3
OutputMethod = SDL-Software
Renderer = software
LinearFiltering = 0
Widescreen = 0
FrameBlend = 0
VSync = 0
[Sound]
EnableAudio = 0
Volume = 0
AudioFreq = 32000
AudioChannels = 2
AudioSamples = 512
"""

# The widescreen feature, enabled exactly as the launcher writes it. The mod
# package itself is the tracked one (mods/preloaded/packages/...).
STATE_ENABLED = """\
format_version = 1

[[package]]
id = "demons-crest.enhancement.widescreen"
version = "1.0.0"

[[feature]]
package_id = "demons-crest.enhancement.widescreen"
id = "widescreen"
enabled = true
"""


class Skip(Exception):
    """A prerequisite is missing: report the test as skipped, not failed."""


class Fail(Exception):
    """The test ran and the invariant does not hold."""


# ───────────────────────────── small helpers ──────────────────────────────

def repo_root():
    return pathlib.Path(__file__).resolve().parents[1]


def find_rom(repo):
    env = os.environ.get("SNESRECOMP_ROM")
    if env and pathlib.Path(env).is_file():
        return pathlib.Path(env)
    # The wizard writes rom.cfg beside the executable; the repo root is where
    # tools/regen.sh looks as a fallback.
    for cfg in (repo / "rom.cfg", repo / "build" / "rom.cfg",
                repo / "build-trace" / "rom.cfg"):
        if not cfg.is_file():
            continue
        line = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
        if line and line[0].strip() and pathlib.Path(line[0].strip()).is_file():
            return pathlib.Path(line[0].strip())
    for name in ("Demon's Crest (USA).sfc", "demonscrest.sfc", "demonscrest.smc"):
        candidate = repo / name
        if candidate.is_file():
            return candidate
    return None


def require_rom(repo):
    rom = find_rom(repo)
    if rom is None:
        raise Skip("no ROM: set SNESRECOMP_ROM or point rom.cfg at your dump")
    return rom


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def run_game(exe, rom, cwd, script, env_extra=None, timeout=300):
    """Run one headless session; returns (returncode, stdout+stderr)."""
    env = dict(os.environ)
    env.update({
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
        "SNESRECOMP_NO_LAUNCHER": "1",
    })
    if env_extra:
        env.update({k: str(v) for k, v in env_extra.items()})
    script_path = cwd / "route.script"
    write_text(script_path, script)
    cmd = [str(exe), "--no-launcher", "--config", str(cwd / "config.ini"),
           "--script", str(script_path), str(rom)]
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), env=env, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        raise Fail("game run timed out after %ss" % timeout)
    out = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise Fail("game exited with %d\n%s" % (proc.returncode, tail(out)))
    return out


def tail(text, lines=25):
    parts = text.strip().splitlines()
    return "\n".join(parts[-lines:])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_bgrx(path):
    """A state-dump framebuffer as a flat uint32 array (BGRA, top-down)."""
    data = path.read_bytes()
    if len(data) % (FRAME_HEIGHT * 4):
        raise Fail("%s is not a %d-line BGRA dump (%d bytes)" %
                   (path.name, FRAME_HEIGHT, len(data)))
    pixels = array.array("I")
    pixels.frombytes(data)
    return pixels, len(data) // (FRAME_HEIGHT * 4)


def changed_columns(a, b, width=None):
    """Columns whose pixels differ between two frames (paths or arrays)."""
    if isinstance(a, (str, pathlib.Path)):
        a, wa = read_bgrx(a)
        b, wb = read_bgrx(b)
        if wa != wb:
            raise Fail("frame widths differ: %d vs %d" % (wa, wb))
        width = wa
    if width is None:
        raise Fail("changed_columns needs a width for raw arrays")
    return [x for x in range(width) if a[x::width] != b[x::width]]


def frame_has_content(path):
    pixels, _ = read_bgrx(path)
    seen = set()
    for i in range(0, len(pixels), 7):  # sample, no need for every pixel
        seen.add(pixels[i])
        if len(seen) > 8:
            return True
    return len(seen) > 1


def prepare_dir(repo, case, widescreen):
    """A self-contained working directory for one headless session.

    Widescreen is driven the way the product drives it: the mod package's
    `state.toml`. The host resolves the catalog (`mods/preloaded`) relative to
    the working directory when `--config` is passed, so staging the tracked
    package beside the case makes the run independent of the build tree and of
    a launcher state left on the machine.
    """
    write_text(case / "config.ini", CONFIG_TEMPLATE.format(widescreen=0))
    (case / "dump").mkdir(exist_ok=True)
    catalog = case / "mods" / "preloaded"
    shutil.copytree(repo / "mods" / "preloaded", catalog,
                    ignore=shutil.ignore_patterns("state.toml"))
    if widescreen:
        write_text(catalog / "state.toml", STATE_ENABLED)



# ───────────────────────────── unit: injector ─────────────────────────────

SYNTH_CULL = """\
#include "funcs.h"
static void fake_cull(void) {{
    uint16 _v1 = 0x60;
    uint16 _v2 = 0x1c0;
    if (_v2 < 0x1c0) goto L_86F0_1;
    uint16 _v3 = 0x60;
    uint16 _v4 = 0x1a0;
    if (_v4 < 0x1a0) goto L_8704_1;
    uint16 _v5 = 0xff00;
    uint16 _v6 = cpu_read_a16(cpu);
    uint16 _v7 = (uint16)(_v6 & _v5);
    cpu_write_a_m(cpu, _v7);
L_E6C4_1:;
}}
"""

SYNTH_EMITTER = """\
#include "funcs.h"
static void fake_emitter(void) {{
    uint16 _v45 = 0xff;
    uint16 _v46 = cpu_read_a16(cpu);
    uint16 _v47 = (uint16)(_v46 & _v45);
    cpu->_flag_Z = ((_v47) == 0) ? 1 : 0;
    cpu->_flag_N = (((_v47) & 0x8000) != 0) ? 1 : 0;
    cpu_write_a_m(cpu, (uint16)(_v47));
    uint16 _v48 = 0xf3;
    if (_v48 < 0xf3) goto L_F788_1;
    goto L_F762_1;
  L_F762_1:;
}}
"""

SYNTH_TRACKER = """\
#include "funcs.h"
RecompReturn bank_00_CF7D_M1X1(CpuState *cpu) {
  extern const char *g_last_recomp_func;
  g_last_recomp_func = "bank_00_CF7D_M1X1";
  RecompStackPush("bank_00_CF7D_M1X1");
  uint8 _v1 = cpu_read8(cpu, 0x00, (uint16)(cpu->D + 0x0010));
  if (cpu->host_return_valid == 1) {
    RecompStackPop();
    return RECOMP_RETURN_NORMAL;
  }
  L_CF7D_M1X1:;
  uint16 _v2 = (uint16)(cpu->D + 0x09ef);
  uint8 _v3 = cpu_read8(cpu, 0x00, _v2);
  goto L_CF89_M1X1;
  L_CF89_M1X1:;
  RecompStackPop();
  return RECOMP_RETURN_NORMAL;
}
"""

INJECTOR_EXPECT = ["--expect", "cull_x=1", "--expect", "cull_y=1",
                   "--expect", "emitter=1", "--expect", "screen=1",
                   "--expect", "stream_ahead=1",
                   "--expect", "prototype_files=3"]

# Which marker each synthetic translation unit has to receive.
INJECTOR_MARKERS = {
    "bank82_fake.c": ("/*DCWS4*/", "/*DCWS5*/"),
    "bank00_fake.c": ("/*DCWS4*/",),
    "bank00_tracker_fake.c": ("/*DCWS6*/",),
}


def test_injector(repo, args):
    injector = repo / "tools" / "dc_apply_widescreen_hooks.py"
    py = sys.executable
    with tempfile.TemporaryDirectory(prefix="dc_injector_") as td:
        tmp = pathlib.Path(td)
        gen = tmp / "gen"
        gen.mkdir()
        write_text(gen / "bank82_fake.c", SYNTH_CULL)
        write_text(gen / "bank00_fake.c", SYNTH_EMITTER)
        write_text(gen / "bank00_tracker_fake.c", SYNTH_TRACKER)
        before = {p.name: p.read_text() for p in gen.glob("*.c")}

        # --check on an unpatched tree must fail (nothing has been injected).
        rc = subprocess.run([py, str(injector), "--gen-dir", str(gen),
                             "--check"] + INJECTOR_EXPECT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if rc.returncode == 0:
            raise Fail("--check passed on an unpatched tree")
        if b"still unpatched" not in rc.stdout:
            raise Fail("--check failed for the wrong reason:\n%s" %
                       tail(rc.stdout.decode("utf-8", "replace")))

        # Inject, then check the tree, then prove idempotency byte-for-byte.
        rc = subprocess.run([py, str(injector), "--gen-dir", str(gen)] +
                            INJECTOR_EXPECT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if rc.returncode != 0:
            raise Fail("injector failed:\n%s" %
                       tail(rc.stdout.decode("utf-8", "replace")))
        patched = {p.name: p.read_text() for p in gen.glob("*.c")}
        for name, markers in INJECTOR_MARKERS.items():
            for marker in markers:
                if marker not in patched[name]:
                    raise Fail("%s did not receive %s" % (name, marker))
        # The tracker hook has to drive the engine's own writer with the same
        # call frame the authentic JSR site uses, or it corrupts the guest.
        tracker = patched["bank00_tracker_fake.c"]
        for needle in ("bank_00_D57F_M1X1(cpu)",
                       "cpu->host_return_valid = 2",
                       "cpu->D + 0x00d0"):
            if needle not in tracker:
                raise Fail("tracker hook lacks %r" % needle)
        rc = subprocess.run([py, str(injector), "--gen-dir", str(gen),
                             "--check"] + INJECTOR_EXPECT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if rc.returncode != 0:
            raise Fail("--check failed after injection:\n%s" %
                       tail(rc.stdout.decode("utf-8", "replace")))
        rc = subprocess.run([py, str(injector), "--gen-dir", str(gen)] +
                            INJECTOR_EXPECT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if rc.returncode != 0:
            raise Fail("second injection failed:\n%s" %
                       tail(rc.stdout.decode("utf-8", "replace")))
        again = {p.name: p.read_text() for p in gen.glob("*.c")}
        for name in patched:
            if patched[name] != again[name]:
                raise Fail("%s changed on the second run (not idempotent)" % name)

        # A vanished hook site must fail loudly: drop the emitter block's limit.
        emitter_text = "\n".join(
            line for line in again["bank00_fake.c"].splitlines()
            if "0x00F3 - DcWsObjectCullMargin" not in line) + "\n"
        write_text(gen / "bank00_fake.c", emitter_text)
        rc = subprocess.run([py, str(injector), "--gen-dir", str(gen),
                             "--check"] + INJECTOR_EXPECT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if rc.returncode == 0:
            raise Fail("a missing emitter site was not detected")
        if b"hook sites are missing" not in rc.stdout:
            raise Fail("wrong failure for the missing site:\n%s" %
                       tail(rc.stdout.decode("utf-8", "replace")))

        # A changed anchor shape must not be silently skipped: restore a clean
        # tree, then rename the cull constant so the anchor no longer matches.
        for name, text in before.items():
            write_text(gen / name, text)
        broken = (gen / "bank82_fake.c").read_text().replace(
            "uint16 _v2 = 0x1c0;", "uint16 _v2 = 0x1c1;")
        write_text(gen / "bank82_fake.c", broken)
        rc = subprocess.run([py, str(injector), "--gen-dir", str(gen)] +
                            INJECTOR_EXPECT,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if rc.returncode == 0:
            raise Fail("a changed cull anchor was accepted")
        if b"hook sites are missing" not in rc.stdout:
            raise Fail("wrong failure for the changed anchor:\n%s" %
                       tail(rc.stdout.decode("utf-8", "replace")))

    return "synthetic anchors: inject (cull/emitter/screen/stream), idempotent " \
           "re-run, missing site and changed anchor both rejected"


def test_injector_check(repo, args):
    gen = repo / "src" / "gen"
    if not gen.is_dir() or not any(gen.glob("bank*.c")):
        raise Skip("src/gen is empty: run tools/regen.sh first")
    injector = repo / "tools" / "dc_apply_widescreen_hooks.py"
    rc = subprocess.run([sys.executable, str(injector), "--check",
                         "--gen-dir", str(gen)],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = rc.stdout.decode("utf-8", "replace")
    if rc.returncode != 0:
        raise Fail("injector --check rejected src/gen:\n%s" % tail(out))
    return tail(out, 1)


# ────────────────────────── integration: the game ─────────────────────────

def test_boot(repo, args):
    rom = require_rom(repo)
    with tempfile.TemporaryDirectory(prefix="dc_boot_") as td:
        tmp = pathlib.Path(td)
        prepare_dir(repo, tmp, widescreen=False)
        out = run_game(args.exe, rom, tmp,
                       "wait 240\ndump boot\nquit\n",
                       env_extra={"SNESRECOMP_DUMP_DIR": str(tmp / "dump")})
        frame = tmp / "dump" / "boot.fb.bgrx"
        if not frame.is_file():
            raise Fail("no frame dump was written\n%s" % tail(out))
        data, width = read_bgrx(frame)
        if width != FRAME_WIDTH:
            raise Fail("4:3 frame is %d wide, expected %d" % (width, FRAME_WIDTH))
        if not frame_has_content(frame):
            raise Fail("boot frame is blank")
        wram = tmp / "dump" / "boot.wram.bin"
        if not wram.is_file() or wram.stat().st_size != 0x20000:
            raise Fail("WRAM dump missing or truncated")
        if b"exit: script quit" not in out.encode():
            raise Fail("the script did not reach its quit command")
        return "boot: 256x224 frame at f240, 128 KiB WRAM, clean quit"


def check_wide_field(repo, args, rom, tmp, reference, extra):
    """Run one widened boot scene and verify P16 + pillarbox for `extra` px.

    `reference` is the 4:3 frame from the same boot point; the center 256
    columns of the wide field must match it byte for byte, and both margins
    must be a flat backdrop because the boot scene is not gameplay (the gate
    pillarboxes it).
    """
    case = tmp / ("wide%d" % extra)
    prepare_dir(repo, case, widescreen=True)
    out = run_game(args.exe, rom, case, "wait 240\ndump f\nquit\n",
                   env_extra={"SNESRECOMP_DUMP_DIR": str(case / "dump"),
                              "SNESRECOMP_DUMP_FULL_FB": "1",
                              "SNESRECOMP_WS_EXTRA": str(extra)})
    on = case / "dump" / "f.fbwide.bgrx"
    if not on.is_file():
        raise Fail("no widened frame for extra=%d "
                   "(SNESRECOMP_DUMP_FULL_FB did not apply)\n%s" %
                   (extra, tail(out)))
    off_data, off_w = read_bgrx(reference)
    on_data, on_w = read_bgrx(on)
    if off_w != FRAME_WIDTH:
        raise Fail("4:3 frame width %d" % off_w)
    if on_w != FRAME_WIDTH + 2 * extra:
        raise Fail("extra=%d: widened frame is %d, expected %d" %
                   (extra, on_w, FRAME_WIDTH + 2 * extra))
    for y in range(FRAME_HEIGHT):
        a = off_data[y * off_w:(y + 1) * off_w]
        b = on_data[y * on_w + extra:y * on_w + extra + FRAME_WIDTH]
        if a != b:
            raise Fail("extra=%d: center row %d differs from the 4:3 frame"
                       % (extra, y))
    for x in list(range(0, extra)) + list(range(FRAME_WIDTH + extra, on_w)):
        if len(set(on_data[x::on_w])) != 1:
            raise Fail("extra=%d: margin column %d is not a flat pillarbox"
                       % (extra, x))
    return "%d->%dx%d" % (extra, on_w, FRAME_HEIGHT)


def wide_field_report(repo, args, extras):
    rom = require_rom(repo)
    with tempfile.TemporaryDirectory(prefix="dc_geo_") as td:
        tmp = pathlib.Path(td)
        off_case = tmp / "off"
        prepare_dir(repo, off_case, widescreen=False)
        out = run_game(args.exe, rom, off_case, "wait 240\ndump f\nquit\n",
                       env_extra={"SNESRECOMP_DUMP_DIR": str(off_case / "dump")})
        reference = off_case / "dump" / "f.fb.bgrx"
        if not reference.is_file():
            raise Fail("no 4:3 reference frame\n%s" % tail(out))
        results = [check_wide_field(repo, args, rom, tmp, reference, extra)
                   for extra in extras]
    return ("wide field, center byte-identical to 4:3, margins pillarboxed "
            "(%s)" % ", ".join(results))


def test_geometry(repo, args):
    """P16 for the reported case: a 48-px margin (Adaptive on a wide window)."""
    return wide_field_report(repo, args, [MARGIN])


def test_aspects(repo, args):
    """The mod's fixed-ratio views: 16:9 (43), 21:9 (96), 32:9 (213)."""
    return wide_field_report(repo, args, [43, 96, 213])


def test_determinism(repo, args):
    rom = require_rom(repo)
    with tempfile.TemporaryDirectory(prefix="dc_det_") as td:
        tmp = pathlib.Path(td)
        hashes = []
        for run in ("a", "b"):
            case = tmp / run
            prepare_dir(repo, case, widescreen=True)
            run_game(args.exe, rom, case,
                     "wait 200\npress right 12\nwait 20\ndump end\nquit\n",
                     env_extra={"SNESRECOMP_DUMP_DIR": str(case / "dump"),
                                "SNESRECOMP_DUMP_FULL_FB": "1",
                                "SNESRECOMP_WS_EXTRA": str(MARGIN)})
            frame = case / "dump" / "end.fbwide.bgrx"
            wram = case / "dump" / "end.wram.bin"
            if not frame.is_file() or not wram.is_file():
                raise Fail("determinism run %s produced no dump" % run)
            hashes.append((sha256(frame), sha256(wram)))
        if hashes[0] != hashes[1]:
            raise Fail("two identical runs differ: %r vs %r" % hashes)
        return "determinism: frame+WRAM SHA-256 identical across two runs"


def eight_periodic(data, width, lo, hi):
    """True when every row repeats with period 8 over [lo, hi).

    The repair continues the last staged 8-px tile over the band, so a repaired
    band is exactly tile-periodic -- a property the stale content does not have.
    """
    for y in range(FRAME_HEIGHT):
        row = data[y * width:(y + 1) * width]
        for x in range(lo, hi - 8):
            if row[x] != row[x + 8]:
                return False
    return True


def test_staging_band(repo, args):
    """The repair replaces exactly the band the engine has not staged.

    The fixture is a save whose right margin holds another room's art (a level
    end is the reliable one: the ring wrapped and the engine stopped restaging).
    The test drives it twice, with SNESRECOMP_WS_EDGE=0 and =1, and asserts the
    repair leaves the native view and the staged margin bit-identical, stays
    inside the margins, and turns the stale band into the tile continuation.
    """
    rom = require_rom(repo)
    save = args.save or os.environ.get("SNESRECOMP_TEST_SAVE")
    if not save:
        raise Skip("no save state: set SNESRECOMP_TEST_SAVE (or --save) to a "
                   ".sav whose right margin shows another room (a level end)")
    save = pathlib.Path(save)
    if not save.is_file():
        raise Skip("save state not found: %s" % save)
    with tempfile.TemporaryDirectory(prefix="dc_band_") as td:
        tmp = pathlib.Path(td)
        cases = {}
        for name, repair in (("off", "0"), ("on", "1"), ("default", None), ("noclamp", "0")):
            case = tmp / name
            prepare_dir(repo, case, widescreen=True)
            (case / "saves").mkdir()
            shutil.copyfile(save, case / "saves" / "save0.sav")
            script = ("loadstate 0\nwait 2\ndump s0\n"
                      "press right 6\ndump s1\nquit\n")
            env = {"SNESRECOMP_DUMP_DIR": str(case / "dump"),
                   "SNESRECOMP_DUMP_FULL_FB": "1",
                   "SNESRECOMP_WS_EXTRA": str(MARGIN)}
            if repair == "0" and name == "noclamp":
                env["SNESRECOMP_WS_EDGE"] = "0"
                env["SNESRECOMP_WS_MARGIN_CLAMP"] = "0"
            elif repair is not None:
                env["SNESRECOMP_WS_EDGE"] = repair
            else:
                env["SNESRECOMP_WS_EDGE"] = ""  # empty == default (off)
            run_game(args.exe, rom, case, script, env_extra=env)
            cases[name] = case
        repaired = 0
        for tag in ("s0", "s1"):
            off_path = cases["off"] / "dump" / (tag + ".fbwide.bgrx")
            on_path = cases["on"] / "dump" / (tag + ".fbwide.bgrx")
            if not off_path.is_file() or not on_path.is_file():
                raise Fail("missing frame %s" % tag)
            off_data, width = read_bgrx(off_path)
            on_data, on_width = read_bgrx(on_path)
            if on_width != width or width != FRAME_WIDTH + 2 * MARGIN:
                raise Fail("%s: unexpected frame widths %d/%d"
                           % (tag, width, on_width))
            changed = changed_columns(off_data, on_data, width)
            native = [x for x in changed
                      if MARGIN <= x < MARGIN + FRAME_WIDTH]
            if native:
                raise Fail("%s: the repair touched the native view at %r"
                           % (tag, native[:8]))
            right_lo = MARGIN + FRAME_WIDTH
            right = [x for x in changed if x >= right_lo]
            if right:
                repaired += 1
                if not eight_periodic(on_data, width, min(right), width):
                    raise Fail("%s: repaired band is not the tile continuation"
                               % tag)
                if eight_periodic(off_data, width, min(right), width):
                    raise Fail("%s: the stale band was already periodic; the "
                               "fixture does not exercise the repair" % tag)
        if not repaired:
            raise Fail("this save's margins are fully staged, so the repair had "
                       "nothing to do; use a save at a level end where the right "
                       "margin shows another room")
        clamped = 0
        for tag in ("s0", "s1"):
            noc_data, noc_w = read_bgrx(cases["noclamp"] / "dump" / (tag + ".fbwide.bgrx"))
            def_data, def_w = read_bgrx(cases["default"] / "dump" / (tag + ".fbwide.bgrx"))
            if noc_w != def_w:
                raise Fail("%s: clamp-off width differs" % tag)
            clamp_changed = changed_columns(noc_data, def_data, def_w)
            if clamp_changed:
                clamped += 1
                # The layer clamp can flip the boundary column itself (the
                # framework's span edge); anything deeper would be a bug.
                native = [x for x in clamp_changed
                          if MARGIN + 1 <= x < MARGIN + FRAME_WIDTH - 1]
                if native:
                    raise Fail("%s: the margin clamp touched the native view at %r"
                               % (tag, native[:8]))
        if not clamped:
            raise Fail("the margin clamp never fired on this save; use a save at a "
                       "level end where the right margin is not staged")

        for tag in ("s0", "s1"):
            off_bytes = (cases["off"] / "dump" / (tag + ".fbwide.bgrx")).read_bytes()
            default_bytes = (cases["default"] / "dump" /
                             (tag + ".fbwide.bgrx")).read_bytes()
            if off_bytes != default_bytes:
                raise Fail("%s: the default frame differs from "
                           "SNESRECOMP_WS_EDGE=0 (the repair is not off by "
                           "default)" % tag)
        return ("edge repair (opt-in): native view + staged margin "
                "bit-identical, %d frame(s) continued as a tile repeat; "
                "default output identical to WS_EDGE=0" % repaired)


# ──────────────────────────────── dispatch ────────────────────────────────

TESTS = {
    "injector": (test_injector, False),
    "injector-check": (test_injector_check, False),
    "boot": (test_boot, True),
    "geometry": (test_geometry, True),
    "aspects": (test_aspects, True),
    "determinism": (test_determinism, True),
    "staging-band": (test_staging_band, True),
}


def default_exe(repo):
    for name in ("build/DemonsCrestSNESRecomp.exe", "build/DemonsCrestSNESRecomp"):
        candidate = repo / name
        if candidate.is_file():
            return candidate
    raise SystemExit("no executable found: pass --exe (build/DemonsCrestSNESRecomp)")


def run_one(name, repo, args):
    fn, needs_exe = TESTS[name]
    if needs_exe and args.exe is None:
        args.exe = default_exe(repo)
    try:
        detail = fn(repo, args)
    except Skip as exc:
        print("SKIP %-14s %s" % (name, exc))
        return SKIP
    except Fail as exc:
        print("FAIL %-14s %s" % (name, exc))
        return 1
    print("ok   %-14s %s" % (name, detail))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("test", choices=list(TESTS) + ["all"])
    ap.add_argument("--repo", default=None,
                    help="project root (default: parent of tests/)")
    ap.add_argument("--exe", default=None,
                    help="game executable (default: build/DemonsCrestSNESRecomp)")
    ap.add_argument("--save", default=None,
                    help="save state for staging-band (or SNESRECOMP_TEST_SAVE)")
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).resolve() if args.repo else repo_root()
    if args.exe:
        args.exe = pathlib.Path(args.exe).resolve()

    names = list(TESTS) if args.test == "all" else [args.test]
    results = {}
    for name in names:
        results[name] = run_one(name, repo, args)

    failed = [n for n, rc in results.items() if rc == 1]
    skipped = [n for n, rc in results.items() if rc == SKIP]
    print("\n%d passed, %d failed, %d skipped" %
          (len(results) - len(failed) - len(skipped), len(failed), len(skipped)))
    if failed:
        print("failed: %s" % ", ".join(failed))
        return 1
    if names != ["all"] and results[names[0]] == SKIP:
        return SKIP
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
