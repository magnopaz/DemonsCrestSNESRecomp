# Porting notes — Demon's Crest (USA)

Verified state of this project plus the engineering log for turning the
scaffold into a validated playable port. Facts below were produced in this
workspace on 2026-10-10 with the framework pins in `framework_pins.txt`.

## Feasibility summary

Demon's Crest is in the same platform class as Mega Man X: standard
**LoROM + FastROM**, cartridge type `$00` — **no enhancement chip**, no SRAM.
The shared runner already models everything this cartridge needs, so no
mapper or coprocessor work is required. The project was cut from the exact
framework revisions the Mega Man X project pins, and the full loop — ROM
verification → C generation → CMake build → boot — has been run end to end.

| | Demon's Crest (USA) | Mega Man X (U) (V1.1) |
|---|---|---|
| Image | unheadered `.sfc`, 2 MiB | 512-byte copier header, 1.5 MiB |
| Mapping | LoROM FastROM (`$30`) | LoROM FastROM (`$30`) |
| Cartridge type | `$00` ROM only | `$00` ROM only |
| Coprocessor | none | none |
| SRAM | none (password saves) | none (password saves) |
| Publisher / year | Capcom / 1994 | Capcom / 1993 |
| Header checksum | valid | valid |
| CRC32 (bare image) | `e8236ad2` | `ded53c64` |

### Shared Capcom library code

A byte-level comparison of the two bare ROM images found a substantial shared
code footprint despite the games being different titles:

- a byte-identical run of **2,862 bytes** — Demon's Crest `08:F42B`
  (file offset `$04742B`), Mega Man X `09:C6FA` (file offset `$04C6FA`);
- a cluster of ~1 KB of identical runs around Demon's Crest `06:8xxx`
  ↔ Mega Man X `09:8xxx`;
- 130 runs of ≥24 bytes in total (~8.3 KB).

This is Capcom's shared SNES library surfaced in the ROM images. It does not
remove the per-title work, but it means some routines identified in the Mega
Man X project (and its `third_party/dizProjects` annotations) may map onto
Demon's Crest addresses. Identify and name them as they are reached.

Tooling used for this check is checked in as `tools/rom_similarity.py`; the
durable artifact remains `recomp/symbols.toml` with names as they are
identified.

## What has been verified

1. **ROM identity.** `bash tools/regen.sh` verifies CRC32/SHA-256 from
   `rom_identity.txt` before generating: `e8236ad2` /
   `18d40a80…5844de`, 2,097,152 bytes.
2. **Generation.** Initial seed (`recomp/bank00.cfg`: `auto_vectors` +
   `tier_down_stubs`) produced 4 analysis roots → 11 exact AOT variants,
   16 edges; banker emitted `src/gen/bank00_v2.c`, `src/gen/bank80_v2.c`
   (~76 KB) and a dispatch table (I_IRQ plus four bank-`$80` entries) in
   ~17 s with the native Rust analyzer. The tiny surface is expected — the
   seed only knows the hardware vectors. The unproven remainder runs on the
   authoritative interpreter tier.
3. **Build.** `cmake -S . -B build -DCMAKE_BUILD_TYPE=Release` +
   `cmake --build build -j` produced an 8.1 MB ELF
   (`build/DemonsCrestSNESRecomp`) with no errors (only format-truncation
   warnings from the framework/launcher).
4. **Boot.** A headless smoke run executed 300 frames at ~60.1 FPS
   (`cpu_seconds≈1.5`, LLE frame service) with no crash, and the presentation
   reached the game's boot sequence: copyright/license screen (~frame 310),
   Capcom logo (~frame 500), then the intro ("TWO DIFFERENT LANDS.",
   ~frame 5000). Screenshots were captured with the framework's harness:

   ```sh
   cd build
   SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
   SNESRECOMP_RUN_FRAMES=320 \
   SNESRECOMP_SCREENSHOT=/tmp/dc.ppm SNESRECOMP_SCREENSHOT_FRAME=310 \
   ./DemonsCrestSNESRecomp "/path/to/Demon's Crest (USA).sfc"
   ```

   (`SDL_VIDEODRIVER=dummy` also tells the host to skip the GUI launcher.)

   Captures from that run are kept locally (untracked — they are game
   imagery) under `docs/verification/`.

## What remains — the port

The scaffold stops where the game-specific work starts. In rough order:

1. **Boot-to-game coverage.** The attract route is promoted and validated;
   extend it with input-driven routes (title → file select → first stage) and
   capture those, then fold the captures into `recomp/tier2_coverage.json`
   the same way. After every regen, resolve dispatch misses and
   interpreter-gap entries before anything else. `SNESRECOMP_STATE_TRACE`,
   `SNESRECOMP_FRAME_TIMING` and the dump/screenshot harness make runs
   observable.
2. **Name the code.** Add `[[func]]` entries to `recomp/symbols.toml` as
   routines are identified; `emit = true` promotes a function into AOT
   analysis. Re-run `bash tools/regen.sh` after every config change.
3. **Keep the scheduler seam pinned.** The task context-switch family in
   `recomp/symbols.toml` must stay `emit = false` (`force_lle`). Promoting any
   member re-creates the 2026-10-10 stall; a capture can reintroduce a seed
   for those PCs, so check new captures against the pins before regenerating.
4. **HLE only where the general driver cannot follow.** The scheduler does not
   need HLE: the LLE-scheduler architecture executes the coroutine switches
   byte-exact and runs task bodies compiled. Add per-title HLE for other
   seams only when evidence shows the general path cannot follow (example:
   Mega Man X's `src/mmx_rtl.c` for its optional fiber scheduler).
5. **Interpreter-gap manifest.** TIER2 is enabled in `CMakeLists.txt`; read
   the manifest the post-mortem report carries after gameplay runs and feed
   it back through `tools/regen.sh --profile-manifest`.
6. **Annotations.** The framework can ingest disassembly labels through
   `snesrecomp/tools/` (see `DISASSEMBLY_AUTHORITY.md`). A partial external
   disassembly of this game exists:
   <https://github.com/FredYeye/various-game-disassembly/blob/main/SNES/demons_crest.asm>.
7. **Validation.** Once the game is playable, expand `tests/` and CI; the
   scaffold's workflow deliberately verifies only framework and host sources
   because CI cannot legally fetch a ROM.

## Coverage feedback loop (wired 2026-10-10)

The project carries the framework's Tier-2 interpreter-coverage loop, mirroring
the Mega Man X setup:

- `CMakeLists.txt` builds the desktop host with `TIER2`, so post-mortem
  reports carry the interpreter-gap manifest.
- `tools/regen.sh` accepts repeatable `--profile-manifest <file>` and includes
  `recomp/tier2_coverage.json` automatically when present (`--no-profile`
  opts out). Captures seed optional AOT roots from clean call landings; bails
  are excluded by the framework.
- `scripts/routes/attract.script` is the headless route: boot → story intro →
  first gameplay scene, no input, 24,000 frames.
- `tools/disasm_range.py` disassembles a ROM range with the framework's own
  decoder. `tools/trace_diff.py` compares `SNESRECOMP_STATE_TRACE` files.
- `tools/rom_similarity.py` finds shared code with another ROM image.

Capture a route:

```sh
SNESRECOMP_TIER2_CAPTURE=1 SNESRECOMP_COVERAGE_DIR=coverage/<name> \
  ./build/DemonsCrestSNESRecomp "<rom>" --script scripts/routes/attract.script
```

**First capture (scaffold build):** 911 transfer tuples, all `missing_entry`,
zero bails; 461,482,934 interpreted instructions over 24,000 frames, with 72%
of them in the scheduler poll loop at `$80:8181–$81A1`. The boot and
scheduler entries named in `recomp/symbols.toml` (`ResetInit`,
`SchedulerLoop`, `TaskInit`, `NmiHandler`, `IrqHandler`) were identified from
that trace and a disassembly of the same region.

**Rich AOT promotion — implemented and validated.** The default
`tools/regen.sh` now includes `recomp/tier2_coverage.json` (a 283 KB slim
copy of the first capture, committed), and the program is generated with
463 roots → 4,829 exact variants (4,535 AOT) across 15 banks. The
task-switch family below stays interpreted; everything else in the captured
route is compiled. Results are in "Rich configuration" below.

## The scheduler seam (why the promotion needed a fix)

The first promotion attempt (2026-10-10) blanked the intro and could stall:
the analyzer had materialized members of the title's cooperative
task-switch family, whose control flow is a dynamic context switch
(`TSC`/`TCS` plus jumps back into the scan loop) that static analysis cannot
prove. The complete family, found by disassembly and ROM pattern scan, is
pinned to LLE in `recomp/symbols.toml`:

| PC | Role |
|---|---|
| `$8179` | scheduler scan loop (`lda $0083` vblank flag; walks the 16-byte-stride task table at `$0030`) |
| `$81A3` | resume a status-4 task (saves scheduler S to `$0070`, switches S to `$0032,Y`, pops task regs, RTL) |
| `$81C0` | fresh dispatch / status ≥ 5 via the `$82C3` jump table |
| `$81FE` | task yield return (restore scheduler context; clear slot status) |
| `$8212` | clear a task slot and RTL (JSL'd from task code) |
| `$821E` | task yield: save task S to `$0032,Y`, set status, restore scheduler context, `jmp $8195` (JSL'd from ~90 sites) |
| `$8276` | yield with status 4 (suspend to next scan; JSL from `$00:C300`/`$04:A0C2`) |
| `$829B` | task install/restart with status 8 (no static callers; found by pattern scan) |

This matches the framework's current architecture
(`snesrecomp/docs/LLE_SCHEDULER.md`): keep the real scheduler interpreted so
the coroutine switches execute byte-exact, and run task bodies compiled
through the bridge bounce. The fiber-based HLE scheduler (`src/mmx_rtl.c` in
the Mega Man X project) is the older alternative and is being retired
framework-wide; this port does not need it.

## Gameplay route and stage coverage (2026-10-18)

`scripts/routes/gameplay.script` is the first input-driven route: title
(~frame 24000) → Start starts a new game → ~20000 frames of cutscene rooms
(`$8D = 0xA0 + room`) → the first playable stage segment (`$8D = 2`, the
graveyard) at frame 43659, anchored with `until 008D == 02`. The route walks
right and leaves guest state at `stage_start`/`stage_600` dumps; both are
byte-identical across two runs of the same build (WRAM SHA-256), and the
attract route still passes.

Coverage: attract and gameplay captures were folded into
`recomp/tier2_coverage.json` (1,023 rows) with `tools/merge_coverage.py`.
The committed baseline is the persistent seed record — code that is already
AOT never reappears as an interpreter fallback, so a fresh capture cannot
re-derive it. The merge tool unions rows, drops per-build `costs`/
`ram_routines`, and stamps the newest capture's identity so the file is a
valid `--profile-manifest` for the current build. Regen moved the program to
**484 roots / 4,935 AOT variants** (from 463 / 4,535); the rebuild was
re-verified with the routes above. `tools/regen.sh` passes the merged file as
the baseline profile.

## Widescreen margin history and the framework guard patch (2026-10-18)

The widescreen mod serves BG1/BG2 margins from the framework's world-keyed
tilemap store (`snes/ws_shadow.c`) instead of the streamed VRAM window: the
native viewport sweep plus the game's own VRAM uploads at write time
(`WsShadowOnVramWrite`) keep ahead-of-view content available. World-row keys
(no `retainHistory`) are required: the retain variant keys rows by viewport
index, which the write capture does not, so staged uploads were never read
(measured east-margin hits 14% retain vs 85–87% world; west 99.9%).

`WsShadowTile` was patched locally (`snesrecomp/runner/src/snes/ws_shadow.c`)
so a chunk that straddles the native edge is rendered from the renderer's own
tile instead of the history. Demon's Crest updates map columns the moment
they reach the native edge, so the straddling cell could hold content the
sweep had not observed; with history serving it, native columns x=0..5 and
x=251..255 differed from the authentic frame. The guard now serves history
only for chunks entirely outside [0,256), which keeps the center bit-exact at
the cost of at most a one-tile seam inside the margin. **This patch must be
upstreamed; `git submodule update` reverts it.** Diagnostics:
`SNESRECOMP_WS_HISTORY=0` (fall back to raw VRAM) and `SNESRECOMP_WS_STATS=1`
(hit/miss/fallback counters every 600 frames).

## Save states: runtime execution chunk + beam-driver resume (2026-10-18)

`snes_saveload` serializes the guest machine (WRAM, PPU, DMA, APU ports, beam
registers, the legacy `Cpu`) but **not** the recomp runtime's `CpuState`
(`g_cpu`: registers, flags, E mode, master clock) nor the interpreter bridge's
LLE resume state. The framework streams those through the v5 game chunk
(`RtlGameInfo.state_save_extra` / `state_load_extra` →
`RtlSaveExecutionState` / `RtlLoadExecutionState` /
`RtlApplyExecutionState`), the same wiring MMX uses for its scheduler fibers.
Without it, a load in a fresh process left `g_cpu` at its reset values
(emulation mode, S=01FF, PB=0, master clock 0); the first NMI handler decoded
its 16-bit `LDA #$0000` as an 8-bit LDA + BRK and vectored into a `BRA` spin
(45M cycles/frame to the interp step cap). In-game loads appeared to work only
because the live `g_cpu` was already a valid mid-game scheduler context.

`src/game_rtl.c` now implements all three hooks. Legacy saves (no chunk, e.g.
the owner's) rebuild the native-mode scheduler context the guest's boot leaves
behind when it `JMP`s to `$80:8179` (E=0, M=X=1, DB=PB=$80, D=0, S=01FF) and
resume there; the scheduler then resumes each task from the loaded WRAM stacks.
New saves carry the chunk and restore exactly (verified: frame counter, camera
and WRAM round-trip).

The beam driver also needs to be told a machine now exists:
`snes_beam_frame_driver_state_loaded(resume_pc24)` (local patch in
`snesrecomp/runner/src/beam_frame_driver.{c,h}`) re-arms `s_resume_pc`.
Without it the driver's `s_resume_pc == 0` boot path ran the reset vector over
the loaded machine. **Upstream this too**; `git submodule update` reverts it.

## Widescreen objects/sprites in the margins (Fase 4, 2026-10-19)

Two guest-side tests kept objects and their sprites inside the authentic
256-px window; both are widened by the live margin through
`tools/dc_apply_widescreen_hooks.py` (idempotent generated-code injector, run
by the build as `DemonsCrestSNESRecomp_ws_hooks` and by `tools/regen.sh`; it
fails loudly if an anchor disappears):

- the bank `$82` object loop's cull (`dx + 0x60 < 0x1C0` X, `dy + 0x60 <
  0x1A0` Y — the same code is also emitted under the bank `$02` mirror, and
  the injector patches both);
- the sprite emitter's X test (function `$F689`, an AOT root): the authentic
  test hides every 9-bit OAM X >= 256 with low byte < `$F3`; the injected one
  keeps the right margin (low < margin) and the widened left-edge window
  (low >= `0xF3 - margin`).

`DcWsObjectCullMargin()` (`src/dc_widescreen.c`) returns 0 unless widescreen
is on AND active AND the stage gameplay gate passes, so a pillarboxed
cutscene cannot reveal hidden objects; `SNESRECOMP_WS_OAM=0` disables both
hooks. At margin 0 the injected expressions evaluate to the authentic
constants (verified: WRAM byte-identical to the unpatched build over the area
2 route). End-to-end: enemies just outside the native view now appear drawn
in the right margin.

A third injected patch (`patch_screen_test`, marker `/*DCWS5*/`) widens the
"is this object on screen?" helper at `$82:E6AC`, which the attack/hit path
uses to despawn a shot: the authentic test keeps a coordinate only while its
high byte is zero (`and #$FF00`), i.e. inside [0,255]. The owner's save2
reproduction showed the fireball dying at dx=+257 / dx=-1 (the native edges);
the widened test keeps [-margin, 255+margin), so the projectile now flies
through the whole margin and dies at dx=+299 / dx=-44 (the wide field's
edges). Located with the trace build's debug server
(`-DSNESRECOMP_ENABLE_TRACE=ON`, `build-trace/`): a WRAM watch on the object's
flags at `$1080` reported the killer block `$82:E49E` and its caller
`$82:E6AC`.

## Status bar anchored to the widened left edge (Fase 6, 2026-10-19)

BG3 carries only the status bar: map rows 1..5 (native y 8..47), map columns
3..29 (native x 24..239) of the VRAM map at `$5800`; the rest of the map is
empty. On the bar's scanlines BG3 is remapped as one rigid elastic segment
shifted left by the live margin (`PpuSetWidescreenLayerElasticBand(2, 0, 48,
{0,256,-m,256-m}, 1)`): the bar hugs the left edge of the widened field and
the columns the remap does not cover stay transparent, so the scenery shows
through where the bar used to sit. BG3 is no longer clamped in gameplay (the
remap keeps it in place) and `PpuSetWidescreenBg3Widen(1)` makes the band
live. `SNESRECOMP_WS_HUD=0` restores the authentic position; margin 0 is the
identity remap.

## Top-of-screen black band flicker (investigated 2026-10-19)

Reported as a black bar at the top that appears/disappears between frames.
Measured with per-frame BMP captures and the PPU register-write journal
(`*.ppuw.tsv` from `SNESRECOMP_DUMP_DIR`):

- **Not widescreen-related**: identical at 4:3 with the mod disabled, and the
  older Fase 3 captures (`walk_world`) already show it.
- The NMI handler finishes inside vblank (ends at beam v=232..238, +10.9k..+19k
  master cycles).
- The journal shows the real mechanism: the game forces blank
  (`$2100=$80`) in the NMI handler and a "present" task writes `$0F` back
  ~64k cycles (good frames -> visible line ~9) to ~80k cycles (busier frames ->
  line ~19..21) after the frame boundary. The HUD's empty top border is ~8
  lines, so the good case is invisible and the busy case clips the glyph tops.
- Steady gameplay jitter is 9..12 lines; the large 19..21 case is
  transitions/level start.
- The framework's DMA model is hardware-accurate (8 master cycles/byte); the
  remaining difference is guest execution timing, which needs a reference trace
  (Mesen) that is not installed here.

Options: leave it (game behaviour), drop the forced-blank bit from the raster
journal (the render runs after the CPU half, so the upload cover is redundant;
brightness fades still work -- changes emulation semantics), or patch the
guest's `$2100=$80` writes (fragile). Awaiting the owner's choice.

**Chosen and implemented (option 2)**: new PPU flag
`PpuSetIgnoreForcedBlank` (`ppu->wsIgnoreForcedBlank`, outside the savestate
ranges). When set, `ppu_rasterApplyLine` drops INIDISP writes with bit 7 set
from the render replay and `ppu_rasterRenderBegin` starts the walk with bit 7
of the baseline cleared; brightness writes (fades) still replay. The game
enables it only in stage gameplay with widescreen
(`DcWidescreenConfigureFrame`), so transitional fields keep the authentic
blank; kill switch `SNESRECOMP_WS_NOBLANK=0`. Verified: 20 captured frames in
the owner's scene 3 show **0** black top rows (vs 9/20/9/18/20 with the switch
off), the HUD glyph tops are complete, the 4:3 mod-off path is unchanged
(policy off -> the authentic 9/20/9 pattern returns) and the intro fades still
render. This is the third local framework patch to upstream alongside the
`ws_shadow` guard and the save-state driver API.

## Boss statue effect: the HDMA upload cover (2026-10-19)

Reported with the owner's `save3` during the first boss's awakening: the
transformation effect -- a white/lavender silhouette that should sit on the
statue -- was drawn ~50 lines below it, cut by the bottom edge. It is not a
sprite or a background: layer isolation shows it on every layer because it is
the color-math window (WH0, `$2126`/`$2127`) written per scanline by HDMA from
the tables at `$7F:F200`/`$7F:F300`; the window masks where the math applies,
so the math lands on whatever is beneath. The shape data starts with 127 rows
of an empty window, then 63 rows of the silhouette: it is positioned for a
table that runs from the top of the field.

The game brackets its per-frame VRAM/OAM upload the same way it covers it with
INIDISP: save `$420C`/`$2100`, write `$420C=0` and `$2100=$80`, move the data,
restore both. The forced blank is dropped by the flicker policy, but the HDMA
disable was still replayed: this frame model runs the CPU half before the
raster walk, so the restore landed at visible line ~46 (38..52, varying with
the frame's work) and the window's 127 empty rows put the silhouette at
restore+127 instead of 127 -- below the statue, and jittering frame to frame.

Fix, inside the same `PpuSetIgnoreForcedBlank` policy: during the replay, the
`$420C` change that opens an upload cover (a `$420C` write immediately
followed by a forced blank) and any `$420C` change while the cover is open are
treated as non-display state. The field's HDMA keeps running from line 0 with
the mask and tables the CPU half left (the restored values), which is what the
tables were authored for. A real mid-field HDMA change without a blank still
replays. Measured on `save3`: the silhouette now spans native y=128..190 (over
the statue) in every sampled frame and no longer jitters; the top band stays
absent (0 black rows in four samples); `save2` gameplay is unchanged; the 4:3
path was untouched in that measurement (policy off at the time); two runs
produce byte-identical frames.

The policy is a frame-model correction, not a display-width feature, so it is
now enabled in stage gameplay even when the mod is off or the field is at
native width: the statue effect lands on the statue at 4:3 too. Menus and
transitional screens keep the authentic behaviour (`DcStageGameplay` gate,
`SNESRECOMP_WS_NOBLANK=0` kill switch).

## Mode 7 flying map in the widened field (2026-10-19)

The overworld flying map renders in PPU Mode 7. It stayed pillarboxed because
the gameplay gate accepted only `$8D` in 1..0x7F; the map runs the alternate
HUD variant (`$8D >= $A0`). The gate now also accepts `$8D >= $A0` when the
PPU is in Mode 7. Menus and the title use Mode 1 (`$8D=$A0`, bgmode 9 on the
title), so they remain pillarboxed. With the gate open the Mode 7 renderer
fills the whole widened field — no renderer change was needed; in the `save5`
capture the map and its margins are continuous.

## Dialogue boxes: parked windows and margins (2026-10-19)

The dialogue box is a fixed-color color window; its text is BG3. On lines
without the box the game leaves window 1 at `[0,0]`. The framework's
pinned-window remap treated a 0 left edge as "the screen edge" and expanded it
to `[-margin,0]`, opening a live window across the whole left margin; the
fixed color then painted a purple strip at the top-left (one native pixel at
x=0 in 4:3, 43 pixels wide with widescreen). `PpuWidescreenAdjustPinnedWindowEdges`
now only remaps an edge when the window spans more than one native pixel, so
`[0,0]`/`[255,255]` parked windows stay closed. The box and its text are
unchanged; the 4:3 path returns early (no margins).

The same `[0,0]` pattern appears as an **inverted layer window** on BG1/BG2 in
one stage, excluding the leftmost screen column. Once the side margin was live
it drew a one-pixel backdrop seam at the native edge (reproduced with
`save0`). Parked one-pixel **layer** windows now move to the widened screen
edge (both edges), so the exclusion sits at the far edge and the picture is
continuous; the color window still keeps its parked one-pixel window.

## Spawn (Fase 5): measured, not a camera-gated spawner (2026-10-19)

The plan assumed an incremental camera-driven spawner (as in MMX) whose cursor
would need widening. Measurement in area 2 shows Demon's Crest loads a room's
objects at room entry: the object list already holds every room object when
the camera is at 0 (including one at dx=280..330, outside the native view),
and walking the camera 0→207 with 10-frame sampling adds no new room objects —
only gameplay effects (ghost attacks) created inside the view. So there is no
native-edge spawn gate to widen here; objects outside the view already exist
and the Fase 4 cull keeps them updating, which is what makes them appear in
the margins. Reopen only if some stage shows objects *appearing* at dx≈256;
the ~13 `TaskInit` ($80:81E0) call sites in banks 0x85/0x83/0x84/0xBE/0x02/0x03
are the starting point (the camera reads in those banks are the $C0→$C2
parallax, not spawn gates).

## Phase 7 validation summary (2026-10-19)

Full matrix in `docs/WIDESCREEN.md`. Highlights: determinism (two runs,
`SNESRECOMP_STATE_TRACE`, 351 frames, byte-identical SHA-256); 4:3 center
bit-identical (3 frames, 0 diffs, object/HUD/blank policies off) and WRAM
byte-identical to the unpatched build at margin 0; `SNESRECOMP_WS_EXTRA=43`
frame byte-identical to the normal 16:9 output; a save loaded 300 frames into
a run produces the same WRAM as a cold load; the new-format save round-trip
and the intro fades render correctly. HUD states beyond full health/magic and
a left-margin trailing-object capture remain as documented limitations.

## Rich configuration (validated 2026-10-10)

| Metric | Baseline scaffold | Rich config |
|---|---|---|
| Analysis roots / AOT variants | 4 / 11 | 463 / 4,535 |
| Interpreted instructions (24,000-frame route) | 461,482,934 | 361,688,593 |
| Route WRAM deltas (6k→12k→18k→24k) | 9,163 / 28,567 / 80,855 | 9,158 / 28,562 / 80,723 |
| Framebuffers at 12k / 24k | flying intro / gameplay | flying intro / gameplay (`inidisp=15`) |
| Determinism (two runs, `STATE_TRACE`) | identical | identical (24,000 frames) |

The remaining interpreted work is the scheduler machinery itself (the poll
loop and context switches), which is inherent to the LLE-scheduler
architecture. Removing it would require the retired fiber HLE path; the
bigger wins now are gameplay coverage and features, not the scheduler tier.

## Verifying a promotion

Within one build, two runs of the same route produce byte-identical
`SNESRECOMP_STATE_TRACE` files (verified, SHA-256); that file is the
determinism oracle and `tools/trace_diff.py` localizes any difference.
Across builds, acceptance is route-level: dump guest state at frames
6000/12000/18000/24000 and require non-blank displays
(`inidisp != $80`), baseline-like WRAM activity, and baseline-like
framebuffers.

```sh
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
SNESRECOMP_DUMP_DIR=/tmp/cand ./build/DemonsCrestSNESRecomp "<rom>" \
  --script <probe script with dump at 6000/12000/18000/24000>
```

Any stall, hang or blank screen rejects the promotion and the previous
configuration is restored before committing — promotion is a decision, not a
default. The same probe also caught that a *partial* promotion is less
stable than the full one (mixed AOT/interpreted bounces are timings the
title does not tolerate as well); prefer promoting the full captured route.

## Layout reminders

- Generated C (`src/gen/`) is never committed; regenerate with
  `bash tools/regen.sh` (the ROM path is cached in git-ignored `rom.cfg`).
- The framework submodule pins are recorded in `framework_pins.txt` and are
  the same revisions the Mega Man X project validates:
  `snesrecomp eb75c88`, `recomp-ui 7e614a4`.
- `saves/` is intentionally unused: this cartridge has no battery SRAM.

## References

- `snesrecomp/docs/GAME_PROJECT_SETUP.md` — project workflow and host contract
- `snesrecomp/docs/LLE_FIRST_ANALYSIS.md` — AOT vs interpreter policy
- `snesrecomp/docs/FRAME_MODEL_HOSTS.md` — what "one frame" and interrupts mean
- `snesrecomp/docs/MULTI_TIER.md` — tier-down and coverage behavior
- Mega Man X project (same framework pins): `recomp/bank00.cfg`,
  `src/mmx_rtl.c`, `src/mmx_renderer.c` as mature examples
