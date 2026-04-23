# Roadmap: Path C (SU2-NEMO Coupled Chemistry) + SimOps Integration

**Date:** 2026-04-23
**Status:** Active — Path C in progress; SimOps integration plan extends existing `PlasmaNet_SimOps_Integration_Document.md` with post-audit modules
**Supersedes and updates:** `PlasmaNet_SimOps_Integration_Document.md` §8 roadmap

---

## 1. Purpose

This document does two things:

1. Lays out **Path C**: the technical plan to get coupled-chemistry CFD (SU2-NEMO linked against Mutation++) working, which closes the remaining RAM-C validation gap (log10 error 1.9 → <0.5 at lower altitudes).
2. Updates the **SimOps integration plan** from the pre-audit document to include the new post-audit physics modules (wave propagation, LOS integration, chemistry UQ, RAM-C validation, detectability API).

The pre-audit SimOps integration doc remains valid for the frontend / backend / Fargate architecture and database schema. The post-audit modules plug into that architecture cleanly.

---

## 2. Why Path C Now

Post-audit, the RAM-C II benchmark shows:

| Altitude | log₁₀ error (current stack) | Interpretation |
|:--------:|:---------------------------:|----------------|
| 81 km, M 23.9 | +0.12 | Acceptable; equilibrium + pitot is fine here |
| 71 km, M 23.6 | +0.25 | Acceptable |
| 61 km, M 22.5 | +1.92 | 83× overprediction — NEQ effect |
| 47 km, M 18.5 | +1.18 | 15× overprediction — NEQ effect |

At high altitude the residence time / reaction time ratio is such that the flow is near equilibrium; at lower altitudes it is not. Equilibrium models cannot close this gap — you must solve the flow with the chemistry coupled in.

The project tried two coupled-CFD approaches earlier:

- **Eilmer** — worked at Mach 10, unstable at Mach 14+. Poorly documented, academic code.
- **SU2-NEMO + Mutation++** — segfaulted, was abandoned.

Path C is: **fix SU2-NEMO + Mutation++**. Rationale in `PROJECT_OVERVIEW_POST_AUDIT.md` §3. If after 2 weeks of effort it still doesn't work, fall back to debugging Eilmer (Path B).

---

## 3. Path C Technical Plan

### 3.1 What SU2-NEMO does

NEMO is the thermochemical-nonequilibrium branch of SU2. It solves:

- Multi-species Navier–Stokes (11 species: N₂, O₂, N, O, NO, N₂⁺, O₂⁺, NO⁺, N⁺, O⁺, e⁻)
- Two-temperature energy equations (translational–rotational T_tr, vibrational–electronic T_v)
- Finite-rate chemistry with Park (1993) / Gupta (1990) rate constants
- Arrhenius rates evaluated at Park's effective temperature T_eff = √(T_tr · T_v) for heavy-particle reactions
- Electron-impact ionisation at T_v

Chemistry and transport data come from **Mutation++**, a C++ library maintained at VKI (Von Karman Institute). SU2 links against Mutation++ at build time.

### 3.2 The failure mode, from the prior run

Project note, dated pre-audit: "SU2 NEMO (coupled) NOT WORKING — Segfault in Mutation++ library — replaced by Eilmer".

A segfault inside Mutation++ called from SU2-NEMO almost always traces to one of the following (ordered by empirical likelihood across reported issues on github.com/vki/mutationpp and su2code github):

1. **Missing or misconfigured `MPP_DATA_DIRECTORY` environment variable.** Mutation++ loads species thermodynamic / kinetic data from XML files at runtime. Without the env var pointing at the `data/` directory of the Mutation++ install, it dereferences a null pointer rather than raising a clean error.
2. **Version mismatch between SU2-NEMO build and installed Mutation++.** Mutation++ APIs changed between 1.0.x and 1.1.x in the `Mixture` constructor and `GSI` (gas-surface interaction) interfaces. SU2-NEMO in SU2 8.0 expects Mutation++ ≥ 1.0.4; earlier versions crash in the mixture setup.
3. **Mesh boundary markers wrong for NEMO.** NEMO requires `MARKER_ISOTHERMAL` or `MARKER_HEATFLUX` on the body — not `MARKER_EULER`. Using the existing inviscid-Euler-case mesh directly with NEMO crashes on BC application.
4. **Config option case-sensitivity / wrong keys.** NEMO needs `SOLVER= NEMO_EULER` or `NEMO_NAVIER_STOKES` (not `EULER`), `FLUID_MODEL= MUTATIONPP`, `GAS_MODEL= air_11` (string matches a filename in MPP data dir), `TRANSPORT_COEFF_MODEL= WILKE` or `GUPTA-YOS`.
5. **SU2 compiled without NEMO module.** If SU2 was built from the default meson/autotools config with the quick-install script, NEMO is often omitted. Need explicit `--enable-nemo` or meson flag `enable-nemo=true` and a valid Mutation++ install visible at configure time.
6. **Initial condition: freestream too rarefied for 2-T solver.** Very low post-shock density (high altitude, strong shock) can hit the `n_total < epsilon` guard in Mutation++ partition functions.

### 3.3 Investigation and fix plan

Ordered from cheapest to verify:

**Step 0 — Baseline.** SSH into `openfoam-hgv`. Inventory the current SU2 install: `SU2_CFD --version`, check for `SU2_NEMO` binary or `NEMO_EULER` in feature list, locate Mutation++ (`mutation++` is the typical name), print `MPP_DATA_DIRECTORY`, and check the `cadpipe` repository for any prior NEMO config files left behind. **This step, plus reading any remaining crash logs, is where 60% of these issues resolve.**

**Step 1 — Environment and data files.** If Mutation++ exists but `MPP_DATA_DIRECTORY` is unset, set it, rerun, see if the crash moves. If the data files are absent, install them.

**Step 2 — Minimal reproduction case.** Write the smallest NEMO config that should work — a 1-species test at low Mach with `GAS_MODEL= argon_CR` or similar — and run it. If a trivial NEMO case works, the prior failure is about our config or mesh. If trivial cases also fail, it is a build/install issue.

**Step 3 — Run under gdb.** `gdb --args SU2_CFD run_nemo.cfg`, `run`, `bt` on segfault. This gives the function and line. Match against known issues.

**Step 4 — Fix root cause.** Most likely outcomes (in order):
- Missing env var / data dir → one-line fix
- Version mismatch → reinstall Mutation++ from source at a specific tag that SU2 8.0 is known to build against
- Mesh markers → regenerate or convert existing meshes
- SU2 build missing NEMO → rebuild with `enable-nemo=true`

**Step 5 — Validate on blunt_cone M10 @ 30 km.** We already have SU2 Euler results for this case. Run NEMO with the same mesh (with correct markers). Confirm convergence. Compare T_stag, ne_stag to:
- perfect-gas Euler (overshoot)
- T-corrected Euler (ours)
- published coupled-chem results (Candler 1988 for similar conditions)

Target: NEMO T_stag within 10% of Candler reference, ne_stag within factor of 2.

**Step 6 — RAM-C II at 61 km, Mach 22.5.** Single case to validate we close the NEQ gap. If NEMO predicts ne ≈ 2–5 × 10¹⁹ (vs reference 2 × 10¹⁹), Path C is a success.

**Step 7 — Full batch.** Port the 40-case batch from Euler to NEMO. Slower (~5–10× Euler runtime due to chemistry stiffness), but gives us the production-grade dataset.

### 3.4 Parallel-paths to reduce risk

These run concurrently with Path C:

- **Path A (streamline-based NEQ chemistry)** as a fast-fallback if Path C takes longer than expected. Can be built in 2–3 days on top of existing Euler data, gets ~80% of the NEQ benefit.
- **Eilmer revival (Path B)** kept on the shelf; only pursued if Path C fundamentally won't work (SU2-NEMO dependencies too fragile, upstream bug we can't fix).

### 3.5 Estimated timeline

| Step | Days | Risk |
|------|:----:|------|
| 0. Inventory GCP state | 0.5 | Low |
| 1. Env + data files | 0.5 | Low — likely the answer |
| 2. Minimal repro case | 1 | Low |
| 3. gdb trace if still broken | 1 | Medium — depends on stack complexity |
| 4. Root-cause fix | 1–5 | Medium — could be rebuild |
| 5. Validate blunt_cone M10 | 1 | Low |
| 6. Validate RAM-C 61 km | 2 | Medium — stiff chemistry, convergence |
| 7. Port full 40-case batch | 3–5 | Medium — runtime scales |

Target: **first working NEMO run within 3 days**, full batch ported within 2 weeks.

---

## 4. SimOps Integration Update (Post-Audit Modules)

The pre-audit SimOps doc described Phases 1–4 (instant service, CFD-coupled, DOE sweep, production polish). Those phases still hold. What changes is the **content** of each phase now that we have a proper physics stack rather than just a stagnation-point NN.

### 4.1 Phase 1 addition — `detectability.analyze_detectability()` becomes the primary API

The pre-audit plan called for the PlasmaNet NN to serve `/api/plasma/predict`. Post-audit, the serving contract changes: the endpoint now calls `detectability.analyze_detectability()`, which internally uses the physics stack (full_analysis → SheathProfile → LOS → UQ) rather than just the NN. The NN is still used inside `full_analysis()` for fast ne at stagnation, but the envelope of the call is different.

New request/response:

```
POST /api/plasma/analyze
Request:
{
  "vehicle": {"nose_radius_m": 0.08, "half_angle_deg": 15, "length_m": 2.5},
  "flight": {"mach": 10, "altitude_km": 35},
  "radar": {"frequency_hz": 12e9, "aspect_angles_deg": [0, 30, 60, 90, 120, 150, 180]},
  "uncertainty": {"enabled": true, "n_samples": 64}
}
Response:
{
  "stagnation": {"T_K": 3333, "p_Pa": 72200, "ne_m3": 5.89e17, "fp_GHz": 6.89},
  "uq": {"ne_P05_m3": 2.5e16, "ne_P95_m3": 5.4e18, "log10_ne_std": 0.74},
  "aspect_scan": [
    {"angle_deg": 0, "attenuation_dB": 0.0, "status": "DETECTABLE"},
    {"angle_deg": 30, "attenuation_dB": 0.0, "status": "DETECTABLE"},
    ...
  ],
  "overall_status": "DETECTABLE→DEGRADED (UQ-dependent)",
  "worst_case": {"aspect_deg": 150, "attenuation_dB": 0.9}
}
```

### 4.2 Phase 2 addition — CFD worker uses NEMO (not Euler) once Path C lands

The pre-audit plan had the CFD worker running SU2 Euler and post-processing with PlasmaNet NN. Post-audit, the worker changes:

```
Plasma CFD Worker (updated):
  1. Fetch mesh from S3
  2. Generate SU2 config (NEMO if Path C complete, else Euler + T correction)
  3. Run SU2 (15–90 min depending on solver & geometry)
  4. extract_cfd_field() → T, p, ne, ν_c at every sampled cell
  5. build_unstructured_field() → LOS-consumable field
  6. analyze_detectability() with real CFD field
  7. Write report + ne field + diagnostic plots to S3
  8. Update simulations + plasma_analyses tables
```

Runtime impact: if NEMO adds 5× to the solver step, Fargate task cost per CFD case rises from $0.10 to ~$0.50. At expected usage (hundreds of cases per month) that is still acceptable.

### 4.3 New Phase 2.5 — RAM-C validation as a built-in demo

Add `POST /api/plasma/benchmark/ram_c` that runs the `ram_c_validation.py` harness and returns a table of predicted-vs-reference for all 12 altitude × frequency combinations. This is a self-test the SimOps UI can run to show any visitor "here's how good the tool is against the canonical flight dataset".

### 4.4 Database schema update

Extend the `plasma_analyses` table from the pre-audit doc with one additional column:

| Column | Type | Notes |
|--------|------|-------|
| `aspect_scan_json` | JSONB | Per-angle attenuation and status arrays from LOS |
| `uq_band_json` | JSONB | P05/P50/P95 ne bands + aspect × UQ attenuation arrays |
| `solver` | TEXT | `"plasmanet"`, `"cantera_pitot"`, `"su2_euler_corrected"`, `"su2_nemo"` — traceability |
| `validation_log10_error` | FLOAT | Only populated when the analysis is a RAM-C or other benchmark case |

### 4.5 Component-level additions

| Component | New / Changed | What it does | Effort |
|-----------|---------------|--------------|--------|
| PlasmaNet Service ECS image | Changed | Include post-audit modules (wave, LOS, UQ, ram_c). Base image unchanged. | 0.5 day |
| Plasma CFD Worker image | Changed | Add VTK Python bindings for new VTU reader. Add Mutation++ for NEMO once Path C lands. | 2 days (NEMO), 0.5 day (VTK) |
| `/api/plasma/analyze` endpoint | New (replaces `/predict`) | Serves detectability report, not raw ne | 2 days |
| `/api/plasma/benchmark/ram_c` | New | Runs RAM-C harness on demand | 1 day |
| Frontend: aspect polar plot | New | Render attenuation-vs-aspect as a polar chart; shade UQ band | 3 days |
| Frontend: detection envelope with UQ | Changed | Existing envelope plot extended to show P05/P95 bands | 2 days |
| Agent tool: `analyze_plasma(condition)` | New | LLM-accessible tool that calls the analyze endpoint | 1 day |

---

## 5. Updated Full Roadmap

### 5.1 Near-term (next 2 weeks)

| Code | Task | Depends On | Status |
|------|------|------------|--------|
| C-0 | Inventory SU2-NEMO + Mutation++ on GCP VM | — | **in progress** |
| C-1 | Resolve SU2-NEMO segfault (root-cause fix from §3.3) | C-0 | — |
| C-2 | Validate NEMO on blunt_cone M10 @ 30 km | C-1 | — |
| C-3 | Validate NEMO on RAM-C II 61 km (NEQ test) | C-2 | — |
| C-4 | Port the 40-case CFD batch to NEMO | C-3 | — |
| A-1 | Streamline-based chemistry (Path A fallback) | CFD batch complete | **optional, only if C slips** |
| S-1 | RAM-C validation run against full pipeline with T-corrected Euler | CFD batch complete | **partially ready** |

### 5.2 Medium-term (weeks 2–5)

| Code | Task | Depends On |
|------|------|------------|
| I-1 | PlasmaNet Service Fargate image update with post-audit modules | C-1 |
| I-2 | Plasma CFD Worker image update (VTK, optional NEMO) | C-2 |
| I-3 | `/api/plasma/analyze` endpoint on KhoriumBackend | I-1 |
| I-4 | `/api/plasma/benchmark/ram_c` endpoint | I-1 |
| I-5 | Frontend aspect polar plot + UQ band envelope | I-3 |
| I-6 | Agent tool binding `analyze_plasma` | I-3 |
| T-1 | Retrain PlasmaNet on NEMO-derived ne fields (geometry-aware) | C-4 |
| T-2 | Field-NN experiment: learn ne(x,y,z) from NEMO output | C-4 |

### 5.3 Longer-term (weeks 5–10)

| Code | Task | Depends On |
|------|------|------------|
| P-1 | AFRL SBIR demo: live web walk-through of analyze + RAM-C bench | I-5 |
| P-2 | PDF auto-report (aspect polar plot, detection envelope, UQ bands, RAM-C self-check) | I-5 |
| P-3 | Production billing: each `analyze` call metered | I-3 |
| P-4 | Paper revision: publication-ready writeup using NEMO results for RAM-C validation | C-4 |

### 5.4 Milestone stack

1. **Week 1 end:** NEMO segfault fixed, blunt_cone M10 passes
2. **Week 2 end:** RAM-C 61 km NEMO prediction within factor of 2 of measured
3. **Week 3 end:** 40-case batch ported to NEMO, `analyze_detectability(cfd_field=NEMO_output)` produces aspect-resolved reports
4. **Week 4 end:** SimOps `/api/plasma/analyze` live on staging
5. **Week 5 end:** Frontend polar plot + envelope UI shipped
6. **Week 8 end:** AFRL SBIR demo ready
7. **Week 10 end:** Paper submitted

### 5.5 Risk register

| Risk | Impact | Mitigation |
|------|--------|------------|
| SU2-NEMO build too broken to fix in 2 weeks | High — have to switch to Eilmer or Path A | Monitor blocker every day; commit to Path A fallback at day 7 if no working NEMO case |
| Mutation++ version lock pulls in dependency chain | Medium | Build in Docker, pin versions, publish working image |
| NEMO convergence fails at Mach 22+ for RAM-C | Medium — partial validation still useful | Accept Mach 15 validation as interim, document gap |
| SimOps simulations table schema conflict | Low | Work in branch, coordinate migration |
| Frontend polar plot rendering slow in WebGPU | Low | Static PNG fallback |

### 5.6 What will drag in practice

Based on the pre-audit roadmap's honest-assessment section and the project's history of "works at Mach 10 but not Mach 15" patterns, the realistic drag items are:

1. **Mutation++ builds that don't match SU2.** Plan 2 days of dependency debugging even if the immediate NEMO fix is one line.
2. **RAM-C Mach 22 convergence.** Strong shocks + stiff chemistry + 2-T will produce CFL-limit crashes; plan iterative CFL tuning and possibly adaptive mesh.
3. **Frontend integration.** The WebGPU code base is less familiar; polar-plot rendering and UQ-band shading may need more iteration than a backend-dominant team expects. Plan full 3 days, not 1.

---

## 6. Decision Points For The Team

| When | What to decide | Default if nothing decided |
|------|----------------|----------------------------|
| Day 3 of Path C | NEMO working on blunt_cone, or switch to Path A? | Switch to Path A, keep NEMO as research track |
| Day 7 | Proceed with RAM-C NEMO validation? | Yes if blunt_cone OK; otherwise Path A |
| Week 3 | Begin SimOps integration of `/api/plasma/analyze`? | Yes — don't wait for NEMO to finish entire batch |
| Week 4 | Submit AFRL SBIR white paper? | Decide based on whether RAM-C NEMO match is < 1 order; if so submit, if not delay to end of week 8 |
| Week 6 | Retrain PlasmaNet NN on NEMO data, or stay with current? | Retrain only if geometry-generalization error is > 3× on held-out shapes |

---

## 7. Summary

- **Path C is the right next physics investment.** It closes the remaining 1–2-order-of-magnitude RAM-C gap at lower altitudes that equilibrium models cannot close.
- **SimOps integration does not need to wait for Path C.** The post-audit physics stack already delivers aspect-resolved, UQ-quantified detection predictions that are materially better than the pre-audit binary. We can ship that to SimOps now, and upgrade the CFD engine behind it when Path C lands.
- **First concrete goal:** get SU2-NEMO working on blunt_cone M10 @ 30 km in the next 3 days. Everything else is scheduled downstream of that.
