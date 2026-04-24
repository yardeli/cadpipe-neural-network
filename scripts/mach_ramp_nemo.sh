#!/bin/bash
# Mach ramping for SU2-NEMO strong-shock convergence.
#
# At Mach 22+ the bow shock is strong enough that NEMO cannot converge
# from a freestream initial condition — the 2-T inner loop fails on the
# first few iterations and the flow field diverges. The standard remedy
# is to ramp the Mach number:
#
#   1. Run Mach 10 to convergence (freestream init OK here).
#   2. Restart from that solution at Mach 15.
#   3. Restart from Mach 15 solution at Mach 18.
#   4. Restart from Mach 18 solution at Mach 22.5.
#
# Each stage writes restart.dat which becomes the next stage's
# initial condition.
#
# Usage (on the VM):
#   bash mach_ramp_nemo.sh ram_c  # runs all 4 stages sequentially
#
# Environment: LD_LIBRARY_PATH and MPP_DATA_DIRECTORY must be set.

set -e

CASE_BASE=${1:-ram_c}
RUNS_ROOT=/home/yarden/ram_c_runs
MESH_FILE=ram_c_domain.su2
SU2=/opt/su2-nemo/bin/SU2_CFD

# Freestream at 61 km
P_INF=253.7116
T_INF=242.6500

make_cfg() {
    local mach=$1
    local iter=$2
    local restart=$3   # YES or NO
    cat <<EOF
SOLVER= NEMO_EULER
GAS_MODEL= AIR-5
GAS_COMPOSITION= (0.77, 0.23, 0.0, 0.0, 0.0)
MATH_PROBLEM= DIRECT
RESTART_SOL= $restart
SOLUTION_FILENAME= solution.dat

FLUID_MODEL= SU2_NONEQ

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
CFL_NUMBER= 0.5
ITER= $iter

CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
TIME_DISCRE_FLOW= EULER_IMPLICIT

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

CONV_RESIDUAL_MINVAL= -8
CONV_STARTITER= 10

MESH_FILENAME= $MESH_FILE
MESH_FORMAT= SU2
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
OUTPUT_WRT_FREQ= 200
OUTPUT_FILES= (RESTART, PARAVIEW)
EOF
}

run_stage() {
    local mach=$1
    local iter=$2
    local prev_restart=$3   # path to restart.dat from previous stage, or empty
    local stage_dir="${RUNS_ROOT}/${CASE_BASE}_M${mach}_A61"
    mkdir -p "$stage_dir"

    # Copy mesh if not present
    if [ ! -f "$stage_dir/$MESH_FILE" ]; then
        cp "${RUNS_ROOT}/${CASE_BASE}_M22.5_A61/$MESH_FILE" "$stage_dir/$MESH_FILE"
    fi

    # Generate config
    if [ -n "$prev_restart" ] && [ -f "$prev_restart" ]; then
        make_cfg "$mach" "$iter" YES > "$stage_dir/run.cfg"
        cp "$prev_restart" "$stage_dir/solution.dat"
        echo "Stage M=$mach — restart from $prev_restart"
    else
        make_cfg "$mach" "$iter" NO > "$stage_dir/run.cfg"
        echo "Stage M=$mach — freestream init"
    fi

    cd "$stage_dir"
    rm -f history.csv su2.log su2.exitcode
    echo "  running SU2_CFD at $(date)..."
    $SU2 run.cfg > su2.log 2>&1
    local ec=$?
    echo $ec > su2.exitcode
    if [ $ec -ne 0 ]; then
        echo "  FAILED with exit $ec"
        tail -20 su2.log
        exit $ec
    fi
    if ! grep -q "Exit Success" su2.log; then
        echo "  WARNING: no Exit Success in log"
        tail -10 su2.log
    fi
    local last_res=$(tail -1 history.csv | awk -F, '{print $4}' | tr -d ' ')
    echo "  DONE — last residual Rho_0 = $last_res"
}

# Stage 1: Mach 10 freestream
run_stage 10  400  ""

# Stage 2: Mach 15 restart from 10
run_stage 15  400  "${RUNS_ROOT}/${CASE_BASE}_M10_A61/restart.dat"

# Stage 3: Mach 18 restart from 15
run_stage 18  400  "${RUNS_ROOT}/${CASE_BASE}_M15_A61/restart.dat"

# Stage 4: Mach 22.5 restart from 18
run_stage 22.5  800  "${RUNS_ROOT}/${CASE_BASE}_M18_A61/restart.dat"

echo ""
echo "=== Mach ramping complete ==="
echo "Final Mach 22.5 flow.vtu at:"
echo "  ${RUNS_ROOT}/${CASE_BASE}_M22.5_A61/flow.vtu"
