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

**Reap your runs.** `probe.py`/`coltrace.py`/`oracle.py` SIGTERM the headless
game when the script ends, but a run whose Python parent is killed (Ctrl-C, a
tool timeout, a dropped debug-server connection) leaves the game spinning at
~96% CPU forever: one was found after 9 h, eating a quarter of this Pi and
making every rebuild look mysteriously slow. Before a long build, check
`ps -eo pid,etime,pcpu,args | grep '[D]emonsCrestSNESRecomp'` and kill anything
older than the current command.

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

## 10. ANSWERED (2026-11-01, later session) — the plan in §2 is aimed at the wrong place

Measured with a new tool, `tools/dev/coltrace.py`, which arms the recomp-side
VRAM write trace (`trace_vram <lo> <hi>`, BYTE addresses) and pulls
`get_vram_trace` live while the scripted run walks. BG1 map for the measured
rooms is `BG1SC $49` ⇒ bytes `0x9000..0x9fff` (block 0 = ring columns 0..31,
block 1 = columns 32..63).

**What the engine actually does (both measured, frame-exact):**

1. **A genuine door transition rewrites the ENTIRE ring in one frame.** Room
   build, `dark-avenue_before_door` → next room, frame 494319: **4096 bytes,
   one contiguous run, `0x9000-0x9fff`** = all 64 columns × 32 rows. Then 4
   frames of 512 bytes (the entry view), then the screen blanks and the new
   room appears. So the build already stages every column; "stage `margin/8`
   extra columns at build time" would write nothing.
2. **The rolling sweep is purely camera-driven and writes 2 adjacent columns
   per event, 16 px behind the camera's own progress.** `front-hall` (state
   load, walking right, 2 px/frame), BG1 map writes only, with the camera
   sampled per frame:

   | frame | bytes | ring columns | camera | cam>>3 |
   |---|---|---|---|---|
   | 21065 | 128 | 38, 39 | 19 | 2 |
   | 21076 | 128 | 40, 41 | 32 | 4 |
   | 21088 | 128 | 42, 43 | 51 | 6 |
   | 21099 | 128 | 44, 45 | 62 | 7 |
   | 21111 | 128 | 46, 47 | 82 | 10 |

   So **written pair start column = (cam>>3) + 36**, i.e. the write covers
   world `cam+285 .. cam+300` — a fixed frontier **29..44 px past the native
   edge**, and it fires only when the camera has moved 16 px. While the camera
   is stationary there are **zero** map writes (dark-avenue: nothing between
   frame 494360 and 494663, then one event per ~11 frames once the press
   resumes).
3. All map writes carry the same attribution, `bank_00_8543_M1X1` (the DMA is
   set up there; the trace's `func` is the last dispatched recomp function).

**Consequence — the real model, replacing §1/§3's "transient after a build":**

Column `c` holds the content for world `w` from the moment the frontier writes
it until the camera has advanced 512 px (one revolution). The frontier writes
`w` when `cam = w-288`. The margin pixel at offset `k` displays
`w = cam+256+k` and needs it written at `cam' = cam+k-32`. That is in the past
only while **k ≤ 32**. For `k > 32` the ring still holds the *previous
revolution's* world, so the far 39 px of a 71-px margin are permanently one page
stale — not a ramp-up that clears after 250..500 px of scroll. It also explains
the one measurement that looked like a build problem: **right after a build the
whole ring holds the new room's content for world 0..511**, which is correct in
the margin until `cam+327 > 511`, i.e. until `cam ≈ 184`. `front-hall` clamps its
camera at 163, so a measurement taken there from a state load is dominated by
the stale band, while `demon-realm` (clamp 1470) is not — that is the whole
`front-hall` vs `demon-realm` split in §3, and it is not about a build transient.

Re-measured `front-hall` (state load, `SNESRECOMP_WS_MARGIN_CLAMP=0`, oracle
`k` profile, 176 rows): k 0-7 1.1%, k 8-15 2.2%, k 16-23 5.7%, k 24-31 15.4%,
k 32-39 20.0%, k 40-47 11.2%, **k 48-55 50.3%, k 56-63 58.7%, k 64-70 50.8%** —
reproduces §3's 51.2% exactly, and the per-camera breakdown shows the bad band
moving with the camera rather than clearing as the player walks.

**The stale band is permanent, not a load artifact — measured content-free.**
The pixel oracle cannot settle this (sprites, the BG2 parallax and the fade all
move the number, and a uniform far margin silently "passes"). The decisive test
is column bookkeeping: for each map write take the camera at that frame, derive
which world the written column serves, and then ask, for every margin pixel of
every later frame, whether the column holding that world was last written for
*that* world or for the previous revolution. On `demon-realm` (wide room, camera
15 -> 594, mid-room) that gives:

| k | staged | | k | staged |
|---|---|---|---|---|
| 0..45 | **100%** | | 50 | 14% |
| 46 | 93% | | 51..70 | **0%** |

So the leading margin is stage-fresh only for the first ~46 px, at every camera
position, in every room. `demon-realm`'s pixel profile looks clean at all k
(k 48-71 ~= 2.7-3.7%) purely because its far margin is uniform there — a
false negative worth remembering before trusting a pixel oracle on a dark room.

**Therefore the lever is the streaming lookahead, not the build — and it has
to be paid somewhere the generator lets us touch.**

The room-load restream is `$00:C840` (`StreamRestream` in `recomp/symbols.toml`;
entered by `jsl` from the room loader, so it is an LLE entry). Disassembled:

```
C840  ldx $10                ; layer 0
C846  lda $D0,X / dec x4 / and #$3F / sta $D0,X     ; cursor -= 4 columns
C858  lda #$14 / sta $14     ; budget = 20  (dec/bpl -> 21 iterations)
C860  jsr $D57F              ; stage the 2 columns at $D0 (the map writer)
C86B  lda $D0,X / inc / inc / and #$3F / sta $D0,X  ; cursor += 2
C87B  ... and #$03 : every 4th column jsl $80821E (TaskYield) + stz $8A/$8B
C889  dec $14 / bpl $C860
```

21 iterations x 2 columns = 42 columns = 336 px starting 4 columns behind the
cursor, so the frontier lands at camera+304 — 48 px past the authentic view.
The per-frame tracker `$00:CF7D` then only maintains that phase (+2 columns per
16 px of scroll), so **one wider catch-up per room load moves the frontier
permanently**.

Widening `$14` itself is not reachable: the routine yields to the scheduler
in-line (`jsl $80821E`), and the analyzer refuses to emit `$00:C840` in ANY M/X
variant — `dispatch_v2.c` shows `{ 0x00C840u, { NULL, NULL, NULL, NULL }, 0 }`
for all four, i.e. LLE-only, and there is no `force_aot` directive to override
it. So the debt is paid from an AOT function that drives the same writer:

- `src/dc_widescreen.c` — `DcWsStreamAheadColumns()` = `ceil((margin - 48)/8)`
  rounded up to a whole writer call (4 columns for margin 71, 0 for margin <=
  48, so 4:3 and 3:2 stay bit-identical), plus the debt state:
  `DcWsStreamCatchUpArm()` (armed by the staged-window tracker when it sees a
  restream), `DcWsStreamCatchUpTick()` (7-frame delay so the engine's own burst
  is finished), `DcWsStreamCatchUpTake(layer)` (guest-side hook, layer 0 only).
- `tools/dc_apply_widescreen_hooks.py` — new `/*DCWS6*/` hook: a preamble at the
  entry of `bank_00_CF7D_M1X1` (the AOT tracker) that, while the debt is
  non-zero, calls `bank_00_D57F_M1X1` (the engine's own map writer) and then
  advances the ring cursor exactly like the restream loop ($D0 += 2 mod 64,
  $D8++ on wrap). The call frame mirrors the authentic JSR site at `$00:CFCF`
  (Option-1 `cpu->S` frame + `host_return_valid = 2`) and propagates a
  non-local return the same way; `CpuState` is saved/restored around it so the
  tracker's entry state is untouched.
- Kill switch: `SNESRECOMP_WS_STREAM_AHEAD=<columns>` forces the catch-up size
  for A/B captures; `0` disables it.

Ring budget with `margin` 71: `71 (left) + 256 (native) + 71 + 32 (extra
lookahead) = 430 px` < 512, so it fits without eating the trailing margin.

### New tools from this session (in `tools/dev/`)

| tool | purpose |
|---|---|
| `dmasample.py` | live poller for the always-on `ppu_dmas` ring; de-dupes by global ring index (`total-1-k`), pulls `wram_timeseries` while alive, writes `dmas.json`/`wram.json` |
| `coltrace.py` | arms `trace_vram <lo> <hi>` and pulls `get_vram_trace` by cursor; `--cam` also samples `frame` + WRAM `$C0` so every map write gets a camera; writes `vram_trace.jsonl`/`cam.jsonl` |

`oracle.py` gained `--pre "<lines>"` so the measured walk can happen *after* a
door transition (lines are inserted between `loadstate 0` and the walk). Note
`oracle.py` must be run with its CWD set to `$DC_WORK` (its `--case` is relative
to the CWD while `probe.py` resolves the case under `$DC_WORK`).

### Traps added

- `trace_vram` replies with **every armed range**, and the debug server already
  arms one at startup (`nranges: 2` after one `trace_vram`) — always filter the
  rows to your own `lo..hi` or the map analysis is 97% boot-time noise.
- Prefer **map/column** evidence over framebuffer pixels for staging questions:
  the pixel oracle mixes in sprites, BG2 parallax and the fade, and a pair whose
  first frame is still fading reads as ~100% mismatch anywhere.
- A door transition can be detected without any input plumbing: watch the BG1
  map for a single-frame 4096-byte contiguous write.
- A room that clamps its camera short (`dark-avenue`'s next room clamps at 88,
  `front-hall` at 163) cannot be used for margin work near its right edge — past
  the clamp the margin samples world that does not exist, which reads as 100%
  mismatch for a reason that has nothing to do with staging.

### Implemented and measured (2026-11-02)

The fix is in and it works. What it does:

- `src/dc_widescreen.c` — `DcWsStreamAheadColumns()` = `ceil((margin - 48) / 8)`
  rounded up to a whole writer call (4 columns for margin 71, 0 for margin
  <= 48, so 4:3 and 3:2 stay bit-identical), `DcWsStreamAheadIters()` in writer
  calls, and the debt state polled per frame by `DcWsStreamCatchUpTick()` and
  spent by `DcWsStreamCatchUpTake(layer)`.
- `tools/dc_apply_widescreen_hooks.py` — the `/*DCWS6*/` hook: a preamble at the
  entry of `bank_00_CF7D_M1X1` (the AOT per-frame tracker) that, while the debt
  is non-zero, calls `bank_00_D57F_M1X1` (the engine's own map writer) and then
  advances the ring cursor exactly like the restream loop ($D0 += 2 mod 64,
  $D8++ on wrap). The call frame mirrors the authentic JSR site at `$00:CFCF`
  (Option-1 `cpu->S` frame + `host_return_valid = 2`) and propagates a
  non-local return the same way; `CpuState` is saved/restored around it.
- The restream itself stays LLE (`recomp/symbols.toml`: `emit = false`,
  `force_lle 00c840`): it yields in-line and the analyzer refuses to emit it in
  any M/X variant, so its budget at `$00:C858` is unreachable.

**Arming rule — this is the part that took the longest, and getting it wrong
makes the picture worse than the bug.** The debt is armed by watching the ring
cursor's *burst*, never by "the scene changed":

| candidate trigger | why it is wrong |
|---|---|
| map base change / camera jump (`dc_ws_edge.c` restart) | those do not rebuild the map; the 4 columns get written from whatever source phase is live, for the wrong world — measured: `front-hall` pixel mismatch went from 8% to 80% in k 24-47 |
| state load | same failure, and worse: the source phase is the savestate's |
| the `-4` rewind alone | the restream rewinds and writes its first columns in the *same* frame, so the observed delta is 0 |

The signature that does identify it: the restream pushes **4+ columns per frame
for several consecutive frames**, where the steady-state tracker only ever
advances 0 or 2 (2 per 16 px of scroll). Measured in dark-avenue, door
transition at frame ~494416: cursor 62 → 6 → 14 → 22 → 30 → 36 (delta 8-16 per
frame), then it parks at 36. So: two consecutive burst frames arm the debt, and
the advance our own catch-up causes is subtracted so it cannot re-arm itself.

**Results** (`demon-realm` state load + walk; `dark-avenue_before_door` walking
through the door; same script and ROM in each A/B):

| room / trigger | control (`SNESRECOMP_WS_STREAM_AHEAD=0`) | fix (4 columns) |
|---|---|---|
| demon-realm (load-time restream) | writes at `cam_col+36` → frontier **288 px** (ends 304) | `cam_col+40` → **320 px** (ends 336) |
| dark-avenue (door transition) | `cam_col+36` → **288 px** | `cam_col+40` → **320 px** |
| dark-avenue (state load only) | `cam_col+36` | `cam_col+36` — **no catch-up, by design** |

The margin needs world `cam+256..cam+327`; 336 covers it, 304 leaves the outer
23 px permanently one ring revolution behind.

**Content proof.** The columns the catch-up writes early are byte-identical to
what the engine writes into those same columns later: 32/32 rows for columns
38 and 39 in dark-avenue (varied tile content — a uniform wall like demon-realm
proves nothing), and 32/32 in demon-realm. `tools/dev/colcontent.py` also
confirms every column in a room carries exactly one content, i.e. no write from
a foreign source phase.

`tools/dev/frontier.py` reports the frontier from a `coltrace.py --cam` capture
(per write frame: distance between the written column and the camera column).

**Traps found on the way, both cost a rebuild each:**

- `$10` is *not* a stable channel index. It holds the layer index only inside
  the routines that load it; at frame boundaries it is whatever the last caller
  left (measured across one room: 2, 0, 11, 224). Reading `g_ram[0xD0+g_ram[0x10]]`
  from the host therefore reads garbage — read `g_ram[0xD0]` (or `$D2`; both are
  ring cursors for different layers, they run the same burst a few frames apart
  and both park at 36 after a build).
- `DcWsStreamAheadColumns()` must use the **rendered** margin
  (`DcDisplay_FrameWidth()`), not `DcWsLiveMargin()`: during a door transition
  the scene policy has BG1 clamped, so the live margin is 0 on exactly the
  frames whose burst identifies the restream (`iters=0` in the debug trace, and
  the debt was silently computed as zero).
- Kill switches: `SNESRECOMP_WS_STREAM_AHEAD=<columns>` forces the size (0
  disables), `SNESRECOMP_WS_STREAM_DEBUG=1` prints `cur/delta/run/owed/iters`
  per frame.

`frontier.py` also documents two traps of its own: `read_ram` answers a
**space-separated** hex string (slicing `hex[2:4]` reads a space and silently
yields camera 0), and a map column is **not** `offset // 8` — the ring is two
32-column blocks of 64-byte rows, so
`column = (off // 0x800) * 32 + (off % 64) // 2`. With `off // 8` every write
looks like it lands on the camera column and the frontier reads as 0.
