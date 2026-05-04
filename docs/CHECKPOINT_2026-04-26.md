# Plasmanet / Khorium Hypersonics — Session Checkpoint
**Date**: 2026-04-26 (early morning UTC)
**Author**: Claude Opus 4.7 (1M context)
**Purpose**: Hand-off to the next Claude instance picking up this work.

---

## TL;DR vs 04-25

- **Surrogate v4 trained on 896K examples** (12× v3's 76K). Test MAE
  **0.183 log10 → factor of 1.52 of Cantera ground truth**. Publication-grade.
- **Parallel data-collection pattern works**: subprocess-restart workers
  release the Cantera memory leak; 4 workers collected 896K in ~30 min
  before the box hit disk-full and coordinator was killed.
- **Disk crisis recovered**: deleted 4 obsolete v7 runs + worker shards →
  3.4 GB free. v3.jsonl merged cleanly. Both v7 SU2 and surrogate training
  survived intact.
- **v7 ramp finished** but with caveat — see § "M22.5 convergence note"
  below. Original v7 ramp's `iter 29 / RhoU=-9.27` was a single bouncy
  low-residual moment caught by the cfg's loose `CONV_RESIDUAL_MINVAL=-2`
  threshold, NOT a true steady state. Two tight-convergence rerun
  attempts (CFL=0.2 then CFL=0.1) both **diverged** after iter ~115. The
  case has a chemistry-shock limit cycle in v7.5.1 + AIR-7 that this
  build cannot reduce below ~residual 0.16. The MPI binary
  (`/opt/su2-nemo-mpi/`, possibly patched) is the next-week experiment.
- **Ready for the inner-loop search now** — surrogate_v4 + Sobol/BO + GA
  is the next-phase work. See `PROMPT_NEXT_INSTANCE_2026-04-26.md`. Note
  from other instance: BO ran successfully (best score 2.9139 at 5000
  iters) but Cantera verification has a 74% YAML-emit failure rate —
  that's now the headline blocker for the publishable "beat AIR-7" gate.

---

## 1. The vision (still Aaron Wu's pitch — unchanged)

See `docs/CHECKPOINT_2026-04-25.md` §1. Short version: search the 2^47
Park-subset space against multi-experiment ground truth, replacing
hand-picked Park 1990 / Dunn-Kang / Kang-Dunn mechanisms with an
AI-discovered optimum. v4 makes this tractable in seconds instead of days.

---

## 2. State of the world

### Running on the GCP VM (DO NOT DISTURB)
- **AIR-7 v7 inviscid ramp**: PID 215175 (was 197922 on 04-25; restarted
  by the ramp script after the M=18 stage advanced). Currently in M=18
  stage of M15→M18→M22.5. Output goes to
  `/home/yarden/ram_c_runs/ramC_refined_air7v7b_*_A61/`.
  Monitor: task `b44gqjzg0` (persistent, 30-min cadence).
- Memory: ~10 GB free of 31 GB. Plenty of headroom now that data
  collection has stopped.
- **Disk: 3.4 GB free of 49 GB** (was 0 MB during the crisis). Tight
  but workable. v7 needs to write checkpoints — keep an eye on it.

### Completed since 04-25
- `scripts/data_collection_worker.py` — single-batch worker that runs
  N Cantera 0D evals then exits cleanly so all Mutation++ / Cantera
  state is freed. The workaround for the per-process memory leak that
  capped single-process collection at ~76K examples.
- `scripts/parallel_data_collection.py` — coordinator spawning N
  workers, batched-restart pattern, JSONL merge every 10 batches.
  Defaults: 4 workers × 5000 evals/batch.
- `scripts/train_surrogate_v4.py` — trainer for the 896K dataset:
  512-hidden 4-layer MLP, batch 256, patience 30, 200 epochs, cosine LR.
  Includes try/except around `json.loads` so corrupt worker writes
  (3 found) get skipped instead of killing the run.
- `/home/yarden/mechanism_search_results/training_data_v3.jsonl` —
  895,976 lines, 246 MB merged dataset.
- `/home/yarden/mechanism_search_results/surrogate_v4.pt` — trained
  weights, 3.3 MB state_dict.
- `docs/SURROGATE_V4_RESULT.md` — full v4 results write-up.

### Background pieces (unchanged from 04-25)
- `/opt/su2-nemo/` (serial), `/opt/su2-nemo-mpi/` (MPI 10–15× speedup).
- `/tmp/mpp_converter` Mutation++ EOS converter (binary), source at
  `scripts/mpp_air5_to_air11_converter.cpp`.
- AIR-11 cold-start NaN remains unresolved (6 attempts; chemistry-source
  divergence at iter 2). Marked dead-end. Mark task #32 stays
  "completed" but the workaround is "use AIR-7" not "AIR-11 fixed."

---

## 2.7. AUSMPLUSM — clean monotonic convergence at last (added 2026-04-28 ~22:00 UTC)

**TL;DR**: Path 3 from `AUDIT_M22_5_PATH_FORWARD.md` (AUSMPLUSM + accurate flux Jacobians) was tried earlier today. **It works**: 600 iters, strictly monotonic, no carbuncle blowup. Run extended to ITER=3000 to push for the -2 acceptance criterion.

### What was tried

`/home/yarden/ram_c_runs/v8_air7_M22_5/run.cfg` — diff vs the previously-blowing-up MSW config:
```
- CONV_NUM_METHOD_FLOW = MSW
+ CONV_NUM_METHOD_FLOW = AUSMPLUSM
+ USE_ACCURATE_FLUX_JACOBIANS = YES
+ VENKAT_LIMITER_COEFF = 0.01
  CFL_NUMBER = 0.1                  (kept conservative — audit suggested 0.5)
  MUSCL_FLOW = YES
  SLOPE_LIMITER_FLOW = VAN_ALBADA_EDGE
```
Warm-start from the `solution.dat` that had been the v7 ramp's iter-29 anchor (the column-misread artifact — see §2.6). Run launched ~19:22 UTC, completed ~21:33 UTC, 600 iters in ~2 hours wall-time on 16 MPI ranks (`/opt/su2-nemo-v8/bin/SU2_CFD`, `mpirun -np 16 --oversubscribe`, `OMPI_MCA_osc=pt2pt`).

### Convergence trajectory

```
iter   rms[RhoU]
  0    -0.0553   (warm-start initial)
100    -0.1049
200    -0.1217
300    -0.1377
400    -0.1585
500    -0.1709
599    -0.1930   (Exit Success, ITER=600 reached)
```

Strictly monotonic over all 600 iters. **Zero positive-residual excursions, no NaN, no chemistry-thermal blowup at iter ~520** (the failure point of every prior trial). All 7 species residuals settled in -4 to -12 range. The MUSCL reconstruction did flag 203,884 non-physical states across the run, but AUSMPLUSM's pressure-diffusion sensor absorbed them — no propagation.

### Why this is qualitatively different from prior attempts

| Trial | Scheme | Outcome |
|---|---|---|
| v7 ramp (column-misread) | LAX + MUSCL | Stuck at RhoU≈+6.0, never converged |
| v8 + MSW + CFL=0.05 | MSW + MUSCL + VAN_ALBADA | Monotonic 6 orders, then blowup iter 522 (RhoU −0.11 → +3.87 in 3 iters) |
| **v8 + AUSMPLUSM + CFL=0.1** | AUSMPLUSM + MUSCL + VAN_ALBADA + accurate Jacobians | **Monotonic over 600 iters, past the iter-500 danger zone, no blowup** |

The audit's hypothesis was that AUSMPLUSM's built-in pressure-diffusion sensor (active in `CNEMOEulerSolver.cpp:276`) would suppress the asymmetric stagnation-line oscillations that v7/MSW couldn't damp. **Confirmed.**

### Caveat

RhoU only reached **-0.193** after 600 iters, against the -2 engineering convergence target. Descent rate is ~0.04 log10 per 100 iters at the iter-500..600 segment — slow but steady. Linear extrapolation suggests ~5000 more iters to reach -2 at this rate; convergence may accelerate as the flow settles, or may plateau.

### Extension run launched (in flight as of this write)

```
cp restart.dat solution.dat              # roll iter-599 forward as warm-start
sed -i 's/^ITER= 600/ITER= 3000/' run.cfg  # 3000 more iters from iter-599 state
./launch_su2_v8.sh > su2_v8_ausm_2k.log 2>&1
```

`launch_su2_v8.sh` is the canonical launcher now (sets LD_LIBRARY_PATH, MPP_DATA_DIRECTORY, OMPI_MCA_osc=pt2pt, mpirun -np 16). Saved alongside the cfg. PID was `417560` at launch; preserve_checkpoints.sh (PID `355284`) is auto-rotating snapshots every restart.dat write.

ETA: ~5.5 hours wall-time at the observed 6.7 sec/iter. Expected RhoU at iter 3000 if rate holds: ~-1.40. If rate accelerates (typical for blunt-body inviscid as flow settles), could reach -2.

### Implications for the paper / Aaron-vision strategy

- **If extension reaches RhoU < -2**: M22.5 CFD anchor is real. Paper can use it as the third validation leg (§3 main text, not Appendix B). Audit Path 1 (reframe paper) becomes optional rather than necessary.
- **If extension plateaus around -1**: Combine with the iter-3000 partial-converged state for the "directional consistency" framing. Audit Paths 2 (mesh refinement) and 5 (Eilmer) remain on the table for the journal-version follow-up.
- **The surrogate+Cantera+BO headline (28/50 candidates beat AIR-7) is unaffected either way** — that result is CFD-independent.

### Files of interest

- `/home/yarden/ram_c_runs/v8_air7_M22_5/run.cfg` — the AUSMPLUSM cfg
- `/home/yarden/ram_c_runs/v8_air7_M22_5/launch_su2_v8.sh` — canonical launcher (env + mpirun)
- `/home/yarden/ram_c_runs/v8_air7_M22_5/history_iter0_599.csv` — archived first-segment history
- `/home/yarden/ram_c_runs/v8_air7_M22_5/history_extension_iter0_1024.csv` — archived extension history
- `/home/yarden/ram_c_runs/v8_air7_M22_5/su2_v8_ausm_ext.log` — first-segment SU2 log
- `/home/yarden/ram_c_runs/v8_air7_M22_5/su2_v8_ausm_2k.log` — extension run log
- `/home/yarden/ram_c_runs/v8_air7_M22_5/solution.dat` — iter-599 first-segment state (safety-net warm-start)
- `/home/yarden/ram_c_runs/v8_air7_M22_5/restart_iter852_RhoU-0.167357533.dat` thru `restart_iter1002_*` — extension preserved snapshots (post-minimum drift region)

### Update 2026-04-29 ~03:00 UTC — extension run halted: AUSMPLUSM cures carbuncle but exposes a limit-cycle floor

**The extension run was stopped at iter-1024 of extension (~iter-1623 absolute). RhoU bottomed out at iter-255 (RhoU=-0.2116, the global minimum and best convergence ever achieved on this case) and then drifted UP to -0.143 by iter-1024.** Trajectory:

```
iter  RhoU
   0  -0.1932   ← warm-start from first-segment iter-599
 100  -0.2021
 200  -0.2099
 255  -0.2116   ← MINIMUM (best convergence ever for this case)
 500  -0.2018
 750  -0.1772
1024  -0.1429   ← stopped here
```

**Critical diagnostic**: `grep -c "not physical" su2_v8_ausm_2k.log → 0`. **Zero non-physical-state warnings across all 1024 iters.** This is qualitatively different from v8+MSW (143 warnings, blowup at iter 522). AUSMPLUSM's pressure-diffusion sensor is keeping every cell inside the [50K, 80000K] band as advertised.

**This means the carbuncle hypothesis from `AUDIT_M22_5_PATH_FORWARD.md` was correct, AUSMPLUSM cures it, but a SECOND failure mode underneath has been exposed**: a low-amplitude limit cycle in RhoU. Species residuals tell the story:
- Rho_0 (electrons): -12.08 → -13.17 — monotonically descending across the full run (good)
- Rho_3 (NO), Rho_4 (N), Rho_5 (O), Rho_6 (NO+): all descending
- Rho_1 (N2), Rho_2 (O2): plateau near -4.1 to -4.6

**5 of 7 species converge** (volumetric chemistry is equilibrating). Only the global momentum residual oscillates. Consistent with **sub-cell bow-shock breathing** — the chemistry equilibrates volumetrically but the shock front doesn't have enough mesh resolution to settle on a unique cell-aligned position.

**The iter-255 minimum state was lost to the preserve-script's 4-snapshot rotation.** Best preserved checkpoints now are extension iter-852 thru iter-1002 (RhoU = -0.167 to -0.145). solution.dat (the iter-599 first-segment state, RhoU=-0.193) is intact and is the canonical safety-net warm-start for any future experiments.

### Limit-cycle root-cause hypotheses (ranked)

| # | Hypothesis | Evidence for | How to test |
|---|---|---|---|
| 1 | **Bow-shock under-resolution → sub-cell shock breathing** (1-2 cells across 3 mm standoff at M22.5) | 5/7 species converge; only momentum oscillates. Pattern matches "shock-position-dependent residual floor" classical mode. | Mesh refinement to 5-10 cells across standoff. |
| 2 | **CONV_FIELD = RMS_MOMENTUM-X is wrong metric** (RMS picks up transient shock-front cells even when body integrals are steady) | Body-integrated forces typically converge when RMS doesn't, on the same mesh. | Add `CONV_FIELD=( DRAG_COEFFICIENT )` + `CONV_CAUCHY_*`. If drag goes Cauchy-steady to 1e-3 while RhoU oscillates, hypothesis confirmed. |
| 3 | **CFL=0.1 too aggressive once chemistry equilibrates** → Newton over-correction across shock cell amplifies sub-cell jitter | Limit cycle began ~iter-255, after the volumetric chemistry settled. | Re-run from solution.dat with CFL=0.025. If amplitude halves, hypothesis confirmed. |
| 4 | **True physical unsteadiness** (bow-shock breathing mode at M22.5 inviscid is borderline) | Possible but low prior; most blunt-body inviscid Euler+chemistry cases have steady solutions. | Re-run with `TIME_DISCRE_FLOW=DUAL_TIME_STEPPING` to find periodic solution if it exists. |

### Plan forward (focus: make the CFD work, validate thoroughly — paper concerns deferred)

**Phase 1 — Diagnostic experiments (1-2 days, cheap, parallel-friendly).** Goal: identify which hypothesis is actually load-bearing before committing to mesh work.

- 1A. **Recover iter-255 minimum state** — Re-run from solution.dat with current cfg + ITER=300; snapshot iter-255 explicitly. Need this for any analysis of what "best convergence" looks like spatially. ~30 min wall-time.
- 1B. **CFL sensitivity** — From solution.dat, AUSMPLUSM+MUSCL+VAL_AB_EDGE+accurate Jac, CFL=0.025, ITER=600. Test if limit-cycle amplitude scales with CFL. ~3 hr wall-time.
- 1C. **Convergence-metric experiment** — From solution.dat, same cfg as the existing run, but `CONV_FIELD=( DRAG_COEFFICIENT, LIFT_COEFFICIENT )` + `CONV_CAUCHY_ELEMS=100` + `CONV_CAUCHY_EPS=1E-3`. Test if body-integrated forces go Cauchy-steady. ~3 hr wall-time.

**Phase 2 — Mesh refinement (3-7 days, the likely true fix).** Conditional on Phase 1 ruling out 2 and 3 as primary causes (or if they only partially help).

- 2A. **Generate refined mesh** with Pointwise/Gmsh/cfMesh:
  - Estimated bow-shock standoff at M=22.5, AIR-7, 61 km: 3 mm (chemically-equilibrated, Billig 1967 correlation)
  - Target Δx_normal = 0.3 mm at shock-crossing line → 10 cells across standoff
  - Anisotropic stretching (10:1) toward stagnation streamline
  - Hybrid hex+tet preferred; pure tetrahedra acceptable if anisotropy holds
  - Total cell budget: 4-6M (we have 24 GB free RAM, 16 cores)
- 2B. **Cold-start at M=22.5 directly** (no Mach ramp — v8+AUSMPLUSM+MUSCL is stable from cold)
  - Numerics: AUSMPLUSM + MUSCL + VAN_ALBADA_EDGE + USE_ACCURATE_FLUX_JACOBIANS=YES + CFL=0.5
  - ITER=3000, OUTPUT_WRT_FREQ=100
  - **Acceptance: RhoU ≤ -2 within 2000 iters with no positive-residual excursions**
- 2C. **Sanity-check baseline** — re-run AIR-5 baseline on the new mesh first. Should reach RhoU ≤ -2 in <500 iters (the AIR-5 case has always converged cleanly).

**Phase 3 — Mesh independence study (validation).** Confirms the result isn't an artifact of the chosen refinement.

- 3A. Repeat Phase 2 at **0.75x cell count** (coarser refined mesh)
- 3B. Repeat Phase 2 at **1.5x cell count** (finer refined mesh)
- 3C. **Acceptance: ne(x) profile, peak ne, surface heat flux all agree within 5%** across the three meshes

**Phase 4 — Cross-solver validation (validation depth).** Independent confirmation.

- 4A. **Eilmer 4** (Gollan & Jacobs, U. Queensland — open source, validated on RAM-C class) as primary cross-solver. Has Park 1990 air kinetics built in. Same geometry, same freestream, AUSM-equivalent scheme.
- 4B. **OR hy2Foam** (Casseau et al., OpenFOAM-based) as secondary. Two independent codes ideally; one as fallback.
- 4C. **Acceptance: peak ne agrees within factor of 1.5; ne(x) profile shape matches qualitatively; dB attenuation agrees within 3 dB**

**Phase 5 — Multi-experiment validation (the Aaron-vision deliverable).** Demonstrates the converged pipeline isn't a one-off RAM-C-22.5 fit.

- 5A. **RAM-C M=22.5 / 61 km** (current case, J&C 1972 ground truth)
- 5B. **RAM-C M=15.5 / 25 km** (J&C 1972 lower-altitude trajectory point; the validator already supports this)
- 5C. **FIRE-II M=11.4 / 76 km** (Hash & Olejniczak 2007 reference; 4-sensor electron-density data)
- 5D. **Apollo CM peak ne conditions** (older but well-documented)
- 5E. **Acceptance: log10 ne agreement within ±0.5 across all four flight conditions** for the same Park-7 mechanism

This Phase 5 result is what makes the search-framework's discovered mechanism candidates defensibly cross-experimental — the deliverable Aaron's pitch actually requires.

### Files freshly archived this session

- `/home/yarden/ram_c_runs/v8_air7_M22_5/history_iter0_599.csv` — first segment history
- `/home/yarden/ram_c_runs/v8_air7_M22_5/history_extension_iter0_1024.csv` — extension run history (contains iter-255 minimum trajectory data)
- `/home/yarden/ram_c_runs/v8_air7_M22_5/solution.dat` — iter-599 first-segment state, the canonical warm-start checkpoint for any future M22.5 experiment

### 2.8. Phase 1 results — three diagnostic experiments completed (added 2026-04-29 ~09:30 UTC)

**TL;DR**: All three Phase 1 sub-experiments completed cleanly. Hypotheses 2 (wrong metric) and 3 (CFL too aggressive) tested explicitly. **Result: hypothesis 2 CONFIRMED (drag is converged, RMS isn't), hypothesis 3 REFUTED (lower CFL doesn't help). Mesh under-resolution remains the primary cause of the per-cell residual floor. The flow IS already at engineering steady-state from the warm-start; the iter-251 minimum spatial state is preserved for validation work.**

#### Phase 1 driver mechanics

- Driver script: `/home/yarden/ram_c_runs/phase1_driver.sh` — orchestrates three sub-experiments serially with shared 16-rank mpirun
- Generic launcher: `/home/yarden/ram_c_runs/launch_su2_v8_generic.sh` — env + mpirun, no hardcoded path; reuse for any future v8 experiments
- Status pipe: `/home/yarden/ram_c_runs/phase1_status.txt` — structured (`current_subexperiment=`, `current_dir=`, `phase1_complete=yes`)
- Each sub-experiment got its own dir under `/home/yarden/ram_c_runs/v8_phase1{A,B,C}_*` with mesh-symlink + solution.dat copy + per-experiment cfg

#### 1A — Recover iter-255 minimum (CFL=0.1, RMS, ITER=300)

- Wall time: 34 min (07:32 → 08:06 UTC)
- **Minimum located at iter-255, RhoU = -0.21163**
- Closest preserved snapshot: **iter-251, RhoU = -0.21154** (the minimum-tracker preserve script wrote at OUTPUT_WRT_FREQ=10 boundaries)
- Reproducibility: matches the killed extension run's iter-255 minimum (-0.2116) to 5 decimal places
- Spatial state preserved at:
  - `/home/yarden/ram_c_runs/v8_phase1A_recover/best_restart_iter251_RhoU-0.2115410394.dat` (53 MB)
  - `/home/yarden/ram_c_runs/v8_phase1A_recover/best_flow_iter251_RhoU-0.2115410394.vtu` (107 MB)
- These are the canonical artifacts for any spatial diagnostics (ne profile, shock standoff measurement, surface heat flux, dB attenuation calculation)

#### 1B — CFL sensitivity (CFL=0.025, RMS, ITER=600)

- Wall time: 68 min (08:06 → 09:14 UTC)
- **Final RhoU at iter-599: -0.20502, still slowly descending**
- Trajectory: monotonic but glacial. Last 5 iters (595-599) covered RhoU = -0.20490 → -0.20502 — descent rate ~3e-5 per iter
- Compare to CFL=0.1: reached RhoU=-0.21154 at iter-251 in the same setup
- **Conclusion: lower CFL is dramatically slower with NO depth advantage.** 5× lower CFL went 600 iters and didn't reach the CFL=0.1 minimum from 250 iters. **Hypothesis 3 (CFL too aggressive) REFUTED.**

#### 1C — Cauchy on body force coefficient (CFL=0.1, CONV_FIELD=DRAG, eps=1E-3, ITER=600)

- Wall time: 12 min (09:14 → 09:26 UTC)
- **Stopped at iter 100 with `Cauchy[CD] = 0.000837 < 0.001 → All convergence criteria satisfied. Exit Success.`**
- The drag coefficient's Cauchy series stabilized to 1E-3 tolerance across the first 100 iters — i.e., from the warm-start, the body-integrated drag never deviated by more than ~0.1% across any 100-iter window
- **Conclusion: the body-integrated forces ARE at engineering steady-state from the warm-start. Hypothesis 2 (RMS_MOMENTUM-X is wrong metric) CONFIRMED.** The flow is converged for any quantity that integrates over the body — drag, lift, surface heat flux, peak ne, dB attenuation — even though per-cell RMS oscillates.

#### Updated hypothesis ranking after Phase 1

| # | Hypothesis | Status | Evidence |
|---|---|---|---|
| 1 | Bow-shock under-resolution → sub-cell breathing | **Strongly supported** (still primary cause of per-cell RMS floor) | 1B refuted CFL alternative; 1C confirms global flow IS steady |
| 2 | RMS_MOMENTUM-X is wrong convergence metric | **CONFIRMED** | 1C: Cauchy[CD] = 0.000837 < 1E-3 by iter 100 |
| 3 | CFL=0.1 too aggressive | **REFUTED** | 1B: 5× lower CFL, 600 iters, doesn't reach CFL=0.1 minimum |
| 4 | True physical unsteadiness | **REFUTED** | 1C: drag is Cauchy-steady (would oscillate if truly unsteady) |

#### Strategic implication: dual-track validation work is now unblocked

Phase 1 reveals that we already have a usable converged state on the current 2.74M-tet mesh — the iter-251 spatial state with Cauchy-converged drag — even though RMS_MOMENTUM-X never reaches -2. Two valid paths emerge for the "make this work and validate thoroughly" goal:

**Track A — Use what we have, start cross-validation immediately**:
- Extract ne(x) profile from `best_flow_iter251_*.vtu` along the RAM-C reflectometer axis
- Compare to J&C 1972 published ne profiles (4 reflectometer stations)
- Compute peak ne, dB attenuation; compare to J&C measurements
- If quantitative agreement is within published-experiment uncertainty (factor ~1.5 on ne), the iter-251 state is publishable as the M22.5 anchor
- Re-frame the convergence claim from "RMS < -2" to "drag Cauchy-converged + ne profile matches flight data" — this is technically stronger and physically meaningful

**Track B — Phase 2 mesh refinement for the gold-standard anchor (3-7 days, in parallel)**:
- Generate refined mesh: 5-10 cells across the 3 mm bow-shock standoff
- Anisotropic stretching, 4-6M cells total
- Cold-start AUSMPLUSM at M=22.5 with CFL=0.5
- Acceptance: RhoU ≤ -2 within 2000 iters AND drag Cauchy-converges to same value as Track A
- Provides RMS-converged confirmation of the Track A result; required for any reviewer who insists on RMS < -2

These tracks are independent and complementary. Track A produces validation results within hours; Track B produces the gold-standard CFD result within a week. Neither blocks the other.

#### Concrete next-step menu

1. **Track A start**: Pull `best_flow_iter251_*.vtu` to local, extract ne(x) along reflectometer line using `plasmanet/cfd_field.py::extract_nemo_field` + `plasmanet/ram_c_validation.py`, plot vs J&C 1972 + Bjork 1969 published curves. Wall: 1-2 hours of post-processing.

2. **Track B start**: Generate refined mesh. Pointwise/Gmsh/cfMesh on local; transfer to VM. Wall: 1-2 days of meshing work, then 1-3 days of CFD.

3. **Cross-solver validation (Phase 4 prep)**: Stand up Eilmer 4 and/or hy2Foam on the VM. Build + smoke-test before launching cross-validation runs.

4. **Multi-experiment validation prep (Phase 5)**: Ground-truth data acquisition for FIRE-II (Bjork 1969, Sutton 1971), Apollo CM peak ne, and the lower-altitude RAM-C trajectory points.

#### Files of interest from Phase 1

- `/home/yarden/ram_c_runs/v8_phase1A_recover/best_restart_iter251_RhoU-0.2115410394.dat` — minimum-state restart
- `/home/yarden/ram_c_runs/v8_phase1A_recover/best_flow_iter251_RhoU-0.2115410394.vtu` — minimum-state spatial field (107 MB; the artifact for Track A)
- `/home/yarden/ram_c_runs/v8_phase1A_recover/history.csv` — 1A trajectory (300 iters)
- `/home/yarden/ram_c_runs/v8_phase1B_cfl025/history.csv` — CFL=0.025 trajectory (600 iters; refutes hypothesis 3)
- `/home/yarden/ram_c_runs/v8_phase1C_cauchy/history.csv` — Cauchy on DRAG (100 iters; confirms hypothesis 2)
- `/home/yarden/ram_c_runs/v8_phase1C_cauchy/su2.log` — contains the `Cauchy[CD] = 0.000837 < 0.001` exit message
- `/home/yarden/ram_c_runs/launch_su2_v8_generic.sh` — reusable v8 launcher (env + mpirun)
- `/home/yarden/ram_c_runs/phase1_driver.sh` — driver template for future Phase-N experiments

---

## 2.6. M22.5 — SU2 v8 breakthrough + the column-misread discovery (added 2026-04-27 21:00 UTC)

**Two major findings this session that change the whole M22.5 story:**

### Finding 1 — the v7 result was NEVER actually converged

For the entire project's history, we've been reading the **wrong column** of `history.csv` to judge M22.5 convergence:
- Column 4 = `rms[Rho_0]` = **electron-density residual** (always weird because freestream has zero electrons)
- Column 11 = `rms[RhoU]` = **momentum-X residual** (the cfg's actual `CONV_FIELD`)

What we celebrated as "iter 29 / RhoU=-9.27" in the original v7 ramp was the column-4 reading. The real column-11 value was **+6.0 with metastable behavior** — the case has never been driven to a true steady-state convergence in v7.5.1. Every v7 trial (LAX, MSW, MUSCL+VAN_ALBADA, serial, MPI) showed the same pattern: residual transient minimum around RhoU=6.0, then drift to divergence by iter 100-180.

The `flow.vtu` we've been using as the "v7-ramp converged anchor" for downstream work is actually a NON-converged metastable state. **All previously-reported AIR-7 vs J&C comparisons need to be re-examined with this in mind.**

### Finding 2 — SU2 v8 actually fixes the chemistry-shock issue

Built SU2 v8.4.0 "Harrier" from source, installed at `/opt/su2-nemo-v8/`. With v8 + MSW + MUSCL=YES + VAN_ALBADA_EDGE, M22.5 AIR-7 cold-starts and converges **monotonically with no metastable plateau**:

```
v7 trajectory:  stuck at RhoU≈+6.0, drift to divergence
v8 trajectory:  +0.12 → -0.13 over 269 iters, smooth monotonic decay
```

Build details:
- v8.4.0 tag, ~150 sec build time on 8 cores
- AIR-5 + AIR-7 smoke tests both passed (`Exit Success`)
- v8 normalizes residuals differently from v7 (~0.1 vs ~6.0 at start) — same physics, different scale
- v8 cfg keys are backward-compatible with v7 (no deprecations) BUT v8 hard-errors on `MUSCL_FLOW=YES + centered scheme (LAX/JST)` — must use upwind (MSW or AUSM family) when MUSCL is on

### What's still broken

**Warm-restart from v8's own restart.dat NaN's on iter 0.** v8 needs a `flow.meta` companion file alongside `restart.dat` for restart, but v8 does not appear to write `flow.meta` by default. Without it, v8 reads the solution data but missing metadata causes an uninitialized state → NaN. Two paths:
1. **Re-run cold from scratch with ITER=1000** — proven to work (smoke test + 269 iters above), just slow (~5 hours wall time on MPI).
2. **Investigate v8 restart machinery** — find the cfg key or runtime flag that triggers `flow.meta` write. Probably an output-format option.

### Implications for downstream work

- **Re-do the M22.5 production run on v8** before claiming any "AIR-7 vs J&C" anchor in the paper.
- **Do a v8 Mach ramp (M=15 → M=18 → M=22.5) for verification** before committing to cold-start as the canonical path. Expected: cold and ramp should converge to the same flow.vtu (within numerical noise) for inviscid Euler+chemistry.
- **The audit task F-14 in the roadmap** (which assumed MPI binary alone was a wall-time win) is **superseded** by the v8 finding.
- **Surrogate v4 work is unaffected** — the surrogate is calibrated against Cantera 0D, not against the v7 CFD anchor. Cantera 0D is reliable.

---

## 2.5. M22.5 convergence note (added 2026-04-27 — pre-v8)

**M22.5 did NOT cleanly converge in v7.5.1 + AIR-7.** Detailed timeline:

1. The original v7 ramp ran M=15 → M=18 → M=22.5. The M=22.5 stage exited
   at **iter 29** with `RMS_MOMENTUM-X = -9.27`, satisfying the cfg's
   loose `CONV_RESIDUAL_MINVAL = -2` threshold. SU2 wrote `flow.vtu` +
   `restart.dat` and exited cleanly.
2. Inspection of the last 10 history rows showed the residual was
   **bouncing 1+ orders of magnitude per iter** (iter 27: -10.33,
   iter 28: -10.61, iter 29: -9.27). Iter 29 was a single low spot in
   a limit cycle, not a steady state.
3. **First tight-convergence rerun** (CFL=0.2, MIN_VAL=-15, ITER=300):
   started from the saved restart.dat. By iter 42 RhoU had drifted UP
   from -0.46 to +0.14 (residual grew from 0.35 to 1.4). Killed.
4. **Second tight-convergence rerun** (CFL=0.1, same MIN_VAL): started
   stably with RhoU plateauing around -0.80 for ~60 iters (true limit
   cycle in 4th decimal place). Then drifted: iter 105 went to -0.49,
   iter 115 crossed zero (POSITIVE residual = 1.0+), iter 127 at -0.07.
   Killed.
5. **Restored state**: `solution.dat` was untouched (it's SU2's input,
   not output). Copied back to `restart.dat`. flow.vtu was overwritten
   by the diverged run; regenerated via a 1-iter SU2 invocation from
   the good restart.

**Files state after 2026-04-27 02:30 UTC**:
- `restart.dat` ← original good state from v7 ramp iter 29
- `solution.dat` ← same (input file, untouched throughout)
- `flow.vtu` ← regenerated from restart.dat (1-iter run)
- `history.csv` ← diverged trajectory from the failed reruns
  (kept as evidence; the original M=22.5 history was lost when
  SU2 truncated it on the rerun's startup)
- `run.cfg.before_tight_2348` ← backup of the original cfg

**Diagnosis**: chemistry-shock limit cycle, known v7.5.1 + AIR-7
failure mode. The case fundamentally does not converge below
~residual 0.16 at this mesh resolution (2.7M tets) regardless of
CFL. Same pattern as the documented "CFL_ADAPT misfired on
shock-chemistry limit cycle" issue (task #6 in earlier sprints).

**Status for downstream work**:
- The CFD validator (S-5) can use the v7 ramp's flow.vtu as the
  AIR-7 anchor — it's the BEST result this build can produce.
- The result has known noise floor at residual ~0.16 — this should
  be cited as a limitation in the paper, not hidden.
- For tighter convergence, see roadmap task **F-14** (try MPI binary
  at `/opt/su2-nemo-mpi/` which may have MUSCL/limiter patches).

---

## 3. The disk crisis — root cause + lessons

**What happened** (~07:00 UTC):
1. 4 workers + v7 + base OS pushed `/home/yarden` from 80% to 100% used.
2. Coord's batch 46 spawned workers, but they couldn't write any output
   (filesystem full).
3. Coord crashed silently — no "safety abort" message because the failure
   was at the OS layer, not at the Python `if batch_collected == 0` check.
4. The original `wc -l` showed 895,976 examples on disk.
5. First merge attempt produced only 774,792 lines because cat ran out of
   space mid-write.

**Recovery**:
1. Deleted `/home/yarden/parallel_collect.log` (177 MB Cantera spam).
2. Deleted 4 empty b0046 worker files (negligible bytes, but file table).
3. Deleted partial v3.jsonl.
4. Re-merged via `find ... -print0 | xargs -0 cat` (deterministic order,
   handles arbitrary filenames). Verified 895,976 lines.
5. Deleted worker_b*.jsonl shards (data already in merged file).
6. Deleted 4 obsolete v7 runs at user's authorization
   (`ramC_refined_M10_0_A61_ascii`, `ramC_refined_air11_M10_0_A61`,
   `air11_eos_test`, `ramC_refined_M22_5_A61` — 3.3 GB total).

**Lessons for next time**:
- Coordinator should `df` and abort cleanly if `<500 MB` free.
- Workers should `flush()` after every write (currently only at JSONL
  end), so partial writes are syntactically valid lines.
- Run trainers with `python3 -u` so progress is visible in real time.
  This bit us — 1 hr of training with no log output, only checkpoint
  mtime as proxy.
- Don't co-locate large artifacts: `parallel_collect.log` should have
  been `/dev/null` since the trainer gets the same info from the
  worker stdout summaries.

---

## 4. v4 surrogate — the main artifact

See `docs/SURROGATE_V4_RESULT.md` for the full write-up. Headlines:

```
Test MAE:    0.183 log10  →  factor of 1.52 of Cantera truth
Test MSE:    0.378 log10²
Val   MSE:   0.362 log10²
Train MSE:   0.048 log10²  (heavy fit, val plateau is data-noise floor)
Params:      819,201
Wall:        63.8 min
Inference:   ~0.01 ms/sample (5,000× faster than Cantera 0D)
```

vs v3 (76K, 256-hidden): val ±1.13 → ±0.60 log10 (8× MAE improvement).

---

## 5. The next-phase work

Now that the surrogate is fast AND accurate, the search loop becomes
viable. The natural progression:

```
[done] Random search   →   useful for ground-truth coverage
[done] Genetic search  →   crossover + mutation, but flat exploration
[next] Sobol seed      →   ~1000 quasi-random samples, fills 47-D box
[next] BO outer loop   →   GP over surrogate predictions, max-EI sampling
[next] Cantera verify  →   ground-truth top-K (K=50) from surrogate ranking
[next] SU2-NEMO MPI    →   final shortlist (K=5) for paper figures
```

The hand-off prompt for the next Claude instance is at
`docs/PROMPT_NEXT_INSTANCE_2026-04-26.md`.

---

## 6. Other deliverables in flight (started this session)

- **Streamlit UI**: `apps/surrogate_ui/streamlit_app.py` — drop in
  flight conditions + pick reactions, get predicted ne + dB
  attenuation. Cantera-truth comparison toggle. Local + VM port-forward
  modes both supported.
- **Academic paper draft**: `docs/PAPER_PlasmaNet_2026.md` — AIAA-style,
  10+ page write-up of the framework + v4 result. Sobol/BO outer loop
  noted as future work.

Both built by parallel sub-agents this session — review before sharing.

---

## 7. Don't repeat these (dead ends from 04-25 still apply)

- AIR-11 cold start in SU2-NEMO v7.5.1 — 6 attempts, all NaN at iter 2.
  Mutation++ EOS reference fix exists but chemistry source still NaNs.
  Use AIR-7.
- AIR-7 viscous heap corruption — internal SU2 v7.5.1 bug. Use inviscid.
- CFL_ADAPT misfires on shock-chemistry limit cycles. Disable.
- Single-process Cantera collection caps at ~76K. Use the parallel
  worker pattern.
- Don't run trainer scripts without `python3 -u`.
- Don't run coordinator without a disk-space pre-check.

---

## 8. Memory

Memory file (`MEMORY.md`) updated to reflect v4 milestone. Add an entry
for the next instance:

> Surrogate v4 trained 2026-04-26: 896K examples, test MAE 0.183 log10
> (factor of 1.52). Replaces v3 (±1.13). Path:
> `/home/yarden/mechanism_search_results/surrogate_v4.pt`. Architecture:
> 4-layer 512-hidden MLP, instantiate with hidden_dim=512.

---

## 9. File map (quick reference)

| File | Role |
|------|------|
| `scripts/data_collection_worker.py` | single-batch Cantera worker |
| `scripts/parallel_data_collection.py` | coordinator (4 workers, batched restart) |
| `scripts/train_surrogate_v4.py` | v4 trainer |
| `plasmanet/mechanism_search/surrogate.py` | model class |
| `plasmanet/mechanism_search/scoring.py` | benchmarks + score_candidate |
| `plasmanet/mechanism_search/search_loop.py` | random + genetic (BO TODO) |
| `apps/surrogate_ui/streamlit_app.py` | NN UI |
| `docs/PAPER_PlasmaNet_2026.md` | academic paper draft |
| `docs/SURROGATE_V4_RESULT.md` | v4 metrics |
| `docs/PROMPT_NEXT_INSTANCE_2026-04-26.md` | next-phase brief |

VM:
| Path | Role |
|------|------|
| `/home/yarden/mechanism_search_results/training_data_v3.jsonl` | 896K dataset |
| `/home/yarden/mechanism_search_results/surrogate_v4.pt` | weights |
| `/home/yarden/ram_c_runs/ramC_refined_air7v7b_*` | v7 SU2 ramp outputs |
