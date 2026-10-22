/* Demon's Crest — undead Firebrand skin overlay (test harness).
 *
 * The recompiled game still runs its own OAM/animation logic. For this first
 * test we detect the native player OAM group (attribute $6E at the graveyard
 * route), hide it for the draw, and compose one 48x48 RGB15 frame from the
 * deterministic reskin through the PPU's extra-object path. Nothing in guest
 * WRAM/VRAM/OAM persists: the native OAM bytes are restored right after the
 * frame is drawn.
 */

#include "dc_skin.h"
#include "dc_skin_frame.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "common_rtl.h"
#include "snes/ppu.h"

extern Ppu *g_ppu;

#define DC_SKIN_SLOTS 128

static bool s_enabled = false;
static bool s_saved;
static uint8_t s_saved_oam[DC_SKIN_SLOTS][4];
static bool s_saved_valid[DC_SKIN_SLOTS];
static PpuExtraObject s_object;
static int s_last_cx = -1, s_last_cy = -1;
static int s_idle_tick, s_walk_phase;
static uint8_t s_last_slots[DC_SKIN_SLOTS];
static int s_last_count;
static uint8_t s_last_area = 0xFF;
static int s_missing_frames;

void DcSkin_SetEnabled(bool enabled) { s_enabled = enabled; }
bool DcSkin_IsEnabled(void) { return s_enabled; }

static int oam_size(int slot) {
  static const uint8_t sizes[8][2] = {
    {8, 16}, {8, 32}, {8, 64}, {16, 32},
    {16, 64}, {32, 64}, {16, 32}, {16, 32}
  };
  const uint8_t hi = g_ppu->highOam[slot >> 2];
  const int large = (hi >> ((slot & 3) * 2)) & 2u;
  return sizes[(g_ppu->obsel >> 5) & 7][large ? 1 : 0];
}

/* Firebrand's normal-stage OBJ tiles are 0,2,4 and 6..13 (frames are built
 * from a small tile bank). The palette/priority bits differ per area
 * ($2E/$3E/$6E), so tile identity is the stable discriminator. */
static bool is_player_tile(uint8_t tile) {
  return tile <= 13;
}

/* Same gameplay gate as the widescreen policy: $8D 1..$7F is a stage,
 * $00FB is the start/status menu, and $8D=0/$A0+ covers menus, title,
 * cutscenes and transitional screens. */
static bool dc_skin_gameplay(void) {
  if (!g_ppu) return false;
  if (g_ram[0x00FB]) return false;
  const uint8_t area = g_ram[0x8D];
  /* $8D=0 covers intro/cutscene rooms; keep the skin there too, but rely on
   * the player-group test below so the title/logo sprites are not touched. */
  if (area >= 0x80 && area < 0xA0) return false;
  if (area >= 0xA0 && (g_ppu->bgmode & 7) != 7) return false;
  return true;
}

void DcSkin_BeforeDraw(void) {
  if (!s_enabled || !g_ppu || !dc_skin_gameplay()) return;
  uint8_t *oam = (uint8_t *)g_ppu->oam;

  /* The player group shares one OAM attribute and includes the body tiles
   * 6/7. The title logo uses two attributes and only tiles 0-3, so it is
   * rejected. Screen-shake/effect sprites with other attributes are ignored. */
  uint8_t best_attr = 0;
  int best_count = 0;
  for (int candidate = 0; candidate < 256; ++candidate) {
    int count = 0, body = 0;
    for (int slot = 0; slot < DC_SKIN_SLOTS; ++slot) {
      const uint8_t *e = &oam[slot * 4];
      if (!is_player_tile(e[2]) || (e[3] & 0x0F) != candidate) continue;
      count++;
      if (e[2] == 6 || e[2] == 7) body = 1;
    }
    if (body && count >= 8 && count > best_count) {
      best_count = count;
      best_attr = (uint8_t)candidate;
    }
  }
  const uint8_t area = g_ram[0x8D];
  if (area != s_last_area) {
    s_last_area = area;
    s_last_count = 0;
    s_missing_frames = 0;
  }

  int player_slots[DC_SKIN_SLOTS];
  int player_count = 0;
  if (best_count >= 8) {
    for (int slot = 0; slot < DC_SKIN_SLOTS; ++slot) {
      const uint8_t *e = &oam[slot * 4];
      if (!is_player_tile(e[2]) || (e[3] & 0x0F) != best_attr) continue;
      if (e[0] > 240 || e[1] > 220) continue;
      player_slots[player_count++] = slot;
    }
    if (player_count >= 8) {
      memcpy(s_last_slots, player_slots, sizeof(s_last_slots));
      s_last_count = player_count;
      s_missing_frames = 0;
    }
  }
  /* Transient animation/tile-bank changes can hide the group for a frame.
   * Keep covering the last known player slots briefly instead of letting the
   * native sprite flash through. */
  if (player_count < 8 && s_last_count >= 8 && s_missing_frames < 60) {
    memcpy(player_slots, s_last_slots, sizeof(player_slots));
    player_count = s_last_count;
    s_missing_frames++;
  }
  if (player_count < 8) {
    s_last_count = 0;
    return;
  }

  int min_x = 999, min_y = 999, max_x = -1, max_y = -1;
  for (int i = 0; i < player_count; ++i) {
    const int slot = player_slots[i];
    const uint8_t *e = &oam[slot * 4];
    if (e[0] > 240 || e[1] > 220) continue;
    const int size = oam_size(slot);
    if (e[0] < min_x) min_x = e[0];
    if (e[1] < min_y) min_y = e[1];
    if (e[0] + size > max_x) max_x = e[0] + size;
    if (e[1] + size > max_y) max_y = e[1] + size;
  }
  if (max_x < 0) return;

  /* Hide the native player pieces for this draw only. */
  s_saved = true;
  memset(s_saved_valid, 0, sizeof(s_saved_valid));
  for (int i = 0; i < player_count; ++i) {
    const int slot = player_slots[i];
    uint8_t *e = &oam[slot * 4];
    memcpy(s_saved_oam[slot], e, 4);
    s_saved_valid[slot] = true;
    e[1] = 0xF0; /* park below the visible field */
  }

  int cx = (min_x + max_x) / 2;
  int cy = (min_y + max_y) / 2;
  /* Cutscene rooms use screen shake/bob of 1-2 px. Follow X (real motion)
   * but hold Y on small deltas so the overlay does not visibly bounce. */
  if (g_ram[0x8D] == 0 && s_last_cy >= 0 && abs(cy - s_last_cy) <= 2)
    cy = s_last_cy;
  /* The camera follows Firebrand, so the player OAM can stay at the same
   * screen X while he is walking. Use the actual d-pad state instead. */
  const uint16_t pad = RtlGetPadState(0);
  const bool moving = (pad & (kJoypadH_Left | kJoypadH_Right)) != 0;
  int frame;
  if (moving) {
    s_walk_phase = (s_walk_phase + 1) % 6;
    frame = 4 + s_walk_phase;
  } else {
    s_idle_tick++;
    frame = (s_idle_tick / 10) % 4;
  }
  s_last_cx = cx;
  s_last_cy = cy;

  int x = cx - DC_SKIN_FRAME_WIDTH / 2;
  int y = max_y - DC_SKIN_FRAME_HEIGHT;
  if (x < 0) x = 0;
  if (y < 0) y = 0;

  memset(&s_object, 0, sizeof(s_object));
  s_object.x = x;
  s_object.y = y;
  s_object.width = DC_SKIN_FRAME_WIDTH;
  s_object.height = DC_SKIN_FRAME_HEIGHT;
  s_object.stride = DC_SKIN_FRAME_WIDTH;
  s_object.priority = 3;
  s_object.math = 0;
  s_object.oamSlot = 1;
  s_object.order = 1;
  s_object.pixels = kDcSkinFrames[frame];
  PpuSetExtraObjects(g_ppu, &s_object, 1);
}

void DcSkin_AfterDraw(void) {
  if (!s_enabled || !g_ppu) return;
  PpuSetExtraObjects(g_ppu, NULL, 0);
  if (!s_saved) return;
  uint8_t *oam = (uint8_t *)g_ppu->oam;
  for (int slot = 0; slot < DC_SKIN_SLOTS; ++slot) {
    if (s_saved_valid[slot]) memcpy(&oam[slot * 4], s_saved_oam[slot], 4);
  }
  s_saved = false;
}
