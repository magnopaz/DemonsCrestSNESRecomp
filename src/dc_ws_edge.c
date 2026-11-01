/*
 * Demon's Crest — staged-window margin measurement.
 *
 * The engine streams its BG tilemaps just in time for the authentic 256-pixel
 * view, and how far it stages ahead is not constant: measured from the owner's
 * saves, the newest staged column sits 34..42 px past the native edge while
 * walking, up to ~48 px after a room load, and at the native edge itself at a
 * level's end. Beyond that the ring still holds whatever it last held — often
 * the previous page, which is how the level's *entrance* gate (the shop area)
 * ended up drawn at the level's exit.
 *
 * This unit measures that instead of guessing: the BG tilemap lives in VRAM at
 * `(bgXsc & 0xfc) << 8` words (BG1 0x9000/0x9800 bytes, BG2 0x8000/0x8800), the
 * engine is its only writer, and a column whose entries changed since the
 * previous frame was just restaged for the world it now serves. Each column
 * records the world its content belongs to; a margin pixel is *known* when its
 * column's world equals the world the pixel samples, and stale when the camera
 * has travelled a ring (512 px) without a restage.
 *
 * Two things consume the measurement:
 *
 *  - `DcWidescreenStaleMarginPixels()`, used by the per-frame policy: when most
 *    of the right margin is stale, dc_widescreen.c clamps BG1 to the authentic
 *    256 columns for that frame. The margin then shows the layers *below* the
 *    level geometry (the parallax city, the backdrop) — real content, never
 *    invented pixels, and no foreign gate.
 *  - `DcWidescreenRepairField()`, an opt-in diagnostic (`SNESRECOMP_WS_EDGE=1`,
 *    off by default) that instead continues the last staged 8-px tile over the
 *    stale band on the composed field. It is off by default because the engine
 *    is often only a few pixels behind, and replacing real margin content with a
 *    repeat reads as an artifact.
 *
 * Kill switches / diagnostics: `SNESRECOMP_WS_EDGE=0/1` (repair off/on),
 * `SNESRECOMP_WS_EDGE_DEBUG=1` (per-frame tracker state on stderr).
 *
 * The permanent fix is on the engine side: make the streamer stage `margin`
 * pixels further ahead (its room-cell cursor is camera driven), or expand the
 * room's metatiles host-side with WsShadowPrefillTile. Both are tracked in
 * docs/WIDESCREEN.md. */

#include "dc_widescreen.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "snes/ppu.h"
#include "widescreen.h"

extern Ppu *g_ppu;

enum {
    /* The BG tilemap ring: 64 columns of 8 px = 512 px (this game uses a
     * 64x32 map; a 32x32 map would be 256 px and is handled too). */
    DC_WS_MAP_COLS_MAX = 64,
    DC_WS_MAP_ROWS = 32,
    /* Native view width: everything inside it is the engine's guarantee. */
    DC_WS_NATIVE = 256,
    /* Width of the tile the opt-in repair repeats over the band. */
    DC_WS_TILE = 8,
};

typedef struct {
    int inited;
    int base_words;                  /* BG map base, PPU word index */
    int cols;                        /* 32 or 64 */
    int margin;                      /* current frame's widescreen margin */
    int ring;                        /* cols * 8 px */
    int last_h;                      /* raw hScroll of the previous frame */
    int32_t cam;                     /* unwrapped camera in world px */
    int32_t known[DC_WS_MAP_COLS_MAX]; /* world of each column's content */
    uint16_t snap[DC_WS_MAP_COLS_MAX * DC_WS_MAP_ROWS];
} DcEdgeTrack;

static DcEdgeTrack s_track[2]; /* BG1, BG2 */
static int s_tracks;           /* how many tracks are valid this frame */

/* Result of the current frame's measurement (begin_sim_frame decides with it). */
static int s_margin;           /* margin the measurement was taken with */
static int s_first_bad = -1;   /* first right-margin pixel the engine has not staged */
static int s_first_known_left = 0; /* first left-margin pixel that is staged */

static int DcEdgeDebug(void) {
    static int on = -1;
    if (on < 0) {
        const char *env = getenv("SNESRECOMP_WS_EDGE_DEBUG");
        on = env && env[0] && env[0] != '0';
    }
    return on;
}

static int DcEdgeRepairEnabled(void) {
    /* OFF by default: the clamp above already keeps foreign content out of the
     * margins while leaving real content alone, and the continuation replaces
     * real content wherever the engine is only a few pixels behind. */
    static int enabled = -1;
    if (enabled < 0) {
        const char *env = getenv("SNESRECOMP_WS_EDGE");
        enabled = env && env[0] ? (env[0] != '0') : 0;
    }
    return enabled;
}

static int DcWrapMod(int v, int m) {
    int r = v % m;
    if (r < 0)
        r += m;
    return r;
}

/* World position (multiple of 8) of the content in ring column `c`. The engine
 * writes a column just before it comes into view, so the world is the camera
 * plus the column's current screen offset; no period adjustment is needed --
 * the pixel test compares absolute worlds, which is exactly what detects a ring
 * revolution the engine has not restaged yet. */
static int32_t DcColumnWorld(const DcEdgeTrack *t, int c) {
    return (int32_t)t->cam + DcWrapMod(c * DC_WS_TILE - (int)t->cam, t->ring);
}

static const uint16_t *DcMapColumn(const DcEdgeTrack *t, int c) {
    /* 64-wide maps store columns 32..63 in the next 32x32 block (0x400 words). */
    int block = (c >> 5) * 0x400;
    return &g_ppu->vram[t->base_words + block + (c & 31)];
}

/* Row stride inside a 32-entry-wide block. */
#define DC_WS_MAP_STRIDE 32

/* Snapshot/compare one column: returns 1 when any entry changed. */
static int DcColumnChanged(DcEdgeTrack *t, int c) {
    const uint16_t *src = DcMapColumn(t, c);
    uint16_t *old = &t->snap[c * DC_WS_MAP_ROWS];
    int changed = 0;
    for (int r = 0; r < DC_WS_MAP_ROWS; ++r) {
        uint16_t v = src[r * DC_WS_MAP_STRIDE];
        if (v != old[r])
            changed = 1;
        old[r] = v;
    }
    return changed;
}

/* Start (or restart) tracking. The engine's guarantee is the native view, and
 * everything *behind* the camera was staged when the camera passed it, so the
 * whole ring behind the camera plus the native view count as known. The right
 * margin is not known until the engine restages it -- that is the band the
 * clamp and the opt-in repair exist for. */
static void DcEdgeRestart(DcEdgeTrack *t, const Ppu *ppu, int layer, int h) {
    uint8_t sc = ppu->bgXsc[layer];
    t->base_words = (int)((sc & 0xfc) << 8);
    t->cols = (sc & 1) ? 64 : 32;
    t->ring = t->cols * DC_WS_TILE;
    t->last_h = h;
    t->cam = h;
    for (int c = 0; c < DC_WS_MAP_COLS_MAX; ++c) {
        t->known[c] = INT32_MIN;
        if (c < t->cols) {
            int x = DcWrapMod(c * DC_WS_TILE - h, t->ring);
            /* Native view, plus the columns that just wrapped past the camera's
             * left edge (those were staged while the camera crossed them). */
            if (x < DC_WS_NATIVE)
                t->known[c] = (int32_t)h + x;
            else if (x >= t->ring - t->margin)
                t->known[c] = (int32_t)h + x - t->ring; /* behind the camera */
        }
    }
    for (int c = 0; c < t->cols; ++c)
        (void)DcColumnChanged(t, c); /* prime the snapshot */
    t->inited = 1;
}

/* Advance tracking by one frame; returns 0 when tracking is not usable. */
static int DcEdgeTrackFrame(DcEdgeTrack *t, const Ppu *ppu, int layer,
                            int margin) {
    if (ppu->bgmode == 7)
        return 0; /* Mode 7 has no tilemap ring; leave the overworld alone. */
    int h = (int)(ppu->hScroll[layer] & 0x3ff);
    t->margin = margin;
    if (!t->inited) {
        DcEdgeRestart(t, ppu, layer, h);
        return 1;
    }
    uint8_t sc = ppu->bgXsc[layer];
    int base_words = (int)((sc & 0xfc) << 8);
    int cols = (sc & 1) ? 64 : 32;
    if (base_words != t->base_words || cols != t->cols) {
        /* Room/scene switch: the map moved, nothing is known any more. */
        DcEdgeRestart(t, ppu, layer, h);
        return 1;
    }
    int delta = DcWrapMod(h - t->last_h + 512, 1024) - 512;
    if (delta > 200 || delta < -200) {
        /* Door transition or a camera jump; the map is rebuilt. */
        DcEdgeRestart(t, ppu, layer, h);
        return 1;
    }
    t->cam += delta;
    t->last_h = h;
    for (int c = 0; c < t->cols; ++c) {
        if (DcColumnChanged(t, c))
            t->known[c] = DcColumnWorld(t, c);
    }
    return 1;
}

/* Staging state of the pixel at logical x for one layer:
 *   1  staged for the world it is drawn for
 *   0  staged for a different world (the ring wrapped: definitely stale)
 *  -1  never observed (the layer was not restaged since tracking started) */
static int DcEdgePixelState(const DcEdgeTrack *t, int x) {
    int32_t world = t->cam + x;
    int32_t tile = world & ~(int32_t)(DC_WS_TILE - 1);
    if (tile < 0)
        return 0; /* before the level's start there is nothing to sample */
    int c = DcWrapMod((int)(tile % t->ring), t->ring) / DC_WS_TILE;
    if (t->known[c] == INT32_MIN)
        return -1;
    return t->known[c] == tile;
}

/* 1 when the composed pixel at logical x is backed by content the engine has
 * staged for that world. BG1 anchors the decision: its right margin is only
 * trusted once the engine restages it. BG2 rides along because it shows through
 * BG1's gaps, but a BG2 column that was never observed is not enough to call an
 * otherwise valid margin stale. */
static int DcEdgeKnown(int x) {
    int bg1 = DcEdgePixelState(&s_track[0], x);
    if (bg1 <= 0)
        return 0;
    for (int i = 1; i < s_tracks; ++i) {
        if (DcEdgePixelState(&s_track[i], x) == 0)
            return 0;
    }
    return 1;
}

/* Measure this frame's margins. Called once per frame from begin_sim_frame,
 * before the raster, so the policy can act on the same frame. */
void DcWidescreenTrackMargins(void) {
    s_margin = 0;
    s_first_bad = -1;
    s_first_known_left = 0;
    if (!g_ppu)
        return;
    if (!DcDisplay_IsWidescreenEnabled() || !DcDisplay_IsWidescreenActive())
        return;
    if (!DcWsStageGameplay())
        return;
    const int margin = g_ws_extra;
    if (margin <= 0)
        return;

    s_tracks = 0;
    if ((g_ppu->screenEnabled[0] & 0x01) &&
        DcEdgeTrackFrame(&s_track[0], g_ppu, 0, margin))
        s_tracks = 1;
    if (s_tracks && (g_ppu->screenEnabled[0] & 0x02)) {
        if (DcEdgeTrackFrame(&s_track[1], g_ppu, 1, margin))
            s_tracks = 2;
    } else {
        s_track[1].inited = 0;
    }
    if (!s_tracks)
        return;
    s_margin = margin;

    for (int x = DC_WS_NATIVE; x < DC_WS_NATIVE + margin; ++x) {
        if (!DcEdgeKnown(x)) {
            s_first_bad = x;
            break;
        }
    }
    for (int x = -margin; x < 0; ++x) {
        if (DcEdgeKnown(x)) {
            s_first_known_left = x;
            break;
        }
    }

    if (DcEdgeDebug()) {
        int known_n = 0;
        for (int x = -margin; x < DC_WS_NATIVE + margin; ++x)
            known_n += DcEdgeKnown(x);
        fprintf(stderr,
                "[wsedge] cam=%d h0=%d cols=%d ring=%d tracks=%d known=%d/%d "
                "first_bad=%d\n",
                (int)s_track[0].cam, (int)(g_ppu->hScroll[0] & 0x3ff),
                s_track[0].cols, s_track[0].ring, s_tracks, known_n,
                DC_WS_NATIVE + 2 * margin, s_first_bad);
    }
}

/* Diagnostic kill switch for the margin clamp (A/B captures). */
int DcWidescreenMarginClampEnabled(void) {
    static int on = -1;
    if (on < 0) {
        const char *env = getenv("SNESRECOMP_WS_MARGIN_CLAMP");
        on = env && env[0] ? (env[0] != '0') : 1;
    }
    return on;
}

/* How many columns of the right margin the engine has not staged for the world
 * they are drawn for. 0 when the margin is trustworthy. */
int DcWidescreenStaleMarginPixels(void) {
    if (s_first_bad < 0 || s_margin <= 0)
        return 0;
    return DC_WS_NATIVE + s_margin - s_first_bad;
}

/* Copy one BGRA pixel between logical x positions (the margin maps them onto
 * the buffer); rows are independent, so the caller loops over rows. */
static void DcEdgeCopy(uint8_t *row, int margin, int dst, int src) {
    memcpy(row + (size_t)(dst + margin) * 4, row + (size_t)(src + margin) * 4,
           4);
}

/* Opt-in diagnostic: continue the last staged tile over the band the engine has
 * not staged. Inert unless SNESRECOMP_WS_EDGE=1. */
void DcWidescreenRepairField(uint8_t *field, unsigned pitch, int width,
                             int height) {
    if (!field || width <= 0 || height <= 0 || !g_ppu)
        return;
    if (!DcEdgeRepairEnabled())
        return;
    if (!DcDisplay_IsWidescreenEnabled() || !DcDisplay_IsWidescreenActive())
        return;
    const int margin = s_margin;
    if (margin <= 0 || width != DC_WS_NATIVE + 2 * margin)
        return;
    if (s_first_bad < 0 && s_first_known_left <= -margin)
        return;

    for (int y = 0; y < height; ++y) {
        uint8_t *row = field + (size_t)y * pitch;
        for (int x = s_first_known_left - 1; x >= -margin; --x) {
            int src = s_first_known_left +
                      ((x - s_first_known_left) & (DC_WS_TILE - 1));
            if (src > DC_WS_NATIVE + margin - 1)
                src = DC_WS_NATIVE + margin - 1;
            DcEdgeCopy(row, margin, x, src);
        }
        if (s_first_bad >= 0) {
            for (int x = s_first_bad; x < DC_WS_NATIVE + margin; ++x) {
                int src = s_first_bad - DC_WS_TILE +
                          ((x - s_first_bad) & (DC_WS_TILE - 1));
                if (src < -margin)
                    src = -margin;
                DcEdgeCopy(row, margin, x, src);
            }
        }
    }
}
