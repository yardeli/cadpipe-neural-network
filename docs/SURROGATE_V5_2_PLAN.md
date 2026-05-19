# Surrogate v5.2 — Multi-fuel Mechanism Axis Plan

**Status (2026-05-19)**: framework landed (`plasmanet.mechanism_search.fuel_axis`,
worker stub `scripts/data_collection_worker_v52.py`), tests 5/5 passing.
**Data collection NOT launched** — pending explicit budget approval
(estimated ~4 hr c2d-highcpu-16 wall + ~4 hr training).

This document is the design for the v5.2 surrogate: the first to score
**scramjet ingestion of fuel** into the plasma sheath. v5_prime
covers Park-AIR-7 (47-reaction air) only; an HGV cruising on H2 or CH4
ingests fuel into the post-shock boundary layer and the resulting
combustion chemistry shifts ne by orders of magnitude.

## 1. What v5_prime can't do, that v5.2 will

| Regime | v4 | v5_prime | v5.2 |
|---|---|---|---|
| Pure-air RAM-C / re-entry  | factor 1.52 | factor 1.09 | factor 1.09 (regression-anchored) |
| Pure-air HGV cruise        | extrapolation | in-distribution | in-distribution |
| Scramjet inlet pre-combustion | out of scope | air-only | in-distribution |
| Scramjet combustion (H2 / CH4 + air) | out of scope | out of scope | **first model** |
| Fuel-rich exhaust plume | out of scope | out of scope | extrapolation only |

The combustion regime matters: at scramjet combustor temperatures
(2,200 – 3,500 K) H2/O2 produces OH + H + H2O at ~ 10⁻²–10⁻¹ mole
fraction, all of which sink electrons (OH and HO2 are strong electron
attachers). For CH4/Air the analogous sinks are H, OH, CHO, CH3 plus
CO formation. The expected v5.2 finding: at hypersonic scramjet
conditions, fuel ingestion typically **drops ne by 0.3–1.5 log10**
relative to pure-air at the same freestream — i.e., scramjets are
*harder* to blackout than the pure-air HGV approximation predicts.

## 2. Mechanism axis

Existing 47-bit Park-AIR-7 axis (v4 / v5 / v5_prime) is unchanged.

v5.2 adds two new axes:

  - `fuel_kind_id ∈ {0=AIR, 1=H2, 2=CH4}`
  - `equivalence_ratio φ_fuel ∈ [0.5, 3.0]` (continuous, only when fuel ≠ AIR)

The composite mechanism is the union of:

  - any Park-AIR-7 subset (drawn the same way v5 worker draws random subsets)
  - the fuel's reaction list (full set; not subset — fuel chemistry is
    too compact to meaningfully prune)

H2/O2 set: 9 species, 11 reactions (Li 2004 subset). CH4/Air set: 14
species, 16 reactions (Smooke 1991 reduced). Sources documented inline
in `plasmanet/mechanism_search/fuel_axis.py`.

## 3. Freestream feature for the surrogate

v5_prime is 5-d:

    (alt, M, T_inf, P_inf, log10(τ))

v5.2 extends to **7-d**:

    (alt, M, T_inf, P_inf, log10(τ), φ_fuel/4.0, fuel_kind_id/2.0)

The two fuel features are normalised to [0, 1]. AIR + φ=0 reduces the
v5.2 input to the v5_prime input with the last two features = 0; this
is the regression-anchor test (≥ 1 M records of AIR at φ=0 in the
training corpus to certify zero-regression on RAM-C).

## 4. Worker contract

`scripts/data_collection_worker_v52.py` extends the v5_prime worker
pattern. Per-record schema (JSONL):

```json
{
  "name": "Park_1990_air_47rxn_subset_14rxn_CH4_phi0.78",
  "alt_km": 75.6, "mach": 9.9, "log10_tau_s": -6.44,
  "phi_fuel": 0.78, "fuel_kind_id": 2,
  "fingerprint": [0, 0, 1, ...],    // 47-bit Park axis
  "n_reactions": 30,
  "ne_m3": 1.23e+19,                // populated by cantera_evaluator hook
  "T_final_K": 4250.0
}
```

The framework worker ships **without the Cantera evaluation hook
wired** — `--no-evaluate` is required for any `--target > 1000` run
so the worker can't accidentally consume cloud budget. The
evaluation hook lands together with the cloud-budget approval.

## 5. Prerequisites before launching data collection

Each item below MUST be green before the v5.2 worker is allowed
to consume billable VM time:

  1. **Thermo polynomials** — `thermo_data.NASA9_THERMO` needs the
     6 H2-set + 11 CH4-set species (see test 4 of
     `scripts/test_fuel_axis.py` for the explicit missing list).
     Source: NASA Glenn coefficients (TP-2002-211556, free).
     Estimated work: ~2 hr (mostly data entry).

  2. **Cantera load round-trip green** — re-run
     `scripts/test_fuel_axis.py`; test 4 must report 0 missing on
     both H2 and CH4 composites.

  3. **Reactor sanity check** — composite reactor at φ=1, T=2500 K,
     P=1 atm, τ=1 ms must produce H2O + OH > 1 % mole fraction.
     (This catches a transcription bug in the reaction rate constants.)

  4. **Evaluator hook landed** — wire the v5.2 worker to
     `plasmanet.mechanism_search.cantera_evaluator.evaluate` with the
     composite mechanism and `fuel_initial_composition` for initial
     mass fractions.

  5. **Budget approval** — explicit go-ahead from the user for the
     ~4 hr × 16-core × $ + storage cost of one full 5 M-record run.

## 6. Estimated wall budget

Using the v5_prime worker performance (529 – 541 evals/s aggregate
across 4 workers on `openfoam-hgv` c2d-highcpu-16):

| Phase | Wall | Notes |
|---|---|---|
| Data collection | ~4 hr | 5 M records, 4 workers parallel |
| Train v5.2 (199 epoch, 512-hidden 7-d input) | ~4 hr | Same arch as v5_prime |
| Compare-v5_prime-vs-v5.2 regression | ~10 min | Verify AIR axis bit-exact |

Total ~8 hr wall. v5_prime cost from CHECKPOINT_2026-05-06 was
~4 hr data + ~4 hr train = same envelope. v5.2 adds zero new
worker cost on top of v5_prime; the cost is "we re-collect" not
"we collect more in parallel".

## 7. Acceptance criteria

  - **R1 (zero regression):** v5.2 prediction on AIR + φ=0 inputs
    matches v5_prime to ≤ 0.05 log10 (RMS over 10 K RAM-C-anchor inputs).
  - **R2 (H2 reactor sanity):** v5.2 at fuel_kind=H2 / φ=1 produces
    H2O > 1 % at τ=1 ms (matches Cantera 0D within factor 2).
  - **R3 (CH4 reactor sanity):** same, with CH4/CO2 product check.
  - **R4 (HGV scramjet plausibility):** v5.2 at M=8, alt=25 km, φ=1
    CH4 predicts ne 0.3 – 1.5 log10 *below* pure-air at the same
    freestream (consistent with electron-sink expectations).

If R1 fails, the AIR axis was contaminated by the fuel features in
training — usually a normalisation bug. Block launch.

## 8. Cross-references

  - Existing v5_prime plan: `docs/SURROGATE_V5_PLAN.md`,
    `docs/SURROGATE_V5_PRIME_RESULT.md`
  - Cantera YAML leak fix (prerequisite for any long-running v5.2
    collection): commit `d73ebdf` (`fix: cantera_evaluator.evaluate()
    no longer leaks tmp YAML per call`).
  - v0.3.1 strip mode + shock chains (used to feed v5.2 the
    inlet-shock-corrected freestream): `docs/CHECKPOINT_2026-05-06.md`.
