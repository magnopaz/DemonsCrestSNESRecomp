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

/* Capture the native viewport for world-keyed margin history. Called from
 * end_sim_frame, after the frame's raster. No-op until the room-map capture
 * lands (plano, Fase 3). */
void DcWidescreenAfterRaster(void);

#ifdef __cplusplus
}
#endif

#endif /* DC_WIDESCREEN_H */
