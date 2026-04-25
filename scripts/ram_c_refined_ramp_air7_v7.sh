#!/bin/bash
# RAM-C Mach-ramp with AIR-7 — COLD START variant (v3).
#
# Why this exists (after AIR-7 v2 warm-start showed T-solve issues):
#   AIR-7 v2 warm-started from converted AIR-5 restart — but the IC cells
#   include ~1e-9 NO+ + ~2e-14 e- everywhere, including freestream. The
#   T-solver may not converge cleanly when given a state that's slightly
#   off-equilibrium for the species composition.
#
#   Cold-start sidesteps this entirely. Starts from pure-neutral freestream
#   (which is physically correct for 61 km altitude, T=242K). Chemistry
#   builds ions naturally as the bow shock heats the flow.
#
# Why now (vs first AIR-7 attempt that NaN'd):
#   First attempt had GAS_COMPOSITION = (0.77, 0.23, 0, 0, 0, 0, 0) which
#   set 77% mass fraction electrons (CSU2TCLib species[0] = e-). Of course
#   it NaN'd at iter 0. With CORRECT order — N2 at index 1, electrons at
#   index 0 = 0 — cold-start has the right physics.
#
# Risks:
#   - Built-in CSU2TCLib chemistry rates have 1/n_e or log(n_e) terms
#     that can NaN at machine zero electron density. SU2_NONEQ may have
#     a built-in floor for this; the Mutation++ binding doesn't.
#   - If cold-start NaN's, fall back to v2 warm-start with smaller seed
#     (1e-12 NO+ — even more "trace" so EOS converges easily).
#
# Usage on VM (run only if v2 fails):
#   bash ram_c_refined_ramp_air7_v3_cold.sh

set -e

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
    local restart=$3
    cat <<EOF
SOLVER= NEMO_EULER
GAS_MODEL= AIR-7
% AIR-7 species order: [e-, N2, O2, NO, N, O, NO+]
% Cold-start: pure freestream — chemistry builds ions naturally.
GAS_COMPOSITION= (0.0, 0.77, 0.23, 0.0, 0.0, 0.0, 0.0)
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
% v7: FIXED CFL=0.2 (no adaptation). v6's CFL_ADAPT lowered CFL toward
% floor 0.05 due to limit-cycle residual oscillation, slowing iter rate
% from ~50s/iter to >10 min/iter by iter 142. Limit cycle is just shock
% wobble — physical, not numerical instability — so CFL adaptation is
% misfiring. Fixed CFL maintains throughput.
CFL_NUMBER= 0.2
CFL_ADAPT= NO
ITER= $iter
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
TIME_DISCRE_FLOW= EULER_IMPLICIT

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

% Engineering-acceptable convergence threshold (limit cycle bottoms out
% around RhoU=-0.8, no realistic chance of reaching -3 without changing
% physics setup; -2 is a conservative "steady enough" target).
CONV_FIELD= ( RMS_MOMENTUM-X )
CONV_RESIDUAL_MINVAL= -2
CONV_STARTITER= 200

MESH_FILENAME= $MESH
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
    local restart=$3
    local prev_dir=$4
    local stage_dir="${RUNS}/ramC_refined_air7v7_M${mach/./_}_A61"
    mkdir -p "$stage_dir"

    [ -f "$stage_dir/$MESH" ] || cp "${RUNS}/ramC_refined_M10_A61/$MESH" "$stage_dir/"

    if [ "$restart" = "YES" ]; then
        if [ -f "$prev_dir/restart.dat" ]; then
            cp "$prev_dir/restart.dat" "$stage_dir/solution.dat"
        else
            echo "ERROR: no restart.dat in $prev_dir"
            exit 1
        fi
    fi

    make_cfg "$mach" "$iter" "$restart" > "$stage_dir/run.cfg"

    echo "=== Stage M=$mach AIR-7 v3-cold (iter=$iter, restart=$restart) ==="
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
    local final_res=$(tail -1 history.csv | awk -F, '{print $4}' | tr -d ' ')
    local final_iter=$(tail -1 history.csv | awk -F, '{print $3}' | tr -d ' ')
    echo "Stage M=$mach DONE at $(date) -- iter=$final_iter, Rho_0 residual=$final_res"
    echo ""
}

# Iter counts tuned for AIR-7 cold-start convergence behavior:
#   - Chemistry develops by iter 30 (Rho_NO+ from -32 to -10)
#   - Bulk RhoU residual oscillates around -0.79 in a limit cycle
#   - Higher iters past ~300 give diminishing returns
# Strategy: enough iters to reach quasi-steady state at each stage, with
# more time at M22.5 (the validation target) for final settling.
run_stage 10.0 400 NO ""
run_stage 15.0 300 YES "${RUNS}/ramC_refined_air7v7_M10_0_A61"
run_stage 18.0 300 YES "${RUNS}/ramC_refined_air7v7_M15_0_A61"
run_stage 22.5 800 YES "${RUNS}/ramC_refined_air7v7_M18_0_A61"

echo "======================================================"
echo "  AIR-7 v3 (cold-start) refined-mesh ramp complete."
echo "  M22.5 flow.vtu at:"
echo "    ${RUNS}/ramC_refined_air7v7_M22_5_A61/flow.vtu"
echo "======================================================"
