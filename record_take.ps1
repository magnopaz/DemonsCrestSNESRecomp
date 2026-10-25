# Record one replayable take of the recomp.
#
# Starts a recording on the first guest frame (so the log can be replayed from
# boot), keeps only the input log (no per-frame BMPs), and puts the take under
# captures\rec_<timestamp>\input_log.jsonl next to this script.
#
# Play as long as you like, then press Alt+R to stop the take (or just close the
# window; the log is flushed every 64 frames).

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$exe = Join-Path $root "build\DemonsCrestSNESRecomp.exe"
$rom = "M:\Opencode\roms\Demon's Crest (USA).sfc"

if (-not (Test-Path $exe)) {
    $exe = Join-Path $root "build-trace\DemonsCrestSNESRecomp.exe"
}
if (-not (Test-Path $rom)) {
    throw "ROM not found: $rom  (pass another path by editing `$rom in this script)"
}

$env:SNESREC_AUTORECORD = "1"     # begin the take on the first frame of boot
$env:SNESREC_INPUT_ONLY = "1"     # input log only, no per-frame BMPs
$env:SNESREC_RECORD_DIR = (Join-Path $root "captures")

Write-Host "recording a replayed-from-boot take -> $env:SNESREC_RECORD_DIR"
Write-Host "play, then press Alt+R to stop (or close the window)"
& $exe $rom
