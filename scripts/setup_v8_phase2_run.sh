#!/usr/bin/env bash
# Track B (Phase 2 RAM-C M22.5 cold-start) launch chain.
#
# Run on the GCP VM after `mesh_ram_c_v8_phase2.py` finishes.
# Tags the raw SU2 mesh, copies it + the cfg into a fresh run dir under
# /home/yarden/ram_c_runs/v8_phase2_M22_5_cold/, and prints the launch
# command. Does NOT submit the SU2 run — that's a 5+ hour billable
# operation on the VM, so the user kicks it off explicitly.
#
# Usage (on VM):
#   cd /home/yarden/plasmanet
#   bash scripts/setup_v8_phase2_run.sh
#
# After this finishes, launch with:
#   cd /home/yarden/ram_c_runs/v8_phase2_M22_5_cold
#   nohup bash launch.sh > su2_v8_phase2_cold.log 2>&1 &

set -euo pipefail

REPO=/home/yarden/plasmanet
MESH_DIR=$REPO/data/cfd_cases_nemo/ram_c_v8_phase2
RUN_DIR=/home/yarden/ram_c_runs/v8_phase2_M22_5_cold
RAW_SU2=$MESH_DIR/ram_c_domain_raw.su2
TAGGED_SU2=$MESH_DIR/ram_c_tagged.su2
COLD_CFG=$REPO/scripts/configs/v8_phase2_cold.cfg
GENERIC_LAUNCHER=/home/yarden/ram_c_runs/launch_su2_v8_generic.sh

if [[ ! -f "$RAW_SU2" ]]; then
    echo "ERROR: raw mesh not found at $RAW_SU2" >&2
    echo "       Has scripts/mesh_ram_c_v8_phase2.py finished?" >&2
    exit 1
fi
if [[ ! -f "$COLD_CFG" ]]; then
    echo "ERROR: cold-start cfg not found at $COLD_CFG" >&2
    exit 1
fi
if [[ ! -x "$GENERIC_LAUNCHER" ]]; then
    echo "ERROR: generic launcher not found / not executable at $GENERIC_LAUNCHER" >&2
    echo "       Expected from CHECKPOINT_2026-04-26 §2.8 Phase 1 driver work." >&2
    exit 1
fi

echo "[setup] Tagging raw mesh -> $TAGGED_SU2"
cd $REPO
PYTHONPATH=. python3 -u scripts/add_markers_su2.py \
    --input "$RAW_SU2" --output "$TAGGED_SU2"

echo "[setup] Provisioning run dir $RUN_DIR"
mkdir -p "$RUN_DIR"
cp "$TAGGED_SU2" "$RUN_DIR/ram_c_tagged.su2"
cp "$COLD_CFG" "$RUN_DIR/run.cfg"

# Generate a per-run launcher pointing at the generic env-setter
cat > "$RUN_DIR/launch.sh" <<'EOF'
#!/usr/bin/env bash
# Per-run launcher — calls the canonical generic launcher with this dir's cfg.
exec /home/yarden/ram_c_runs/launch_su2_v8_generic.sh run.cfg
EOF
chmod +x "$RUN_DIR/launch.sh"

echo "[setup] DONE."
echo
echo "Files staged in $RUN_DIR:"
ls -lh "$RUN_DIR"
echo
echo "To launch the 5+ hour cold-start CFD run (DETACHED, billable):"
echo "  cd $RUN_DIR"
echo "  nohup bash launch.sh > su2_v8_phase2_cold.log 2>&1 &"
echo "  pgrep -af SU2_CFD"
echo
echo "Monitor convergence:"
echo "  tail -f $RUN_DIR/history.csv"
echo "  tail -f $RUN_DIR/su2_v8_phase2_cold.log"
