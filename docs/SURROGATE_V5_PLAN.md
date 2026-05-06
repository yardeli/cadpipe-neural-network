# PlasmaNet v5 — surrogate retraining plan

## The audit (v4 is narrow)

The v4 surrogate (4-layer 512-hidden MLP, 819K params, factor-of-1.52
of Cantera 0D ground truth) is trained on **895,973 valid Cantera 0D
evaluations**, which sounds like a lot until you look at the
distribution.

After auditing 200K-line sample of `data/search_v4/training_data_v3.jsonl`:

| Axis | v4 training distribution | Coverage problem |
|---|---|---|
| **Mach number** | Only 4 unique values: 18.5, 22.5, 23.6, 23.9 | No data for M < 18.5 or M > 23.9. Cannot generalize to HGV cruise (M=5–10), scramjet (M=8–15), or extreme reentry (M=25–30) |
| **Altitude (km)** | Only 4 unique values: 47, 61, 71, 81 | No data for h < 47 km or h > 81 km, and nothing between the four anchors. Cannot generalize to low-altitude (terminal phase) or very high (skip-glide) |
| **Residence time (s)** | Only 3 unique values: 1e-6, 1e-5, 1e-4 | No data at sub-µs (sharp small bodies) or super-100µs (large blunt bodies). The v0.3.0 axial profile produces τ values spanning 0.5–40 µs, partially out of training distribution |
| **Mechanism subset** | Random sub-mechanisms of Park-47 (with ≥1 dissoc + ≥1 ion forced) | Only Park 1990 air. Cannot generalize to Mars-EDL (CO₂ chemistry), scramjet (CH₄/H₂), or non-air atmospheres |

**Bottom line**: v4 is a 4 × 4 × 3 = **48-point freestream lookup table**
extended over the 47-bit Park subset axis. It interpolates the
mechanism-subset axis correctly (that's the headline contribution),
but it's effectively **extrapolating** anywhere else.

This was an explicit choice during v3→v4: the team wanted a publishable
result on RAM-C reflectometer trajectory anchors, so the data collection
focused on the four J&C 1972 anchor altitudes and three "interesting"
residence times. It worked for that purpose. But it's NOT a general-
purpose hypersonic plasma surrogate.

## What v5 should cover

Designed-in coverage for the use cases the strategy doc cites
(early-design detectability + blackout, beyond RAM-C):

| Axis | v4 (current) | v5 (proposed) | Justification |
|---|---|---|---|
| Mach | 4 values: {18.5, 22.5, 23.6, 23.9} | **41 values** at ΔM = 0.5: {5.0, 5.5, 6.0, …, 25.0} | HGV cruise, scramjet, all reentry classes |
| Altitude | 4 values | **31 values** at Δh = 2.5 km: {20, 22.5, …, 95} | Terminal phase to skip-glide |
| Residence time | 3 values | **9 values** log-spaced: {0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000} µs | Sharp narrow → blunt capsule range |
| Mechanism subsets | random Park-47 with ≥1 dissoc + ≥1 ion | **same** for v5 (Park-47 is still the focus); v5.1 adds Park 1994 CO₂/N₂ for Mars EDL | Aaron's headline — chemistry search |
| Total grid points (no mech) | **48** | **41 × 31 × 9 = 11,439** | 240× more freestream coverage |
| Mech samples per grid point | ~18,700 (avg) | **300–500** | Maintains broadly comparable mechanism-axis density |
| Total examples | ~896 K | **3.4–5.7 M** | 4–6× more total |

The 4–6× total-data inflation is feasible — the parallel data-collection
pattern in `scripts/parallel_data_collection.py` was capped at ~40
evals/sec by Cantera's per-process memory leak. With the existing
batched-restart workaround that gave 896K in 30 minutes, a 5M dataset
takes ~3 hours wall.

## Active learning, not just brute-force grid

The 11K-grid-point freestream coverage above is uniform. A smarter v5
collection would use **active learning** with an ensemble of v4-style
models to identify the regions of (Mach, altitude, τ, subset) space
where the model is most uncertain, and seed the next collection batch
there.

Implementation outline:

1. Train 4 v4-style models with different random seeds → ensemble
2. Evaluate on a 100K-point uniform grid; rank by ensemble disagreement
3. Run Cantera 0D at the top 50K most-uncertain points
4. Retrain on the union of v4 data + uncertainty-targeted points
5. Iterate

This typically gets the same effective accuracy with 30-50 % of the
data of a uniform grid. For our 5 M target, active learning could land
us at ~2 M total examples.

## v5 architecture options

Three candidates worth benchmarking:

### Option A — Same architecture, more data
- 4-layer 512-hidden MLP (819K params)
- Train on 5M examples instead of 896K
- Expected: similar test MAE (~0.18 log10) but with much wider
  coverage. Best if compute is limited.

### Option B — Wider architecture, same data
- 6-layer 1024-hidden MLP (~6 M params)
- Train on the existing 896K
- Expected: marginal accuracy gain (~0.15 log10) but no coverage
  improvement. Probably not worth it.

### Option C — Multi-head architecture
- Shared 4-layer 512-hidden trunk
- 3 heads: ne_peak, q_w (Fay-Riddell), τ_residence
- Train on 5M examples augmented with per-station axial-profile data
  from `compute_axial_profile`
- Expected: surrogate becomes a drop-in replacement for the entire
  axial flowfield + chemistry pipeline, with single-pass inference
  (~0.05 ms instead of 5s for a 50-station axial profile)

Option C is the most ambitious and the highest-leverage. It's also
the most consistent with Aaron's strategy doc framing: the system
should *predict detectability* directly, not just chemistry.

## Recommended phasing

**Phase A (1 week, $0)**:
- Add a `data_collection_v5.py` script that walks the 11K grid uniformly
- Run on the GCP VM with the existing parallel-worker pattern
- Output: 5M-example training_data_v5.jsonl

**Phase B (1 week, ~$50 GCP compute)**:
- Train v5.0 (Option A) on the 5M dataset
- Validate against:
    - The existing RAM-C 4-anchor benchmarks (regression test)
    - 5–10 new "out-of-original-distribution" benchmarks (M=10/30km,
      M=15/45km, M=8/25km — typical HGV / scramjet conditions)
- Compare to v4 on both: v5 should match v4 on the original benchmarks
  (within 0.05 log10) and crush v4 on the new ones (where v4 is
  extrapolating)

**Phase C (2 weeks, ~$200 GCP compute)**:
- Active-learning campaign — use v5.0 ensemble to identify uncertain
  regions, collect ~1M targeted examples, retrain v5.1
- Add the multi-head architecture (Option C) for end-to-end axial-
  profile prediction
- Wire v5 as the default surrogate in `khorium_hypersonic.chemistry`

**Phase D (open-ended)**:
- v5.2 with non-air chemistry (Mars EDL CO₂/N₂, Park 1994)
- Differentiable-physics version of the v5.1 architecture for
  trajectory-shape optimization

## What's actually broken right now

Beyond the data-coverage gap, the v4 surrogate has one known issue
that was masked because the v0.1.0–v0.2.0 solver only used it at the 4
RAM-C anchors:

- The surrogate's `freestream_features` encoder takes (h_km, M, T_inf,
  P_inf) as 4 separate inputs. T_inf and P_inf are functionally
  redundant with h_km (they're set by USSA76). Training data has
  T_inf and P_inf computed from the BUGGY pre-2026-05-03
  `standard_atmosphere` (the one with the 51-71 km sign error). So
  v4's "61 km" feature actually maps to the broken-atmosphere P_inf
  of 254 Pa, not the corrected 17.7 Pa.

  v5 collection MUST regenerate the freestream features with the
  corrected `standard_atmosphere`. This is one-line change in
  `scripts/parallel_data_collection.py` but it requires the full
  re-collection — can't just refit the model on the old data.

## Cost estimate

- Phase A data collection: ~3 hr × 16 cores × $0.05/core-hr = $2.40
  (vCPU compute on the existing VM, marginal)
- Phase B training: ~70 min on 16 cores = $1.00 marginal
- Phase C active learning + multi-head: ~1 day GPU = $30
- Phase D non-air: depends, probably another $10–50

Total to v5.1: **<$50** of GCP compute. The bottleneck is engineering
time, not money.

## Recommended next action

Phase A is cheap and high-leverage. I'd kick off the
`data_collection_v5.py` campaign on the GCP VM tonight; first 1M
examples land overnight, full 5M by end of day tomorrow. Then we have
a v5.0 model within 2 days that can be honestly benchmarked against
v4 on a Mars-EDL or HGV cruise condition without us hand-waving about
extrapolation.
