/*
 * Demon's Crest widescreen mod plugin.
 *
 * The package (mods/preloaded/packages/demons-crest.enhancement.widescreen)
 * declares the feature "widescreen" with the "aspect" choice; this file is
 * the trusted activation half. The runtime runs the reset callback before
 * activating plugins, so a disabled feature restores authentic 4:3 on every
 * launch even if a legacy config.ini stored Widescreen = 1.
 *
 * Mirrors MegaManXSNESRecomp's src/mods/mmx_widescreen_plugin.c.
 */

#include "mod_runtime.h"

#include <string.h>

#include "dc_display.h"
#include "dc_widescreen.h"

#if defined(RECOMP_LAUNCHER)
#include "recomp_launcher.h"
#endif

/* Must match the manifest: [[target]] applies to the package id, [[feature]]
 * and [[plugin]] carry these ids. */
#define DC_WIDESCREEN_PACKAGE "demons-crest.enhancement.widescreen"
#define DC_WIDESCREEN_FEATURE "widescreen"
#define DC_WIDESCREEN_PLUGIN  "demons-crest.widescreen"

static void DcWidescreenResetMod(void) {
    DcWidescreenReset();
    DcDisplay_SetWidescreenEnabled(false);
}

static void DcWidescreenActivateMod(void) {
    DcRenderAspect aspect = DC_ASPECT_ADAPTIVE;

#if defined(RECOMP_LAUNCHER)
    const RecompLauncherCModProvider *provider =
        snes_mod_runtime_launcher_provider_c();
    RecompLauncherCModOption option;
    for (int i = 0; provider && provider->feature_option_get &&
                    provider->feature_option_get(provider->ctx,
                                                 DC_WIDESCREEN_PACKAGE,
                                                 DC_WIDESCREEN_FEATURE, i,
                                                 &option);
         ++i) {
        if (strcmp(option.id, "aspect") != 0)
            continue;
        if (strcmp(option.value, "16:9") == 0)
            aspect = DC_ASPECT_16_9;
        else if (strcmp(option.value, "21:9") == 0)
            aspect = DC_ASPECT_21_9;
        else if (strcmp(option.value, "32:9") == 0)
            aspect = DC_ASPECT_32_9;
        else
            aspect = DC_ASPECT_ADAPTIVE;
    }
#endif

    DcWidescreenReset();
    g_dc_aspect = aspect;
    DcDisplay_SetWidescreenEnabled(true);
}

SNES_MOD_CONSTRUCTOR(DcRegisterWidescreenPlugin) {
    (void)snes_mod_register_reset_callback(DcWidescreenResetMod);
    (void)snes_mod_register_activation_plugin(DC_WIDESCREEN_PLUGIN,
                                              DcWidescreenActivateMod);
}
