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

1. **Boot-to-game coverage.** Follow the framework doctrine: after every
   regen, resolve dispatch misses and interpreter-gap entries before anything
   else. Use `SNESRECOMP_STATE_TRACE`, `SNESRECOMP_FRAME_TIMING` and the
   screenshot harness to make runs observable.
2. **Name the code.** Add `[[func]]` entries to `recomp/symbols.toml` as
   routines are identified; `emit = true` promotes a function into AOT
   analysis. Re-run `bash tools/regen.sh` after every config change.
3. **Promote coverage intentionally.** Seed `bank00.cfg` with discovered
   entry points once the boot path is mapped (Mega Man X's `recomp/bank00.cfg`
   is the reference for what a mature Capcom LoROM config looks like:
   task entries, yield wrappers, HLE boundaries, tier-down policy).
4. **HLE only where the general driver cannot follow.** The scaffold's
   `src/game_rtl.c` starts on the framework's beam-aligned frame driver; it
   is the right general driver. Add per-title HLE (scheduler, task system,
   decompressors) only when evidence shows the driver does not fit — that is
   where Mega Man X's `src/mmx_rtl.c` lives.
5. **Tier 2 diagnostics.** CMakeLists has a reminder: add `TIER2` to
   `snesrecomp_target_desktop_host` once this port reads the interpreter-gap
   manifest after each run.
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

**First AOT promotion attempt — reverted.** Regenerating with the capture as a
profile manifest expanded the program from 4 roots / 11 AOT variants to
468 roots / 4,904 AOT variants across 15 banks. The attract-route replay
showed the promoted build skipping/blanking the intro and stalling, so the
promotion was not kept. The investigation below is the reason.

## AOT promotion investigation (2026-10-10)

Summary: under this framework revision the title must not run coverage-driven
AOT yet. The promotion was bisected to a single observation and the failure
class identified.

- Baseline scaffold (seed cfg only): healthy through the whole 24,000-frame
  route (461M interpreted instructions; screenshots show copyright → CAPCOM
  logo → story text → flying intro → first gameplay scene).
- Method: `SNESRECOMP_STATE_TRACE` is byte-identical across two runs of the
  same build (verified), so it is a valid within-build determinism oracle.
  Across builds with different AOT sets, traces are **not** expected to be
  byte-identical: the frame cut lands on a slightly different instruction
  (straight-line blocks are charged atomically) and yield/stack residue
  differs. Route acceptance therefore used long-window WRAM deltas (`dump`
  at frames 6000/12000/18000/24000; baseline deltas 9,163/28,567/80,855
  bytes) plus framebuffer evidence.
- Bisection: the stall is dose-dependent (more promoted AOT → earlier
  failure). One discovery explains a fatal path by itself: the call
  `$80:86DD → $80:821E` (M1X1, observed once at frame 6). `$821E` is the
  **task yield**: it saves the task's stack pointer (`TSC` → `$0032,Y`),
  restores the scheduler context from `$0070` and jumps back into the
  scheduler scan. Promoting it alone reproduces the stall. With it pinned to
  LLE the route survives, but other promoted code still blanks the display
  mid-intro (`INIDISP=$80` at frame 12000 while the guest keeps running).
- Cause class: `$821E`, `$81FE`, `$81A3`, `$81C0`, `$8212` are a cooperative
  task context-switch family (dynamic `TSC`/`TCS` plus jumps into the scan
  loop). Static materialization of that family is exactly what the analyzer
  cannot prove; Mega Man X HLE-replaces its equivalent scheduler and yield
  points in `src/mmx_rtl.c`. This title needs the same treatment before AOT
  promotion is trustworthy.
- Current state: `recomp/symbols.toml` names the boot/scheduler entries and
  pins the task-switch family with `force_lle`; nothing is promoted (default
  regen is seeds-only, no `recomp/tier2_coverage.json` baseline committed).
  The verified 24,000-frame route stays healthy this way.

## Verifying a promotion

Within one build, two runs of the same route produce byte-identical
`SNESRECOMP_STATE_TRACE` files (verified twice, matching SHA-256); that file
is the determinism oracle, and `tools/trace_diff.py` localizes any
difference. Across builds, acceptance is route-level:

```sh
# candidate run with probes (see docs for the probe script)
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy \
SNESRECOMP_DUMP_DIR=/tmp/cand ./build/DemonsCrestSNESRecomp "<rom>" \
  --script <probe script with dump at 6000/12000/18000/24000>
```

Acceptance requires baseline-like scene progression: non-blank framebuffers
at every probe and WRAM activity in the same order of magnitude as the
baseline's. Any stall, hang or blank screen rejects the promotion and the
previous configuration is restored before committing — promotion is a
decision, not a default.

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
