#include "dc_skin.h"
#include "mod_runtime.h"

static void dc_skin_enable(void) { DcSkin_SetEnabled(true); }
static void dc_skin_reset(void) { DcSkin_SetEnabled(false); }

SNES_MOD_CONSTRUCTOR(register_dc_skin_mod) {
  snes_mod_register_reset_callback(dc_skin_reset);
  snes_mod_register_activation_plugin("demonscrest.skin.undead", dc_skin_enable);
}
