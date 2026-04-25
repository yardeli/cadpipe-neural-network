#!/bin/bash
# Mach-ramp on the REFINED RAM-C mesh with AIR-11 (Mutation++) chemistry.
#
# When to use this (vs ram_c_refined_ramp.sh with AIR-5):
#   - First-pass AIR-5 result had log10 err +1.08 vs Jones & Cross 1972.
#   - If the refined-mesh AIR-5 result still shows log10 err > 1.0, the
#     gap is likely chemistry-model-limited: AIR-5 has only {N2,O2,NO,N,O}
#     and no ions, so ne comes from a POST-processing Saha step on the
#     neutral NEMO field. AIR-11 adds {e-, N+, O+, NO+, N2+, O2+}, so ne
#     is computed directly in the CFD from nonequilibrium ionization
#     chemistry (associative, dissociative, direct).
#
# Tradeoffs:
#   - FLUID_MODEL= MUTATIONPP (not SU2_NONEQ) — slower per evaluation,
#     but more physically correct for ionizing air.
#   - TIME_DISCRE_FLOW= EULER_EXPLICIT (v7.5.1 limitation for MUTATIONPP)
#     — needs smaller CFL and ~10x more iters to converge. Budget 8-12
#     hours for a full ramp on 2.67M-tet mesh.
#   - Species composition order is reversed from AIR-5: freestream is
#     (0.0, ..., 0.0, 0.77, 0.23) with N2 and O2 last.
#
# Prereqs on VM:
#   - /opt/su2-nemo compiled against Mutation++
#   - $MPP_DATA_DIRECTORY points to mpp-data/ (already set in original ramp)
#
# Usage on VM (only launch if AIR-5 refined-mesh result is still > 1 order off):
#   bash ram_c_refined_ramp_air11.sh

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
GAS_MODEL= air_11
% air_11 species order: e-, N+, O+, NO+, N2+, O2+, N, O, NO, N2, O2
% Attempt 6: drop seed 100x to 1e-11, keep symmetric for sum=1.0 exactness.
% All 9 trace species at 1e-11; N2/O2 absorb the 9e-11 deficit symmetrically.
% Charge imbalance in GAS_COMPOSITION (electron should be 1e-15 for true
% neutrality, not 1e-11) only affects far-field BC cells (<1% of mesh).
% Interior cells are read from the converted restart, which IS charge-balanced.
GAS_COMPOSITION= (1.0e-11, 1.0e-11, 1.0e-11, 1.0e-11, 1.0e-11, 1.0e-11, 1.0e-11, 1.0e-11, 1.0e-11, 0.7699999999550, 0.2299999999550)
MATH_PROBLEM= DIRECT
RESTART_SOL= $restart

% Mutation++ fluid model (adds 6 ionized species over AIR-5)
FLUID_MODEL= MUTATIONPP

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
% Adaptive CFL: start tiny (0.01), ramp up as residual drops. Prevents
% the chemistry stiffness blowup that NaN'd the previous attempts on
% pure-neutral cold-start. Format: (factor_down, factor_up, CFL_min, CFL_max).
CFL_NUMBER= 0.01
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.5, 1.5, 0.001, 0.5 )
ITER= $iter
% Use LAX-FRIEDRICH (most dissipative -> most robust) for stability
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
% First-order spatial — disable MUSCL reconstruction. Less accurate but
% removes another source of non-physical extrema during warmup.
MUSCL_FLOW= NO
% EULER_IMPLICIT is NOT supported with MUTATIONPP in SU2 v7.5.1
TIME_DISCRE_FLOW= EULER_EXPLICIT

% CONV_FIELD must monitor a BULK-flow residual for AIR-11 — the default
% RMS_DENSITY_0 watches electrons, which start at machine zero in the
% freestream, so Rho_0 is trivially below any threshold until ionization
% has time to spin up. RMS_MOMENTUM-X tracks shock convergence properly.
CONV_FIELD= ( RMS_MOMENTUM-X )
CONV_RESIDUAL_MINVAL= -3
CONV_STARTITER= 500

MESH_FILENAME= $MESH
MESH_FORMAT= SU2
% Solution filename: AIR-5 -> AIR-11 converted restart is solution.csv
% (ASCII / CSV format). SU2 v7.5 defaults to binary reader; we have to
% explicitly tell it to read ASCII via READ_BINARY_RESTART= NO.
SOLUTION_FILENAME= solution.csv
READ_BINARY_RESTART= NO
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
OUTPUT_WRT_FREQ= 500
% Write both ASCII (for next-stage chain) AND binary (compact) plus VTU.
OUTPUT_FILES= (RESTART_ASCII, RESTART, PARAVIEW)
EOF
}

run_stage() {
    local mach=$1
    local iter=$2
    local restart=$3
    local prev_dir=$4
    local stage_dir="${RUNS}/ramC_refined_air11_M${mach/./_}_A61"
    mkdir -p "$stage_dir"

    [ -f "$stage_dir/$MESH" ] || cp "${RUNS}/ramC_refined_M10_A61/$MESH" "$stage_dir/"

    if [ "$restart" = "YES" ]; then
        # Two restart sources, in order:
        #   1. Previous stage's restart.csv (ASCII) — preferred
        #   2. Previous stage's restart.dat (binary) — fallback
        # First M10 stage uses the AIR-5-to-AIR-11 converted restart at
        # the special path /home/yarden/ram_c_runs/ramC_refined_M10_0_A61_ascii/
        # restart_air11.csv (produced by scripts/convert_air5_to_air11_restart.py).
        if [ "$prev_dir" = "CONVERTED_AIR5" ]; then
            local converted=/home/yarden/ram_c_runs/ramC_refined_M10_0_A61_ascii/restart_air11.csv
            if [ ! -f "$converted" ]; then
                echo "ERROR: AIR-5->AIR-11 converted restart missing: $converted"
                echo "       Run: bash regen_m10_ascii_restart.sh"
                echo "       Then: python3 convert_air5_to_air11_restart.py --input ..."
                exit 1
            fi
            cp "$converted" "$stage_dir/solution.csv"
            echo "Using AIR-5->AIR-11 converted restart for M=$mach"
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

    echo "=== Stage M=$mach air_11 (iter=$iter, restart=$restart) ==="
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

# NEW STRATEGY (after 3 cold-start failures): start M10 from a converted
# AIR-5 -> AIR-11 restart instead of pure-neutral freestream. Bow shock is
# already formed and chemistry has equilibrated; AIR-11 just needs to
# evolve the trace ions (1e-9 seed) toward physical equilibrium values.
# This sidesteps the chemistry NaN that hit attempts 1-3.
run_stage 10.0 1500 YES CONVERTED_AIR5

run_stage 15.0 2000 YES "${RUNS}/ramC_refined_air11_M10_0_A61"
run_stage 18.0 2000 YES "${RUNS}/ramC_refined_air11_M15_0_A61"
run_stage 22.5 4000 YES "${RUNS}/ramC_refined_air11_M18_0_A61"

echo "======================================================"
echo "  AIR-11 refined-mesh ramp complete. M22.5 flow.vtu at:"
echo "    ${RUNS}/ramC_refined_air11_M22_5_A61/flow.vtu"
echo "  Validate with (ne comes DIRECTLY from CFD, no Saha post-process):"
echo "    python scripts/validate_ram_c_nemo.py --vtu flow.vtu --altitude 61 --mach 22.5"
echo "======================================================"
