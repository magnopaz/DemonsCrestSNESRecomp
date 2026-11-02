#!/usr/bin/env python3
"""Probe harness for Demon's Crest Recompiled: run scenes, dump frames, convert to PNG.

Usage examples
  probe.py run --name base --ws 0 --script script.txt
  probe.py run --name ws48 --ws 1 --extra 48 --save widescreenproblem.sav --script script.txt
  probe.py png dump/base/boot.fb.bgrx        # -> boot.png
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
EXE = REPO / "build" / "DemonsCrestSNESRecomp"
ROM = REPO / "rom" / "Demon's Crest (USA).sfc"
SAVES = REPO / "build" / "saves"
WORK = pathlib.Path(os.environ.get("DC_WORK", "~/.hermes/cache/scratch/dcwork")).expanduser()

CONFIG = """[General]
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

STATE_ENABLED = """format_version = 1

[[package]]
id = "demons-crest.enhancement.widescreen"
version = "1.0.0"

[[feature]]
package_id = "demons-crest.enhancement.widescreen"
id = "widescreen"
enabled = true
"""


def prepare(case, ws, aspect="Adaptive"):
    if case.exists():
        shutil.rmtree(case)
    case.mkdir(parents=True)
    (case / "config.ini").write_text(CONFIG, newline="\n")
    (case / "dump").mkdir()
    catalog = case / "mods" / "preloaded"
    shutil.copytree(REPO / "mods" / "preloaded", catalog,
                    ignore=shutil.ignore_patterns("state.toml"))
    if ws:
        txt = STATE_ENABLED
        if aspect != "Adaptive":
            txt += '[feature.values]\naspect = "%s"\n' % aspect
        (catalog / "state.toml").write_text(txt, newline="\n")


def run(args):
    case = WORK / args.name
    prepare(case, args.ws, args.aspect)
    if args.save:
        (case / "saves").mkdir(exist_ok=True)
        shutil.copy(SAVES / args.save, case / "saves" / "save0.sav")
    script = args.script
    if script and pathlib.Path(script).is_file():
        script = pathlib.Path(script).read_text()
    (case / "route.script").write_text(script, newline="\n")
    env = dict(os.environ)
    env.update({
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
        "SNESRECOMP_NO_LAUNCHER": "1",
        "SNESRECOMP_DUMP_DIR": str(case / "dump"),
    })
    if args.ws:
        env["SNESRECOMP_DUMP_FULL_FB"] = "1"
        if args.extra is not None:
            env["SNESRECOMP_WS_EXTRA"] = str(args.extra)
    for kv in args.env or []:
        k, _, v = kv.partition("=")
        env[k] = v
    cmd = [str(EXE), "--no-launcher", "--config", str(case / "config.ini"),
           "--script", str(case / "route.script"), str(ROM)]
    print("+", " ".join(cmd), file=sys.stderr)
    proc = subprocess.run(cmd, cwd=str(case), env=env, timeout=args.timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode("utf-8", "replace")
    print(out[-4000:])
    print("exit", proc.returncode)
    print("dumps:", sorted(p.name for p in (case / "dump").glob("*")))


def tobgra(path):
    """Read a BGRX dump; return (bytes of RGBA, width, height)."""
    data = pathlib.Path(path).read_bytes()
    h = 224
    width = len(data) // (h * 4)
    out = bytearray(len(data))
    for i in range(0, len(data), 4):
        out[i + 0] = data[i + 2]  # R
        out[i + 1] = data[i + 1]  # G
        out[i + 2] = data[i + 0]  # B
        out[i + 3] = 255
    return bytes(out), width, h


def png(args):
    from PIL import Image
    src = pathlib.Path(args.path)
    rgba, w, h = tobgra(src)
    img = Image.frombytes("RGBA", (w, h), rgba).convert("RGB")
    scale = args.scale
    if scale != 1:
        img = img.resize((w * scale, h * scale), Image.NEAREST)
    dst = src.with_suffix(".png")
    if args.out:
        dst = pathlib.Path(args.out)
    img.save(dst)
    print(dst, img.size)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--name", required=True)
    r.add_argument("--ws", type=int, default=0)
    r.add_argument("--extra", type=int, default=None)
    r.add_argument("--aspect", default="Adaptive")
    r.add_argument("--save", default=None)
    r.add_argument("--script", required=True)
    r.add_argument("--env", action="append")
    r.add_argument("--timeout", type=int, default=900)
    r.set_defaults(func=run)

    p = sub.add_parser("png")
    p.add_argument("path")
    p.add_argument("--scale", type=int, default=1)
    p.add_argument("--out", default=None)
    p.set_defaults(func=png)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
