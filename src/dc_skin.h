#ifndef DC_SKIN_OVERLAY_H
#define DC_SKIN_OVERLAY_H

#include <stdbool.h>

/* Test harness: draw the undead Firebrand reskin over the native player OAM.
 * This is deliberately presentation-only: native OAM is hidden for the draw
 * and restored immediately after, so guest state is unchanged. */
void DcSkin_SetEnabled(bool enabled);
bool DcSkin_IsEnabled(void);
void DcSkin_BeforeDraw(void);
void DcSkin_AfterDraw(void);

#endif
