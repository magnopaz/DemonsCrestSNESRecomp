# HANDOFF — widescreen leading-margin staging (room-build lookahead)

Written 2026-11-01 at the end of a long session. Everything below is measured,
not assumed; the two dead ends are recorded so they are not re-explored.

## 1. The bug being fixed

In widescreen, the **leading (right) margin** shows a narrow band that looks
like graphics popping into existence inside the player's view — the illusion of
a continuous world breaks. User recording: `borda_direita.mp4` (16:9, so
`WS_EXTRA = 71`, native view centred at logical x 71..327).

Root cause (measured, see §3): the engine keeps the BG ring coherent for the
authentic 256-px view and refreshes it with a **rolling sweep** that runs only
~14..28 px ahead of the camera. For world that is `256+k` px past the camera the
content was written ~250 px of scroll earlier, so it is normally **correct** —
*except in the first ~250..500 px of scroll after a room is built*, when the
sweep has not reached the margin yet and the margin still holds the previous
page. That transient is the artifact.

So the fix is **not** a lookahead constant in the sweep. It is: at room-build
time, stage the `margin/8` extra columns up front so the margin is valid from
frame 1 of the room.

## 2. Next step (the actual task)

Find the **room-build** routine (not the rolling sweep) and make it stage
`ceil(margin / 8)` extra ring columns on top of what it already stages.

Leads for locating it:
- The sweep routine is `bank_00_CF7D` (`$00:CF7D`, `src/gen/bank00_part09_v2.c`
  line 2834) — this one keeps `$00D0,X` updated, it is **not** the build.
- The room build fills the whole ring in one go; it is therefore a routine that
  writes many map columns per frame (watch for a big VRAM/DMA burst on room
  entry). `ppu_dmas` (debug server, trace build) is the fastest way to see it:
  a 2048-byte page DMA burst plus many 64-byte column DMAs on the same frame.
- Useful trick: start from `lvl_II_ruined-city-dark-avenue_before_door.sav`,
  walk right into the door, and sample `ppu_dmas` + `func_watch_arm` around the
  transition frame.
- The patch must go through `tools/dc_apply_widescreen_hooks.py` (idempotent,
  marker-tagged, counts hook sites, fails on anchor drift), in the same style as
  the existing `cull_x` / `cull_y` / `slack` / `emitter` / `screen` hooks
  (expected counts: cull_x 5, cull_y 5, slack 10, emitter 1, screen 6).

### Acceptance criteria (all must hold before calling it fixed)

1. `python3 tests/dc_test.py all` → 6 passed, 0 failed; and
   `python3 tests/dc_test.py staging-band --save build/saves/lvl_II_ruined-city-dark-avenue_before_door.sav`
   → passed. **This guard is the one that broke both rejected attempts.**
2. Oracle per-k profile for `lvl_VII_phalanxs-fortress-front-hall` (entered
   163 px earlier ⇒ reproduces the bug): `k >= 48` must drop from ~50% mismatch
   toward the ~1..5% of the `k < 48` band.
3. `lvl_VII_phalanxs-fortress-demon-realm` (mid-room control) must stay at
   ~4% or better — it is already correct, so a regression there is a bug.
4. The **native view is bit-identical** to before the change (column diff of the
   widened frame, native x range only). 4:3 (`mod off`) must be unaffected.
5. No new column outside the margins may change.

### What NOT to do (both measured to fail)

- **Do not poke `$00D0`.** It is the streamer's ring cursor, but writing it
  every frame (+6/-6/+12) collapsed the tracker's staged-column count from
  335/398 to 255..287/398: the streamer writes its *next* column and leaves the
  skipped ones holding the previous page.
- **Do not trust the whole ring at cold start.** It fixes `front-hall`
  (51.2% → 23.6% mismatch) but disables the level-end protection that
  `dc.staging_band` exists for; the test fails immediately. The cold-start code
  in `DcEdgeRestart()` carries this note.
- **Do not clamp BG1 across the whole leading margin** (current shipped clip):
  it is measured at 51.2% wrong versus 23.6% with the clip off, because it hides
  *correct* level geometry and reveals the dark parallax layer instead.

## 3. The measured model (do not re-derive)

All numbers from `lvl_VII_phalanxs-fortress-front-hall` / `...-demon-realm` at
`WS_EXTRA = 71`, oracle = "compare each margin column against the same world
once it becomes native", rows 48..224 (HUD excluded):

| band | front-hall (fresh room) | demon-realm (mid-room) |
|---|---|---|
| control (native in both frames = noise floor) | 0.8% | 0.0% |
| trailing (left) margin | **0.0%** | 0.0% |
| leading margin, shipped BG1 clip | 51.2% | 3.4% |
| leading margin, `SNESRECOMP_WS_MARGIN_CLAMP=0` | k<48: 1.1..5.7%, k>=48: ~50% | ~3% |

Engine behaviour, established with per-frame VRAM word diffs while walking:

- The ring is a **64-column (512 px) map**. BG1 map base = word `$4800`
  (`BG1SC $49`), BG2 = word `$4000` (`BG2SC $41`), both 64x32 words.
  (Formula: `base_words = (sc & 0xfc) << 8`, which equals the hardware rule
  `((sc & 0xfc) >> 2) << 10` — the port's `dc_ws_edge.c` uses the first form.)
- The sweep restages **pairs of columns 32 apart** (`P` and `P+32`) with
  `P = (cam>>3) + 4 mod 64`, advancing 2 columns per event, one event per ~16 px
  of scroll.
- A ring column keeps the content it was given for a whole revolution. Verified
  by hashing column 6: written at `cam=22`, displayed unchanged at `cam=36..50`,
  then holds the next revolution's content until `cam=531..545`.
- DMA layout (debug server `ppu_dmas`): whole 2048-byte pages of the BG2 map to
  VRAM words `$4000`/`$4400` every ~6 frames from a rotating window of WRAM
  `$7E:9000..$7E:F000`; single 64-byte BG1 columns to `$49c0`/`$49e0`; 12-byte
  cells elsewhere. All channel 0, line 225 (vblank).
- All VRAM data writes funnel through `$8B4A` (CPU copy loop); the DMA setups go
  through `$8ADD` (`$4305` count and `$2116` VMADD taken from DP `$14`/`$18`).
- Per-layer arrays in the direct page: `$00C0,X` and `$00C4,X` (camera mirrors,
  also mirrored at `$09EF`), `$00DC,X`, `$00D0,X` (ring column cursor, measured
  `(cam>>3)+35 mod 64`).

## 4. Repo state at handoff

Committed by the user: `4dd2b16 fixes on widescreen` (includes the CI build job,
docs, `dc.staging_band`, `DcWidescreenStaleLeftMarginPixels()`), and the
submodule fix `a9d25f4 host: include <errno.h> for RecEnsureDir` is **pushed**
on `demons-crest/host-hooks` (`git -C snesrecomp log`).

Uncommitted work in the tree (leave or commit deliberately, do not revert):

- `docs/PORTING_NOTES.md` — two new bullets: "widescreen margins: measured" and
  "engine streaming: what the RE established" (the corrected model).
- `src/dc_ws_edge.c` — `DcWidescreenStaleLeftMarginPixels()` (measurement only)
  and the cold-start note in `DcEdgeRestart()`.
- `src/dc_widescreen.c` — the "staging frontier is NOT poked from here" note.

Verified green at handoff: build ok, `dc_test.py all` 6 passed / 0 failed,
`staging-band` passed.

## 5. Environment (already set up on this Pi)

```bash
cd ~/Projetos/DemonsCrestSNESRecomp
# normal build (release, SDL2, headless-capable)
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DSNESRECOMP_SDL_BACKEND=SDL2        # already configured; incremental rebuild ~1.5 min
cmake --build build -j4

# trace build WITH the debug server (exists already: build-trace, 132 MB binary)
cmake -S . -B build-trace -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DSNESRECOMP_SDL_BACKEND=SDL2 -DSNESRECOMP_ENABLE_TRACE=ON

# tests
export SNESRECOMP_ROM="$PWD/rom/Demon's Crest (USA).sfc"
python3 tests/dc_test.py all
python3 tests/dc_test.py staging-band --save build/saves/lvl_II_ruined-city-dark-avenue_before_door.sav
```

- ROM: `rom/Demon's Crest (USA).sfc`, sha256 `18d40a807d5f88c5b6a1ad849eec7e0f189225d9a1586037c850f6680b5844de`, 2 MiB.
- `src/gen` is generated (rustup stable 1.99.1 needed for `tools/regen.sh`); 207
  `.sav` fixtures in `build/saves` (298 files including `desc.txt`).
- Host quirks: `sudo` works without password; the `terminal` tool may still ask
  for approval (the user approves when asked — say so explicitly, e.g. avoid
  `pkill`, use a different port instead).

## 6. Dev tools (copied into the repo so scratch pruning cannot lose them)

`tools/dev/` — all take `DC_WORK` (default `~/.hermes/cache/scratch/dcwork`) as
their working dir:

| tool | purpose |
|---|---|
| `probe.py` | run a scene headless: `probe.py run --name X --ws 1 --extra 71 --save <fixture.sav> --script s.txt [--env K=V]`, dumps `.fbwide.bgrx`/`.wram.bin`/`.vram.bin` |
| `oracle.py` | per-margin-pixel ground-truth test (walk, dump per frame, compare margin vs the same world once native) |
| `maporacle.py` | tilemap/CHR-level comparison (BG map entries + tile patterns) |
| `bounds.py` | empirical search for a room-bound variable in WRAM (found none; see below) |
| `watchstack.py` | debug-server client: `func_watch_arm/get` call-stack capture on a running trace build |
| `asmview.py` | turns a slice of generated C back into readable pseudo-65816 (`asmview.py src/gen/bank00_part09_v2.c 2834 3300 --only 00D0,00C0`) |

Debug server (trace build only): `SNESRECOMP_DEBUG_PORT=<port>`, plain-text
line protocol, JSON replies. Useful commands: `ping`, `ppu_dmas count=N`,
`ppu_frames`, `func_watch_arm <name>`, `func_watch_get`, `dispatch_log_get`,
`trace_dump N`, `read_ram <addr> <len>`, `run_to_frame`, `savestate`/`loadstate`.
Input still has to come from `--script`; there is no input command.

## 7. Traps that cost hours

- **Pixel stride**: `.bgrx` dumps are 4 bytes per pixel. A column is
  `buf[x*4::W*4]`; `buf[x::W]` walks bytes and invents thousands of differences.
- **BG base formula**: `(sc & 0xfc) << 8` gives *word* addresses (`$4800` for
  `BG1SC $49`, `$4000` for `BG2SC $41`). Using `$2400` (bytes/2) finds no
  changes and makes it look like nothing is staged.
- **Comparison confounders**: comparing the same world across camera positions
  also compares sprites and the parallax BG2, so an unclean control band hides
  the signal. Always report a control band (world native in both frames) next to
  the margin band; the control sits at 0.8%.
- **Save-state loads are not gameplay**: a loaded state has no room build, so
  the ring is whatever the capture had. `front-hall` reproduces the bug from a
  state load; `demon-realm` does not. Do not generalise from one fixture.
- **Bilinear search failures**: the room clamps its camera (front-hall: 163,
  dark-avenue: 371, demon-realm: 1470), so the oracle needs any delta `d` with
  `extra+8 <= d <= 256`, not an exact 256.
- **Room-bound variable does not exist in WRAM**: three rooms walked to their
  clamp, `0x2000` addresses scanned — only the camera mirror (`$00C0`, `$00A2`,
  `$09EF`) and ring-size constants (`$158C`/`$15DC`, 512/2048) matched. The
  bound is computed (probably from the room header each frame). Do not spend
  time on that route again.
- The mod manifest claims margin columns "continue the last staged tile", which
  describes `DcWidescreenRepairField()` — **off by default**. Keep text and
  behaviour in sync when touching either.

## 8. Kill switches for A/B (no code edits)

`SNESRECOMP_WS_EXTRA=<px>`, `SNESRECOMP_WS_MARGIN_CLAMP=0`, `SNESRECOMP_WS_EDGE=0/1`,
`SNESRECOMP_WS_EDGE_DEBUG=1` (per-frame tracker line on stderr: `cam`, `known`,
`first_bad`, `first_bad_bg1`, `first_known_left`), `SNESRECOMP_WS_HUD`,
`SNESRECOMP_WS_OAM`, `SNESRECOMP_WS_NOBLANK`, `SNESRECOMP_WS_HISTORY`,
`SNESRECOMP_DUMP_DIR`, `SNESRECOMP_DUMP_FULL_FB=1`, `SNESREC_AUTORECORD=1`.

## 9. Open question worth answering first in the new session

Does the ring refresh sweep actually stop during the first frames of a room, or
does it run but target the native view only? Answer it by sampling `ppu_dmas`
(64-byte BG1 column DMAs) on the frames immediately after a door transition in
the trace build. If the sweep does run, the fix may be as small as shifting its
start column by `margin/8`; if it does not run, the fix belongs in the build
routine. That single measurement decides where the hook goes.
