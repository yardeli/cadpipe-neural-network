#!/bin/bash
# Regenerate M10 AIR-5 restart in ASCII format for the AIR-11 converter.
#
# The existing restart.dat is BINARY — easier to convert if we have ASCII.
# This re-runs M10 for 1 iteration starting from the existing converged
# restart, with RESTART_FILE_FORMAT= ASCII so we get a human-readable
# version of essentially the same converged state.
#
# Output: /home/yarden/ram_c_runs/ramC_refined_M10_0_A61_ascii/restart.dat
# (ASCII, ~few MB, can be parsed line-by-line in Python)

set -e

RUNS=/home/yarden/ram_c_runs
SU2=/opt/su2-nemo/bin/SU2_CFD
SRC=$RUNS/ramC_refined_M10_0_A61
DST=$RUNS/ramC_refined_M10_0_A61_ascii

export LD_LIBRARY_PATH=/opt/su2-nemo/lib:$LD_LIBRARY_PATH
export MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data
export OMP_NUM_THREADS=16

mkdir -p $DST
cp $SRC/ram_c_refined.su2 $DST/
cp $SRC/restart.dat $DST/solution.dat   # use existing binary as initial

cat > $DST/run.cfg <<EOF
SOLVER= NEMO_EULER
GAS_MODEL= AIR-5
GAS_COMPOSITION= (0.77, 0.23, 0.0, 0.0, 0.0)
MATH_PROBLEM= DIRECT
RESTART_SOL= YES
SOLUTION_FILENAME= solution.dat

FLUID_MODEL= SU2_NONEQ

MACH_NUMBER= 10.0
AOA= 0.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= 253.7116
FREESTREAM_TEMPERATURE= 242.6500
FREESTREAM_TEMPERATURE_VE= 242.6500

MARKER_EULER= ( body )
MARKER_FAR= ( farfield )
MARKER_PLOTTING= ( body )
MARKER_MONITORING= ( body )

NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
CFL_NUMBER= 0.5
ITER= 1
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
TIME_DISCRE_FLOW= EULER_IMPLICIT

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

CONV_RESIDUAL_MINVAL= -10
CONV_STARTITER= 100

MESH_FILENAME= ram_c_refined.su2
MESH_FORMAT= SU2
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
% Critical: ASCII so the converter can read it. v7.5 picks format from
% OUTPUT_FILES: RESTART_ASCII writes a CSV-style readable restart.
OUTPUT_FILES= (RESTART_ASCII)
EOF

echo "Re-running M10 with ASCII restart output..."
cd $DST
$SU2 run.cfg > su2.log 2>&1
echo "Done. Restart file:"
ls -la $DST/restart.dat
echo "First 5 lines:"
head -5 $DST/restart.dat
