# Headless tests

The port's correctness claims used to live only in prose (the P1–P16 matrix in
`docs/WIDESCREEN.md`, the validation notes in `PORTING_NOTES.md`). This suite
runs the real executable through the framework's script driver and checks the
invariants that matter, so a change to the widescreen policy, the frame model or
the generated-code injector fails loudly instead of being noticed while playing.

```sh
cmake --build build -j          # the tests run the built executable
cd build && ctest --output-on-failure
ctest -L unit                   # no ROM needed
ctest -L integration            # needs a ROM; SKIPs without one
```

The full suite takes ~25 s on a desktop CPU (the tests drive the game faster
than real time: `DisableFrameDelay = 1`, dummy video/audio, software renderer).

## What runs

| Test | Class | Asserts |
|---|---|---|
| `dc.injector` | unit | the injector patches a synthetic bank file with one of each anchor, is byte-for-byte idempotent on a second run, rejects a missing hook site and a changed anchor shape |
| `dc.injector_check` | unit | `--check` passes against the current `src/gen` (all anchors patched, expected site counts met) |
| `dc.boot` | integration | boot → 240 frames: 256×224 frame, non-blank, 128 KiB WRAM dump, clean `quit` |
| `dc.geometry` | integration | P16 in a non-gameplay scene: the widened field (`SNESRECOMP_WS_EXTRA=48`) is 352×224, its center 256 columns are **byte-identical** to the 4:3 frame, and both margins are a flat pillarbox (the scene gate clamps, so no stale pixels survive) |
| `dc.aspects` | integration | the mod's fixed-ratio views: 16:9 (342×224), 21:9 (448×224) and 32:9 (682×224) each keep the same center identity and a flat pillarbox |
| `dc.determinism` | integration | two identical scripted runs (widescreen on) produce the same frame and WRAM SHA-256 |
| `dc.staging_band` | integration | the far-right repair touches **exactly** the columns past the engine's staging frontier, in every captured frame (see `PORTING_NOTES.md`, "Widescreen: the engine's staging window") |

`dc.staging_band` also needs a save state, because the band only exists during
stage gameplay. Point `SNESRECOMP_TEST_SAVE` at any `.sav` the game can load
into slot 0 (a state captured while walking a stage is ideal); the test SKIPs
otherwise. It is the regression test for the artifact reported on the far right.

A SKIP is exit code 77 (`SKIP_RETURN_CODE` in `tests/CMakeLists.txt`), so
`ctest` stays green on a machine without a legally owned ROM. CI can therefore
run the `unit` label unconditionally and the `integration` label only where a
ROM is available.

## Prerequisites

| Input | Where it comes from |
|---|---|
| ROM | `$SNESRECOMP_ROM`, else `rom.cfg` (repo root, `build/`, `build-trace/`), else `Demon's Crest (USA).sfc` at the repo root. The integration tests SKIP when none is found. |
| Save state | `$SNESRECOMP_TEST_SAVE` or `--save <path>`; only `dc.staging_band`. |
| Executable | `--exe <path>`, default `build/DemonsCrestSNESRecomp[.exe]`. CMake passes `$<TARGET_FILE:...>`. |

Every integration test builds its own working directory in the system temp dir:
`config.ini` (software renderer, dummy-friendly), the **tracked** mod package
copied into `mods/preloaded/`, a `state.toml` that enables the widescreen
feature (that is how the product enables it, so the tests exercise the real
activation path instead of a config flag), a `saves/` slot when needed, and the
frame/state dumps. Nothing is written into the build tree or the repository.

## The injector contract

`tools/dc_apply_widescreen_hooks.py` is the only thing between a generator
change and a silently narrower game, so it counts what it patched:

```sh
python tools/dc_apply_widescreen_hooks.py --check        # verify, never write
python tools/dc_apply_widescreen_hooks.py --check --no-strict   # report only
```

* `EXPECTED_MIN` at the top of the script is the minimum number of hook sites
  the generator must emit today (`cull_x`, `cull_y`, `emitter`, `screen`,
  `prototype_files`). More is fine (coverage can grow); fewer means an anchor
  vanished. A generator change that deliberately changes the hook set must
  update `EXPECTED_MIN` in the same commit — that is the whole point.
* `--expect key=count` overrides one minimum (the synthetic unit test uses it).
* Writes are atomic (temp file + rename), so a crash cannot leave a
  half-patched translation unit for the build to compile.
* `--check` is suitable for CI: it exits non-zero when any anchor is unpatched
  or a site is missing.

## Adding a test

1. Add a function to `tests/dc_test.py` that takes `(repo, args)` and either
   returns a one-line success detail or raises `Skip(...)` / `Fail(...)`.
2. Register it in the `TESTS` dict (`True` if it needs the executable).
3. Add an `add_test(NAME dc.<name> COMMAND ...)` line to
   `tests/CMakeLists.txt` with the right label, timeout and
   `SKIP_RETURN_CODE 77`.
4. Prefer asserting on the `.bgrx`/`.wram.bin` state dumps (`SNESRECOMP_DUMP_DIR`)
   over screenshots: they are exact and carry no game imagery into the repo.

## Continuous integration

`.github/workflows/tests.yml` runs the injector unit test on Ubuntu and Windows
for every push and pull request. It needs no submodules, no ROM and no build, so
it stays fast and works on a fresh checkout — it is the job that catches a
generated-code anchor drifting or the injector regressing.

The `integration` label needs a legally owned ROM, which CI cannot provide, so
those tests stay local/self-hosted by design. A setup-host build
(`-DSNESRECOMP_SETUP_HOST=ON`, empty `src/gen`) registers only the `unit` label;
`dc.injector_check` SKIPs there because there is no `src/gen` to verify.
