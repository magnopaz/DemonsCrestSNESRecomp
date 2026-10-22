# Undead Firebrand skin — test mod

Replaces the native Firebrand player OAM with the deterministic undead reskin
from `../DemonCrestAssets/pipeline/out/firebrand_undead_reskin/`.

## What it does

- Detects the player OAM group by its normal-stage tile bank (tiles 0–13),
  requiring one OAM attribute shared by the group and the body tiles 6/7.
  This rejects the title/logo sprites, which only use tiles 0–3 and two
  different attributes.
- Hides those native OAM entries **for the current draw only**.
- Composes a 48×48 RGB15 frame through the PPU extra-object path.
- Restores the native OAM immediately after the draw, so guest WRAM/VRAM/OAM
  are not modified persistently.
- Uses 4 idle frames and 6 walk frames. Walk is selected from the **d-pad**
  (left/right), not from OAM displacement: the camera follows Firebrand, so
  his screen X can stay fixed while he walks.
- If the player group changes tile bank/attribute for a frame, the last valid
  slots are kept covered for up to 60 frames, preventing the native sprite
  from flashing through.

## Supported test scenes

Verified with the supplied saves:

| Save | Scene | Skin |
|---|---|---|
| save0 | graveyard, standing | works |
| save1 | purple cathedral corridor | works |
| save2 | pillar/graveyard | works |
| save3 | graveyard, ghost | works |
| save4 | Arma boss room | works in gameplay; boss dialogue can stay native (UI gate) |
| save5 | Mode 7 overworld | not yet (different tile bank $C0+) |
| save6 | title/menu | native (correct) |
| save7 | first cutscene | undead, idle-stable |

## How to run

The test build is:

```bash
cd /Data/OpenCodeProjects/DemonsCrestSNESRecomp
cmake --build build-trace -j
./build-trace/DemonsCrestSNESRecomp \
  --no-launcher \
  --rom "/Data/OpenCodeProjects/roms/Demon's Crest (USA).sfc"
```

The mod is **enabled by default** in `build-trace/mods/preloaded/state.toml`.
Disable it in the launcher’s Mods page, or set `enabled = false` for the
`demonscrest.skin.undead` feature.

## Limitations

- The extra object is presentation-only; it does not replace ROM/VRAM tiles.
- Attack, hurt and death frames are not selected yet; idle/walk are.
- The fallback keeps the last OAM slots for up to 60 frames, which covers
  transient animation-bank changes but is not a full animation state machine.
- Mode 7 overworld uses a different tile bank and is not handled.
- The skin is 48×48; native OAM bbox varies with pose, so the overlay may be
  slightly offset in some animations.
- Do not use this as a final mod: it is a visual test harness for the reskin.

## Files

- `src/dc_skin.c` / `src/dc_skin.h`
- `src/dc_skin_frame.h` (generated RGB15 idle/walk frames)
- `src/mods/dc_skin_plugin.c`
- `mods/preloaded/packages/demonscrest.skin.undead/0.0.1/manifest.toml`

## Menu/cutscene behavior

- Title/menu (`$8D=0xA6`): skin is not applied; the logo is native.
- Cutscene rooms (`$8D=0`): skin is applied, but the actor stays in idle when
  only the screen shakes vertically.
- Stage gameplay (`$8D=1..0x7F`): skin is applied.

## Screenshots

- `screenshots/before-after.png` — original vs. undead skin in the cathedral corridor (save1).
- `screenshots/arma-room.png` — undead skin in the Arma boss room (save4).
- `screenshots/title-default.png` — title/menu stays native (save6).
- `screenshots/cutscene-undead.png` — cutscene uses the skin, idle-stable (save7).
