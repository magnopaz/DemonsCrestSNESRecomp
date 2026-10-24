# Recording boss fights and animations

## Hotkey (no client needed)

Press **Alt+R** during play to start a recording and **Alt+R** again to stop it.
Each take lands in its own folder:

```
captures/rec_20261024_200010/
    frames/frame_000310.bmp ...   (one per frame, 256x224)
    input_log.jsonl                (the pad stream, replayable)
```

The path is configurable with `SNESREC_RECORD_DIR`; the toast reports
"REC started" / "REC saved N frames". Rebind it in `config.ini`:

```ini
[KeyMap]
Record = Alt+R      # Ctrl+R is Reset, R alone toggles the renderer
```

`keymap_dump` (debug command) prints what every hotkey resolved to, e.g.
`Record=0x0472`, which is how the binding is verified without a keyboard.

## Debug workflow

The runner's debug server can capture a play session and reproduce it exactly, so
a fight or an animation only has to happen once. Everything works over the same
TCP debug protocol used by the other tools (`SNESRECOMP_DEBUG_PORT`).

## Commands

| command | what it does |
|---|---|
| `record_input_start` | start buffering the controller stream |
| `record_input_stop [path.jsonl]` | write it (`{"frame":N,"inputs":M,"active":A}` per frame) |
| `replay_input <path.jsonl>` | feed the recorded stream back, frame by frame |
| `replay_stop` | stop replaying and hand the pad back to the player |
| `record_frames <dir> <count> [every_n]` | write one BMP per frame from now |
| `record_frames_stop` | stop and report how many frames were written |
| `record_ring_start [frames]` | keep the last N frames (default 300 ≈ 5 s) in RAM |
| `record_ring_stop` | stop the rolling buffer |
| `record_last <dir>` | write the rolling buffer + `input_log.jsonl` |
| `record_status` | JSON with every recorder's state |

Input is sampled at the same point the runner reads the pad, so **file frame N is
exactly the input frame N ran with**; replay writes it back at that same point.

## Recommended workflow

1. **Play the fight** with the rolling buffer armed:

   ```powershell
   $env:SNESREC_RING_DIR = "captures\somulo"
   .\DemonsCrestSNESRecomp.exe "Demon's Crest (USA).sfc"
   ```

   `SNESREC_RING=1` (or `record_ring_start`) keeps the last ~5 s in memory;
   quitting the window writes those frames and the input log to
   `SNESREC_RING_DIR`. Nothing has to be pressed during the fight.

2. **Or record the whole session** from a client:

   ```
   record_input_start
   ... play ...
   record_input_stop captures\fight.jsonl
   ```

3. **Re-capture it deterministically** without playing again:

   ```
   replay_input captures\fight.jsonl
   record_frames captures\somulo 600 1
   run_to_frame 900
   record_frames_stop
   ```

4. **Turn the frames into something shareable**:

   ```powershell
   python tools\bmp_sequence.py captures\somulo --gif somulo.gif --mp4 somulo.mp4
   ```

   `--every 2` halves a 60 fps capture; `--scale 3` upscales with nearest
   neighbour so the pixels stay crisp.

## Notes and limits

- The frame capture writes 24-bit BMP (the same pixel source as `screenshot`:
  the title compositor's surface when one is running, otherwise the PPU render
  buffer), so widescreen/coprocessor output is what gets recorded.
- `record_frames` at 60 fps writes ~150 KiB per frame; prefer the rolling buffer
  for long play, or `every_n` to thin the capture.
- Replay is meant to be frame-exact. It has been verified that the recorded file
  round-trips and that replay applies the stored pad state per frame; a strict
  bit-exact comparison of two full sessions is still on the TODO list, so treat a
  replayed capture as very close rather than guaranteed identical until that test
  lands.
