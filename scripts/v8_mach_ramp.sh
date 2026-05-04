#!/bin/bash
# v8 Mach ramp for M22.5 verification (F-18 in roadmap).
#
# Runs the canonical M=15 → M=18 → M=22.5 ramp on SU2 v8.4.0 with the
# verified-working numerics (MSW + MUSCL + VAN_ALBADA_EDGE). Each stage
# warm-starts from the previous stage's restart.dat. Compare the final
# flow.vtu to the cold-start v8 result (in v8_air7_M22_5/) to verify
# cold-start was a valid path.
#
# WHEN TO RUN: only after the current cold-start v8 in
# /home/yarden/ram_c_runs/v8_air7_M22_5/ has finished (otherwise CPU
# competition will kill both).
#
# Wall time: ~5-7 hours (200 + 200 + 1000 iters at ~8 sec/iter MPI).
#
# Usage on the VM:
#     cd /home/yarden/plasmanet/scripts
#     ./v8_mach_ramp.sh
#
# Output dirs created:
#     /home/yarden/ram_c_runs/v8_ramp_M15_A61/
#     /home/yarden/ram_c_runs/v8_ramp_M18_A61/
#     /home/yarden/ram_c_runs/v8_ramp_M22_5_A61/
#
# Exits non-zero if any stage fails. Each stage's su2.log + history.csv
# is preserved in its own dir.

set -euo pipefail

SU2=/opt/su2-nemo-v8/bin/SU2_CFD
MESH=/home/yarden/ram_c_runs/ramC_refined_air7v7b_M22_5_A61/ram_c_refined.su2
TEMPLATE_CFG=/home/yarden/ram_c_runs/v8_air7_M22_5/run.cfg   # v8-validated cfg

export LD_LIBRARY_PATH=/opt/su2-nemo-v8/lib:/opt/su2-nemo/lib:${LD_LIBRARY_PATH:-}
export MPP_DATA_DIRECTORY=/opt/su2-nemo-v8/mpp-data
export OMPI_MCA_osc=pt2pt   # OpenMPI 4.1.2 fix per build agent

# Pre-flight: refuse to run if there's already a v8 SU2 process active
if pgrep -f "/opt/su2-nemo-v8/bin/SU2_CFD" >/dev/null; then
    echo "ERROR: A v8 SU2 process is already running. Aborting to avoid resource contention."
    pgrep -af "/opt/su2-nemo-v8/bin/SU2_CFD"
    exit 1
fi

# Pre-flight: disk
free_gb=$(df -BG /home/yarden | awk 'NR==2{print $4}' | tr -d 'G')
if [ "$free_gb" -lt 3 ]; then
    echo "ERROR: only ${free_gb}G free; need >=3G for ramp outputs."
    exit 1
fi

# Helper: build a stage cfg by overriding mach + freestream + restart settings.
build_stage_cfg() {
    local stage_dir=$1
    local mach=$2
    local p_inf=$3
    local t_inf=$4
    local restart_sol=$5      # NO for cold, YES for warm
    local iter=$6

    cp "$TEMPLATE_CFG" "$stage_dir/run.cfg"
    sed -i "s/^MACH_NUMBER=.*/MACH_NUMBER= $mach/" "$stage_dir/run.cfg"
    sed -i "s/^FREESTREAM_PRESSURE=.*/FREESTREAM_PRESSURE= $p_inf/" "$stage_dir/run.cfg"
    sed -i "s/^FREESTREAM_TEMPERATURE=.*/FREESTREAM_TEMPERATURE= $t_inf/" "$stage_dir/run.cfg"
    sed -i "s/^FREESTREAM_TEMPERATURE_VE=.*/FREESTREAM_TEMPERATURE_VE= $t_inf/" "$stage_dir/run.cfg"
    sed -i "s/^RESTART_SOL=.*/RESTART_SOL= $restart_sol/" "$stage_dir/run.cfg"
    sed -i "s/^ITER=.*/ITER= $iter/" "$stage_dir/run.cfg"
}

# Helper: launch a stage and wait for it to finish.
run_stage() {
    local stage_dir=$1
    local stage_name=$2
    local n_ranks=${3:-16}

    cd "$stage_dir"
    echo "[ramp] === $stage_name === launching ($(date)) ..."
    mpirun -np "$n_ranks" --oversubscribe "$SU2" run.cfg > su2.log 2>&1
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "[ramp] ERROR: $stage_name failed with rc=$rc"
        echo "[ramp] last 10 log lines:"
        tail -10 su2.log
        exit $rc
    fi
    if grep -q "Error Exit\|diverged\|NaN detected" su2.log; then
        echo "[ramp] ERROR: $stage_name solver reported divergence in log"
        grep -E "Error|diverged|NaN" su2.log | tail -5
        exit 2
    fi
    final_iter=$(awk -F, 'NR>1 {iter=$3} END{print iter}' history.csv | tr -d ' ')
    final_rhou=$(awk -F, 'NR==1{for(i=1;i<=NF;i++) if($i ~ /rms\[RhoU\]/) c=i; next} {print $c}' history.csv | tail -1 | tr -d ' ')
    echo "[ramp] $stage_name complete: final iter=$final_iter, RhoU=$final_rhou"
}

# Stage 1: M=15 cold start (ramp anchor)
M15_DIR=/home/yarden/ram_c_runs/v8_ramp_M15_A61
mkdir -p "$M15_DIR"
ln -sf "$MESH" "$M15_DIR/ram_c_refined.su2"
# US-Std @ 61 km: T=242.65 K, P=253.71 Pa (same as M22.5; M sets the velocity).
build_stage_cfg "$M15_DIR" 15.0 253.71 242.65 NO 200
run_stage "$M15_DIR" "Stage M=15 (cold)"

# Stage 2: M=18 warm from M=15
M18_DIR=/home/yarden/ram_c_runs/v8_ramp_M18_A61
mkdir -p "$M18_DIR"
ln -sf "$MESH" "$M18_DIR/ram_c_refined.su2"
cp "$M15_DIR/restart.dat" "$M18_DIR/solution.dat"
build_stage_cfg "$M18_DIR" 18.0 253.71 242.65 YES 200
run_stage "$M18_DIR" "Stage M=18 (warm from M=15)"

# Stage 3: M=22.5 warm from M=18
M225_DIR=/home/yarden/ram_c_runs/v8_ramp_M22_5_A61
mkdir -p "$M225_DIR"
ln -sf "$MESH" "$M225_DIR/ram_c_refined.su2"
cp "$M18_DIR/restart.dat" "$M225_DIR/solution.dat"
build_stage_cfg "$M225_DIR" 22.5 253.71 242.65 YES 1000
run_stage "$M225_DIR" "Stage M=22.5 (warm from M=18)" 16

# Final summary
echo ""
echo "============================================================"
echo "[ramp] Mach ramp complete. Compare:"
echo "  cold:   /home/yarden/ram_c_runs/v8_air7_M22_5/flow.vtu"
echo "  ramped: /home/yarden/ram_c_runs/v8_ramp_M22_5_A61/flow.vtu"
echo ""
echo "Run validate_ram_c_nemo on both and compare predicted ne."
echo "If they agree within factor 1.5 (surrogate noise), cold-start is valid."
echo "============================================================"
