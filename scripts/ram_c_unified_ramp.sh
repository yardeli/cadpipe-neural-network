#!/bin/bash
# Unified RAM-C Mach-ramp runner — replaces the proliferation of one-shot
# scripts (ram_c_ramp_stages.sh, ram_c_refined_ramp.sh,
# ram_c_refined_resume_M15.sh, ram_c_refined_phase2_low_iter.sh,
# mach_ramp_nemo.sh, ram_c_refined_ramp_air11.sh).
#
# Architectural fixes vs the old scripts:
#
#   1. Single source of truth for stage dir naming (stage_dir_for_mach helper).
#      The old typo "ramC_refined_M10_A61" vs "ramC_refined_M10_0_A61" is now
#      unrepresentable — every stage dir is computed via the same function
#      so prev_dir for stage N+1 is just stage_dir_for_mach $prev_mach, no
#      string literal to mistype.
#
#   2. Idempotent run_stage. If $stage_dir/su2.exitcode exists and is "0",
#      the stage is skipped. Re-running the script after a crash or after a
#      manual kill picks up where it left off — no need for one-shot resume
#      scripts.
#
#   3. Restart auto-detection. If a previous stage's restart.dat exists,
#      run_stage uses it. The "cold" sentinel for stage 1 (RESTART_SOL=NO)
#      is set explicitly via the prev_mach argument.
#
#   4. Configurable from variables at the top of the file. Choose case,
#      mesh, gas model, ITER_PER_STAGE map, etc. without forking the script.
#      AIR-5 / AIR-11 selection switches FLUID_MODEL + TIME_DISCRE_FLOW + CFL
#      automatically.
#
# Usage on VM:
#   bash ram_c_unified_ramp.sh                    # uses defaults from header
#   CASE=refined GAS=AIR-5 bash ram_c_unified_ramp.sh
#   bash ram_c_unified_ramp.sh                    # re-run after crash; resumes
#
# Stage chain is configured at the bottom via STAGE_CHAIN array.

set -e

# ── Configuration ────────────────────────────────────────────────────────────
RUNS="${RUNS:-/home/yarden/ram_c_runs}"
CASE="${CASE:-refined}"             # case name -> dir prefix ramC_${CASE}_*
MESH="${MESH:-ram_c_refined.su2}"   # mesh filename copied into each stage dir
MESH_SOURCE="${MESH_SOURCE:-${RUNS}/ramC_refined_M10_A61/${MESH}}"
ALT="${ALT:-61}"                    # altitude in km, used in dir suffix
GAS="${GAS:-AIR-5}"                 # AIR-5 (built-in) | air_11 (Mutation++)
SU2="${SU2:-/opt/su2-nemo/bin/SU2_CFD}"

# Freestream @ ALT (defaults: US standard atmosphere 61 km)
P_INF="${P_INF:-253.7116}"
T_INF="${T_INF:-242.6500}"

# CONV_RESIDUAL_MINVAL — early-exit if Rho_0 drops below this. -3 is enough
# for restart purposes; tighten on the final stage if you want a publication-
# quality solution.
CONV_MIN="${CONV_MIN:--3}"

export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-/opt/su2-nemo/lib}:$LD_LIBRARY_PATH"
export MPP_DATA_DIRECTORY="${MPP_DATA_DIRECTORY:-/opt/su2-nemo/mpp-data}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-16}"

# ── Helpers ──────────────────────────────────────────────────────────────────

# Single source of truth for stage dir naming. mach 10.0 -> M10_0,
# mach 22.5 -> M22_5. Every reference to a stage dir comes through here,
# so you can never get the M10 vs M10_0 mismatch that broke the old chain.
stage_dir_for_mach() {
    local mach=$1
    echo "${RUNS}/ramC_${CASE}_M${mach/./_}_A${ALT}"
}

# Switches to set based on gas model.
fluid_model_for_gas() {
    case "$1" in
        AIR-5|AIR-7) echo "SU2_NONEQ" ;;
        air_11|air_5) echo "MUTATIONPP" ;;
        *) echo "ERROR: unknown gas model '$1'" >&2; exit 2 ;;
    esac
}
time_discre_for_gas() {
    case "$1" in
        AIR-5|AIR-7) echo "EULER_IMPLICIT" ;;
        air_11|air_5) echo "EULER_EXPLICIT" ;;  # MUTATIONPP doesn't support IMPLICIT in SU2 v7.5.1
    esac
}
cfl_for_gas() {
    case "$1" in
        AIR-5|AIR-7) echo "0.5" ;;
        air_11|air_5) echo "0.3" ;;
    esac
}
composition_for_gas() {
    case "$1" in
        AIR-5)  echo "(0.77, 0.23, 0.0, 0.0, 0.0)" ;;
        AIR-7)  echo "(0.77, 0.23, 0.0, 0.0, 0.0, 0.0, 0.0)" ;;
        air_5)  echo "(0.0, 0.0, 0.0, 0.77, 0.23)" ;;
        air_11) echo "(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.77, 0.23)" ;;
    esac
}

make_cfg() {
    local mach=$1
    local iter=$2
    local restart=$3
    local fluid=$(fluid_model_for_gas "$GAS")
    local time_discre=$(time_discre_for_gas "$GAS")
    local cfl=$(cfl_for_gas "$GAS")
    local comp=$(composition_for_gas "$GAS")
    cat <<EOF
SOLVER= NEMO_EULER
GAS_MODEL= $GAS
GAS_COMPOSITION= $comp
MATH_PROBLEM= DIRECT
RESTART_SOL= $restart
SOLUTION_FILENAME= solution.dat

FLUID_MODEL= $fluid

MACH_NUMBER= $mach
AOA= 0.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= $P_INF
FREESTREAM_TEMPERATURE= $T_INF
FREESTREAM_TEMPERATURE_VE= $T_INF

MARKER_EULER= ( body )
MARKER_FAR= ( farfield )
MARKER_PLOTTING= ( body )
MARKER_MONITORING= ( body )

NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
CFL_NUMBER= $cfl
ITER= $iter
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
TIME_DISCRE_FLOW= $time_discre

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

CONV_RESIDUAL_MINVAL= $CONV_MIN
CONV_STARTITER= 10

MESH_FILENAME= $MESH
MESH_FORMAT= SU2
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
OUTPUT_WRT_FREQ= 100
OUTPUT_FILES= (RESTART, PARAVIEW)
EOF
}

# run_stage MACH ITER PREV_MACH
#   PREV_MACH is the mach number of the previous stage, or the literal
#   string "cold" for stage 1 (RESTART_SOL=NO).
#
# Idempotent: returns 0 immediately if $stage_dir/su2.exitcode == 0.
run_stage() {
    local mach=$1
    local iter=$2
    local prev_mach=$3
    local stage_dir
    stage_dir=$(stage_dir_for_mach "$mach")

    # Idempotency check.
    if [ -f "$stage_dir/su2.exitcode" ] && [ "$(cat "$stage_dir/su2.exitcode")" = "0" ]; then
        local prev_iter prev_res
        prev_iter=$(tail -1 "$stage_dir/history.csv" 2>/dev/null | awk -F, '{print $3}' | tr -d ' ')
        prev_res=$(tail -1 "$stage_dir/history.csv" 2>/dev/null | awk -F, '{print $4}' | tr -d ' ')
        echo "[$(date)] SKIP M=$mach (already done: iter=$prev_iter, Rho_0=$prev_res)"
        return 0
    fi

    mkdir -p "$stage_dir"

    # Mesh: copy from MESH_SOURCE into the stage dir if not already there.
    if [ ! -f "$stage_dir/$MESH" ]; then
        if [ ! -f "$MESH_SOURCE" ]; then
            echo "ERROR: MESH_SOURCE not found: $MESH_SOURCE" >&2
            exit 1
        fi
        cp "$MESH_SOURCE" "$stage_dir/"
    fi

    # Restart from previous stage.
    local restart_flag="NO"
    if [ "$prev_mach" != "cold" ]; then
        local prev_dir
        prev_dir=$(stage_dir_for_mach "$prev_mach")
        if [ ! -f "$prev_dir/restart.dat" ]; then
            echo "ERROR: no restart.dat in previous stage $prev_dir" >&2
            exit 1
        fi
        cp "$prev_dir/restart.dat" "$stage_dir/solution.dat"
        restart_flag="YES"
    fi

    make_cfg "$mach" "$iter" "$restart_flag" > "$stage_dir/run.cfg"

    echo "=== Stage M=$mach (iter=$iter, restart=$restart_flag) ==="
    cd "$stage_dir"
    rm -f history.csv flow.vtu su2.log su2.exitcode
    echo "Launching at $(date)"
    $SU2 run.cfg > su2.log 2>&1
    local ec=$?
    echo $ec > su2.exitcode
    if [ $ec -ne 0 ]; then
        echo "Stage M=$mach FAILED with exit $ec"
        tail -30 su2.log
        exit $ec
    fi
    local final_iter final_res
    final_iter=$(tail -1 history.csv | awk -F, '{print $3}' | tr -d ' ')
    final_res=$(tail -1 history.csv | awk -F, '{print $4}' | tr -d ' ')
    echo "Stage M=$mach DONE at $(date) -- iter=$final_iter, Rho_0 residual=$final_res"
    echo ""
}

# ── Stage chain ──────────────────────────────────────────────────────────────
# Edit this block to change the ramp.
# Format: run_stage MACH ITER PREV_MACH (use "cold" for stage 1).

run_stage 10.0  400 cold
run_stage 15.0  300 10.0
run_stage 18.0  200 15.0
run_stage 22.5  400 18.0

echo "======================================================"
echo "  Ramp complete. Final flow.vtu at:"
echo "    $(stage_dir_for_mach 22.5)/flow.vtu"
echo "======================================================"
