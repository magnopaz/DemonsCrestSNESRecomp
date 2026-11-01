/*
 * Demon's Crest — staged-window edge repair.
 *
 * The engine stages the BG tilemaps just in time for the authentic 256-px
 * view, so the outer columns of a widened field can still hold a cleared
 * column or a previous room's tiles. This unit owns the measured staging model
 * and the post-raster repair that continues the picture over that band; the
 * per-frame policy (gate, clamps, HUD anchoring) lives in dc_widescreen.c.
 *
 * See dc_widescreen.h for the public contract and docs/WIDESCREEN.md
 * ("Janela de staging") for the measurements.
 */

#include "dc_widescreen.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "snes/ppu.h"
#include "widescreen.h"

extern Ppu *g_ppu;

/* ───────────── Staged-window edge repair (far-right background) ────────────
 *
 * The engine does not keep a "bigger framebuffer" for the BG tilemaps: it
 * stages them for the authentic 256-px view, just in time, one 16x16 room cell
 * at a time. Measured from the engine's own tilemap writes (docs/WIDESCREEN.md,
 * "Janela de staging"), the staged world window for the live camera is
 *
 *     [frontier - 512, frontier)      (the BG tilemap ring is 64x32 = 512 px)
 *     frontier = 16 * floor((camera + DC_WS_STAGE_LEAD) / 16)
 *
 * so the newest staged column is 288..303 px ahead of the camera. The left
 * margin (at most ~209 px of ring behind the camera) is therefore always
 * authentic, but the right margin asks for world past the frontier: those
 * columns still hold whatever the engine last wrote -- a cleared column, or a
 * previous room's tiles. That band, up to one 16-px room cell at the far right,
 * is the artifact reported while walking.
 *
 * This is a *repair*, not a reconstruction: the engine has not produced the
 * content for those columns yet, so nothing host-side can show the real thing.
 * Repeating the last staged 8-px tile over the band continues the picture with
 * the correct phase instead of showing cleared or foreign art, and leaves
 * every column the engine did stage bit-identical. It runs on the composed
 * field, after the raster, so it cannot disturb guest state or the PPU's
 * rendering of the staged columns. The pass works on composed pixels, so a
 * sprite inside the band is replaced by the background continuation as well --
 * that is the same band whose background is invalid, and it is at most 16 px
 * wide. At margin 0 (authentic 4:3) no band exists and the pass does nothing.
 * Kill switch: SNESRECOMP_WS_EDGE=0; SNESRECOMP_WS_STAGE_LEAD=<px> overrides
 * the measured lead.
 *
 * The permanent fix is on the engine side: make the streamer stage
 * DC_WS_STAGE_LEAD + margin pixels ahead (its room-cell cursor is camera
 * driven, so a +margin bias in that comparison is enough), or expand the
 * room's metatiles host-side with WsShadowPrefillTile. Both are tracked in
 * docs/WIDESCREEN.md. */

enum {
    /* Measured lookahead of the engine's tilemap staging window. */
    DC_WS_STAGE_LEAD = 304,
    /* The engine stages whole 16x16 room cells. */
    DC_WS_STAGE_CELL = 16,
    /* Width of the tile the repair repeats over the band. */
    DC_WS_TILE = 8,
};

static int DcEdgeRepairEnabled(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *env = getenv("SNESRECOMP_WS_EDGE");
        enabled = env && env[0] ? (env[0] != '0') : 1;
    }
    return enabled;
}

static int DcStageLead(void) {
    static int lead = -1;
    if (lead < 0) {
        const char *env = getenv("SNESRECOMP_WS_STAGE_LEAD");
        lead = env && env[0] ? atoi(env) : DC_WS_STAGE_LEAD;
        if (lead < 256)
            lead = 256; /* the frontier must at least reach the native edge */
        if (lead > 0x3ff)
            lead = 0x3ff;
    }
    return lead;
}

/* Ring-relative positions of the staged window for the live camera. `ahead` is
 * how far the newest staged column is ahead of the camera (288..303 with the
 * measured lead); `behind` is how much staged world the 512-px ring still has
 * behind the camera (209..224). */
static void DcStagedWindow(int *ahead, int *behind) {
    const int cam = (int)(g_ppu->hScroll[0] & 0x3ff);
    const int cell = DC_WS_STAGE_CELL;
    const int frontier = ((cam + DcStageLead()) / cell * cell) & 0x1ff;
    int a = frontier - cam;
    if (a < 0)
        a += 0x200;
    if (ahead)
        *ahead = a;
    if (behind)
        *behind = 0x200 - a;
}

/* Repair the composed field in place. `field` holds BGRA rows of `pitch` bytes
 * at `width` pixels; the widened field starts at the left margin, so logical x
 * maps to buffer column x + margin. Called from end_sim_frame, after the
 * raster and before the field is presented or dumped. */
void DcWidescreenRepairField(uint8_t *field, unsigned pitch, int width,
                             int height) {
    if (!field || width <= 0 || height <= 0)
        return;
    if (!DcEdgeRepairEnabled() || !g_ppu)
        return;
    if (!DcDisplay_IsWidescreenEnabled() || !DcDisplay_IsWidescreenActive())
        return;
    if (!DcWsStageGameplay())
        return;
    const int margin = g_ws_extra;
    if (margin <= 0 || width != 256 + 2 * margin)
        return;
    int ahead = 0, behind = 0;
    DcStagedWindow(&ahead, &behind);
    const int right_from = ahead;              /* logical x */
    const int right_to = 256 + margin;         /* logical x, exclusive */
    const int left_from = -behind;             /* logical x of the ring's end */
    for (int y = 0; y < height; ++y) {
        uint8_t *row = field + (size_t)y * pitch;
        for (int x = right_from; x < right_to; ++x) {
            /* Same tile phase, last staged tile: continues the picture. */
            int src = right_from - DC_WS_TILE +
                      ((x - right_from) & (DC_WS_TILE - 1));
            if (src < 256 - margin)
                src = 256 - margin;
            memcpy(row + (size_t)(x + margin) * 4,
                   row + (size_t)(src + margin) * 4, 4);
        }
        /* Left margin outside the 512-px ring (only for a field wider than
         * ~2x209 px of margin, i.e. 32:9): repeat the first staged tile. */
        for (int x = left_from - 1; x >= -margin; --x) {
            int src = left_from + ((left_from - 1 - x) & (DC_WS_TILE - 1));
            if (src > 256 + margin - 1)
                src = 256 + margin - 1;
            memcpy(row + (size_t)(x + margin) * 4,
                   row + (size_t)(src + margin) * 4, 4);
        }
    }
}
