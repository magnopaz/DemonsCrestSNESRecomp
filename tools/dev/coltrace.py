#!/usr/bin/env python3
"""Trace VRAM byte writes into a chosen range, live, from the debug server.

`trace_vram <lo> <hi>` (BYTE addresses) arms an always-on recomp-side VRAM write
ring that records (frame, adr_byte, val, registers, func, stack).  This tool
arms it, polls `get_vram_trace` while the run is live (keeping a cursor into the
ring so nothing is pulled twice), and writes the rows to
`$DC_WORK/<name>/vram_trace.jsonl`.

Use it to answer "who writes the BG tilemap, and on which frames" without
touching the port: BG1 map bytes = ((bg1sc & 0xfc) << 9), BG2 = ((bg2sc & 0xfc)
<< 9); a 64x32 map is 0x1000 bytes, a 32x32 one 0x800.

Usage:
  coltrace.py --name trans --save <fixture>.sav --script walk.script \\
              --lo 9000 --hi 9fff --frames 700 [--ws] [--extra 71] [--stacks]
"""
import argparse
import json
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[2]
EXE = REPO / "build-trace" / "DemonsCrestSNESRecomp"
ROM = REPO / "rom" / "Demon's Crest (USA).sfc"
SAVES = REPO / "build" / "saves"
WORK = pathlib.Path(os.environ.get("DC_WORK", "~/.hermes/cache/scratch/dcwork")).expanduser()

CONFIG = """[General]
Autosave = 0
DisableFrameDelay = 0
SkipLauncher = 0
RunAhead = 0
[Graphics]
WindowSize = Auto
Fullscreen = 0
WindowScale = 1
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


class Client:
    def __init__(self, port, timeout=20.0):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        self.buf = b""

    def cmd(self, line):
        self.sock.sendall((line + "\n").encode())
        return self.recv_json()

    def recv_json(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise EOFError("server closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        try:
            return json.loads(line.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            return {"raw": line.decode("utf-8", "replace")[:200]}


def prepare(case, save, script, ws):
    if case.exists():
        shutil.rmtree(case)
    (case / "dump").mkdir(parents=True)
    (case / "saves").mkdir()
    catalog = case / "mods" / "preloaded"
    shutil.copytree(REPO / "mods" / "preloaded", catalog,
                    ignore=shutil.ignore_patterns("state.toml"))
    if ws:
        (catalog / "state.toml").write_text(STATE_ENABLED, newline="\n")
    (case / "config.ini").write_text(CONFIG, newline="\n")
    if save:
        shutil.copy(SAVES / save, case / "saves" / "save0.sav")
    text = script
    if pathlib.Path(script).is_file():
        text = pathlib.Path(script).read_text()
    (case / "route.script").write_text(text, newline="\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--save", default=None)
    ap.add_argument("--script", required=True)
    ap.add_argument("--lo", required=True, help="byte address, hex")
    ap.add_argument("--hi", required=True, help="byte address, hex")
    ap.add_argument("--frames", type=int, required=True)
    ap.add_argument("--port", type=int, default=4477)
    ap.add_argument("--ws", action="store_true")
    ap.add_argument("--extra", type=int, default=71)
    ap.add_argument("--stacks", action="store_true")
    ap.add_argument("--cam", action="store_true",
                    help="also sample frame + WRAM $C0/$D0 per poll into cam.jsonl")
    ap.add_argument("--env", action="append", default=[])
    a = ap.parse_args()

    case = WORK / a.name
    prepare(case, a.save, a.script, a.ws)

    env = dict(os.environ)
    env.update({
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
        "SNESRECOMP_NO_LAUNCHER": "1",
        "SNESRECOMP_DEBUG_PORT": str(a.port),
        "SNESRECOMP_DUMP_DIR": str(case / "dump"),
    })
    if a.ws:
        env["SNESRECOMP_WS_EXTRA"] = str(a.extra)
    for kv in a.env:
        k, _, v = kv.partition("=")
        env[k] = v

    log = open(case / "run.log", "wb")
    proc = subprocess.Popen(
        [str(EXE), "--no-launcher", "--config", str(case / "config.ini"),
         "--script", str(case / "route.script"), str(ROM)],
        cwd=str(case), env=env, stdout=log, stderr=subprocess.STDOUT)

    client = None
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            client = Client(a.port)
            break
        except OSError:
            time.sleep(0.3)
    if client is None:
        print(open(case / "run.log", "rb").read().decode("utf-8", "replace")[-3000:])
        sys.exit(1)
    print("ping:", client.cmd("ping"), flush=True)
    print("arm:", client.cmd("trace_vram %s %s" % (a.lo, a.hi)), flush=True)

    out = open(case / "vram_trace.jsonl", "w")
    cams = open(case / "cam.jsonl", "w") if a.cam else None
    cursor, rows = 0, 0
    base_frame, last_frame = None, 0
    polls = 0
    t0 = time.time()
    while proc.poll() is None and (base_frame is None or last_frame < base_frame + a.frames):
        try:
            r = client.cmd("get_vram_trace idx_from=%d%s" % (cursor, "" if a.stacks else " nostack"))
        except (EOFError, OSError):
            break
        polls += 1
        if r.get("error"):
            print("trace error:", r, flush=True)
            break
        got = r.get("log") or []
        for e in got:
            out.write(json.dumps(e) + "\n")
            f = e.get("f", 0)
            if base_frame is None:
                base_frame = f
            last_frame = max(last_frame, f)
        cursor += len(got)
        rows += len(got)
        if cams is not None:
            try:
                fr = client.cmd("frame")
                rw = client.cmd("read_ram c0 32")
                cams.write(json.dumps({"f": fr.get("frame"), "hex": rw.get("hex")}) + "\n")
            except (EOFError, OSError):
                break
        if polls % 25 == 0:
            print("  f=%d rows=%d cursor=%d (%.0fs)" % (last_frame, rows, cursor, time.time() - t0),
                  flush=True)
        else:
            time.sleep(0.01)
    out.close()

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()

    print("wrote %s: %d rows, frames %s..%s" %
          (case / "vram_trace.jsonl", rows, base_frame, last_frame))


if __name__ == "__main__":
    main()
