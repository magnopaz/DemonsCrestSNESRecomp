/*
 * Demon's Crest — per-game runtime glue.
 *
 * THIS FILE IS THE PORT. Everything else the scaffold produced is layout,
 * build wiring, and packaging; this is where the actual work happens.
 *
 * The framework does not, and cannot, drive an arbitrary SNES game on its
 * own. Two responsibilities always land on the game host:
 *
 *   1. Deciding what "one frame" means for THIS title, and returning from
 *      run_frame() at that boundary. A real ROM's reset vector never
 *      returns — it enters a main loop that waits on vblank — so somebody
 *      has to choose the yield point.
 *   2. Delivering NMI/IRQ at the hardware edge (see
 *      snesrecomp/docs/FRAME_MODEL_HOSTS.md).
 *
 * A new port starts on the framework's beam-aligned driver
 * (runner/src/beam_frame_driver.h): one frame is one PPU field, cut at the
 * beam's vblank edge; interrupts -- raster splits and a coprocessor's IRQ
 * line -- are taken where the beam latches them; parked time still runs the
 * beam, APU and coprocessors; and the field is rasterized from the raster
 * journal with real HDMA. It is the framework's, so a fix to it reaches this
 * port on a submodule pull.
 *
 * This file used to hold its own copy of a simpler driver: frames measured
 * from wherever the CPU last stopped, NMI delivered at an arbitrary beam
 * position, the field drawn with end-of-frame register state. A game that
 * uploads in vblank between INIDISP=$80 and $0F flickered black, and one
 * that chains raster splits fell apart. Replace these calls only for what
 * the driver does not do; MetalWarriorsSNESRecomp's src/mw_rtl.c and
 * GundamWingEndlessDuelSNESRecomp's src/game_rtl.c are developed examples of
 * title-specific drivers.
 */

#include "game_rtl.h"

#include "beam_frame_driver.h"
#include "common_rtl.h"
#include "cpu_state.h"
#include "snes/interp_bridge.h"

/*
 * Save states: the guest blob (snes_saveload) covers WRAM, PPU, DMA, APU
 * ports and the beam registers, but NOT the recomp runtime's own execution
 * state -- g_cpu (registers, flags, E mode, master clock) or the interpreter
 * bridge's resume state (the LLE scheduler's pending resume PC). The
 * framework streams that as the v5 game chunk through
 * RtlSaveExecutionState/RtlLoadExecutionState/RtlApplyExecutionState.
 *
 * Without it, a load in a fresh process left g_cpu at its reset values
 * (emulation mode, S=01FF, PB=0, master clock 0): the first NMI handler
 * decoded its 16-bit `LDA #$0000` as an 8-bit LDA followed by a BRK and
 * vectored into a BRA spin. In-game loads only appeared to work because the
 * live g_cpu was already a valid mid-game scheduler context.
 */
static bool s_exec_state_loaded;

static void GameStateSaveExtra(struct SaveLoadInfo *sli)
{
    RtlSaveExecutionState(sli);
}

static void GameStateLoadExtra(struct SaveLoadInfo *sli, uint32_t version)
{
    (void)version;
    s_exec_state_loaded = RtlLoadExecutionState(sli);
}

static void GameStateLoaded(uint32_t version)
{
    (void)version;
    uint32_t resume;
    bool had_exec = s_exec_state_loaded;
    s_exec_state_loaded = false;

    if (had_exec) {
        /* Restores g_cpu, the bridge's LLE resume PC, beamMasterLast, the
         * frame counter, APU pacing and MMIO shadows. */
        RtlApplyExecutionState();
        resume = interp_bridge_lle_resume_pc();
        if (!resume)
            resume = 0x808179u; /* bridge had no pending resume: scheduler */
    } else {
        /* Legacy save (no execution chunk): the runtime state is whatever
         * this process had. Rebuild the native-mode scheduler context the
         * guest's own boot leaves behind when it JMPs to $80:8179: native
         * mode, 8-bit A/X, DB=PB=$80 (WRAM mirror for $0083/$0086), D=0,
         * scheduler stack. The scheduler then resumes each task from the
         * loaded WRAM stacks, exactly as an in-game load does. */
        g_cpu.emulation = 0;
        g_cpu.PB = 0x80;
        g_cpu.DB = 0x80;
        g_cpu.D = 0;
        g_cpu.S = 0x01FF;
        g_cpu.A = 0;
        g_cpu.X = 0;
        g_cpu.Y = 0;
        g_cpu.P = 0x34; /* M=1, X=1, I=1 -- SEP #$30 at the loop head */
        cpu_p_to_mirrors(&g_cpu);
        resume = 0x808179u;
    }
    snes_beam_frame_driver_state_loaded(resume);
}

void GameRunOneFrame(void)
{
    snes_beam_frame_driver_run_frame();
}

void GameDrawPpuFrame(void)
{
    snes_beam_frame_driver_draw_ppu_frame();
}

void GameSessionReset(void)
{
    /* Rematch / soft-return: clear anything that must not survive a new
     * session. recomp-ai-rules/NETPLAY.md §3 — sticky state that "has always
     * been fine" is the usual desync culprit, because single-player never
     * re-enters the boot path twice in one process. */
    snes_beam_frame_driver_reset();
}

const RtlGameInfo kGameInfo = {
    .title = "demonscrest",
    .initialize = NULL,
    .run_frame = &GameRunOneFrame,
    .draw_ppu_frame = &GameDrawPpuFrame,
    .save_name_prefix = "save",
    .session_reset = &GameSessionReset,
    .state_save_extra = &GameStateSaveExtra,
    .state_load_extra = &GameStateLoadExtra,
    .on_state_loaded = &GameStateLoaded,
};
