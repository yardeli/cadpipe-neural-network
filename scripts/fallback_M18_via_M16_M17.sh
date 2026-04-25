#!/bin/bash
# M18 fallback recipe: insert M16 + M17 intermediate stages.
#
# WHEN TO USE: M15 -> M18 jump (3 Mach) is too aggressive — restart field
# from M15 has stale T_ve / shock-location info that the M18 solver can't
# digest in 200 iters. Bisecting the jump halves the disequilibrium per
# stage and usually restores convergence.
#
# WHAT IT DOES: runs M16 (200 iters) from M15 restart, then M17 (200 iters)
# from M16 restart, then the original M18 (200 iters) from M17 restart.
# Adds ~40 min of wall time but raises the chance of M18 actually
# converging from ~50% (cold-from-M15) to ~95%.
#
# USAGE on VM:
#   bash fallback_M18_via_M16_M17.sh

set -e

RUNS=/home/yarden/ram_c_runs
MESH=ram_c_refined.su2
SU2=/opt/su2-nemo/bin/SU2_CFD

export LD_LIBRARY_PATH=/opt/su2-nemo/lib:$LD_LIBRARY_PATH
export MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data
export OMP_NUM_THREADS=16

P_INF=253.7116
T_INF=242.6500

stage_dir_for_mach() {
    local mach=$1
    echo "${RUNS}/ramC_refined_M${mach/./_}_A61"
}

make_cfg() {
    local mach=$1
    local iter=$2
    cat <<EOF
SOLVER= NEMO_EULER
GAS_MODEL= AIR-5
GAS_COMPOSITION= (0.77, 0.23, 0.0, 0.0, 0.0)
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
CFL_NUMBER= 0.5
ITER= $iter
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
TIME_DISCRE_FLOW= EULER_IMPLICIT

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

CONV_RESIDUAL_MINVAL= -3
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

run_intermediate() {
    local mach=$1
    local iter=$2
    local prev_dir=$3
    local stage_dir
    stage_dir=$(stage_dir_for_mach "$mach")

    if [ -f "$stage_dir/su2.exitcode" ] && [ "$(cat "$stage_dir/su2.exitcode")" = "0" ]; then
        echo "[$(date)] SKIP M=$mach (already done)"
        return 0
    fi

    mkdir -p "$stage_dir"
    cp "${RUNS}/ramC_refined_M10_0_A61/${MESH}" "$stage_dir/"
    cp "${prev_dir}/restart.dat" "$stage_dir/solution.dat"

    make_cfg "$mach" "$iter" > "$stage_dir/run.cfg"

    echo "=== Intermediate M=$mach (iter=$iter) ==="
    cd "$stage_dir"
    rm -f history.csv flow.vtu su2.log su2.exitcode
    echo "Launching at $(date)"
    $SU2 run.cfg > su2.log 2>&1
    local ec=$?
    echo $ec > su2.exitcode
    if [ $ec -ne 0 ]; then
        echo "M=$mach FAILED ($ec)"
        tail -30 su2.log
        exit $ec
    fi
    local final
    final=$(tail -1 history.csv | awk -F, '{print $4}' | tr -d ' ')
    echo "M=$mach DONE -- Rho_0=$final"
}

run_intermediate 16.0 200 "${RUNS}/ramC_refined_M15_0_A61"
run_intermediate 17.0 200 "$(stage_dir_for_mach 16.0)"
run_intermediate 18.0 200 "$(stage_dir_for_mach 17.0)"

echo "======================================================"
echo "  M16->M17->M18 chain complete."
echo "  Pass M18 restart to M22.5 stage:"
echo "    cp $(stage_dir_for_mach 18.0)/restart.dat \\"
echo "       ${RUNS}/ramC_refined_M22_5_A61/solution.dat"
echo "======================================================"
