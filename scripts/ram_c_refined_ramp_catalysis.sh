#!/bin/bash
# RAM-C ramp variant — wall catalysis (NEMO Navier-Stokes + non-catalytic body).
#
# WHEN TO USE: After the AIR-11 ramp completes — only launch this if the
# AIR-11 result didn't close the gap to |log10 err| < 1.0. Wall catalysis
# is the second-largest expected impact on the gap (~0.3-0.5 log10
# improvement per docs/PLASMANET_NOTION.md and KHORIUM_ALIGNMENT.md).
#
# WHAT'S DIFFERENT FROM ram_c_refined_ramp_air11.sh:
#   - SOLVER= NEMO_NAVIER_STOKES (not NEMO_EULER) — viscous flow with
#     real boundary layer. Catalysis acts at the wall in the BL.
#   - MARKER_HEATFLUX= ( body, 0 ) — adiabatic non-catalytic wall, OR
#     MARKER_ISOTHERMAL= ( body, T_wall ) — fixed-temperature wall.
#     Use ISOTHERMAL with T_wall=2500 K matching RAM-C's SiO2 heat-shield
#     ablation temperature.
#   - MARKER_CATALYTIC= ( body, NON_CATALYTIC ) — RAM-C had a non-catalytic
#     SiO2 heat shield. Radicals pass through the BL without recombining.
#   - VISCOSITY_MODEL= SUTHERLAND  (or use Mutation++'s GUPTA-YOS for NEMO)
#   - CFL_NUMBER lower (0.1) — viscous + chemistry stiffness
#   - More iters per stage (2x AIR-11) — viscous convergence is slower
#
# COST: ~24 hours wall time on the c2d-highcpu-16 VM (3-5x slower than
#       AIR-5 inviscid; 2x slower than AIR-11 inviscid). ~$6 GCP cost.
#
# Usage on VM:
#   bash ram_c_refined_ramp_catalysis.sh

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

# RAM-C SiO2 heat shield temperature — based on Mach 22 stagnation heat
# flux and SiO2 thermal limit. Real RAM-C ablated mass; we approximate
# as a constant 2500 K isothermal wall.
T_WALL=2500.0

make_cfg() {
    local mach=$1
    local iter=$2
    local restart=$3
    cat <<EOF
% ---- SOLVER (viscous + thermochemistry) ----
SOLVER= NEMO_NAVIER_STOKES
GAS_MODEL= air_11
% Species order: e-, N+, O+, NO+, N2+, O2+, N, O, NO, N2, O2
GAS_COMPOSITION= (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.77, 0.23)
MATH_PROBLEM= DIRECT
RESTART_SOL= $restart
SOLUTION_FILENAME= solution.dat

FLUID_MODEL= MUTATIONPP
TRANSPORT_COEFF_MODEL= GUPTA-YOS

% ---- Freestream ----
MACH_NUMBER= $mach
AOA= 0.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= $P_INF
FREESTREAM_TEMPERATURE= $T_INF
FREESTREAM_TEMPERATURE_VE= $T_INF

% ---- Boundary conditions ----
% Body is now an isothermal viscous wall with non-catalytic surface.
% Catalytic option: NON_CATALYTIC keeps radicals (N, O, ions) from
% recombining at the body — sustains downstream sheath ne, which is
% exactly the gap the AIR-5 result showed.
MARKER_ISOTHERMAL= ( body, $T_WALL )
MARKER_CATALYTIC= ( body, NON_CATALYTIC )
MARKER_FAR= ( farfield )
MARKER_PLOTTING= ( body )
MARKER_MONITORING= ( body )

% ---- Numerics ----
NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
% Viscous + chemistry stiffness — keep CFL conservative
CFL_NUMBER= 0.1
ITER= $iter
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
% MUTATIONPP doesn't support EULER_IMPLICIT in SU2 v7.5.1
TIME_DISCRE_FLOW= EULER_EXPLICIT

CONV_RESIDUAL_MINVAL= -3
CONV_STARTITER= 50

% ---- I/O ----
MESH_FILENAME= $MESH
MESH_FORMAT= SU2
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
OUTPUT_WRT_FREQ= 1000
OUTPUT_FILES= (RESTART, PARAVIEW)
EOF
}

run_stage() {
    local mach=$1
    local iter=$2
    local restart=$3
    local prev_dir=$4
    local stage_dir="${RUNS}/ramC_refined_catalysis_M${mach/./_}_A61"
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

    echo "=== Stage M=$mach catalysis (iter=$iter, restart=$restart) ==="
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

# Iteration counts are higher because Navier-Stokes + EULER_EXPLICIT
# converges much slower than the AIR-5 inviscid implicit baseline.
# Budget: ~24 hours total wall time.
run_stage 10.0 6000 NO ""
run_stage 15.0 4000 YES "${RUNS}/ramC_refined_catalysis_M10_0_A61"
run_stage 18.0 4000 YES "${RUNS}/ramC_refined_catalysis_M15_0_A61"
run_stage 22.5 8000 YES "${RUNS}/ramC_refined_catalysis_M18_0_A61"

echo "======================================================"
echo "  Catalysis ramp complete. M22.5 flow.vtu at:"
echo "    ${RUNS}/ramC_refined_catalysis_M22_5_A61/flow.vtu"
echo ""
echo "  Validate with:"
echo "    python scripts/validate_ram_c_nemo.py \\"
echo "      --vtu data/nemo_test/ramC_refined_catalysis_M22_5_A61_nemo.vtu \\"
echo "      --altitude 61 --mach 22.5"
echo "======================================================"
