#!/bin/bash
# RAM-C Mach-ramp with AIR-7 (built-in CSU2TCLib) chemistry — SECOND ATTEMPT.
#
# Why this exists (after 6 AIR-11 failures):
#   AIR-11 + Mutation++ in SU2 v7.5.1 has a fundamental EOS-mismatch issue
#   with restart files written by built-in CSU2TCLib (AIR-5). Cells get
#   flagged "non-physical" and chemistry source terms NaN. Six separate
#   attempts (cold-start + restart-converter variants) all hit the same
#   pathology. The fix would require rebuilding SU2 with custom patches.
#
#   AIR-7 sidesteps this by using the SAME built-in CSU2TCLib as AIR-5.
#   Restart values map cleanly. Adds e- and NO+ — enough for direct CFD
#   electron density (no Saha post-process). NO+ is the dominant cation
#   in air plasma at the relevant T range (3000-10000 K).
#
# Why _v2 (vs the failed first AIR-7 attempt):
#   - First attempt had SPECIES ORDER WRONG. CSU2TCLib.cpp:686 confirms
#     order is [e-, N2, O2, NO, N, O, NO+]. First attempt used
#     (0.77, 0.23, 0, 0, 0, 0, 0) which set 77% mass fraction ELECTRONS
#     (impossible — 77% e- mass means n_e is enormous, T undefined).
#     Of course it NaN'd at iter 0.
#   - Correct freestream: (1e-15, 0.77, 0.23, 0, 0, 0, 0) — trace electron
#     for charge neutrality, N2/O2 dominant, no atomic neutrals or NO+.
#   - WARM START from converted AIR-5 restart (battle-tested through 6
#     AIR-11 attempts) instead of cold-start.
#
# Usage on VM:
#   bash ram_c_refined_ramp_air7_v2.sh

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
% AIR-7 species order (CONFIRMED from CSU2TCLib.cpp:678-684):
%   [e-, N2, O2, NO, N, O, NO+]
% Freestream is pure N2/O2 (matches physics at 242K: no ions, no electrons).
% Sum: 0 + 0.77 + 0.23 + 0 + 0 + 0 + 0 = 1.0 EXACTLY in float64.
% NO+ and e- come from the CONVERTED RESTART (interior cells), NOT from
% the freestream BC. Cold-start would NaN, but warm-start has trace ions
% baked in everywhere via the AIR-5 -> AIR-7 converter.
GAS_COMPOSITION= (0.0, 0.77, 0.23, 0.0, 0.0, 0.0, 0.0)
MATH_PROBLEM= DIRECT
RESTART_SOL= $restart
SOLUTION_FILENAME= solution.csv

% Built-in 2-T NEQ fluid model — SAME EOS as AIR-5, IMPLICIT supported
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
% Adaptive CFL: start small (0.1), ramp to 1.0 as residual drops.
% Implicit can take much higher CFL than the AIR-11 EXPLICIT (CFL 0.01).
CFL_NUMBER= 0.1
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.5, 1.5, 0.01, 1.0 )
ITER= $iter
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
% IMPLICIT supported by SU2_NONEQ (NOT MUTATIONPP)
TIME_DISCRE_FLOW= EULER_IMPLICIT

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

% Monitor bulk-flow residual. AIR-7 species 0 is e- (machine zero in
% freestream), so RMS_DENSITY_0 is trivially low — same trap as AIR-11.
% Use RMS_MOMENTUM-X for proper convergence detection.
CONV_FIELD= ( RMS_MOMENTUM-X )
CONV_RESIDUAL_MINVAL= -3
CONV_STARTITER= 200

MESH_FILENAME= $MESH
MESH_FORMAT= SU2
% Read ASCII restart written by AIR-5 converter
READ_BINARY_RESTART= NO
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
OUTPUT_WRT_FREQ= 200
% Write both ASCII (for downstream chain) AND binary (compact) plus VTU.
OUTPUT_FILES= (RESTART_ASCII, RESTART, PARAVIEW)
EOF
}

run_stage() {
    local mach=$1
    local iter=$2
    local restart=$3
    local prev_dir=$4
    local stage_dir="${RUNS}/ramC_refined_air7v2_M${mach/./_}_A61"
    mkdir -p "$stage_dir"

    [ -f "$stage_dir/$MESH" ] || cp "${RUNS}/ramC_refined_M10_A61/$MESH" "$stage_dir/"

    if [ "$restart" = "YES" ]; then
        if [ "$prev_dir" = "CONVERTED_AIR5" ]; then
            local converted=/home/yarden/ram_c_runs/ramC_refined_M10_0_A61_ascii/restart_air7.csv
            if [ ! -f "$converted" ]; then
                echo "ERROR: AIR-5->AIR-7 converted restart missing: $converted"
                echo "       Run: python3 convert_air5_to_air7_restart.py --input ..."
                exit 1
            fi
            cp "$converted" "$stage_dir/solution.csv"
            echo "Using AIR-5->AIR-7 converted restart for M=$mach"
        elif [ -f "$prev_dir/restart.csv" ]; then
            cp "$prev_dir/restart.csv" "$stage_dir/solution.csv"
        elif [ -f "$prev_dir/restart.dat" ]; then
            cp "$prev_dir/restart.dat" "$stage_dir/solution.dat"
        else
            echo "ERROR: no restart in $prev_dir"
            exit 1
        fi
    fi

    make_cfg "$mach" "$iter" "$restart" > "$stage_dir/run.cfg"

    echo "=== Stage M=$mach AIR-7 v2 (iter=$iter, restart=$restart) ==="
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

# Warm-start strategy mirrors AIR-11 plan: M10 from converted AIR-5
# restart, then chain M15→M18→M22.5 from previous stage's restart.
run_stage 10.0 1500 YES CONVERTED_AIR5
run_stage 15.0 1500 YES "${RUNS}/ramC_refined_air7v2_M10_0_A61"
run_stage 18.0 1500 YES "${RUNS}/ramC_refined_air7v2_M15_0_A61"
run_stage 22.5 3000 YES "${RUNS}/ramC_refined_air7v2_M18_0_A61"

echo "======================================================"
echo "  AIR-7 v2 refined-mesh ramp complete. M22.5 flow.vtu at:"
echo "    ${RUNS}/ramC_refined_air7v2_M22_5_A61/flow.vtu"
echo "  Validate (ne comes DIRECTLY from CFD, no Saha post-process):"
echo "    python scripts/validate_ram_c_nemo.py --vtu flow.vtu --altitude 61 --mach 22.5"
echo "======================================================"
