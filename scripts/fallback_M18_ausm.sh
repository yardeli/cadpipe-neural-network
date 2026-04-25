#!/bin/bash
# M18 fallback recipe: switch flux scheme to AUSM+.
#
# WHEN TO USE: M18 shock is oscillating (Rho_0 sawtooth pattern), OR
# the LAX-FRIEDRICH dissipation is smearing the bow shock so much that
# the post-shock plasma sheath looks underesolved even on a fine mesh.
# AUSM+ has lower dissipation -> sharper shock, but is less robust at
# extreme conditions (can produce nonphysical states if pushed).
#
# WHAT IT DOES: rerun M18 with CONV_NUM_METHOD_FLOW= AUSMPLUSUP2 (the
# carbuncle-safe AUSM variant in SU2) instead of LAX-FRIEDRICH. Keeps
# CFL=0.5. Same iter budget.
#
# USAGE on VM:
#   bash fallback_M18_ausm.sh

set -e

RUNS=/home/yarden/ram_c_runs
MESH=ram_c_refined.su2
SU2=/opt/su2-nemo/bin/SU2_CFD

export LD_LIBRARY_PATH=/opt/su2-nemo/lib:$LD_LIBRARY_PATH
export MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data
export OMP_NUM_THREADS=16

P_INF=253.7116
T_INF=242.6500

PREV_DIR=${RUNS}/ramC_refined_M15_0_A61
STAGE_DIR=${RUNS}/ramC_refined_M18_0_A61_ausm

mkdir -p "$STAGE_DIR"
cp "${RUNS}/ramC_refined_M10_0_A61/${MESH}" "$STAGE_DIR/"
cp "${PREV_DIR}/restart.dat" "$STAGE_DIR/solution.dat"

cat > "$STAGE_DIR/run.cfg" <<EOF
SOLVER= NEMO_EULER
GAS_MODEL= AIR-5
GAS_COMPOSITION= (0.77, 0.23, 0.0, 0.0, 0.0)
MATH_PROBLEM= DIRECT
RESTART_SOL= YES
SOLUTION_FILENAME= solution.dat

FLUID_MODEL= SU2_NONEQ

MACH_NUMBER= 18.0
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
ITER= 200
% AUSMPLUSUP2 = AUSM+-up2, the carbuncle-safe variant. Sharper shock
% than LAX-FRIEDRICH. Falls back to LAX-FRIEDRICH internally on cells
% with extreme states.
CONV_NUM_METHOD_FLOW= AUSMPLUSUP2
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

echo "=== Fallback M=18 (AUSMPLUSUP2 flux, 200 iter) ==="
cd "$STAGE_DIR"
echo "Launching at $(date)"
$SU2 run.cfg > su2.log 2>&1
EC=$?
echo $EC > su2.exitcode
if [ $EC -ne 0 ]; then
    echo "FAILED with exit $EC"
    tail -30 su2.log
    exit $EC
fi
FINAL=$(tail -1 history.csv | awk -F, '{print $4}' | tr -d ' ')
ITER=$(tail -1 history.csv | awk -F, '{print $3}' | tr -d ' ')
echo "Done at $(date) -- iter=$ITER, Rho_0=$FINAL"
