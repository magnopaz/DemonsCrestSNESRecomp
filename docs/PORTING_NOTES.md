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
