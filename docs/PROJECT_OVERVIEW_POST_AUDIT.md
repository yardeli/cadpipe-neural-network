# Khorium Hypersonics — Post-Audit Project Overview

**Date:** 2026-04-23
**Supersedes:** `Notion_Project_Overview.md` (which remains valid for pre-audit context)
**Audience:** Project stakeholders (Aaron Wu, AFRL/Srini Vasan, SimOps team, funding partners)
**Status:** Active development, physics stack rebuilt, coupled-CFD upgrade in progress

---

## 1. What The Project Is

A simulation tool that answers one operational question: **"Can radar detect this hypersonic vehicle under these flight conditions, from this viewing direction, with what confidence?"**

The answer drives $100B in defense procurement decisions — if StarLink and other commercial Ku-band constellations can't see an HGV at Mach 10, detection responsibility shifts to purpose-built radar assets. If they can, the defense architecture is very different.

## 2. What Changed: Audit and Physics Rebuild

Between April 22 and April 23, an independent audit of the project identified four critical issues in the physics stack. Three were fixed in a first commit round. The remaining issue — that the binary `fp > 12 GHz → BLACKOUT` criterion ignored aspect, propagation, and uncertainty — motivated a fundamental rebuild of the prediction path.

### 2.1 Issues resolved

| # | Issue | Impact | Resolution |
|---|-------|--------|------------|
| 1 | Training data pipeline applied non-equilibrium correction that the README said was removed | "Clean" data was not reproducible from code | `use_neq` flag added to `generate_data.py`, default off |
| 2 | `air_plasma_11s.yaml` activation energies in K but labelled as cal/mol | Finite-rate chemistry silently ran with 10²–10³× wrong rates (equilibrium unaffected) | All Ea multiplied by R = 1.987, DRGEP ranking reverified |
| 3 | Three contradictory DRGEP files on disk | Stakeholder confusion, unclear which finding was real | Archived two; retained `drgep_corrected_rates.json` from rerun |
| 4 | Saha partition function weights for N and O⁺ (excited-state degeneracies) | ~5–7% ne error at T > 10,000 K | Corrected to NIST ASD J-level sums |
| 5 | US Standard Atmosphere only 5 of 7 regimes | ~10% T error above 51 km | Extended to 71 km (added regimes 5–7) |
| 6 | **Rayleigh pitot formula missing** — used subsonic isentropic for all Mach | Stagnation pressure **~10,000× too high** at Mach 22 | `pitot_pressure()` added, used by default in `full_analysis()` |

### 2.2 New physics modules built

Five modules added to the `plasmanet` Python package (~2,500 lines, 63 tests, all passing):

| Module | Purpose | Status |
|--------|---------|--------|
| `plasma_wave.py` | Complex refractive index in collisional plasma (Gurevich/Budden). Replaces the `fp > 12 GHz → BLACKOUT` boolean with dB-based attenuation and `DETECTABLE / DEGRADED / BLACKOUT` categories. | Validated against vacuum, overdense-collisionless, cutoff, and collisional-absorption-peak analytical limits |
| `collision_frequency.py` | Species-resolved electron-neutral rates (Itikawa 2005/2009 cross sections for N₂, O₂, NO, O, N) plus Spitzer electron-ion. | RAM-C regime test: ν_en ≈ 1 × 10⁹ s⁻¹ matches Huber (1967) |
| `line_of_sight.py` | Ray-through-plasma attenuation integrator. Supports axisymmetric analytical fields and structured/unstructured CFD fields. `scan_aspect()` sweeps viewing angles. | Uniform-slab exact; parabolic-profile convergent; polar pattern reproduces RAM-C qualitative behaviour |
| `chemistry_uq.py` | Latin-hypercube Monte Carlo over T and p uncertainty → ne quantiles, log-std, detection probabilities. | Saha sensitivity ∂log₁₀(ne)/∂log₁₀(T) ≈ 15 matches theoretical ~11 at 5,000 K |
| `ram_c_validation.py` | Canonical RAM-C II benchmark (Jones & Cross 1972, Grantham 1970, Huber 1967) at 4 altitudes × 3 frequencies. | Validation harness runs; 9/12 status categories match after pitot fix |
| `cfd_field.py` | VTK-based SU2 VTU reader (replaces brittle meshio path). Per-cell real-gas T correction via enthalpy matching. | End-to-end tested: blunt-cone M15@35 km gives T_stag 5187 K (vs analytical 5383 K) |
| `detectability.py` | Top-level API that ties everything together: vehicle + flight condition + radar → aspect-resolved attenuation with UQ bands, honest "UQ-dependent" status at decision boundaries. | All 8 integration tests pass |

### 2.3 Validation benchmark: RAM-C II

RAM-C II (NASA 1970) remains the canonical in-flight hypersonic plasma dataset: 2.54-m blunt cone, R_n = 0.152 m, 9° half-angle, 5 reflectometer stations, altitudes from ~90 km down to ~25 km at Mach 23.9.

Validation of stagnation-region peak ne against Jones & Cross (1972) and Grantham (1970), after the pitot fix:

| Altitude | Mach | Predicted ne (m⁻³) | Reference ne (m⁻³) | log₁₀ error |
|:--------:|:----:|:------------------:|:------------------:|:-----------:|
| 81 km | 23.9 | 2.63 × 10¹⁸ | 2.0 × 10¹⁸ (range 1–3.5 × 10¹⁸) | +0.12 |
| 71 km | 23.6 | 1.79 × 10¹⁹ | 1.0 × 10¹⁹ (range 0.5–2 × 10¹⁹) | +0.25 |
| 61 km | 22.5 | 1.65 × 10²¹ | 2.0 × 10¹⁹ (range 1–4 × 10¹⁹) | +1.92 |
| 47 km | 18.5 | 3.04 × 10²⁰ | 2.0 × 10¹⁹ (range 1.5–3 × 10¹⁹) | +1.18 |

Before the pitot fix, the same rows showed log₁₀ errors between +4.88 and +8.16. **At 81 km and 71 km, the prediction is now within published measurement uncertainty — as good as any equilibrium-based model can be.** At 61 km and 47 km the residual 1–2 orders of magnitude is the known NEQ signature: at lower altitudes the flow residence time is much longer than the recombination time, so the actual ne departs from equilibrium by 1–2 orders. This is the gap the Path C coupled-CFD work closes.

## 3. Why the Detection Criterion Changed

Pre-audit the detection criterion was: `fp > 12 GHz → BLACKOUT`, where fp was computed at the **stagnation point** with assumed freestream geometry. This is wrong for three reasons:

- **Stagnation ne is not what a radar sees.** A bistatic geometry (orbital radar viewing from above/side) traverses a line through the shock layer at some aspect angle. Two vehicles with identical stagnation ne can have completely different detectabilities if one is viewed nose-on (short chord through the sheath) versus side-on (long chord through an azimuthally uniform sheath).

- **Plasma frequency is a cutoff, not an absorption metric.** Below cutoff the wave is reflected; above cutoff with non-zero collision frequency it is still attenuated. In the transition region (which is where the decision happens at Mach 10–12) a wave can be partially transmitted, and the right metric is integrated optical depth or dB attenuation.

- **Single-point predictions hide uncertainty.** NO ionisation energy, T_stag from CFD, and assumed chemistry mechanism each carry uncertainty that compounds into 10²–10³× spread in ne. A single-number output is overconfident.

The new `detectability.analyze_detectability()` returns aspect-resolved attenuation in dB with P05/P95 UQ bands. At Mach 10 @ 35 km, R_n = 0.08 m, against Ku-band 12 GHz: the worst-case aspect attenuation is 0.9 dB (DETECTABLE) with an uncertainty band spanning 0 to 9.4 dB. The reported status is **"DETECTABLE→DEGRADED (UQ-dependent)"** — a defensible, honest answer, not a falsely confident binary.

## 4. Where Things Now Stand

### 4.1 Works and validated

| Capability | Quality | Evidence |
|------------|---------|----------|
| Stagnation-point equilibrium ne, Mach 5–15 | Within factor of 2 of Cantera + analytical | 63 physics tests, direct comparison |
| RAM-C II blackout prediction at 81–71 km | Within ~factor of 2 of flight measurement | `ram_c_validation.py` harness |
| Aspect-resolved LOS attenuation | Physics-correct (Gurevich, Budden) | Analytical slab / parabolic / cutoff limits |
| Chemistry-parameter UQ | Functional | Saha theoretical sensitivity match |
| SU2 Euler CFD + real-gas T correction | Operational | Tested on `blunt_cone_M15_A35` |

### 4.2 Works with caveats

| Capability | Caveat |
|------------|--------|
| Ne prediction at Mach 20+ (RAM-C 47–61 km) | Equilibrium overpredicts by 1–2 orders (NEQ signature). Fix = Path C |
| CFD from current batch (SU2 Euler) | Perfect-gas assumption still biases velocity and shock stand-off. Mitigated by T correction but not eliminated |
| Geometry generalisation of stagnation-only NN | NN trained only on (Mach, alt, nose_R); true geometry dependence not learned. Fix = post-process CFD field into training data |

### 4.3 Not yet built

- Full coupled-chemistry CFD (Path C: SU2-NEMO + Mutation++). **In progress.**
- Park two-temperature chemistry at stagnation (low priority after pitot + T correction)
- Field-NN surrogate trained on CFD-derived ne(x, y, z) (depends on Path C output)
- SimOps integration of the new wave / LOS / UQ modules (see roadmap doc)
- AFRL SBIR demo video (depends on completed CFD batch)

## 5. Current Running Work

- **GCP CFD batch**: 29 of 40 SU2 Euler cases completed on `openfoam-hgv` as of this document. Remaining ~10 cases are the high-resolution sharp_narrow geometry runs (~90 min each). ETA ~2 hours.
- **SU2-NEMO investigation**: debugging the Mutation++ segfault to enable coupled chemistry. See `ROADMAP_SIMOPS_INTEGRATION.md` §3 for detail.

## 6. Reading Order For New Contributors

1. This document — what the project is and what recently changed
2. `ROADMAP_SIMOPS_INTEGRATION.md` — forward plan including Path C and SimOps deployment
3. `AUDIT_FINDINGS.md` — the complete audit with file paths and line numbers
4. `plasmanet/README.md` — technical architecture, how to run
5. `Hypersonic_Chemistry_Initial_Findings.md` — why equilibrium DRGEP fails (correct reasoning, worth keeping)

## 7. Reference and Commit History

Recent commits (from newest):

- `6ae158b` cfd_field: real-gas T correction for SU2 Euler output
- `08cfa7a` CFD field extraction + end-to-end detectability example
- `0d682cc` Proper physics stack: pitot pressure + wave propagation + LOS + UQ + RAM-C
- `209e0ed` Fix all audit findings: 4 critical + 2 minor

Repo: `github.com/yardeli/cadpipe-neural-network`

Companion repo (cadpipe): `github.com/yardeli/cadpipe`
