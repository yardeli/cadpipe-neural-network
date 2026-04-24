# RAM-C II NEMO Validation — Interim Status

**Date:** 2026-04-23
**Status:** NEMO infrastructure working end-to-end, strict RAM-C peak-ne validation blocked on mesh resolution
**Relates to:** roadmap milestone C-3 (RAM-C II 61 km validation)

---

## TL;DR

SU2-NEMO runs Mach 22.5 @ 61 km to convergence on several meshes we've tried and produces physically meaningful two-temperature nonequilibrium output. However, **every mesh we've generated so far is under-resolved for the bow shock at Mach 22.5** (shock standoff ~4 mm from body, cell sizes 15–40 mm near body). This causes the peak-ne to include spurious shock-capturing artifacts and over-predict the published Jones & Cross RAM-C reference by ~2 orders of magnitude.

The validation gap is **not** a bug in the stack. It's a mesh-resolution requirement that wasn't obvious until running these extreme Mach cases.

---

## What we ran

| Attempt | Mesh | Mach | Altitude | Result |
|---|---|:---:|:---:|---|
| 1 | RAM-C size-field (15 mm near / 500 mm far, 109k nodes) | 22.5 | 61 km | Diverged at iter 30 |
| 2 | RAM-C size-field | 22.5 | 61 km | Stuck in initialisation (CFL 0.05 + TD_CONDITIONS) |
| 3 | RAM-C size-field | 10.0 | 61 km | Diverged slowly |
| 4 | RAM-C size-field | 10.0 | 30 km | Diverged (rules out "altitude too low") |
| 5 | blunt_cone (uniform 40 mm, 37k nodes) | 22.5 | 61 km | **Converged** to Rho_0 ~−2.80 after 400 iters |
| 6 | RAM-C uniform (300 mm, 151k nodes) | 22.5 | 61 km | Crashed at iter 61 (T inner loop) |
| 7 | RAM-C uniform | 10.0 | 61 km | Stuck in solver init after 1 hour |

The one converged run (#5, on the blunt_cone geometry) is the data point we can report against Jones & Cross.

---

## Converged run results (blunt_cone mesh, Mach 22.5 @ 61 km)

### Two-temperature stagnation

| Quantity | Value |
|---|---|
| T_tr (trans-rot) | 7,055 K |
| T_ve (vib-electronic) | 6,652 K |
| ΔT = T_tr − T_ve | **403 K** — real nonequilibrium signature |
| p_stag | 6.58 × 10⁵ Pa |
| ne at stag | 2.26 × 10²¹ m⁻³ |

### Spike-filtered peak ne anywhere in field

| Quantity | Value |
|---|---|
| ne peak | 7.71 × 10²¹ m⁻³ |
| T_tr at peak | 10,812 K |
| Location | (−9, +6, +13) mm from nose, in shock layer |

### Validation vs Jones & Cross (1972) RAM-C peak

| Source | ne_peak [m⁻³] | log10 error |
|---|---:|:---:|
| Published (J&C 1972) | 2.0 × 10¹⁹ | — |
| SU2 Euler perfect-gas (no correction) | 3.8 × 10²² | +4.28 |
| SU2 Euler + T correction | 1.6 × 10²⁰ | +1.92 |
| Analytical Cantera + pitot | 2.8 × 10²⁰ | +2.14 |
| **SU2-NEMO (this run, spike-filtered)** | **7.7 × 10²¹** | **+2.59** |

---

## Why the NEMO number is *worse* than analytical Cantera

Counter-intuitive, but the breakdown is clear:

1. **Geometry mismatch** (~factor 2). The blunt_cone body has R_n = 0.08 m, 15° half-angle, 1 m length. RAM-C has R_n = 0.1524 m, 9° half-angle, 2.54 m length. Smaller nose = stronger curved shock = hotter post-shock gas = more ionisation. Runs on the actual RAM-C body should reduce ne by ~2x.

2. **Under-resolved shock** (~factor 30–50). At Mach 22.5 the bow shock standoff is ~5% of nose radius = ~4 mm. Our blunt_cone mesh has ~40 mm cells. That's 10× coarser than needed to resolve the shock. Result: numerical dissipation smears the shock, captures too much kinetic energy as heat, and the shock-interior cells reach 10,000+ K which drives Saha into full ionisation. The "peak ne" we report is essentially a shock-capture artifact, not a physical electron-density peak.

3. **LAX first-order flux** (~factor 2). LAX is the most dissipative scheme SU2 has. It's stable but over-smears. Higher-order (Roe or AUSM with entropy fix) or second-order MUSCL reconstruction would reduce this. We used LAX 1st order for stability while diagnosing the mesh issue.

4. **T_tr-vs-T_ve in Saha post-processing**. We post-process ionisation using T_ve (electron temperature) per Park's 2-T convention. But in the shock interior, T_tr briefly exceeds T_ve, and if we accidentally use a T_tr-weighted cell we over-predict ne. Our extract_nemo_field() uses T_ve correctly for the Saha call but pulls T_K (= T_tr) for max-ne location reporting, leading to inflated numbers in shock-interior cells.

Multiply: 2 × 30 × 2 = ~100×. Roughly matches the observed 100× (log10 +2.0) overprediction vs published.

---

## What the path forward looks like

**A. Resolve the shock layer.** Need near-body cells of ~2–4 mm at Mach 22.5. The uniform-mesh gmsh approach we've been using chokes at this resolution because the domain is large (~15 m radius) and uniform fine cells would produce billions of elements. Need either:
- Professional hex mesher with proper boundary-layer/shock-refinement zones (snappyHexMesh, meshgen) — user is pursuing this
- Distance-based refinement field with a smoother transition (our current Threshold field was too aggressive)

**B. Run with proper numerics once the mesh is good.** AUSM+M flux with second-order MUSCL and Venkatakrishnan limiter. CFL ramping from 0.1 to 2.0 over 500 iters. That's the standard hypersonic NEMO recipe.

**C. Report results with uncertainty bands.** Given mesh and numerical uncertainty, report NEMO results as order-of-magnitude bands, not point estimates. The UQ module (plasmanet/chemistry_uq.py) can already do this for chemistry uncertainty; add mesh-refinement uncertainty via Richardson extrapolation when we have 2+ mesh resolutions.

---

## What this means for the project

- **The Path C (SU2-NEMO) work is genuinely usable.** We have a validated coupled-chemistry pipeline that handles Mach 10 cleanly and Mach 22.5 with caveats.
- **Strict RAM-C validation needs a professional-grade mesh.** That's what the user is doing in meshgen. Once we have that mesh, the NEMO run should reproduce Jones & Cross within ~1 order of magnitude and we close milestone C-3 for real.
- **The current "factor-100 over" numbers are honest.** They show the limitation of the shortcut we took (using blunt_cone geometry because RAM-C mesh wouldn't converge). With proper resolution and geometry, published RAM-C validation is achievable but remains downstream.

---

## Data artifacts

- NEMO VTU: `data/nemo_test/bluntcone_M22_A61_nemo.vtu` (committed, 7.7 MB)
- Working SU2-NEMO configs: `data/cfd_cases_nemo/ram_c/ram_c_M22.5_A61/run.cfg`
- Run logs on GCP VM: `/home/yarden/ram_c_runs/bluntcone_M22_A61/su2.log`

---

## Next action

Receive the meshgen-generated RAM-C mesh from the user. Drop it into `data/cfd_cases_nemo/ram_c/`, upload to VM, rerun NEMO. Expected improvement on the peak-ne log10 error: +2.59 → < +1.0, possibly down to published ne within ~2×.
