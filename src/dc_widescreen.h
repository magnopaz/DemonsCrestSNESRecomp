#ifndef DC_WIDESCREEN_H
#define DC_WIDESCREEN_H

#include <stdbool.h>
#include <stdint.h>

#include "dc_display.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Demon's Crest widescreen policy. See docs/WIDESCREEN_PLAN.md.
 *
 * The frame is widened by the host (SnesDesktopHostGame.native_widescreen),
 * which publishes PpuSetExtraSpace every frame in prepare_frame. This module
 * publishes the per-frame layer policies in begin_sim_frame, after that call
 * (PpuSetExtraSpace* clears the layer policies, so the order matters).
 *
 * The effective switch is g_config.widescreen: both the mod package and the
 * launcher's Widescreen control drive it. With it off, every function here is
 * a no-op and presentation stays authentically 4:3.
 */

/* Aspect selected by the mod's option (DC_ASPECT_*); owned by the plugin. */
extern DcRenderAspect g_dc_aspect;

/* Reset mod-owned state (runtime reset callback / mod disabled). */
void DcWidescreenReset(void);

/* Publish this frame's policies. Called from begin_sim_frame. */
void DcWidescreenConfigureFrame(void);

/* Measure this frame's margins (staged vs. unstaged columns) before the
 * raster; the per-frame policy and the opt-in repair both read the result. */
void DcWidescreenTrackMargins(void);

/* Right-margin columns the engine has not staged for the world they are drawn
 * for (0 when the margin is trustworthy). */
int DcWidescreenStaleMarginPixels(void);

/* Left-margin columns the engine has not staged for the world they are drawn
 * for (0 when the margin is trustworthy, `margin` when none of it is staged).
 * The trailing margin is the one the streamer rewrites last, so it holds the
 * ring's previous page after a revolution and at a level's start. */
int DcWidescreenStaleLeftMarginPixels(void);

/* Exclusive logical x of BG1's first unstaged right-margin pixel, or the
 * widened field's right edge when every margin pixel is staged. 0 means no
 * measurement/no clip. */
int DcWidescreenBg1RightEdge(void);

/* Margin clip policy switch (SNESRECOMP_WS_MARGIN_CLAMP=0 disables it for
 * A/B captures; the historical switch name is retained). */
int DcWidescreenMarginClampEnabled(void);

/* Extra 8-px BG1 map columns the room restream must stage beyond the engine's
 * own 304-px lookahead so the leading margin is stage-fresh all the way out.
 * 0 = the authentic budget (4:3 and any margin <= 48 px stay bit-identical).
 * Forced by SNESRECOMP_WS_STREAM_AHEAD=<columns> for A/B captures. */
int DcWsStreamAheadColumns(void);

/* The same in map-writer calls (the writer stages 2 columns per call). The
 * restream runs on the interpreter tier and cannot be hooked, so this is paid
 * from the AOT per-frame tracker instead (see DcWsStreamCatchUpArm below). */
int DcWsStreamAheadIters(void);

/* Per-frame poll of the ring cursor ($00D0): arms the catch-up when the cursor
 * shows the room restream's 4-columns-per-frame burst (two frames in a row, so a
 * state load or a camera jump cannot arm it). Call once per frame before the
 * guest runs. No-op when the margin is inside the engine's own lookahead. */
void DcWsStreamCatchUpTick(void);

/* Called from the injected $00:CF7D preamble. Returns the number of extra map
 * writer calls owed right now (0 later in the room), and clears the debt. */
int DcWsStreamCatchUpTake(int layer);

/* The scene gate every widescreen policy keys on: stage gameplay (widescreen
 * on, `$00FB` clear, area `$8D` in 1..0x7F, or the Mode 7 overworld's
 * alternate-HUD area). Shared with the staged-window edge repair. */
bool DcWsStageGameplay(void);

/* Capture the native viewport for world-keyed margin history. Called from
 * end_sim_frame, after the frame's raster. No-op until the room-map capture
 * lands (plano, Fase 3). */
void DcWidescreenAfterRaster(void);

/*
 * Far-right background repair (docs/WIDESCREEN.md, "Janela de staging").
 *
 * The engine stages the BG tilemap ring just in time for the native 256-px
 * view: the newest staged column is only ~288..303 px ahead of the camera, so
 * with a wider field the last margin columns (up to one 16-px room cell) still
 * hold a cleared column or a previous room's tiles -- the strip reported while
 * walking. This pass runs on the composed field (end_sim_frame, after the
 * raster) and continues the last staged tile over that band, leaving every
 * staged column untouched. It is a repair, not a reconstruction: the content
 * does not exist yet. No-op at margin 0, outside gameplay, or with
 * SNESRECOMP_WS_EDGE=0; SNESRECOMP_WS_STAGE_LEAD=<px> overrides the measured
 * lead for a room that streams with a different window.
 *
 * `field` is width*height BGRA pixels with rows `pitch` bytes apart.
 *
 * Implemented in src/dc_ws_edge.c together with the measured staging model;
 * the per-frame policy stays in dc_widescreen.c.
 */
void DcWidescreenRepairField(uint8_t *field, unsigned pitch, int width,
                             int height);

/*
 * Fase 4 — objects and sprites in the margins.
 *
 * DcWsObjectCullMargin() is called by the injected generated-code hooks (the
 * bank $82 object loop's cull window and the bank $00/$80 sprite emitter's X
 * test): it widens both by this many pixels per side. 0 restores the
 * authentic windows exactly (the injected expressions then evaluate to the
 * original constants), so the 4:3 path stays bit-identical. Gated by
 * DcWsLiveMargin(): widescreen enabled AND active AND the stage gameplay
 * gate; SNESRECOMP_WS_OAM=0 disables both hooks.
 */
int DcWsObjectCullMargin(void);
int DcWsLiveMargin(void);

#ifdef __cplusplus
}
#endif

#endif /* DC_WIDESCREEN_H */
