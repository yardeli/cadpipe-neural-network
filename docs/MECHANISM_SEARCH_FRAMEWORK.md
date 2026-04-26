# AI-Exhaustive Chemistry Mechanism Search Framework

**Vision (Aaron Wu, 2026-04-25)**: "If we create a framework that allows the AI
to try exhaust method on the chemistry reaction search, there is a way that we
can do something that nobody has ever done before in human history."

## Problem statement

Hypersonic plasma chemistry is governed by a finite but combinatorially-large
set of reactions. Park 1990's standard mechanism has **47 reactions** for
11-species air. Common reduced sets:

- AIR-5 (5 species, ~17 reactions): N2/O2/NO/N/O. No ions.
- AIR-7 (7 species, ~22 reactions): adds NO+ and e-.
- AIR-11 (11 species, 47 reactions): full Park including N+, O+, N2+, O2+.

Researchers traditionally pick ONE mechanism by hand (educated guess), run CFD,
compare to experiment. Our goal: **let AI search the space of mechanism subsets
automatically and find the one that best matches experimental ne measurements**
across multiple flight conditions (RAM-C, FIRE-II, Apollo).

## Search space

For a base mechanism with N reactions, the subset space is 2^N possibilities.
For Park's 47 reactions: 2^47 ≈ 1.4 × 10^14. Brute force impossible. Must use:

- Smart sampling (Bayesian optimization / genetic algorithms)
- Surrogate models (PlasmaNet, Cantera 0D) for fast evaluation
- CFD only for top-K candidates

Realistic search budget:
- Surrogate evaluations: 100K–1M (hours)
- CFD evaluations: 50–200 (days, with MPI binary)

## Scoring function

Given a mechanism candidate `M`, score it against all known experimental
data:

```
score(M) = sum over experiments e:
    w_e * [
        log10_err(ne_predicted(M, e), ne_published(e)) +
        log10_err(dB_predicted(M, e), dB_published(e))
    ]
```

Lower is better. `w_e` are confidence weights (J&C 1972 ±factor 2,
Grantham 1970 ±factor 1.5, etc.).

Initial ground-truth set:
- RAM-C 81 km / M=23.9 (J&C 1972)
- RAM-C 71 km / M=23.6 (J&C 1972)
- RAM-C 61 km / M=22.5 (J&C 1972) — our primary anchor
- RAM-C 47 km / M=18.5 (Grantham 1970)
- FIRE-II 71 km (NASA TR-R-348) — future
- Apollo CM 75 km (NASA TM-X-2348) — future

## Architecture

```
                      ┌──────────────────────────┐
                      │  Mechanism Generator (S-1) │
                      │  Park 47 → reaction subset │
                      │  → SU2 cfg + Cantera .yaml │
                      └──────────┬─────────────────┘
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
       ┌────────────┐   ┌────────────────┐   ┌──────────────┐
       │  Cantera   │   │   PlasmaNet    │   │ SU2-NEMO MPI │
       │  0D + 1D   │   │   surrogate    │   │ (validation) │
       │  (S-2)     │   │   (S-3)        │   │ (S-5)        │
       └─────┬──────┘   └───────┬────────┘   └──────┬───────┘
             │                  │                    │
             └──────────────────┼────────────────────┘
                                ▼
                       ┌──────────────────┐
                       │  Scoring (S-6)   │
                       │  vs J&C, Grantham │
                       └────────┬──────────┘
                                ▼
                       ┌──────────────────┐
                       │  Search loop     │
                       │  (Bayesian / GA) │
                       │  (S-4)           │
                       └────────┬──────────┘
                                ▼
                       ┌──────────────────┐
                       │  Top-K candidates │
                       │  → publish (S-7) │
                       └──────────────────┘
```

## Existing pieces (reused)

| Component | Already exists at | Status |
|-----------|-------------------|--------|
| RAM-C J&C ground truth | `plasmanet/ram_c_validation.py`, `validate_ram_c_nemo.py` | Done |
| AIR-5 baseline CFD | `data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu` | Done |
| AIR-7 CFD (in progress) | `/home/yarden/ram_c_runs/ramC_refined_air7v7b_*` on VM | Running |
| MPI binary for fast CFD | `/opt/su2-nemo-mpi/bin/SU2_CFD` on VM | Done |
| Mutation++ EOS converter | `scripts/mpp_air5_to_air11_converter.cpp` | Done |
| dB margin scoring | `validate_ram_c_nemo.py: db_margin_to_published()` | Done |
| AIR-5 vs AIR-7 comparison | `scripts/compare_air5_vs_air7_ramc.py` | Done |
| 3D diagnostic figures | `scripts/paraview_3d_diagnostic.py` | Done |
| DRGEP mechanism reduction | cadpipe repo | Existing |
| PlasmaNet equilibrium surrogate | `plasmanet/model.py` | Existing (needs retrain on mechanism axis) |

## Build order (sprint plan)

### Week 1: Foundations
- **S-1**: Mechanism generator (Python). Output Park 47 reaction list as YAML;
  emit cfg + Cantera mechanism file for an arbitrary subset.
- **S-6**: Scoring function. Composes existing validate_ram_c_nemo into a
  one-call `score(vtu_path) → float` against all benchmarks.

### Week 2: Fast evaluator
- **S-2**: Cantera 0D reactor at sheath post-shock conditions. Validates
  against AIR-5 + AIR-7 CFD points to bound the surrogate's accuracy.

### Week 3: Surrogate + Search
- **S-3**: PlasmaNet retrain on (mechanism subset, conditions) → ne field.
  Training set: 50–100 CFD/Cantera evaluations.
- **S-4**: Bayesian optimization over reaction subset space. Initial
  candidates from random sampling + DRGEP-reduced.

### Week 4-5: Validation + Paper
- **S-5**: CFD batch runner. Top-K from S-4 get full SU2-NEMO MPI
  validation.
- **S-7**: Paper draft.

## Limits acknowledged

- **SU2-NEMO v7.5.1 has bugs**: AIR-11 + Mutation++ EOS mismatch (we
  documented + partially fixed), AIR-7 viscous heap corruption (out of
  scope to fix). Search must avoid these failure modes — they're part of
  the framework's knowledge.
- **Cantera 0D ≠ CFD**: surrogate accuracy bounds the search precision.
  The framework's validation step (S-5) catches surrogate errors before
  they propagate into the paper.
- **Combinatorial space is huge**: we won't enumerate. Smart sampling +
  surrogate is the only tractable approach.

## Why this is novel

Existing literature picks mechanisms by hand:
- Park 1990: hand-derived 47-reaction set, calibrated against shock-tube data.
- Dunn-Kang 1973: hand-derived 15-reaction set for low-T air.
- Kang-Dunn 1979: hand-derived 7-species ablation set.

**No published work has automated the search across reaction subsets**
against multi-experiment ground truth. The closest is mechanism reduction
(DRGEP, PFA, sensitivity analysis) which removes reactions from a given
master set. Our framework REVERSES this: starts with no reactions, adds
them iteratively to maximize fit to experiment.

This is what Aaron means by "something nobody has done before."

## Status (updated 2026-04-25)

- Architecture sketched ✓
- Existing pieces inventoried ✓
- AIR-5 + AIR-7 CFD ground truth in hand or queued ✓
- AIR-11 attempt documented as known-broken-in-v7.5.1 ✓
- MPI binary built ✓ (10–15× speedup over serial for any future CFD)
- S-1..S-7 task IDs added to roadmap ✓
- **Next: build S-1 (mechanism generator) starting now**
