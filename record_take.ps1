# Record one replayable take of the recomp.
#
# Starts a recording on the first guest frame (so the log can be replayed from
# boot), keeps only the input log (no per-frame BMPs), and puts the take under
# captures\rec_<timestamp>\input_log.jsonl next to this script.
#
# Play as long as you like, then press Alt+R to stop the take (or just close the
# window; the log is flushed every 64 frames).
#
# Input-only recording is a local four-line patch to the framework host
# (SNESREC_INPUT_ONLY, see docs/RECORDING.md). If a submodule update reverts it,
# the take still records but writes one BMP per frame; this script warns when
# that happens.

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$exe = Join-Path $root "build\DemonsCrestSNESRecomp.exe"
if (-not (Test-Path $exe)) {
    $exe = Join-Path $root "build-trace\DemonsCrestSNESRecomp.exe"
}
if (-not (Test-Path $exe)) {
    throw "Build first: no DemonsCrestSNESRecomp.exe under build/ or build-trace/"
}

# Same ROM resolution as tools/regen.sh: the environment, then the cached path
# the setup wizard wrote (repo root or beside the executable), then a nearby
# dump. A machine-specific hardcoded path made this script useless elsewhere.
function Resolve-Rom {
    if ($env:SNESRECOMP_ROM -and (Test-Path $env:SNESRECOMP_ROM)) {
        return $env:SNESRECOMP_ROM
    }
    foreach ($cfg in @((Join-Path $root "rom.cfg"),
                       (Join-Path $root "build\rom.cfg"),
                       (Join-Path $root "build-trace\rom.cfg"))) {
        if (-not (Test-Path $cfg)) { continue }
        $first = (Get-Content $cfg -TotalCount 1).Trim()
        if ($first -and (Test-Path $first)) { return $first }
    }
    foreach ($name in @("Demon's Crest (USA).sfc", "demonscrest.sfc", "demonscrest.smc")) {
        $candidate = Join-Path $root $name
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

$rom = Resolve-Rom
if (-not $rom) {
    throw ("ROM not found. Set `$env:SNESRECOMP_ROM, record the path in rom.cfg " +
           "(the setup wizard does that), or put a dump at the repository root.")
}

$takeDir = Join-Path $root "captures"
$env:SNESREC_AUTORECORD = "1"     # begin the take on the first frame of boot
$env:SNESREC_INPUT_ONLY = "1"     # input log only, no per-frame BMPs
$env:SNESREC_RECORD_DIR = $takeDir

Write-Host "ROM: $rom"
Write-Host "recording a replayed-from-boot take -> $takeDir"
Write-Host "play, then press Alt+R to stop (or close the window)"
& $exe $rom

# Warn (do not fail) when the input-only patch is missing: the take is still
# usable, it just filled the disk with frames.
$newest = Get-ChildItem $takeDir -Directory -Filter "rec_*" -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($newest) {
    $frames = Join-Path $newest.FullName "frames"
    if (Test-Path $frames) {
        $count = @(Get-ChildItem $frames -Filter "*.bmp" -ErrorAction SilentlyContinue).Count
        if ($count -gt 0) {
            $msg = "Take {0} contains {1} frame BMP(s): SNESREC_INPUT_ONLY is not supported by " +
                   "this build (the local framework patch is missing)."
            Write-Warning ($msg -f $newest.Name, $count)
        }
    }
}
