# Track A — iter-251 v8 vs J&C 1972

**Date**: 2026-05-02
**CFD source**: `/home/yarden/ram_c_runs/v8_phase1A_recover/best_flow_iter251_RhoU-0.2115410394.vtu`
**Local copy**: `data/cfd_runs/v8_phase1A_iter251/flow_iter251.vtu` (108 MB)
**Cfg**: `data/cfd_runs/v8_phase1A_iter251/run.cfg`

## Headline result

`scripts/validate_ram_c_nemo.py` and `scripts/sanity_check.py` both ran cleanly. Reports written to:
- `data/cfd_runs/v8_phase1A_iter251/validation.json`
- `data/cfd_runs/v8_phase1A_iter251/validation.md`
- `data/cfd_runs/v8_phase1A_iter251/sanity_check.json`

| Metric | Value |
|---|---|
| CFD stagnation T_tr | 7099 K |
| CFD stagnation T_ve | 7627 K |
| CFD stagnation p | 2.13e+05 Pa |
| CFD domain max ne | 1.22e+21 m⁻³ (at stagnation) |
| Sheath p99 ne, station z/L = 0.14 | **8.02e+16 m⁻³** |
| J&C 1972 published peak ne (61 km / M22.5) | 2.0e+19 m⁻³ |
| **log10 error vs J&C** | **−2.40** (factor of 250 UNDER) |

The previous v7 column-misread artifact validation logged log10_err = −1.59 (38× under). The v8 iter-251 result is **worse**, despite being the only properly converged solution we've ever produced for this case.

## Sanity-check verdicts (textbook physics, no J&C dependency)

| # | Check | Textbook | CFD | Verdict |
|---|---|---|---|---|
| 1 | Frozen RH post-shock T₂ | 24,115 K | 9,676 K (T_max) | PLAUSIBLE — 60% energy absorbed by chemistry |
| 2 | Real-gas T_stag (Cantera enthalpy) | 7,066 K | 7,099 K | **GOOD** (0.5% rel err) |
| 2b | Pitot p_stag (frozen) | 1.65e+05 Pa | 2.13e+05 Pa | FAIR (29% rel err — real-gas raises it) |
| 3 | Saha-equilibrium ne at CFD (T,p) | 1.01e+22 m⁻³ | 1.22e+21 m⁻³ | FAIR — CFD 0.9 orders UNDER Saha-eq |
| 4 | Billig bow-shock standoff (eq.) | 9.4 mm | 31.9 mm (measured at p>2·p∞) | shock detected too far out — script's 2× threshold is too lenient at M22.5 (real p₂/p₁ ≈ 590); needs tighter detection |
| 5 | Plasma freq closure | f_p = 313 GHz at stag | blackout consistent at all freqs at stagnation |

## Diagnosis

**Stagnation chemistry is roughly correct.** Real-gas T_stag matches Cantera equilibrium to 0.5%. The stagnation ne is only 0.9 orders below full Saha-equilibrium — consistent with AIR-7's NO+-only ion chemistry under-shooting compared to AIR-11's multi-ion model.

**The −2.40 log10 J&C gap comes from inviscid Euler missing the wall boundary layer.** Per-station sheath ne falls from 8.0e+16 (z/L=0.14) to 4.1e+09 (z/L=0.88) — chemistry has already frozen out by station 2. J&C's reflectometers measured the wall-bound BL plasma; an Euler simulation has no BL, so the post-shock streamlines pass the body without near-wall residence time.

**Mesh under-resolution is real but secondary.** The shock is smeared across multiple cells (only 1-2 cells across the 3 mm bow-shock standoff at the existing 2.74M-tet mesh resolution). This contributes to the limit-cycle floor RhoU = −0.21 documented in CHECKPOINT_2026-04-26.md §2.7.

## Conclusion for Track B (mesh refinement)

By the original criterion ("if within factor of 5, mesh refinement is optional; if still −1.5 orders, mesh refinement is mandatory") Track B is **mandatory**. But mesh refinement alone won't close the gap to J&C — the missing physics is the boundary-layer chemistry that requires viscous Navier-Stokes, not just finer cells.

**Recommended path**:
1. Track B as planned (4-6M cell mesh, AUSMPLUSM cold start) — may improve convergence floor and shock resolution; expected to improve stagnation ne agreement with Saha but won't fix the wall-station discrepancy.
2. **Test whether SU2 v8 fixes the AIR-7 viscous heap-corruption bug** that was a v7.5.1 dead-end. If yes, viscous AIR-7 on the refined mesh is the real path to closing the gap.
3. Consider **AIR-11 viscous on v8** as the gold-standard candidate (dependent on resolving the AIR-11 cold-start NaN, which is still marked dead-end).

The headline search result (`SEARCH_V4_RESULT.md`: 28/50 candidates beat AIR-7) is **independent of CFD convergence** — the search ranks Cantera 0D scores at fixed freestream conditions, and Cantera 0D doesn't suffer from any of the CFD convergence problems above.
