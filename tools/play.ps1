# play.ps1 — one-click: regen + configure + build + launch Demon's Crest.
#
# The toolchain this machine uses (found by discovery, overridable):
#   - CMake            (Program Files or PATH)
#   - Ninja            (pip install ninja -> Scripts\ninja.exe)
#   - GCC 16 MinGW-w64 (winget BrechtSanders.WinLibs.POSIX.MSVCRT)
#   - Rust 1.97.1 GNU  (rustup toolchain + the MinGW gcc as linker)
#   - SDL2 2.32.6      (M:\SDL, via -DSNESRECOMP_SDL_BACKEND=SDL2)
#
# Usage:
#   tools/play.ps1                 # regen (if src/gen missing) + build + launch
#   tools/play.ps1 -SkipRegen      # reuse current src/gen
#   tools/play.ps1 -Reconfigure    # wipe the build dir and configure again
#   tools/play.ps1 -NoRun          # build only, print the exe path
#   tools/play.ps1 -KillRunning    # terminate a running instance first
param([switch]$NoRun, [switch]$SkipRegen, [switch]$Reconfigure, [switch]$KillRunning)
$ErrorActionPreference = 'Stop'

$repo = Split-Path $PSScriptRoot -Parent
$buildDir = Join-Path $repo 'build'
$exe = Join-Path $buildDir 'DemonsCrestSNESRecomp.exe'

function Find-Exe([string[]]$candidates, [string]$name) {
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { return $c } }
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "$name not found. Install it or edit tools/play.ps1."
}

$cmake = Find-Exe @("$env:ProgramFiles\CMake\bin\cmake.exe",
                    "${env:ProgramFiles(x86)}\CMake\bin\cmake.exe") 'cmake'
$ninja = Find-Exe @((Join-Path (Split-Path (Get-Command python).Source) `
                    'Scripts\ninja.exe')) 'ninja'
$gcc = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse `
        -Filter gcc.exe -ErrorAction SilentlyContinue |
       Where-Object { $_.FullName -match 'WinLibs' } | Select-Object -First 1
if (-not $gcc) { throw 'MinGW gcc not found (winget BrechtSanders.WinLibs.POSIX.MSVCRT).' }
$mingw = Split-Path $gcc.FullName
$gxx = Join-Path $mingw 'g++.exe'
$sdl2 = Get-ChildItem 'M:\SDL' -Recurse -Filter 'sdl2-config.cmake' `
        -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $sdl2) { throw 'SDL2 cmake package not found under M:\SDL.' }
$sdl2dir = Split-Path $sdl2.FullName
$rom = if ($env:SNESRECOMP_ROM) { $env:SNESRECOMP_ROM }
       elseif (Test-Path 'M:\Opencode\roms\Demon''s Crest (USA).sfc') {
           'M:\Opencode\roms\Demon''s Crest (USA).sfc' }
       else { Join-Path $repo 'Demon''s Crest (USA).sfc' }

$env:PATH = "$mingw;$env:USERPROFILE\.cargo\bin;$env:PATH"
$env:RUSTUP_TOOLCHAIN = '1.97.1-x86_64-pc-windows-gnu'
$env:CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER = Join-Path $mingw 'gcc.exe'
$env:PYTHON = (Get-Command python).Source

$running = @(Get-Process DemonsCrestSNESRecomp -ErrorAction SilentlyContinue)
if ($running.Count -gt 0) {
    $pids = ($running | ForEach-Object { $_.Id }) -join ', '
    if (-not $KillRunning) {
        Write-Host "DemonsCrestSNESRecomp is running (PID $pids)." -ForegroundColor Yellow
        Write-Host 'Close it first, or pass -KillRunning to terminate it.' -ForegroundColor Yellow
        exit 1
    }
    # Terminating a running game is exactly how a QA session ends silently:
    # no atexit report, no crash log, no Windows error event. Only do it when
    # the caller asked for it.
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 300
}

$generated = Get-ChildItem (Join-Path $repo 'src\gen') -Filter '*.c' `
             -ErrorAction SilentlyContinue
if (-not $SkipRegen -and -not $generated) {
    Write-Host '=== regen ===' -ForegroundColor Cyan
    # Git Bash sees the drive as /<letter>/... (M:\x -> /m/x).
    $repoBash = '/' + $repo.Substring(0, 1).ToLower() + ($repo.Substring(2) -replace '\\', '/')
    & 'C:\Program Files\Git\bin\bash.exe' -lc "cd '$repoBash' && bash tools/regen.sh"
    if ($LASTEXITCODE -ne 0) { throw 'regen failed' }
}

if ($Reconfigure -and (Test-Path $buildDir)) { Remove-Item $buildDir -Recurse -Force }
if (-not (Test-Path (Join-Path $buildDir 'CMakeCache.txt'))) {
    Write-Host '=== configure ===' -ForegroundColor Cyan
    & $cmake -G Ninja -S $repo -B $buildDir -DCMAKE_BUILD_TYPE=Release `
        -DCMAKE_MAKE_PROGRAM="$ninja" `
        -DCMAKE_C_COMPILER="$gcc" -DCMAKE_CXX_COMPILER="$gxx" `
        -DSNESRECOMP_SDL_BACKEND=SDL2 -DSDL2_DIR="$sdl2dir"
    if ($LASTEXITCODE -ne 0) { throw 'configure failed' }
}

Write-Host '=== build ===' -ForegroundColor Cyan
& $cmake --build $buildDir -j ([Environment]::ProcessorCount)
if ($LASTEXITCODE -ne 0) { throw 'build failed' }

Write-Host "Built: $exe" -ForegroundColor Green
if ($NoRun) { return }
Write-Host '=== launch ===' -ForegroundColor Cyan
Start-Process $exe -ArgumentList $rom -WorkingDirectory $buildDir
