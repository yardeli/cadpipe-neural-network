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
GAS_COMPOSITION= (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.77, 0.23)
MATH_PROBLEM= DIRECT
RESTART_SOL= $restart
SOLUTION_FILENAME= solution.dat

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
% Explicit scheme needs smaller CFL
CFL_NUMBER= 0.3
ITER= $iter
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
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
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
OUTPUT_WRT_FREQ= 500
OUTPUT_FILES= (RESTART, PARAVIEW)
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
        if [ -f "$prev_dir/restart.dat" ]; then
            cp "$prev_dir/restart.dat" "$stage_dir/solution.dat"
        else
            echo "ERROR: no restart.dat in $prev_dir"
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

# Iteration counts are higher than AIR-5 because EULER_EXPLICIT converges
# ~10x slower per iter (but each iter is cheaper). Use restart.dat from
# the AIR-5 ramp if available to warm-start.
# Stage 1: M10 cold-start (can also seed from AIR-5 M10 restart if desired)
run_stage 10.0 3000 NO ""

run_stage 15.0 2000 YES "${RUNS}/ramC_refined_air11_M10_0_A61"
run_stage 18.0 2000 YES "${RUNS}/ramC_refined_air11_M15_0_A61"
run_stage 22.5 4000 YES "${RUNS}/ramC_refined_air11_M18_0_A61"

echo "======================================================"
echo "  AIR-11 refined-mesh ramp complete. M22.5 flow.vtu at:"
echo "    ${RUNS}/ramC_refined_air11_M22_5_A61/flow.vtu"
echo "  Validate with (ne comes DIRECTLY from CFD, no Saha post-process):"
echo "    python scripts/validate_ram_c_nemo.py --vtu flow.vtu --altitude 61 --mach 22.5"
echo "======================================================"
