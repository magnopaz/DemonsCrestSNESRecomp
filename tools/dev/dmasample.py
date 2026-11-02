#!/usr/bin/env python3
"""Sample the always-on PPU DMA ring + per-frame WRAM history from the debug server.

Why: `ppu_dmas` and the frame-history ring are always-on, and `pause` is
disabled by policy. So the only way to get a per-frame timeline is to poll the
rings while the run is live:

- DMA events are de-duplicated by global ring index: the reply's `total` is the
  ring write index, so the k-th newest event is global index `total-1-k`.
- The WRAM series (`wram_timeseries`, backed by the 6000-frame history ring that
  `debug_server_record_frame()` fills every frame) must be pulled *before* the
  process exits, so the poller re-reads it periodically and merges by frame.

The route script therefore must NOT `quit`; the tool stops the run itself once
the newest sampled frame passes `--frames`.

Usage:
  dmasample.py --name stream --save lvl_II_ruined-city-dark-avenue_before_door.sav \
               --script walk.script --frames 1500 [--port 4477] [--env K=V]
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

# Per-frame WRAM series worth correlating against the DMA timeline.
SERIES = [
    (0x008D, 1, "gamemode"),
    (0x00A2, 4, "camera_a2"),
    (0x00C0, 8, "camera_c0"),
    (0x00D0, 8, "ringcursor_d0"),
    (0x00DC, 8, "dc_dc"),
    (0x09EF, 8, "camera_9ef"),
    (0x158C, 4, "ringsize_158c"),
]


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


def prepare(case, save, script):
    if case.exists():
        shutil.rmtree(case)
    (case / "dump").mkdir(parents=True)
    (case / "saves").mkdir()
    (case / "mods" / "preloaded").mkdir(parents=True)
    shutil.copytree(REPO / "mods" / "preloaded", case / "mods" / "preloaded",
                    ignore=shutil.ignore_patterns("state.toml"), dirs_exist_ok=True)
    (case / "config.ini").write_text(CONFIG, newline="\n")
    if save:
        shutil.copy(SAVES / save, case / "saves" / "save0.sav")
    text = script
    if pathlib.Path(script).is_file():
        text = pathlib.Path(script).read_text()
    (case / "route.script").write_text(text, newline="\n")


def pull_series(client, series):
    """Merge one round of wram_timeseries into `series` (dedupe by frame)."""
    for addr, ln, tag in SERIES:
        try:
            r = client.cmd("wram_timeseries %x %d" % (addr, ln))
        except (EOFError, OSError):
            return False
        if not r.get("ok"):
            continue
        bucket = series.setdefault(tag, {})
        for e in r.get("entries") or []:
            bucket[e["f"]] = e["hex"]
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--save", default=None)
    ap.add_argument("--script", required=True)
    ap.add_argument("--frames", type=int, required=True,
                    help="stop once the newest sampled frame number passes this")
    ap.add_argument("--port", type=int, default=4477)
    ap.add_argument("--env", action="append", default=[])
    a = ap.parse_args()

    case = WORK / a.name
    prepare(case, a.save, a.script)

    env = dict(os.environ)
    env.update({
        "SDL_VIDEODRIVER": "dummy",
        "SDL_AUDIODRIVER": "dummy",
        "SNESRECOMP_NO_LAUNCHER": "1",
        "SNESRECOMP_DEBUG_PORT": str(a.port),
        "SNESRECOMP_DUMP_DIR": str(case / "dump"),
    })
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
            print("process exited early; see run.log", file=sys.stderr)
            break
        try:
            client = Client(a.port)
            break
        except OSError:
            time.sleep(0.5)
    if client is None:
        print(open(case / "run.log", "rb").read().decode("utf-8", "replace")[-3000:])
        sys.exit(1)
    print("ping:", client.cmd("ping"), flush=True)

    events, series = {}, {}
    high, polls, lost = -1, 0, 0
    last_frame = 0
    base_frame = None      # first frame seen; the state load rewinds the counter
    t0 = time.time()
    while proc.poll() is None and (
            base_frame is None or last_frame < base_frame + a.frames):
        try:
            r = client.cmd("ppu_dmas count=1024")
        except (EOFError, OSError):
            break
        polls += 1
        total, dmas = r.get("total"), r.get("dmas") or []
        if total and dmas:
            newest = total - 1
            if high >= 0 and newest - high > len(dmas):
                lost += 1
            for k, d in enumerate(dmas):
                idx = total - 1 - k
                if idx > high:
                    events[idx] = d
            if newest > high:
                high = newest
            last_frame = max(last_frame, max(d["frame"] for d in dmas))
            if base_frame is None:
                base_frame = min(d["frame"] for d in dmas)
        if polls % 20 == 0:
            pull_series(client, series)
            print("  f=%d polls=%d events=%d (%.0fs)" %
                  (last_frame, polls, len(events), time.time() - t0), flush=True)

    pull_series(client, series)          # final pull, still alive
    for addr, ln, tag in SERIES:         # cheaper authoritative pass on one addr
        pass
    try:
        series["_ppu_frames_last"] = client.cmd("ppu_frames count=1")
    except (EOFError, OSError):
        pass

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()

    ordered = [events[i] for i in sorted(events)]
    out = case / "dmas.json"
    out.write_text(json.dumps(ordered, indent=0))
    (case / "wram.json").write_text(json.dumps(series))
    print("wrote %s (%d events, frames %s..%s) and wram.json (%d series, %d frames)"
          % (out, len(ordered),
             ordered[0]["frame"] if ordered else "-",
             ordered[-1]["frame"] if ordered else "-",
             len(series), max((len(v) for k, v in series.items()
                               if not k.startswith("_")), default=0)))
    print("lost-windows:", lost)


if __name__ == "__main__":
    main()
