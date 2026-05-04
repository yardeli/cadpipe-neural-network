#!/usr/bin/env bash
# Track B + Phase 2.5 launch chain (run on VM, after mesh has finished).
#
# Order:
#   1. Tag the new 4-6M-tet mesh.
#   2. Launch Phase 2.5 viscous smoke test (uses existing v8_phase1A 2.74M
#      mesh, NOT the new one; the smoke test answers "does v8 fix the v7.5.1
#      AIR-7 viscous bug?", needs ~30 min, exits cleanly even on crash).
#   3. WAIT for smoke test to finish.
#   4. If smoke test PASSED: launch Phase 2 inviscid cold-start production
#      run (5+ hours) on the new mesh, AND launch Phase 2.5 viscous
#      production on the new mesh from the iter-251 warm-start (also 5+
#      hours, parallel — uses 8 ranks each so 16 total).
#      If smoke test FAILED: launch ONLY Phase 2 inviscid (the documented
#      v7.5.1 bug is unfixed in v8, viscous track is dead-end).
#
# All launches are detached via setsid + nohup so the user's session can
# disconnect.

set -euo pipefail

REPO=/home/yarden/plasmanet
SETUP_SCRIPT=$REPO/scripts/setup_v8_phase2_run.sh
SMOKE_CFG=$REPO/scripts/configs/v8_phase2_5_viscous_smoketest.cfg
PHASE2_CFG=$REPO/scripts/configs/v8_phase2_cold.cfg
GENERIC_LAUNCHER=/home/yarden/ram_c_runs/launch_su2_v8_generic.sh

# Step 1: tag the new mesh + provision the Phase 2 run dir
echo "[chain] Step 1: tagging new mesh + provisioning Phase 2 run dir"
bash "$SETUP_SCRIPT"

# Step 2: provision and launch the smoke test (separate dir, separate
# warm-start, uses the existing 2.74M-tet mesh)
SMOKE_DIR=/home/yarden/ram_c_runs/v8_phase2_5_smoketest
PHASE1A_DIR=/home/yarden/ram_c_runs/v8_phase1A_recover

echo "[chain] Step 2: provisioning Phase 2.5 smoke test run dir"
mkdir -p "$SMOKE_DIR"
ln -sf "$PHASE1A_DIR/ram_c_refined.su2" "$SMOKE_DIR/ram_c_refined.su2"
cp "$PHASE1A_DIR/best_restart_iter251_RhoU-0.2115410394.dat" "$SMOKE_DIR/solution.dat"
cp "$SMOKE_CFG" "$SMOKE_DIR/run.cfg"

cat > "$SMOKE_DIR/launch.sh" <<'EOF'
#!/usr/bin/env bash
exec /home/yarden/ram_c_runs/launch_su2_v8_generic.sh run.cfg
EOF
chmod +x "$SMOKE_DIR/launch.sh"

echo "[chain] Step 3: running smoke test in foreground (~30 min)"
cd "$SMOKE_DIR"
# Foreground so the script naturally blocks until smoke test exits.
# No need to track PIDs or poll. The user already has the parent chain
# launch detached, so this nested foreground is fine.
bash launch.sh > su2_smoke.log 2>&1 || true
echo "[chain] smoke test ended"

# Step 4: examine smoke test outcome
echo "[chain] smoke test ended"
SMOKE_OK=no
if grep -q "Exit Success" "$SMOKE_DIR/su2_smoke.log" 2>/dev/null \
   || [[ $(wc -l < "$SMOKE_DIR/history.csv" 2>/dev/null || echo 0) -gt 50 ]]; then
    if ! grep -qi "heap.*corrupt\|segmentation\|core dumped\|nan\|inf" "$SMOKE_DIR/su2_smoke.log" 2>/dev/null; then
        SMOKE_OK=yes
    fi
fi
echo "[chain] smoke test verdict: $SMOKE_OK"
echo "[chain] tail of smoke log:"
tail -15 "$SMOKE_DIR/su2_smoke.log" || true

# Step 5: launch Phase 2 production (always) and Phase 2.5 viscous production
# (only if smoke passed)
PHASE2_DIR=/home/yarden/ram_c_runs/v8_phase2_M22_5_cold
echo "[chain] Step 5a: launching Phase 2 inviscid cold-start (detached, 5+ hr)"
cd "$PHASE2_DIR"
setsid bash -c "nohup bash launch.sh > su2_v8_phase2_cold.log 2>&1" </dev/null >/dev/null 2>&1 &
sleep 5
echo "[chain] Phase 2 launched. Log: $PHASE2_DIR/su2_v8_phase2_cold.log"

if [[ "$SMOKE_OK" == "yes" ]]; then
    PHASE25_DIR=/home/yarden/ram_c_runs/v8_phase2_5_viscous_prod
    PHASE25_CFG=$REPO/scripts/configs/v8_phase2_5_viscous_smoketest.cfg
    echo "[chain] Step 5b: smoke passed -> launching Phase 2.5 viscous on new mesh"
    mkdir -p "$PHASE25_DIR"
    ln -sf "$PHASE2_DIR/ram_c_tagged.su2" "$PHASE25_DIR/ram_c_tagged.su2"
    cp "$PHASE25_CFG" "$PHASE25_DIR/run.cfg"
    # Switch the mesh filename + extend ITER for production
    sed -i 's|MESH_FILENAME= ram_c_refined.su2|MESH_FILENAME= ram_c_tagged.su2|' \
         "$PHASE25_DIR/run.cfg"
    sed -i 's|^ITER= 100$|ITER= 3000|' "$PHASE25_DIR/run.cfg"
    sed -i 's|^RESTART_SOL= YES$|RESTART_SOL= NO|' "$PHASE25_DIR/run.cfg"
    sed -i '/^SOLUTION_FILENAME/d' "$PHASE25_DIR/run.cfg"
    cat > "$PHASE25_DIR/launch.sh" <<'EOF'
#!/usr/bin/env bash
exec /home/yarden/ram_c_runs/launch_su2_v8_generic.sh run.cfg
EOF
    chmod +x "$PHASE25_DIR/launch.sh"
    cd "$PHASE25_DIR"
    setsid bash -c "nohup bash launch.sh > su2_v8_phase2_5_viscous.log 2>&1" </dev/null >/dev/null 2>&1 &
    sleep 5
    echo "[chain] Phase 2.5 viscous launched. Log: $PHASE25_DIR/su2_v8_phase2_5_viscous.log"
else
    echo "[chain] Step 5b: smoke FAILED -> skipping Phase 2.5 viscous production"
    echo "[chain]    AIR-7 viscous bug in v7.5.1 is NOT fixed in v8.4.0."
    echo "[chain]    Update CHECKPOINT_2026-04-26 'Don't repeat these' list."
fi

echo "[chain] DONE. Active SU2 processes:"
pgrep -af SU2_CFD || echo "(none)"
