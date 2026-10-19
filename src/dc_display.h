#ifndef DC_DISPLAY_H
#define DC_DISPLAY_H

#include <stdbool.h>
#include <stdint.h>

#include "desktop/display_aspect.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Host-only display controls for Demon's Crest. None of this modifies
 * emulated SNES state: with the widescreen mod off, every function here
 * resolves to the authentic 256x224, 4:3 presentation.
 *
 * The mod's aspect controls the logical field width (Adaptive follows the
 * window; the fixed ratios letterbox as needed). config.ini
 * [Graphics] DisplayAspect keeps selecting the SNES pixel shape
 * independently, exactly as it does for every other port.
 */

typedef enum DcRenderAspect {
    DC_ASPECT_ADAPTIVE = 0,
    DC_ASPECT_16_9,
    DC_ASPECT_21_9,
    DC_ASPECT_32_9,
} DcRenderAspect;

enum {
    DC_FRAME_HEIGHT = 224,
};

typedef SnesDisplayViewport DcDisplayViewport;

void DcDisplay_SetWidescreenEnabled(bool enabled);
bool DcDisplay_IsWidescreenEnabled(void);
bool DcDisplay_IsWidescreenActive(void);

/* Logical field width for the selected aspect: even, at least 256, clamped
 * to the host's native-widescreen surface (kPpuBufWidth). The
 * SNESRECOMP_WS_EXTRA probe override pins the margin instead. */
int DcDisplay_ComputeFrameWidth(DcRenderAspect aspect, int drawable_width,
                                int drawable_height,
                                SnesDisplayAspect display_aspect);

/* Presentation geometry in the same shape every port uses. */
void DcDisplay_ComputeViewport(int source_width, int source_height,
                               int drawable_width, int drawable_height,
                               SnesDisplayAspect display_aspect,
                               bool ignore_aspect, bool integer_scale,
                               DcDisplayViewport *viewport);
int DcDisplay_GetWindowBaseWidth(int frame_width,
                                 SnesDisplayAspect display_aspect);
int DcDisplay_GetWindowBaseHeight(void);

#ifdef __cplusplus
}
#endif

#endif /* DC_DISPLAY_H */
