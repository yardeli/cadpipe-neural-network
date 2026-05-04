# AUDIT — M22.5 RAM-C II Convergence Failure (SU2-NEMO v7.5.1 + AIR-7)

**Date**: 2026-04-27
**Scope**: Read-only audit of the chemistry-shock limit cycle blocking M=22.5 / 61 km / 2.74M-tet inviscid case at `ramC_refined_air7v7b_M22_5_A61/`. No cfg or code changes made.
**Bottom line**: The current run.cfg is unusually *minimal* — only the absolute-required keys are set, and all of the obvious convergence-stabilizers (scheme choice, entropy fix, MUSCL+limiter, accurate Jacobians) are at defaults or actively disabled. There are 3 cheap cfg-only changes that should each break the limit cycle, ranked below.

---

## 1. Current cfg inventory

Source: `gcloud compute ssh openfoam-hgv -- cat /home/yarden/ram_c_runs/ramC_refined_air7v7b_M22_5_A61/run.cfg` (read at 2026-04-27 ~03:02 UTC).

| Group | Key | Current value | Default | Notes |
|---|---|---|---|---|
| Solver | `SOLVER` | `NEMO_EULER` | — | Inviscid, two-temperature, finite-rate chem |
| Solver | `GAS_MODEL` | `AIR-7` | — | Built-in CSU2TCLib (Park-1990 reduced) |
| Solver | `GAS_COMPOSITION` | `(0.0, 0.77, 0.23, 0.0, 0.0, 0.0, 0.0)` | — | Order: e-, N2, O2, NO, N, O, NO+ (correct) |
| Solver | `FLUID_MODEL` | `SU2_NONEQ` | — | Required to avoid the segfault documented in `SU2_NEMO_FIX.md` |
| Solver | `MATH_PROBLEM` | `DIRECT` | — | Steady |
| Restart | `RESTART_SOL` | `YES` | — | From iter-29 of v7 ramp |
| Restart | `SOLUTION_FILENAME` | `solution.dat` | — | |
| Freestream | `MACH_NUMBER` | `22.5` | — | RAM-C II |
| Freestream | `FREESTREAM_PRESSURE` | `253.71 Pa` | — | 61 km |
| Freestream | `FREESTREAM_TEMPERATURE` | `242.65 K` | — | 61 km |
| Freestream | `FREESTREAM_TEMPERATURE_VE` | `242.65 K` | — | T_ve = T_tr at freestream |
| Freestream | `AOA` / `SIDESLIP_ANGLE` | `0.0 / 0.0` | — | |
| BCs | `MARKER_EULER` | `( body )` | — | Slip wall on RAM-C nose |
| BCs | `MARKER_FAR` | `( farfield )` | — | |
| BCs | `MARKER_PLOTTING` | `( body )` | — | |
| BCs | `MARKER_MONITORING` | `( body )` | — | |
| Spatial | `NUM_METHOD_GRAD` | `WEIGHTED_LEAST_SQUARES` | GREEN_GAUSS | OK for tets |
| Spatial | `CONV_NUM_METHOD_FLOW` | `LAX-FRIEDRICH` | — | **Centered scheme**, dispatches to `CCentLax_NEMO`. First-order, kappa-controlled artificial dissipation |
| Spatial | `MUSCL_FLOW` | `NO` | YES | **Disabled** — solver runs first-order. Slope-limiter is therefore inactive |
| Spatial | `SLOPE_LIMITER_FLOW` | (unset, default VENKATAKRISHNAN) | VENKATAKRISHNAN | Inactive because MUSCL=NO |
| Spatial | `VENKAT_LIMITER_COEFF` | (unset, default 0.05) | 0.05 | Inactive |
| Spatial | `LAX_SENSOR_COEFF` | (unset, default 0.15) | 0.15 | First-order Lax-Friedrichs dissipation. Higher = more dissipation, more stable |
| Spatial | `JST_SENSOR_COEFF` | n/a (LAX path) | (0.5, 0.02) | Not used because we're not on JST |
| Spatial | `ROE_KAPPA` | n/a (not Roe) | 0.5 | Not used |
| Spatial | `ENTROPY_FIX_COEFF` | (unset, default 0.001) | 0.001 | Lower bound on convective eigenvalue (used by Roe in NEMO; Lax doesn't read it) |
| Time | `TIME_DISCRE_FLOW` | `EULER_IMPLICIT` | — | Backward-Euler. Required for AIR-7 (CSU2TCLib supports implicit, unlike Mutation++) |
| Time | `CFL_NUMBER` | `0.1` | 1.0 | Already 10x below default |
| Time | `CFL_ADAPT` | `NO` | NO | Correctly disabled (per task #6 lesson — CFL_ADAPT misfires on shock-chemistry limit cycles) |
| Time | `USE_ACCURATE_FLUX_JACOBIANS` | (unset, default NO) | NO | Slower per-iter but allows higher CFL. Not currently in use |
| LinSolve | `LINEAR_SOLVER` | `BCGSTAB` | — | |
| LinSolve | `LINEAR_SOLVER_ERROR` | `1E-6` | 1e-5 | Tighter than default |
| LinSolve | `LINEAR_SOLVER_ITER` | `5` | 5 | |
| Convergence | `CONV_FIELD` | `( RMS_MOMENTUM-X )` | — | Single-field; not Cauchy |
| Convergence | `CONV_RESIDUAL_MINVAL` | `-15` | -8 | Tight (effectively means "run ITER iters") |
| Convergence | `CONV_STARTITER` | `100` | 10 | |
| Convergence | `CONV_CAUCHY_*` | (unset) | n/a | Not enabled |
| I/O | `ITER` | `1` | — | Currently set to 1 — last command was a one-shot regen of flow.vtu. Diverged runs used `ITER=300` and `ITER=600` |
| I/O | `OUTPUT_WRT_FREQ` | `50` | 250 | OK |
| I/O | `OUTPUT_FILES` | `(RESTART, PARAVIEW)` | — | |

### What's notable about this cfg

- **MUSCL_FLOW=NO**: solver is strictly first-order. Limiter flapping is NOT the limit-cycle source — it's not even active. This is *good news* for the diagnosis: the bouncing residual is genuine, not an artifact of an oscillating Venkatakrishnan limiter.
- **LAX-FRIEDRICH** is the most dissipative SU2-NEMO scheme on paper, but its dissipation is set by `LAX_SENSOR_COEFF` (default 0.15). Doubling that to 0.3 is the cheapest knob in the entire toolbox.
- **ENTROPY_FIX_COEFF unset**: irrelevant for current LAX path, but becomes critical if we switch to Roe.
- **No CONV_CAUCHY**: convergence is judged only on raw residual minval. A Cauchy residual (relative change over a window) would have caught the original "iter 29 lucky low" behavior automatically.
- **`OMP_NUM_THREADS` is set in the launcher script, not the cfg** — confirmed via `ram_c_refined_ramp_air7_v4.sh` (16 threads).

---

## 2. Known SU2-NEMO v7.5.1 chemistry-shock failure modes

From project history (`CHECKPOINT_2026-04-25.md`, `CHECKPOINT_2026-04-26.md`, `SU2_NEMO_FIX.md`) and external sources:

### From our own dead-end inventory
1. **CFL_ADAPT misfires on shock-chemistry limit cycles** (task #6 fix). Adapter sees the residual bounce, reduces CFL toward floor 0.05, walltime explodes. Fix was to disable CFL_ADAPT — already applied to current cfg.
2. **AIR-11 + Mutation++ chemistry-source NaN at iter 2** (6 attempts). Independent bug, but suggests the v7.5.1 chemistry path has rough edges around source-term Jacobians.
3. **AIR-7 + viscous heap corruption** in NEMO_NS preprocessing. Not relevant to inviscid case but indicative of sloppy memory handling in the AIR-7 code paths.
4. **AIR-5 working cfg used MUSCL+VENKATAKRISHNAN+LAX-FRIEDRICH at CFL=1.0** (per `SU2_NEMO_FIX.md`). Our current cfg is strictly more conservative *except* for MUSCL=NO — this is suspicious as a regression.

### From the SU2-NEMO paper (Maier et al., 2021, MDPI Aerospace 8(7):193)
- Two NEMO-specific schemes: **MSW** (Modified Steger-Warming) and **AUSM** family.
- MSW description: *"highly dissipative, mitigates convergence issues due to the stiffness of nonequilibrium equations"* → this is exactly the failure mode we have.
- AUSM description: *"superior shock-capturing, avoids carbuncles in stagnation regions of blunt bodies"* → carbuncle is one classic cause of bow-shock limit cycles, especially for symmetric blunt bodies on tetrahedral meshes.

### From GitHub / forums
- **Issue #2717** ([github.com/su2code/SU2/issues/2717](https://github.com/su2code/SU2/issues/2717)): SU2-NEMO residuals stall and diverge with AUSMPLUSUP2 + nondimensionalization. Affected user: 1st order works, 2nd order (MUSCL) does not converge below ~1.7. Different specific failure but same family ("residual stalls then diverges in NEMO at high Mach"). Workarounds explored: limiter changes, scheme changes, mesh refinement.
- **CFD Online thread 250099** ([cfd-online.com](https://www.cfd-online.com/Forums/su2/250099-su2-nemo-divergence-hypersonic-apollo.html)): SU2-NEMO Apollo capsule re-entry diverges hypersonically. Common fix: lower CFL toward 0.5–1.0, increase ENTROPY_FIX_COEFF, switch to MSW.
- **SU2 FAQ** (`su2code.github.io/docs/FAQ`): "When previously-converging cases now diverge, lower CFL or increase artificial dissipation coefficients."

### Carbuncle / bow-shock numerical anomaly (relevant general theory)
- Roe-flux schemes are notorious for carbuncle on blunt-body bow shocks at high Mach on prismatic/tetrahedral meshes, *especially* with finite-rate chemistry that reinforces the asymmetric heating loop. Symptom: residual won't drop below ~1, oscillates with a 1e-1 amplitude. Matches our 0.16 floor exactly.
- Standard cures: (a) more dissipative scheme (MSW > Roe > AUSM > Lax for shock-region dissipation in NEMO), (b) entropy fix coefficient raised to 0.05–0.1, (c) shock-aligned mesh, (d) dual-time / pseudo-time damping.

---

## 3. MPI binary source-tree diff vs vanilla v7.5.1

**Verified**: `/tmp/SU2-build-mpi/` is **unmodified vanilla v7.5.1**. Evidence:
- `find /tmp/SU2-build-mpi -newer .gitignore -type f` returns 0 user-modified files (excluding the `build-mpi/` ninja outputs).
- `find -name "*.cpp" -newer AUTHORS.md` (which is from the v7.5.1 release tarball) returns nothing.
- All source-file mtimes are 2026-04-25 22:41 UTC (the extract time).
- `Common/src/CConfig.cpp` lines 6087–6098 contain the AIR-7 allowlist already in the vanilla 7.5.1 release — no patch was needed:

  ```cpp
  case MAIN_SOLVER::NEMO_EULER:
    ...
    if ((GasModel != "N2") && (GasModel != "AIR-5") && (GasModel != "AIR-7") && (GasModel != "ARGON"))
      SU2_MPI::Error("The GAS_MODEL given as input is not valid. ...");
  ```

So the memory's note about "CConfig.cpp:6094-6095 patches for AIR-7 viscous" refers to a *different* attempted patch — the AIR-7 viscous (`NEMO_NAVIER_STOKES`) work that hit heap corruption and was abandoned (per `CHECKPOINT_2026-04-25.md` §4 dead-end #4). That patch was applied to a **different build directory** (`/opt/su2-nemo-mpi-air7v/`, since deleted) and never merged into `/opt/su2-nemo-mpi/`.

**Implication**: switching the runtime binary from `/opt/su2-nemo/bin/SU2_CFD` (serial) to `/opt/su2-nemo-mpi/bin/SU2_CFD` will give us **MPI parallelism only** (10–15× speedup per past benchmarks) but **no different chemistry-shock numerical behavior**. The limit cycle will reproduce. Don't spend a half-day on the MPI swap as a convergence fix — only as a wall-time accelerator once the cfg fix is found.

---

## 4. Ranked fix list (cheapest → expensive)

Each fix shows: cfg lines | physics rationale | risk | how to test | confidence.

### Fix #1 — Re-enable MUSCL with a heavily-clipped limiter
**Cfg changes**:
```ini
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VAN_ALBADA_EDGE
VENKAT_LIMITER_COEFF= 0.01     % only used if SLOPE_LIMITER=VENKATAKRISHNAN
```
**Why**: Counter-intuitive but well-documented — going from 1st to 2nd order with a *sharp* limiter (Van Albada edge formulation) often improves convergence on bow-shock cases by giving the Newton solver a smoother RHS. The current 1st-order LAX is so dissipative that it's smearing the post-shock chemistry layer, which paradoxically lets the chemistry source term pull the smeared profile in two different directions (the limit cycle). Adding back gradient information sharpens the shock, the chemistry source can lock onto a single equilibrium branch. AIR-5 working cfg from `SU2_NEMO_FIX.md` had `MUSCL_FLOW=YES + VENKATAKRISHNAN` and converged to -8.
**Risk**: Limiter flapping (the original task #6 hazard) reappears. Mitigated by VAN_ALBADA_EDGE which is monotone differentiable, *not* the Venkat-style multivalued switch. If it flaps, tighten VENKAT to 0.01 or fall back.
**Test cheaply**: Warm-start from `restart.dat`, ITER=100, monitor RhoU at iter 50. Goal: residual decreasing past -1.0. Wall: ~30 min serial / 3 min MPI.
**Confidence**: medium-high. This is the single most-likely-to-fix change.

### Fix #2 — Switch to MSW (Modified Steger-Warming)
**Cfg changes**:
```ini
CONV_NUM_METHOD_FLOW= MSW
MUSCL_FLOW= NO         % keep 1st order initially
```
**Why**: MSW is purpose-built for stiff chemistry-shock interactions. From the SU2-NEMO paper (Maier 2021): *"widely used due to its highly dissipative nature, mitigating convergence issues due to the stiffness of non-equilibrium equations."* Source confirmed at `/tmp/SU2-build-mpi/SU2_CFD/src/numerics/NEMO/convection/msw.cpp` and dispatched in `CDriver.cpp:1933` via `case UPWIND::MSW`. LAX is also dissipative but its dissipation is uniform; MSW's dissipation is *Mach-aware* and concentrated where it's needed (across the shock).
**Risk**: MSW is more expensive per iteration (eigendecomp inside the flux). May need slightly lower CFL initially. Smearing is more localized than LAX so post-shock T_ve will sharpen — verify no NaN.
**Test cheaply**: Warm-start from `restart.dat`, ITER=100, CFL=0.1. Goal: residual breaks below -1.0 by iter 80. If MSW alone doesn't fix it, combine with Fix #1 (MUSCL_FLOW=YES + VAN_ALBADA_EDGE). Wall: ~40 min serial.
**Confidence**: high. MSW exists *specifically* to fix this class of problem.

### Fix #3 — Crank up Lax artificial dissipation
**Cfg changes**:
```ini
LAX_SENSOR_COEFF= 0.4    % default 0.15 → 0.4 (~2.7× more dissipation)
```
**Why**: Cheapest change in the catalog — single number, no scheme switch. Increasing the Lax-Friedrichs artificial dissipation directly damps high-frequency residual oscillations, including the chemistry-shock limit cycle. The original `SU2_NEMO_FIX.md` AIR-5 reference cfg used the default 0.15 and converged at M=10 with MUSCL — but at M=22.5 the post-shock state is far stiffer, justifying more dissipation.
**Risk**: Solution becomes mushy. Bow-shock thickness grows by ~30%, and the post-shock T_tr peak drops. This is a *quality* hit, not a *correctness* hit — the converged ne profile near the wall (which is what S-5 / RAM-C validation cares about) is set by post-shock equilibrium, which is largely insensitive to shock-thickness choice once you're past the shock.
**Test cheaply**: Warm-start from `restart.dat`, ITER=100, CFL=0.1. Goal: residual smoothly decreasing — limit cycle should disappear or its amplitude should drop by ≥10×. Wall: ~30 min serial.
**Confidence**: medium. Helps if the issue is purely shock-region noise; doesn't help if the issue is genuinely chemistry-source bistability further downstream.

### Fix #4 — Enable accurate flux Jacobians (better Newton convergence)
**Cfg changes**:
```ini
USE_ACCURATE_FLUX_JACOBIANS= YES
```
**Why**: Per SU2 docs / config_template.cfg comment: *"Slower per iteration but potentially more stable and capable of higher CFL."* Currently NEMO is using approximate analytical Jacobians, which are correct for ideal-gas flow but become imprecise for the AIR-7 finite-rate chemistry source coupling. Numerical Jacobians (autodiff or FD inside the linear solve) are more expensive but lock the implicit Newton step on the *true* coupled physics.
**Risk**: ~2-3× per-iter cost. May not even apply for LAX (the option is documented as primarily affecting AUSMPLUSUP2 and SLAU2 schemes — verify by greplog at startup).
**Test cheaply**: Warm-start, ITER=50, CFL=0.2 (push higher since stability should improve). Wall: ~30 min serial.
**Confidence**: low-medium. Worth combining with Fix #2 (MSW + accurate Jacobians) but not a standalone winner.

### Fix #5 — Switch to AUSMPLUSM (carbuncle-resistant scheme)
**Cfg changes**:
```ini
CONV_NUM_METHOD_FLOW= AUSMPLUSM
USE_ACCURATE_FLUX_JACOBIANS= YES
```
**Why**: From the SU2-NEMO paper: *"AUSM family avoids carbuncle in stagnation regions around blunt bodies."* Our case is exactly this geometry (blunt nose, axisymmetric tet mesh). AUSMPLUSM also has a built-in pressure-diffusion sensor active in the NEMO solver (see `CNEMOEulerSolver.cpp:276`), which suppresses asymmetric stagnation-line oscillations.
**Risk**: AUSMPLUSUP2 (similar family) has been documented to crash with reference dimensionalization (issue #2717). AUSMPLUSM is reportedly more stable but warrants a small-iter trial first to confirm it doesn't NaN.
**Test cheaply**: Cold-start at M=10 (cheap, ~5 min) with AUSMPLUSM to verify the scheme is alive, *then* warm-start at M=22.5. Wall: ~40 min total.
**Confidence**: medium. Carbuncle is a real candidate cause for the limit cycle; AUSMPLUSM is the targeted cure.

### Fix #6 — Add CONV_CAUCHY for stable convergence detection
**Cfg changes**:
```ini
CONV_FIELD= ( RMS_MOMENTUM-X )
CONV_CAUCHY_ELEMS= 100
CONV_CAUCHY_EPS= 1E-3
CONV_RESIDUAL_MINVAL= -15
```
**Why**: Doesn't fix the limit cycle, but stops us from getting fooled by lucky low-residual moments (the original "iter 29 lucky -9.27" symptom). With Cauchy enabled, SU2 will only declare convergence if the residual *change over the last 100 iterations* is below 1e-3, which is impossible inside a limit cycle by definition.
**Risk**: None — pure diagnostic. Worst case, `CONV_RESIDUAL_MINVAL=-15` is hit first and Cauchy is irrelevant.
**Test cheaply**: Free — bolted onto any other test.
**Confidence**: high (as a diagnostic), zero (as a fix).

### Fix #7 — MPI binary swap (`/opt/su2-nemo-mpi/bin/SU2_CFD`)
**Cfg changes**: None — launcher script change only:
```bash
SU2=/opt/su2-nemo-mpi/bin/SU2_CFD
mpirun -np 16 $SU2 run.cfg
```
**Why**: 10–15× wall-time reduction per past notes. Does NOT change numerical behavior — vanilla v7.5.1, no patches (verified §3). The limit cycle will still be there, just discovered faster.
**Risk**: MPI domain decomposition can introduce its own non-determinism for chemistry-stiff cases (process boundary halo updates lag the source-term Newton step). Has been seen to *worsen* convergence on stiff cases. Not a free win.
**Test cheaply**: After Fix #2 or #1 succeeds serial, swap to MPI for the production rerun. **Don't combine MPI + a numerical fix in the same trial** — you can't tell which contributed.
**Confidence**: zero (as a numerical fix), high (as a wall-time optimization once numerical fix is identified).

### Fix #8 — Mesh refinement near bow shock
**Cfg changes**: None directly — regenerate `ram_c_refined.su2` with a near-shock layer (5–10 cells across the expected shock standoff distance).
**Why**: At M=22.5 the bow-shock standoff is ~3 mm for the RAM-C nose. If the current 2.74M-tet mesh has 1–2 cells across that, the shock is grossly under-resolved and the limit cycle is partly a *resolution* artifact, not a numerical-scheme one.
**Risk**: Half-day of work (Pointwise/Gmsh time + remeshing + re-run M=10 ramp from scratch). Would also want to re-validate AIR-5 baseline on the new mesh for consistency.
**Test cheaply**: Not cheap. Defer until cfg-only fixes are exhausted.
**Confidence**: medium-low. Mesh is a credible co-factor but rarely the sole cause when the same mesh worked at M=10/15/18.

### Fix #9 — Try Mutation++ + AIR-7 (different chemistry library)
**Cfg changes**:
```ini
FLUID_MODEL= MUTATIONPP
GAS_MODEL= air_7         % lowercase XML name
TIME_DISCRE_FLOW= EULER_EXPLICIT
```
**Why**: CSU2TCLib (built-in) and Mutation++ implement Park rates differently — different reference enthalpies, different vibrational coupling. If the limit cycle is a CSU2TCLib-specific bistability in the chemistry source, swapping libraries breaks it.
**Risk**: Mutation++ doesn't support `EULER_IMPLICIT` in v7.5.1 (per `SU2_NEMO_FIX.md`). Going explicit means CFL ≤ 0.5 hard, ITER counts in the thousands, and the case takes 4× longer. Also, Mutation++ has its own AIR-11 NaN-at-iter-2 reputation; AIR-7 may share the bug.
**Test cheaply**: Cold-start at M=10 first to verify Mutation++/AIR-7 path is alive at all. ~1 hour.
**Confidence**: low. Big sledgehammer for an uncertain payoff.

---

## 5. Top-2 recommended quick wins

### #1: MUSCL_FLOW=YES + VAN_ALBADA_EDGE limiter (Fix #1 above)

**Why first**: 3-line cfg change. Targets the most likely root cause (over-dissipated 1st-order shock smearing the chemistry source's lock-in region). Matches the working AIR-5 cfg from `SU2_NEMO_FIX.md` which converged cleanly at M=10. The earlier project lesson "MUSCL_FLOW=NO is required for stability" comes from the *cold-start* M=10 stage — which is a different physical regime (chemistry mostly frozen) than the *warm-start* M=22.5 stage (chemistry fully active). Re-enabling MUSCL at M=22.5 is appropriate now that the bulk flow is converged.

**Cfg diff** (vs current):
```ini
- MUSCL_FLOW= NO
+ MUSCL_FLOW= YES
+ SLOPE_LIMITER_FLOW= VAN_ALBADA_EDGE
+ CONV_CAUCHY_ELEMS= 100
+ CONV_CAUCHY_EPS= 1E-3
```
Keep `CFL_NUMBER=0.1`, `ITER=100` for the trial.

**Trial command** (read-only, for the user to copy when ready):
```bash
gcloud compute ssh openfoam-hgv --zone=us-central1-a --command='
  cd /home/yarden/ram_c_runs/ramC_refined_air7v7b_M22_5_A61
  cp run.cfg run.cfg.before_muscl_test
  cp restart.dat solution.dat   # warm-start from the good iter-29 state
  # edit run.cfg per diff above, then:
  setsid /opt/su2-nemo/bin/SU2_CFD run.cfg \
    > su2_muscl_test.log 2>&1 < /dev/null &
'
```
**Pass criterion**: RhoU < -1.5 by iter 80, monotonically decreasing. Wall: ~30 min serial.

### #2: CONV_NUM_METHOD_FLOW=MSW (Fix #2 above)

**Why second**: 1-line cfg change. Most physically-motivated fix — MSW is documented in the SU2-NEMO paper specifically as the answer to "stiffness of non-equilibrium equations." Independent of Fix #1 (different scheme entirely, not just a 1st→2nd order change), so worth testing in parallel/sequence. If Fix #1 succeeds you may not need this; if Fix #1 fails this is the next stop.

**Cfg diff**:
```ini
- CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
+ CONV_NUM_METHOD_FLOW= MSW
+ CONV_CAUCHY_ELEMS= 100
+ CONV_CAUCHY_EPS= 1E-3
```
Keep `MUSCL_FLOW=NO`, `CFL_NUMBER=0.1`, `ITER=100` for the trial. If MSW alone insufficient, follow up with `MUSCL_FLOW=YES + SLOPE_LIMITER_FLOW=VAN_ALBADA_EDGE` (combines #1 and #2).

**Pass criterion**: RhoU < -1.0 by iter 60 with no positive-residual excursions. Wall: ~40 min serial.

---

## 6. References / citations

- Maier, W. T., Needels, J. T., Garbacz, C., Morgado, F., Alonso, J. J., & Fossati, M. (2021). **SU2-NEMO: An Open-Source Framework for High-Mach Nonequilibrium Multi-Species Flows.** *Aerospace*, 8(7), 193. [mdpi.com/2226-4310/8/7/193](https://www.mdpi.com/2226-4310/8/7/193)
- SU2 v7 docs — Convective Schemes: [su2code.github.io/docs_v7/Convective-Schemes/](https://su2code.github.io/docs_v7/Convective-Schemes/)
- SU2 v7 docs — Slope Limiters and Shock Resolution: [su2code.github.io/docs_v7/Slope-Limiters-and-Shock-Resolution/](https://su2code.github.io/docs_v7/Slope-Limiters-and-Shock-Resolution/)
- SU2 v7 docs — Thermochemical Nonequilibrium: [su2code.github.io/docs_v7/Thermochemical-Nonequilibrium/](https://su2code.github.io/docs_v7/Thermochemical-Nonequilibrium/)
- SU2 GitHub Issue #2717 — *SU2-NEMO residuals stalling and divergence with nondimensionalization+AUSMPLUSUP2*: [github.com/su2code/SU2/issues/2717](https://github.com/su2code/SU2/issues/2717)
- CFD Online forum thread 250099 — *SU2 NEMO divergence hypersonic Apollo*: [cfd-online.com/Forums/su2/250099-su2-nemo-divergence-hypersonic-apollo.html](https://www.cfd-online.com/Forums/su2/250099-su2-nemo-divergence-hypersonic-apollo.html)
- SU2-NEMO Foundation talk (Garbacz 2020): [su2foundation.org/wp-content/uploads/2020/06/Garbacz.pdf](https://su2foundation.org/wp-content/uploads/2020/06/Garbacz.pdf)
- Project internal: `docs/CHECKPOINT_2026-04-25.md` §4 (dead-end inventory), `docs/CHECKPOINT_2026-04-26.md` §2.5 (M22.5 timeline), `docs/SU2_NEMO_FIX.md` (AIR-5 working reference cfg).
- VM: `/tmp/SU2-build-mpi/SU2_CFD/src/numerics/NEMO/convection/{lax,msw,roe,ausm_slau}.cpp` — vanilla v7.5.1, unmodified. `/tmp/SU2-build-mpi/SU2_CFD/src/drivers/CDriver.cpp:1920–1980` — NEMO scheme dispatch table.

---
*End of audit. Recommended next action: user runs Fix #1 trial (~30 min serial, ~3 min if MPI) before any deeper changes.*
