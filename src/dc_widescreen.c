/*
 * Demon's Crest — widescreen scene policy.
 *
 * Fase 1/2 of docs/WIDESCREEN_PLAN.md:
 *   - outside stage gameplay (logos, intro, title, file select, password,
 *     cutscenes) every BG layer is clamped, so the authentic 256-column
 *     picture sits centered in the widened surface with only the backdrop in
 *     the side margins (a real pillarbox, not stale pixels);
 *   - in stage gameplay BG1/BG2 render into the margins while BG3 — the
 *     upper-left status bar ($80:C9xx, VRAM $5800) — stays inside its
 *     authentic columns.
 *
 * Fase 3: the margins are served from the framework's world-keyed tilemap
 * store (snes/ws_shadow.c) instead of the streamed VRAM window. That store
 * is the "bigger framebuffer" this game needs: 4096x512 tiles, keyed by the
 * world camera, fed by the native viewport sweep AND by the game's own VRAM
 * uploads at write time (WsShadowOnVramWrite) — so content the game stages
 * ahead of the view is available to the margins the moment it is written.
 * Without it, a scroll shows the streamed window's stale columns in the
 * gutter until the game rewrites them.
 *
 * PpuSetExtraSpaceCentered is deliberately NOT used here: it renders the
 * native columns without writing the side margins at all (the caller would
 * have to clear them), so a reused host buffer would show the previous
 * scene's pixels there.
 */

#include "dc_widescreen.h"

#include <stdio.h>
#include <stdlib.h>

#include "desktop/config.h"
#include "snes/ppu.h"
#include "snes/ws_shadow.h"
#include "widescreen.h"

extern uint8_t g_ram[0x20000];
extern Ppu *g_ppu;

DcRenderAspect g_dc_aspect = DC_ASPECT_ADAPTIVE;

void DcWidescreenReset(void) {
    g_dc_aspect = DC_ASPECT_ADAPTIVE;
}

/*
 * Gameplay gate. $8D is the area index the engine keys its per-stage tables
 * on ($80:C114, $84:9C5B, ...). The HUD builder's own range test at $80:C948
 * reads it as: 0 = no stage (menus/intro), 1..$7F = a stage area (the
 * per-area tables have entries across that whole span), $80..$9F = no HUD
 * screen, >= $A0 = the alternate HUD variant. Until Fase 2 proves the exact
 * in-stage screens with watchpoints (including whether >= $A0 areas are
 * playable rooms), only the unambiguous 1..$7F span widens.
 * SNESRECOMP_WS_GATE=1/0 forces the verdict so those measurements can compare
 * both modes without editing code.
 */
static bool DcStageGameplay(void) {
    static int forced = -2;
    if (forced == -2) {
        const char *env = getenv("SNESRECOMP_WS_GATE");
        forced = env && env[0] ? (env[0] != '0') : -1;
    }
    if (forced >= 0)
        return forced != 0;
    /* The start/status menu is a full-screen native UI (its own BG1/BG2
     * tilemap in the middle of a 32x32 map). Widening it shows the stage
     * tilemap in the margins as garbage; $00FB is 1 while it is open. */
    if (g_ram[0x00FB])
        return false;
    const uint8_t area = g_ram[0x8D];
    if (area != 0 && area < 0x80)
        return true;
    /* The flying overworld map uses the alternate HUD variant (>= $A0) and
     * renders in PPU Mode 7. Menus, the title and transitional screens are
     * Mode 1 (or area 0), so this combination is the playable map and can
     * take the widened field like a stage. */
    if (area >= 0xA0 && g_ppu && (g_ppu->bgmode & 7) == 7)
        return true;
    return false;
}

static void DcClearPolicies(void) {
    PpuSetWidescreenLayerClamp(g_ppu, 0);
    PpuSetWidescreenLayerMask(g_ppu, 0);
    PpuSetWidescreenBg3Widen(g_ppu, 0);
    PpuSetWsHudOamShiftRange(g_ppu, 0, 0);
    PpuSetWsHudOamShiftRange2(g_ppu, 0, 0);
    PpuSetWidescreenHudSplit(g_ppu, 0, 0, 0);
    PpuSetWidescreenLayerElasticBand(g_ppu, 2, 0, 0, NULL, 0);
    PpuSetIgnoreForcedBlank(g_ppu, false);
    PpuSetWidescreenLineEnhancer(g_ppu, NULL, NULL);
}

/* History retention window per side, in tiles. The widest margin is 213px
 * at 32:9 (~27 tiles); 32 covers the whole visible gutter plus the write
 * capture's ahead-of-view chunk staging. */
enum { DC_WS_KEEP_TILES = 32 };

/* Margin history switch, DEFAULT OFF (2026-10-18).
 *
 * The world-keyed store is fed by the native viewport sweep and by the
 * game's VRAM uploads, but ground-truth checks (a 256px camera shift with
 * the frame buffer as oracle) show its world keys do not match Demon's
 * Crest's actual tilemap window: the west (trailing) margin differed from
 * the same world region when it later became native in ~65% of pixels, the
 * east margin in ~78%. The margins then scroll at the right rate but show
 * the wrong section, which reads as a visibly different band. The
 * framework's model assumes a ring window anchored at the pixel scroll;
 * this game's streamer (and likely its per-line HDMA scrolls) does not
 * satisfy it. Until the window rule is derived, the raw streamed VRAM is
 * the better default: wrong content in the trailing gutter, but motion
 * identical to the rest of the screen.
 *
 * SNESRECOMP_WS_HISTORY=1 re-enables the history path for experiments. */
static bool DcHistoryEnabled(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *env = getenv("SNESRECOMP_WS_HISTORY");
        enabled = env && env[0] && env[0] != '0';
    }
    return enabled != 0;
}

/*
 * Register one BG layer for world-keyed margin history. `world_x/y` is the
 * layer's own world origin (the game's 16-bit camera/parallax mirror); the
 * PPU's live scroll supplies the VRAM window phase (P1: phase from the PPU,
 * high bits from the game mirror). Must run every frame: the registration
 * only lives for the frame the sweep consumes.
 */
static void DcRegisterLayerHistory(int layer, uint16_t world_x,
                                   uint16_t world_y) {
    WsShadowSetWorld(layer, world_x, world_y);
    WsShadowSetScroll(layer, g_ppu->hScroll[layer], g_ppu->vScroll[layer]);
    /* World-row keys (no retainHistory): the viewport sweep and the
     * write-time capture then use the same Y key space. The retainHistory
     * variant keys Y by viewport row, which the write capture does not
     * (it uses world rows), so ahead-of-view uploads would never be read.
     * Demon's Crest has no elevator-style viewport rewrite to model. */
    WsShadowSetRetainHistory(layer, false);
}

/* Optional margin accounting: SNESRECOMP_WS_STATS=1 prints hit/miss and
 * fallback counters every 600 frames. A raw fallback is the case history
 * could not answer and the streamed VRAM window was used as-is. */
static void DcMaybePrintMarginStats(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *env = getenv("SNESRECOMP_WS_STATS");
        enabled = env && env[0] && env[0] != '0';
    }
    if (!enabled)
        return;
    static unsigned frames;
    if (++frames % 600)
        return;
    WsShadowMarginStat bg1, bg2;
    WsShadowGetMarginStats(0, &bg1);
    WsShadowGetMarginStats(1, &bg2);
    fprintf(stderr,
            "[ws] bg1 w=%llu/%llu e=%llu/%llu raw=%llu/%llu fold=%llu/%llu | "
            "bg2 w=%llu/%llu e=%llu/%llu raw=%llu/%llu fold=%llu/%llu\n",
            (unsigned long long)bg1.westHit, (unsigned long long)bg1.westMiss,
            (unsigned long long)bg1.eastHit, (unsigned long long)bg1.eastMiss,
            (unsigned long long)bg1.westRawFallback,
            (unsigned long long)bg1.eastRawFallback,
            (unsigned long long)bg1.westFold, (unsigned long long)bg1.eastFold,
            (unsigned long long)bg2.westHit, (unsigned long long)bg2.westMiss,
            (unsigned long long)bg2.eastHit, (unsigned long long)bg2.eastMiss,
            (unsigned long long)bg2.westRawFallback,
            (unsigned long long)bg2.eastRawFallback,
            (unsigned long long)bg2.westFold, (unsigned long long)bg2.eastFold);
}

/* ───────────────────────── Fase 6: status bar (BG3) ───────────────────────
 *
 * BG3 carries only the status bar: a left-anchored strip in the upper-left.
 * The VRAM map ($5800, 32x32) holds it on rows 1..5 (native y 8..47) at map
 * columns 3..29 (native x 24..239) — measured from a save-state dump; the rest
 * of the map is empty. In the widened field the bar would sit at native x 24,
 * leaving the whole left margin empty to its left.
 *
 * On the bar's scanlines BG3 is remapped as ONE RIGID segment shifted left by
 * the live margin (source [0,256) -> destination [-margin, 256-margin)): the
 * bar hugs the left edge of the widened field, and every column the remap does
 * not cover stays transparent, so the scenery shows through where the bar used
 * to sit. Below the band BG3 keeps its authentic position.
 *
 * The band is re-applied every frame (ppu_reset zeroes it). margin 0 is the
 * identity remap, i.e. the authentic 4:3 layout; SNESRECOMP_WS_HUD=0 disables
 * it. BG3 must be allowed into the widened line (PpuSetWidescreenBg3Widen) for
 * the band to be live: PpuWidescreenLayerExtra gates it, and the band's merge
 * then ignores the layer's own margin content and copies only the shifted
 * source span. That is also why BG3 is no longer clamped in gameplay — the
 * remap, not the clamp, keeps it in place.
 */
enum {
    DC_HUD_BAND_Y0 = 0,
    DC_HUD_BAND_Y1 = 48,
};

static int DcHudAnchorEnabled(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *env = getenv("SNESRECOMP_WS_HUD");
        enabled = env && env[0] ? (env[0] != '0') : 1;
    }
    return enabled;
}

static void DcAnchorStatusBar(void) {
    int m = g_ws_extra;
    if (!DcHudAnchorEnabled() || m <= 0) {
        PpuSetWidescreenBg3Widen(g_ppu, 0);
        PpuSetWidescreenLayerElasticBand(g_ppu, 2, 0, 0, NULL, 0);
        return;
    }
    if (m > kPpuExtraLeftRight)
        m = kPpuExtraLeftRight;
    /* The elastic band places the bar by remapping BG3's own columns, but the
     * band's merge only reaches the margins when BG3 is allowed to widen on
     * those scanlines. Widen BG3 ONLY on the band's rows: the dialogue box
     * lives on the same layer below it, and widening those rows wrapped its
     * options into the left margin ("NO" at x=0). */
    PpuSetWidescreenBg3WidenRange(g_ppu, 1, DC_HUD_BAND_Y1);
    PpuWsElasticSeg seg;
    seg.srcX0 = 0;
    seg.srcX1 = 256;
    seg.dstX0 = (int16_t)(-m);
    seg.dstX1 = (int16_t)(256 - m);
    PpuSetWidescreenLayerElasticBand(g_ppu, 2, DC_HUD_BAND_Y0, DC_HUD_BAND_Y1,
                                     &seg, 1);
}

/* Fase 7-ish (2026-10-19): the game covers its per-frame uploads with INIDISP
 * forced blank ($2100 = $80) and a "present" task unblanks later. This frame
 * model runs the CPU half before the raster walk, so the upload is never
 * visible; replaying the blank only darkens the first N visible lines, and N
 * varies with the frame's work (the top-of-screen band flicker the owner
 * reported). PpuSetIgnoreForcedBlank drops those writes from the render
 * replay while leaving brightness fades alone. Gameplay only: transitional
 * fields keep the authentic blank. SNESRECOMP_WS_NOBLANK=0 disables it. */
static int DcNoBlankEnabled(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *env = getenv("SNESRECOMP_WS_NOBLANK");
        enabled = env && env[0] ? (env[0] != '0') : 1;
    }
    return enabled;
}

void DcWidescreenConfigureFrame(void) {
    if (!g_ppu)
        return;

    if (!DcDisplay_IsWidescreenEnabled() || !DcDisplay_IsWidescreenActive()) {
        DcClearPolicies();
        /* The upload-cover policy (transient forced blank + HDMA disable
         * around the game's per-frame upload) is a frame-model correction,
         * not a display width: keep it active at 4:3 and in every scene. The
         * replay keeps a real field-long blank (no later unblank). */
        PpuSetIgnoreForcedBlank(g_ppu, DcNoBlankEnabled());
        return;
    }

    if (!DcStageGameplay()) {
        /* Bounded screens: clamp every BG layer (bits 0-2 = BG1-BG3) so the
         * authentic picture stays centered and the margins show only the
         * backdrop. The host's symmetric PpuSetExtraSpace still writes the
         * whole row, so no stale margin pixels survive a scene change. */
        PpuSetWidescreenLayerClamp(g_ppu, 0x07);
        PpuSetWidescreenLayerMask(g_ppu, 0);
        PpuSetWidescreenBg3Widen(g_ppu, 0);
        PpuSetWsHudOamShiftRange(g_ppu, 0, 0);
        PpuSetWsHudOamShiftRange2(g_ppu, 0, 0);
        PpuSetWidescreenLayerElasticBand(g_ppu, 2, 0, 0, NULL, 0);
        PpuSetIgnoreForcedBlank(g_ppu, DcNoBlankEnabled());
        PpuSetWidescreenLineEnhancer(g_ppu, NULL, NULL);
        return;
    }

    /* Stage gameplay.
     * BG3 (layer index 2) is the status bar: DcAnchorStatusBar() remaps it to
     * the widened left edge on the bar's scanlines (Fase 6). BG1/BG2 extend
     * into the margins. */
    PpuSetWidescreenLayerClamp(g_ppu, 0);
    PpuSetWidescreenLayerMask(g_ppu, 0);
    PpuSetWidescreenBg3Widen(g_ppu, 0);
    PpuSetWsHudOamShiftRange(g_ppu, 0, 0);
    PpuSetWsHudOamShiftRange2(g_ppu, 0, 0);
    PpuSetWidescreenLineEnhancer(g_ppu, NULL, NULL);
    DcAnchorStatusBar();
    PpuSetIgnoreForcedBlank(g_ppu, DcNoBlankEnabled());

    /* World-keyed margin history. BG1's world origin is the game camera
     * ($C0/$C4, 16-bit); BG2's is its own parallax mirror ($C2/$C6). The
     * room loader swaps BG1SC/BG2SC per room, but the scroll mirrors keep
     * their meaning: $A2/$A6 (BG1) always carry the camera. */
    if (DcHistoryEnabled()) {
        DcRegisterLayerHistory(0, (uint16_t)(g_ram[0xC0] | (g_ram[0xC1] << 8)),
                               (uint16_t)(g_ram[0xC4] | (g_ram[0xC5] << 8)));
        DcRegisterLayerHistory(1, (uint16_t)(g_ram[0xC2] | (g_ram[0xC3] << 8)),
                               (uint16_t)(g_ram[0xC6] | (g_ram[0xC7] << 8)));
    }
}

void DcWidescreenAfterRaster(void) {
    if (!g_ppu || !DcDisplay_IsWidescreenEnabled())
        return;
    /* Capture this frame's native viewport into the world-keyed store. The
     * game's own VRAM uploads are captured at write time by the framework,
     * so ahead-of-view staging is already in the history. */
    WsShadowFrame(g_ppu);
    DcMaybePrintMarginStats();
}

/* ─────────────────────── Fase 4: objects and sprites ──────────────────────
 *
 * The authentic object loop (bank $82) culls an object when its camera-
 * relative position leaves a fixed window:
 *
 *     dx = objX - camX;   keep if (dx + 0x60) < 0x1C0      (X)
 *     dy = objY - camY;   keep if (dy + 0x60) < 0x1A0      (Y)
 *
 * i.e. dx in [-0x60, 0x160) = [-96, 352): the 256-px native view plus 96 px
 * of slack on each side (sprite widths, activation). The injected hook
 * (tools/dc_apply_widescreen_hooks.py) replaces the two constants with
 * 0x60 + margin and 0x1C0/0x1A0 + 2*margin, which widens BOTH sides by
 * `margin` without moving the window's base. At margin 0 the expressions
 * evaluate to the authentic constants, so the 4:3 path stays bit-identical.
 *
 * The kept object then computes its screen X/Y ($10/$12), sets its visible
 * bit ($00 bit 4) and writes its OAM entry — which is what puts it in the
 * margins.
 *
 * The sprite emitter (the bank $80/$00 function at $F689, an AOT root) is
 * the other half: its X test at $F755 hides every sprite whose 9-bit OAM X is
 * >= 256 with a low byte < 0xF3. The injected hook keeps the right margin
 * (low byte < margin) and the widened left-edge window (low byte >=
 * 0xF3 - margin) instead, so sprites that the authentic frame clips at the
 * screen edge survive in the margins; everything else keeps the authentic
 * $E0 hide. The framework decodes 256..256+extra as positive (right margin)
 * and >= that as the wrapped left margin (PpuDecodeOamX).
 *
 * Gate: the margins are only widened during stage gameplay with widescreen
 * on — a pillarboxed cutscene must not reveal objects the authentic frame
 * hides. SNESRECOMP_WS_OAM=0 disables both halves for A/B captures.
 */

static int DcOamPolicyEnabled(void) {
    static int enabled = -1;
    if (enabled < 0) {
        const char *env = getenv("SNESRECOMP_WS_OAM");
        enabled = env && env[0] ? (env[0] != '0') : 1;
    }
    return enabled;
}

int DcWsLiveMargin(void) {
    if (!DcOamPolicyEnabled())
        return 0;
    if (!DcDisplay_IsWidescreenEnabled() || !DcDisplay_IsWidescreenActive())
        return 0;
    if (!DcStageGameplay())
        return 0;
    if (g_ws_extra <= 0)
        return 0;
    /* The left-edge window is 13 + margin pixels of a 9-bit OAM position;
     * 0xF3 - margin must stay positive (kPpuExtraLeftRight caps at 272). */
    return g_ws_extra > 0xF0 ? 0xF0 : g_ws_extra;
}

int DcWsObjectCullMargin(void) { return DcWsLiveMargin(); }
