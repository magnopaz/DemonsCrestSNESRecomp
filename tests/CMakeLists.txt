# Headless regression tests (see docs/TESTING.md for the full description).
#
# Two classes:
#   unit         no ROM: the generated-code injector (synthetic anchors,
#                idempotency, drift rejection) and --check on the current gen.
#                Registered for every build, including the setup host, which is
#                how CI runs them without a ROM.
#   integration  needs a ROM ($SNESRECOMP_ROM, rom.cfg, or a known filename at
#                the repo root). They report SKIP (exit 77) when none is found,
#                so `ctest` stays green on a machine without a legal dump.
#                Not registered for the setup host: it has no recompiled code
#                to run.
#
# The staging-band test also needs a save state; point SNESRECOMP_TEST_SAVE at
# one, or run it directly with --save.

find_package(Python3 COMPONENTS Interpreter QUIET)
if(NOT Python3_Interpreter_FOUND)
    message(WARNING "ctest: Python3 not found; the headless test suite is skipped")
    return()
endif()

set(_dc_test "${CMAKE_CURRENT_SOURCE_DIR}/dc_test.py")
set(_dc_repo "${PROJECT_SOURCE_DIR}")
set(_dc_exe "$<TARGET_FILE:DemonsCrestSNESRecomp>")
set(_dc_py "${Python3_EXECUTABLE}")
set(_dc_common --repo "${_dc_repo}")

add_test(NAME dc.injector
         COMMAND ${_dc_py} "${_dc_test}" injector ${_dc_common})
add_test(NAME dc.injector_check
         COMMAND ${_dc_py} "${_dc_test}" injector-check ${_dc_common})
set_tests_properties(dc.injector dc.injector_check PROPERTIES
    LABELS "unit"
    TIMEOUT 120
    SKIP_RETURN_CODE 77)

if(NOT SNESRECOMP_SETUP_HOST)
    add_test(NAME dc.boot
             COMMAND ${_dc_py} "${_dc_test}" boot ${_dc_common} --exe "${_dc_exe}")
    add_test(NAME dc.geometry
             COMMAND ${_dc_py} "${_dc_test}" geometry ${_dc_common} --exe "${_dc_exe}")
    add_test(NAME dc.aspects
             COMMAND ${_dc_py} "${_dc_test}" aspects ${_dc_common} --exe "${_dc_exe}")
    add_test(NAME dc.determinism
             COMMAND ${_dc_py} "${_dc_test}" determinism ${_dc_common} --exe "${_dc_exe}")
    add_test(NAME dc.staging_band
             COMMAND ${_dc_py} "${_dc_test}" staging-band ${_dc_common} --exe "${_dc_exe}")
    set_tests_properties(dc.boot dc.geometry dc.aspects dc.determinism dc.staging_band PROPERTIES
        LABELS "integration"
        TIMEOUT 600
        SKIP_RETURN_CODE 77)
endif()
