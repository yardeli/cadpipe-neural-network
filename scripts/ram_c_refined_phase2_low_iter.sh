#!/bin/bash
# Phase-2 watcher: when M15 completes, kill the original resume script
# chain and replace M18/M22.5 with lower iter caps to land the result
# in ~half the wall time.
#
# The original resume script (PID set in ORIG_PID below) is currently
# running M15 at 300 iters. After M15 completes it would launch
# M18(300) -> M22.5(600). Total remaining wall time at observed iter
# rates: ~30 hours.
#
# This script polls every 5 seconds for M15's su2.exitcode. When it
# appears, it SIGTERMs the original bash session (which also kills any
# M18 SU2 that may have just spawned). Then it runs M18(200) +
# M22.5(400) with restart from M15.
#
# Iter cuts are safe: in the small-mesh ramp last night, both M18 and
# M22.5 plateaued in the -2 to -3 range well before their iter budgets,
# so trimming to ~2/3 of the original count costs no convergence.

set -e

ORIG_PID=130828
RUNS=/home/yarden/ram_c_runs
MESH=ram_c_refined.su2
SU2=/opt/su2-nemo/bin/SU2_CFD

export LD_LIBRARY_PATH=/opt/su2-nemo/lib:$LD_LIBRARY_PATH
export MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data
export OMP_NUM_THREADS=16

P_INF=253.7116
T_INF=242.6500

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

CONV_RESIDUAL_MINVAL= -6
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

run_stage() {
    local mach=$1
    local iter=$2
    local prev_dir=$3
    local stage_dir="${RUNS}/ramC_refined_M${mach/./_}_A61"

    # If the stage was partially started by the original chain (M18 dir may
    # already exist), wipe its outputs but keep the mesh + solution.dat.
    mkdir -p "$stage_dir"
    rm -f "$stage_dir/history.csv" "$stage_dir/flow.vtu" \
          "$stage_dir/su2.log" "$stage_dir/su2.exitcode" \
          "$stage_dir/restart.dat"

    [ -f "$stage_dir/$MESH" ] || cp "${RUNS}/ramC_refined_M10_0_A61/$MESH" "$stage_dir/"

    if [ -f "$prev_dir/restart.dat" ]; then
        cp "$prev_dir/restart.dat" "$stage_dir/solution.dat"
    else
        echo "ERROR: no restart.dat in $prev_dir"
        exit 1
    fi

    make_cfg "$mach" "$iter" > "$stage_dir/run.cfg"

    echo "=== Stage M=$mach (iter=$iter, low-iter phase 2) ==="
    cd "$stage_dir"
    echo "Launching at $(date)"
    $SU2 run.cfg > su2.log 2>&1
    local ec=$?
    echo $ec > su2.exitcode
    if [ $ec -ne 0 ]; then
        echo "Stage M=$mach FAILED with exit $ec"
        tail -30 su2.log
        exit $ec
    fi
    local final_res=$(tail -1 history.csv | awk -F, '{print $4}' | tr -d ' ')
    local final_iter=$(tail -1 history.csv | awk -F, '{print $3}' | tr -d ' ')
    echo "Stage M=$mach DONE at $(date) -- iter=$final_iter, Rho_0 residual=$final_res"
    echo ""
}

# ── Wait for M15 to complete ─────────────────────────────────────────────────
echo "[$(date)] phase2 watcher started, waiting for M15 su2.exitcode..."
while [ ! -f "${RUNS}/ramC_refined_M15_0_A61/su2.exitcode" ]; do
    sleep 5
done
EC=$(cat "${RUNS}/ramC_refined_M15_0_A61/su2.exitcode")
echo "[$(date)] M15 done with exit=$EC"
if [ "$EC" != "0" ]; then
    echo "ERROR: M15 failed — aborting phase 2"
    exit 1
fi

# ── Kill the original resume script chain ────────────────────────────────────
# This sends SIGTERM to bash $ORIG_PID; same-session SIGHUP propagation
# kills any M18 SU2 the original chain may have just spawned. We restart
# M18 ourselves below with the lower iter cap.
echo "[$(date)] Terminating original resume script PID $ORIG_PID..."
kill $ORIG_PID 2>/dev/null || true
sleep 3
kill -9 $ORIG_PID 2>/dev/null || true
# Catch any SU2 that may have just spawned for M18 with the original
# 300-iter cfg. pkill -f matches against the cmdline, but SU2's cmdline
# is just "/opt/su2-nemo/bin/SU2_CFD run.cfg" with no stage info, so we
# match by cwd instead.
for pid in $(pgrep -x SU2_CFD 2>/dev/null); do
    cwd=$(readlink /proc/$pid/cwd 2>/dev/null)
    if [[ "$cwd" == *ramC_refined_M18* ]]; then
        echo "[$(date)] killing orphan M18 SU2 PID $pid (cwd=$cwd)"
        kill -9 "$pid" 2>/dev/null || true
    fi
done
sleep 2

# Update the PID file the monitor reads, so check-ins resolve to this script.
echo $$ > /home/yarden/ram_c_refined_ramp.pid

# ── Run M18 (200 iters) and M22.5 (400 iters) ────────────────────────────────
run_stage 18.0 200 "${RUNS}/ramC_refined_M15_0_A61"
run_stage 22.5 400 "${RUNS}/ramC_refined_M18_0_A61"

echo "======================================================"
echo "  Phase-2 ramp complete. M22.5 flow.vtu at:"
echo "    ${RUNS}/ramC_refined_M22_5_A61/flow.vtu"
echo "======================================================"
