# PlasmaNet / Hypersonic Analysis — Session Checkpoint
**Date**: 2026-05-03
**Author**: Claude Opus 4.7 (1M context)
**Purpose**: Hand-off snapshot covering the audit + UX overhaul session that
followed CHECKPOINT_2026-04-26.md.

---

## TL;DR vs 2026-04-26

- **Search v4 made publishable**: pulled BO implementation + v4 weights +
  top-50 search results from the GCP VM into the local checkout. Verified
  bit-exact reproducibility — `Park_AIR7` baseline 6.2462 = local 6.2462,
  top-1 candidate `bo_4889_n=21` 4.3100 = local 4.3100.
- **Track A complete**: iter-251 v8 inviscid vtu pulled, validated
  against J&C 1972. Result: log10 error = **−2.40** (250× under).
  Diagnosis in `TRACK_A_RESULT_2026-05-02.md` — inviscid Euler missing
  the wall-bound boundary-layer chemistry, not a chemistry-model bug.
- **Phase 2.5 viscous smoke test passed**: SU2 v8.4.0 fixes the
  v7.5.1 AIR-7 viscous heap-corruption bug. 100 iters clean exit, all
  7 species residuals finite. Production cold-start cfg + chain script
  staged on the VM but NOT yet launched (5+ hr billable run, awaiting
  user go).
- **4 high-leverage physics fixes** landed after a unified
  textbook-vs-implementation audit (`scripts/unified_hypersonic_solver.py`):
  - `standard_atmosphere` 51-71 km **sign error fixed** (was
    `(T/T_base)^(-12.20)`, must be `+12.20` for negative-lapse layer).
    Single biggest impact: ne over-prediction at M=22.5/61km dropped
    from **14×** to **0.74×** vs hand-calc. P at 60 km now 20.31 Pa
    (USSA76 says 21.97 — 8% drift, was **253 Pa, 12× over**).
  - `SheathProfile._standoff` swapped to **Billig 1967** (`δ_eq =
    R_n × 0.143 × exp(3.24/M²) × ρ_frozen / ρ_eq`). Now scales correctly
    with R_n: capsule (300mm nose) → 18.5mm; sharp_narrow (20mm) →
    1.2mm. Was using `R_n × 0.06 × ρ/10` which happened to give ~9mm
    for RAM-C but was off for any other geometry.
  - `pitot_pressure` audited end-to-end against Rayleigh formula at
    M=2…30. Implementation matches textbook to 1.000 across all Mach.
    The "14× P_t bug" was upstream in atmosphere, not Pitot.
  - `full_analysis` docstring now explicitly documents that **stagnation
    chemistry is geometry-independent** under perfect-gas Pitot — closes
    the recurring "why don't different geometries give different ne?"
    question. Geometry dependence flows through `SheathProfile` (sheath
    thickness via Billig) and `scan_aspect` (LOS through sheath).
- **Frontend wizard UX**: React app at `/` restructured into a 3-step
  flow — `1. Vehicle geometry` (drag-drop + 6-preset tile grid),
  `2. Flight conditions`, `3. Results` (consolidated stagnation +
  per-band attenuation + detection verdict card). Polar plot + station
  profile remain as deeper visualization below.
- **Polar-plot rendering robust across all data**: Catmull-Rom-to-Bézier
  smoothing replaced linear interpolation between sample angles.
  Saturated points (>maxDb) cluster as discrete center markers; near-zero
  rim points break the line; no more spider-web spikes or rim-to-center
  diagonals.
- **Benchmark page no longer dot-jumps**: skeleton placeholder during
  fetch, single render once data arrives. Was rendering pre-bundled
  mock then snapping to live values.
- **Unified solver** (`scripts/unified_hypersonic_solver.py`): single-
  file, audited, hand-calc-vs-implementation comparison across 6
  geometries × 3 flight conditions. Output at
  `data/unified_solver_sweep.md`.

---

## 1. The four physics fixes (the headline)

### 1.1  Atmosphere sign bug at 51–71 km

`plasmanet/physics.py::standard_atmosphere` had:
```python
elif h < 71000:
    T = 270.65 - 0.0028 * (h - 51000)
    p = 66.939 * (T / 270.65) ** (-12.2009)   # WRONG sign
```
For a layer with negative lapse rate L = -0.0028 K/m, the barometric
exponent `-g/(L·R)` evaluates to `+12.20` (negative ÷ negative). With
the wrong negative exponent and T/T_base < 1 (T decreases with
altitude), the formula returns >1, making P **increase** with altitude.

Verified bug impact: at h=61 km the formula gave **P_inf = 253.71 Pa**;
USSA76 reference is **21.97 Pa**. The 12× over-prediction propagated
through Pitot pressure → equilibrium chemistry → ne, accounting for
the 14× ne over-prediction at all M=22.5/61km cases.

After fix:
- 60 km: 20.31 Pa (USSA76: 21.97, within 8%)
- 61 km: 17.66 Pa
- 70 km: 4.63 Pa (USSA76: 5.22, within 11%)
- 80 km: 0.886 Pa (USSA76: 0.886, exact)

Atmosphere also extended cleanly to 86 km with proper isothermal
extrapolation past mesopause.

### 1.2  Billig 1967 in SheathProfile

`plasmanet/ram_c_validation.py::SheathProfile._standoff` was using:
```python
delta_0 = self.nose_radius_m * 0.06 * self.shock_density_ratio / 10.0
```
That happens to give ~9 mm for RAM-C (R_n=152 mm) but is off by 10× for
sharp_narrow / capsule. Replaced with Billig 1967 sphere bow-shock:
```python
delta_frozen_nose = 0.143 * exp(3.24 / M²) * R_n
delta_eq_nose = delta_frozen_nose * 6.0 / shock_density_ratio_eq
```
Added `mach_freestream` field to the dataclass; populated from
`analysis["mach"]` in `build_sheath_field_from_analysis`. Default
`shock_density_ratio` bumped 10 → 14 (correct equilibrium value at
hypersonic). Geometry sweep at M=12 / 35 km now gives:
| vehicle | R_n (mm) | δ_eq (mm) |
|---|---|---|
| sharp_narrow | 20 | 1.25 |
| medium_cone | 50 | 3.13 |
| blunt_cone | 80 | 5.01 |
| ram_c | 152 | 9.55 |
| blunt_wide | 150 | 9.40 |
| capsule | 300 | 18.80 |

Linear scaling with R_n as expected.

### 1.3  pitot_pressure verified

`plasmanet/physics.py::pitot_pressure` matches the textbook Rayleigh
formula to 1.000 across M=2 to M=30. Audit:
| M | text_HC | impl | ratio |
|---|---|---|---|
| 5.0 | 32.65 | 32.65 | 1.000 |
| 10.0 | 129.2 | 129.2 | 1.000 |
| 22.5 | 652.3 | 652.3 | 1.000 |
| 30.0 | 1159 | 1159 | 1.000 |

The earlier 14× P_t apparent bug was 100% upstream from the atmosphere
sign error (#1.1).

### 1.4  Geometry independence documented

`plasmanet/physics.py::full_analysis` docstring now explicitly states:
under perfect-gas Pitot, equilibrium ne depends only on (M, T_∞, P_∞)
— not nose radius, not body length, not half angle. Geometry effects
flow through `SheathProfile` (Billig) and `scan_aspect` (LOS through
sheath). Closes the "why doesn't ne change with geometry?" question
that came up multiple times.

---

## 2. Search v4 reproducibility

### 2.1  Pulled from VM to local

| File | Source on VM | Local path |
|---|---|---|
| `run_search_v4.py` | `/home/yarden/plasmanet/scripts/run_search_v4.py` | `scripts/run_search_v4.py` |
| `search_loop.py` (with `sobol_bayesian_search`) | VM working copy | `plasmanet/mechanism_search/search_loop.py` |
| `surrogate_v4.pt` (3.3 MB) | `/home/yarden/mechanism_search_results/surrogate_v4.pt` | `checkpoints/surrogate_v4.pt` (gitignored) |
| `search_v4_top50_v2.jsonl` | `/home/yarden/mechanism_search_results/search_v4_top50_v2.jsonl` | `data/search_v4/search_v4_top50_v2.jsonl` |
| `search_v4_top50.jsonl` (pre-fix) | same | `data/search_v4/search_v4_top50.jsonl` |
| `baselines_air5_air7.json` | same | `data/search_v4/baselines_air5_air7.json` |
| `search_v4_phase2_full.json` (800 KB) | same | `data/search_v4/` (gitignored — regeneratable) |
| `training_data_v3.jsonl` (285 MB) | same | local backup, **gitignored** |

### 2.2  Reproducibility verified bit-exact

```
Park_AIR7 cantera_0d composite score:
  VM   : +6.2462
  local: +6.2462

Top-1 candidate bo_4889_n=21 cantera_0d composite score:
  VM   : +4.3100
  local: +4.3100
```

Reproduce delta = 0.000000.

### 2.3  Driver `run_search_v4.py` made portable

Originally hardcoded `/home/yarden/...` paths. Updated to:
- `REPO = Path(__file__).resolve().parent.parent`
- `RESULTS_DIR = $PLASMANET_RESULTS_DIR or VM path or repo-relative default`
- `SURROGATE_PATH = $PLASMANET_SURROGATE_PATH or checkpoints/surrogate_v4.pt or VM path`

Runs locally and on VM with no edits.

### 2.4  Cleanup edits

- `cantera_evaluator.py:115`: residence time default 1e-4 → **1e-6**
  (was hitting Saha equilibrium and flattening search signal)
- `surrogate.py:156`: `hidden_dim` default 128 → **512** (was v3, now
  matches v4 weights)
- `mechanism_search/__init__.py`: exports `sobol_bayesian_search`,
  `SobolBOResult`

---

## 3. Track A — iter-251 v8 vs J&C 1972

### 3.1  Validation result

iter-251 v8 inviscid CFD (the converged minimum from Phase 1A's
AUSMPLUSM run, RhoU=−0.2116) at M=22.5 / 61 km gives:

| Metric | Value |
|---|---|
| CFD stagnation T_tr | 7099 K |
| CFD stagnation T_ve | 7627 K |
| CFD stagnation p | 2.13e+05 Pa |
| CFD domain max ne | 1.22e+21 m⁻³ (at stagnation) |
| Sheath p99 ne, station z/L = 0.14 | **8.02e+16 m⁻³** |
| J&C 1972 published peak ne | 2.0e+19 m⁻³ |
| **log10 error vs J&C** | **−2.40** (factor 250 UNDER) |

Worse than v7 column-misread (-1.59). Reason: inviscid Euler has no
boundary layer, so post-shock streamlines pass the body without the
near-wall residence time J&C reflectometers actually measured.

### 3.2  Sanity check (textbook physics, no J&C dependency)

`scripts/sanity_check.py`:

| # | Check | Verdict |
|---|---|---|
| 1 | Frozen RH T₂ (24,115 K) vs CFD T_max (9,676 K) | PLAUSIBLE — chemistry absorbs 60% of kinetic energy |
| 2 | Cantera real-gas T_stag (7,066 K) vs CFD T_tr at stag (7,099 K) | **GOOD** — 0.5% rel err |
| 3 | Saha ne at CFD (T,p) (1.01e22) vs CFD ne at stag (1.22e21) | **FAIR** — CFD 0.9 orders UNDER Saha-eq (AIR-7's NO+-only ion chemistry undershoots) |
| 4 | Billig δ_eq (9.4 mm) vs CFD measured (31.9 mm) | shock detection threshold too lenient at M22.5 |
| 5 | Plasma freq closure | f_p_stag = 313 GHz → blackout consistent at all freqs at stag |

Stagnation chemistry is roughly correct; J&C gap is from inviscid-Euler-
no-BL, not chemistry.

### 3.3  Phase 2.5 viscous smoke test

Result: **SU2 v8.4.0 fixes the v7.5.1 AIR-7 viscous heap-corruption bug.**
100 iters clean exit; residuals finite across all 7 species. The smoke
test ran from the iter-251 warm-start; residuals climbed from -0.23 to
+0.50 in 100 iters because slip→no-slip transition needs many more iters
to relax. Confirms viability — production cold-start cfg + chain script
staged but not launched (5+ hr billable, awaiting user go).

Files:
- `scripts/configs/v8_phase2_5_viscous_smoketest.cfg` (smoke)
- `scripts/configs/v8_phase3_viscous_cold.cfg` (production cold-start)
- `scripts/launch_v8_phase2_chain.sh` (orchestrator: smoke → conditional production)
- `scripts/setup_v8_phase2_run.sh` (mesh tagging + run-dir provisioning)

### 3.4  Track B mesh experiments

Two attempts, both abandoned:
- `mesh_ram_c_v8_phase2.py` — body wall 0.5 mm, produced 12.5M tets
  (target was 4-5M). Coarsening to 1mm wall didn't shrink it further.
- `mesh_ram_c_v8_phase3_viscous.py` — wall-y+ resolved, attempted gmsh
  BoundaryLayer field (silently disabled in 3D). Also targeted full
  domain after first attempt accidentally used body-only STEP.

Conclusion: gmsh threshold-field meshing for hypersonic full-domain at
fine BL resolution overshoots 6M cells. Track B properly needs
Pointwise/cfMesh/Spider with proper hybrid hex+prism BL, not gmsh
field stack.

---

## 4. Frontend UX overhaul

### 4.1  Wizard layout at `/`

Three-step structure on the home page:
1. **Vehicle geometry** (`GeometryUpload.tsx` — new component): drag-drop
   STEP/STL/SU2 zone + 6-preset tile grid. Dropping a file shows the
   filename and a placeholder note (parser not yet wired).
2. **Flight conditions**: existing `FlightSelectors` Mach/altitude pill rows.
3. **Results** (`ResultsCard.tsx` — new component): consolidated
   stagnation T/p/ne/fp tile grid, vs-J&C ratio (when applicable), and
   a per-band peak-attenuation table with DETECTABLE/DEGRADED/BLACKOUT
   verdicts.

Polar plot + station profile chart remain below as deeper viz.

### 4.2  Polar plot robustness

`LOSPolarPlot.tsx`:
- `polarToXY` clamps `r ∈ [0, maxRadius]` (was wrapping past center
  for atten > maxDb)
- maxDb tiers extended to 10/25/50/100/250/500 dB; saturated badge
  shown when raw peak exceeds chart cap
- **Catmull-Rom-to-Bézier `smoothPath`** replaces linear interpolation
  between sample angles — handles any data smoothly, no polygonal
  facets, no rim-to-center diagonals
- Lines break at saturated AND near-zero (<0.1 dB) endpoints; saturated
  cluster shows as small color-coded squares at chart center per band
- UQ shaded band uses same Catmull-Rom densification

### 4.3  Benchmark skeleton

`/benchmark` no longer renders mock data during loading then snaps to
live values. Initial state is `data: null`; shows pulsing skeleton
placeholders; renders the chart/table once and only once when fetch
completes.

### 4.4  Backend perf

`mock_server.py::_compute_scan_data`:
- Per-band request rebuild so all 4 bands hit `_try_real_physics`
  (was: only Ku, others fell to mock that mixed JSON-cached values
  from a different flight condition with near-zero analytical values)
- UQ disabled for VHF/X bands (UQ chart only shown for Ku)
- UQ samples capped at 16 (was 64)
- `physics.full_analysis` wrapped in `@lru_cache(64)` so 4 bands of
  same flight condition share chemistry computation

Warm-cache latency: **~1.4-1.8 s steady-state** for /analyze_scan
(was 2.4-3.3 s before optimizations).

### 4.5  Frontend timeout

`AbortSignal.timeout(6000)` → **15000** ms — accommodates Cantera cold
start without spurious "signal timed out" badges.

---

## 5. New scripts and tools

### 5.1  `scripts/unified_hypersonic_solver.py`

Single-file, fully self-contained reference solver. Walks every step
(atmosphere → shock → stagnation → chemistry → bow-shock →
attenuation) computing each quantity twice: once via closed-form
textbook formula (HC) and once via the existing codebase
implementation (IM). Reports both numbers + percent-difference.

Modes:
- Single case: `--vehicle ram_c --mach 22.5 --altitude 61`
- Sweep: `--sweep` → all 6 geometries × 3 flight conditions to
  `data/unified_solver_sweep.md`

This is the canonical reference for any future hypersonic-physics
audit.

### 5.2  `scripts/sanity_check.py`

Quick first-principles spot-check for any CFD vtu. Computes 5 textbook
references (frozen RH, real-gas Cantera-enthalpy T_stag, Saha at CFD
(T,p), Billig standoff, plasma freq closure) and compares to the
extracted CFD field. Used during Track A to diagnose iter-251.

### 5.3  `scripts/geometry_sweep.py`

Driver that runs `analyze_detectability` across all 6 geometries at
fixed (M, alt) and prints attenuation per aspect angle. Used to confirm
the solver responds to geometry inputs (it does — through SheathProfile
Billig standoff and LOS scan, not chemistry).

### 5.4  Mesh attempts

- `scripts/mesh_ram_c_v8_phase2.py` — gmsh threshold-stack, 0.5 mm wall
- `scripts/mesh_ram_c_v8_phase3_viscous.py` — attempted BoundaryLayer
  field (silently disabled in 3D)
- `scripts/setup_v8_phase2_run.sh` — tag mesh + provision run dir
- `scripts/launch_v8_phase2_chain.sh` — orchestrate smoke → production

Both mesh scripts produced 7-12M tets (overshooting 4-6M target);
neither used in production. Documented for posterity.

---

## 6. What's still pending

### Solver
- **Phase 2.5 viscous production CFD** — staged on VM (`/home/yarden/ram_c_runs/v8_phase3_viscous_prod/`), needs explicit user go to launch (~17 hr wall)
- **LOS Appleton-Hartree band ordering inverted** — VHF<X<Ku in evanescent regime, opposite of textbook. Bug in `plasma_wave.attenuation_rate_db_per_m`. Flagged but not fixed.
- **Stagnation chemistry vs J&C 1972**: still 4× over at M=22.5/61km after the atmosphere fix. That residual gap is equilibrium-vs-finite-rate; only the v4 surrogate (trained at fixed 1µs residence time) captures it correctly.
- **Fay-Riddell heat flux**: not implemented in any layer. Needed to make geometry actually affect chemistry (currently only affects sheath thickness).

### Frontend
- **Backend STEP parser** for the upload flow — `/api/plasma/parse_geometry` endpoint that extracts bbox + nose-radius via cadquery/OCC. Currently the upload accepts the file but falls back to preset selector.
- **3D viewer** — Three.js + STLLoader for the selected geometry, like cadpipe's plasma.html does.
- **PDF report download** — wire a button to `/api/plasma/report` (already returns a PDF).
- **Trajectory sweep visualization** — Mach × altitude grid, like the Benchmark page but for arbitrary vehicle.

### Process
- The `frontend/src/data/mock_benchmark.json` snapshot is now drifting from live data after the recent solver fixes. Worth regenerating from a fresh API call so the offline fallback matches what live currently produces.

---

## 7. File map (new this session)

| Path | Role |
|---|---|
| `scripts/unified_hypersonic_solver.py` | Audit + hand-calc reference solver |
| `scripts/sanity_check.py` | First-principles cross-check for a CFD vtu |
| `scripts/geometry_sweep.py` | Multi-geometry detectability driver |
| `scripts/run_search_v4.py` | Sobol+BO search driver (pulled from VM) |
| `scripts/mesh_ram_c_v8_phase2.py` | Phase 2 inviscid mesh attempt |
| `scripts/mesh_ram_c_v8_phase3_viscous.py` | Wall-resolved mesh attempt |
| `scripts/setup_v8_phase2_run.sh` | Tag mesh + stage run dir |
| `scripts/launch_v8_phase2_chain.sh` | Orchestrate smoke + production |
| `scripts/configs/v8_phase2_cold.cfg` | Phase 2 inviscid cold-start cfg |
| `scripts/configs/v8_phase2_5_viscous_smoketest.cfg` | Viscous smoke cfg |
| `scripts/configs/v8_phase3_viscous_cold.cfg` | Viscous cold-start production cfg |
| `frontend/src/components/GeometryUpload.tsx` | Drag-drop geometry zone + presets |
| `frontend/src/components/ResultsCard.tsx` | Consolidated post-analysis card |
| `data/search_v4/search_v4_top50_v2.jsonl` | BO-discovered top-50 mechanisms |
| `data/search_v4/baselines_air5_air7.json` | Park AIR-5/AIR-7 reference scores |
| `data/cfd_runs/v8_phase1A_iter251/{validation.json,validation.md,sanity_check.json}` | Track A artifacts |
| `data/unified_solver_sweep.md` | Auto-generated audit table |
| `docs/TRACK_A_RESULT_2026-05-02.md` | Track A writeup |
| `docs/CHECKPOINT_2026-05-03.md` | This file |

---

## 8. For the next instance

The next handoff should focus on one of:

1. **Phase 2.5 viscous production launch** — user explicit go required.
   `cd /home/yarden/ram_c_runs/v8_phase3_viscous_prod && nohup bash launch.sh > su2.log 2>&1 &`. ~17 hr wall.

2. **Backend STEP parser** for the frontend upload UX. ~2-3 hr work.
   Use cadquery or OCC.Core to read a STEP file, extract bbox, infer
   sphere-cone params from the nose region, return as a VehicleGeometry.

3. **LOS Appleton-Hartree band ordering bug fix** — `plasma_wave.py`
   evanescent-regime attenuation should be roughly band-independent
   (deep evanescent) or decrease with f (near cutoff). Currently it
   increases with f. Compare against the textbook AH cold-plasma
   dispersion.

4. **Cleanup mock_benchmark.json drift** — regenerate from a fresh
   live API call so the static fallback matches what live serves.

The unified solver (`scripts/unified_hypersonic_solver.py`) is the
canonical reference for any further physics audits — when in doubt,
add a step to it and compare HC vs IM.
