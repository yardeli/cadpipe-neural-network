#!/bin/bash
# RAM-C Mach-ramp variant — AIR-7 ionizing chemistry (built-in SU2_NONEQ).
#
# Replaces ram_c_refined_ramp_air11.sh after that variant produced NaN in
# every chemistry source term and silently froze. Root cause: AIR-11 +
# MUTATIONPP requires TIME_DISCRE_FLOW=EULER_EXPLICIT in SU2 v7.5.1, and
# explicit time-stepping with stiff Mutation++ chemistry on a cold-start
# went non-physical within 30 iters. Solution: AIR-7.
#
# AIR-7 species:  {N2, O2, NO, N, O, N2+, e-}
# Compared to AIR-5: adds N2+ and e- — gives us actual electron density
#   transported by the flow (the thing we care about for plasma freq).
# Compared to AIR-11: drops N+, O+, NO+, O2+ (less complete chemistry)
#   but uses the built-in SU2_NONEQ fluid model which SUPPORTS EULER_IMPLICIT.
#
# Trade-offs vs AIR-5:
#   - AIR-7 carries e- as a transported species (no Saha post-process)
#     -> downstream sheath ne should be sustained where AIR-5 collapsed
#   - Implicit time-stepping like AIR-5: ~10x faster per iter than the
#     failed AIR-11 EXPLICIT path
#   - Should converge in ~3-4 hours per stage (similar to AIR-5)
#
# Expected impact on log10 error: -0.3 to -0.7 (somewhere between AIR-5
# and AIR-11 since we have the key ions e- and N2+ but not the full ion
# set). Headline metric: does ne sustain at z/L > 0.14, where AIR-5
# collapsed.
#
# Usage on VM:
#   bash ram_c_refined_ramp_air7.sh

set -e

RUNS=/home/yarden/ram_c_runs
MESH=ram_c_refined.su2
SU2=/opt/su2-nemo/bin/SU2_CFD

export LD_LIBRARY_PATH=/opt/su2-nemo/lib:$LD_LIBRARY_PATH
export MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data
export OMP_NUM_THREADS=16

# Freestream @ 61 km
P_INF=253.7116
T_INF=242.6500

make_cfg() {
    local mach=$1
    local iter=$2
    local restart=$3
    cat <<EOF
SOLVER= NEMO_EULER
GAS_MODEL= AIR-7
% AIR-7 species order: N2, O2, NO, N, O, N2+, e-
% Freestream is pure N2 + O2 — exact sum 1.0 (SU2 rejects 1.0 + epsilon).
% Built-in SU2_NONEQ chemistry has cold-start safeguards (unlike
% Mutation++ EXPLICIT) so seeding ions isn't necessary.
GAS_COMPOSITION= (0.77, 0.23, 0.0, 0.0, 0.0, 0.0, 0.0)
MATH_PROBLEM= DIRECT
RESTART_SOL= $restart
SOLUTION_FILENAME= solution.dat

% Built-in 2-T NEQ fluid model — supports EULER_IMPLICIT
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
% IMPLICIT supported by SU2_NONEQ (not MUTATIONPP)
TIME_DISCRE_FLOW= EULER_IMPLICIT

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

% CONV_FIELD: monitor bulk-flow residual NOT species 0. For AIR-7,
% Rho_0 is N2 (the dominant species) so this is OK to use as default.
% RMS_DENSITY_0 monitors N2; appropriate threshold is -3 to -4.
CONV_FIELD= ( RMS_DENSITY_0 )
CONV_RESIDUAL_MINVAL= -3
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
    local restart=$3
    local prev_dir=$4
    local stage_dir="${RUNS}/ramC_refined_air7_M${mach/./_}_A61"
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

    echo "=== Stage M=$mach AIR-7 (iter=$iter, restart=$restart) ==="
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

# Iteration counts mirror the AIR-5 ramp (proven stable on this VM).
# Built-in SU2_NONEQ + EULER_IMPLICIT runs at AIR-5 speed (~30s/iter on
# 2.67M-tet mesh) — total ~3-4 hours per stage = ~12 hours total ramp.
run_stage 10.0 400 NO ""
run_stage 15.0 300 YES "${RUNS}/ramC_refined_air7_M10_0_A61"
run_stage 18.0 200 YES "${RUNS}/ramC_refined_air7_M15_0_A61"
run_stage 22.5 400 YES "${RUNS}/ramC_refined_air7_M18_0_A61"

echo "======================================================"
echo "  AIR-7 refined-mesh ramp complete. M22.5 flow.vtu at:"
echo "    ${RUNS}/ramC_refined_air7_M22_5_A61/flow.vtu"
echo "  Validate with (ne now comes DIRECTLY from CFD):"
echo "    python scripts/validate_ram_c_nemo.py --vtu flow.vtu --altitude 61 --mach 22.5"
echo "======================================================"
