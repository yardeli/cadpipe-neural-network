#!/bin/bash
# Resume AIR-7 ramp from the M10 iter-200 checkpoint.
#
# Why: v7 M10 stage hit chemistry stiffness around iter 234, iter rate
# degraded to >30 min/iter making it impossible to reach iter 400.
# But the iter-200 restart has chemistry ALREADY DEVELOPED (Rho_NO+
# residual at -10, all neutrals settled). M15+M18+M22.5 stages can use
# this as warm-start and should converge much faster than cold-start
# because chemistry doesn't have to develop from machine zero.
#
# This script bypasses the M10 stage entirely — we have what we need.

set -e

RUNS=/home/yarden/ram_c_runs
MESH=ram_c_refined.su2
SU2=/opt/su2-nemo/bin/SU2_CFD
M10_RESTART=$RUNS/ramC_refined_air7v7_M10_0_A61/restart.dat

export LD_LIBRARY_PATH=/opt/su2-nemo/lib:$LD_LIBRARY_PATH
export MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data
export OMP_NUM_THREADS=16

P_INF=253.7116
T_INF=242.6500

if [ ! -f "$M10_RESTART" ]; then
    echo "ERROR: M10 restart not found at $M10_RESTART"
    exit 1
fi
echo "Using M10 checkpoint: $M10_RESTART"
ls -la "$M10_RESTART"

make_cfg() {
    local mach=$1
    local iter=$2
    cat <<EOF
SOLVER= NEMO_EULER
GAS_MODEL= AIR-7
GAS_COMPOSITION= (0.0, 0.77, 0.23, 0.0, 0.0, 0.0, 0.0)
MATH_PROBLEM= DIRECT
RESTART_SOL= YES
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
CFL_NUMBER= 0.2
CFL_ADAPT= NO
ITER= $iter
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
TIME_DISCRE_FLOW= EULER_IMPLICIT

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

CONV_FIELD= ( RMS_MOMENTUM-X )
CONV_RESIDUAL_MINVAL= -2
CONV_STARTITER= 100

MESH_FILENAME= $MESH
MESH_FORMAT= SU2
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
OUTPUT_WRT_FREQ= 100
OUTPUT_FILES= (RESTART, PARAVIEW)
EOF
}

run_stage() {
    local mach=$1
    local iter=$2
    local prev=$3   # path to previous stage's restart.dat
    local stage_dir="${RUNS}/ramC_refined_air7v7_M${mach/./_}_A61"
    mkdir -p "$stage_dir"

    [ -f "$stage_dir/$MESH" ] || cp "${RUNS}/ramC_refined_M10_A61/$MESH" "$stage_dir/"
    cp "$prev" "$stage_dir/solution.dat"

    make_cfg "$mach" "$iter" > "$stage_dir/run.cfg"

    echo "=== Stage M=$mach AIR-7 (warm-start from $prev, iter=$iter) ==="
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
    local final_iter=$(tail -1 history.csv | awk -F, '{print $3}' | tr -d ' ')
    echo "Stage M=$mach DONE at $(date) -- iter=$final_iter"
    echo ""
}

# Skip M10 entirely — we have its restart already with chemistry developed.
# Iter counts: shorter because warm-start should converge faster.
run_stage 15.0 250 "$M10_RESTART"
run_stage 18.0 250 "${RUNS}/ramC_refined_air7v7_M15_0_A61/restart.dat"
run_stage 22.5 600 "${RUNS}/ramC_refined_air7v7_M18_0_A61/restart.dat"

echo "======================================================"
echo "  AIR-7 ramp resume complete. M22.5 flow.vtu at:"
echo "    ${RUNS}/ramC_refined_air7v7_M22_5_A61/flow.vtu"
echo "  Validate:"
echo "    python scripts/validate_ram_c_nemo.py --vtu flow.vtu --altitude 61 --mach 22.5"
echo "======================================================"
