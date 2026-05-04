# Prompt for next Claude instance (2026-04-26)

Copy-paste the block below into a fresh Claude Code session inside
`C:\Users\yarden\Desktop\Khorium Hypersonics\plasmanet`.

---

## Context for you

You are picking up the PlasmaNet / Khorium Hypersonics project mid-flight.
A previous instance just finished training **surrogate v4** — a 4-layer
512-hidden MLP that predicts log10(ne_peak) from (4 freestream features,
47-bit Park-mechanism fingerprint), trained on 895,973 valid Cantera 0D
evaluations. **Test MAE = 0.183 log10 → factor of 1.52 of Cantera truth.**
Inference is ~0.01 ms/sample (5,000× faster than Cantera 0D).

Read these first to ground yourself:
1. `docs/CHECKPOINT_2026-04-26.md` — full state of the world
2. `docs/SURROGATE_V4_RESULT.md` — v4 metrics + caveats
3. `docs/MECHANISM_SEARCH_FRAMEWORK.md` — the architectural vision (Aaron Wu)
4. `plasmanet/mechanism_search/search_loop.py` — current random + genetic
   search; **Sobol/BO not yet implemented**
5. `plasmanet/mechanism_search/surrogate.py` — model class; load with
   `MechanismSurrogate(freestream_dim=4, mechanism_dim=47, hidden_dim=512, n_layers=4)`

**Don't disturb**: AIR-7 v7 inviscid ramp on the GCP VM (`openfoam-hgv`,
`us-central1-a`). PID 215175, in M=18→M=22.5 stage. Disk is at 92% used,
keep an eye on it.

## Your mission

**Wire surrogate v4 into the search loop and run the first AI-discovered
mechanism search at scale.** Specifically:

### Phase 1 — register the evaluator (1 hour)

Implement `register_surrogate_evaluator(model, name="plasmanet_v4")` in
`plasmanet/mechanism_search/surrogate.py` (the function name is mentioned
in the docstring but may not yet exist). It should:
- Accept a torch model + a name string
- Insert into the `EVALUATORS` registry used by `score_candidate(...)`
- Return a callable that takes `(mechanism, benchmark, residence_time_s)`
  and returns a `BenchmarkResult` matching the schema of `cantera_0d`

Validate: load the v4 weights, register, then run
`score_candidate(mechanism_name="park_air7", evaluator="plasmanet_v4", ...)`
and confirm the output shape matches `cantera_0d`'s shape.

### Phase 2 — Sobol seed + BO outer loop (3-4 hours)

Add a new search strategy in `search_loop.py`:

```python
def sobol_bayesian_search(
    base_mechanism: Mechanism,
    evaluator: str = "plasmanet_v4",
    benchmarks: list[str] = ["ram_c_61km_M22.5"],
    n_sobol: int = 1000,           # quasi-random seed phase
    n_bo: int = 5000,              # BO acquisition steps
    residence_time_s: float = 1e-6, # PIN to kinetics regime
    seed: int = 42,
) -> SearchResult:
    ...
```

Implementation outline:
1. **Sobol phase**: use `scipy.stats.qmc.Sobol(d=47)` to generate
   `n_sobol` quasi-random points in [0,1]^47. Threshold at 0.5 →
   bitmask → mechanism subset. Enforce ≥1 dissoc + ≥1 ion (re-sample
   if violated, max 10 retries per point).
2. **Evaluate all Sobol points** via the surrogate (batched, GPU if
   available; should take <1s for 1000 points).
3. **BO phase**: fit a GP (use `botorch` if installed, else fall back to
   `sklearn.gaussian_process.GaussianProcessRegressor`) on the Sobol
   results. For each BO step:
   a. Acquire next candidate by max Expected Improvement over a
      candidate pool (sample 10K random masks, rank by EI, pick top-1).
   b. Evaluate via surrogate, append to GP training set.
4. Return all evaluated points + their scores, sorted ascending.

Validate: run with `n_sobol=100, n_bo=500` first to sanity-check; if
the best-found score beats random search of the same budget, BO is
working. Then scale to `n_sobol=1000, n_bo=5000` for the real run.

### Phase 3 — Cantera verification of top-50 (~15 min)

For the top 50 candidates from Phase 2, run actual Cantera 0D evaluation.
Compare surrogate-predicted ne to Cantera truth — quantify the surrogate's
factor-of-1.52 error in practice. Save:
- `/home/yarden/mechanism_search_results/search_v4_top50.jsonl` — all 50
  with both surrogate ne, Cantera ne, log10 error, and the mechanism
- `docs/SEARCH_V4_RESULT.md` — write-up with the top 5 mechanisms,
  their ne predictions, and how they rank against Park AIR-5/AIR-7
  baselines

### Phase 4 — Pick top 5 for SU2-NEMO MPI CFD validation (deferred)

Don't run this yet — wait for the v7 ramp to finish and the user to
confirm. Just write the script `scripts/run_top5_cfd_validation.py`
that reads `search_v4_top50.jsonl`, picks the top 5 by Cantera-verified
score, and emits 5 SU2 cfg files ready to launch via the MPI binary.

## Constraints

- **Don't touch the v7 SU2 run** (PID 215175). It's writing to disk.
- **Don't push disk above 96%**. Run `df -h /home/yarden` periodically
  during evaluation and stop if free <500 MB.
- **Pin residence_time_s = 1µs** in all search runs. The 100µs and 10µs
  data is in the surrogate but those regimes hit Saha equilibrium where
  mechanism identity stops mattering — kills search signal. (See
  `docs/SWEEP_RESULTS_2026-04-26.md` for the original observation.)
- **Use `python3 -u`** for any long-running scripts so stdout flushes
  in real time. (We learned this the hard way during v4 training.)
- **Don't refactor the existing surrogate / generator / scoring code**
  unless required to plug BO in cleanly. There's a separate UI agent's
  output to integrate later — keep API stable.

## Reporting

When you finish Phase 1 + 2 + 3, produce a short Slack-style summary
with:
- Top-5 surrogate-discovered mechanisms (reaction IDs, n_reactions)
- Their predicted ne vs Cantera truth at 61km/M22.5 1µs
- How they compare to Park AIR-5 / AIR-7 baselines
- Whether any of them beat the hand-picked Park AIR-7 baseline (if yes,
  this is publishable)

## You are not blocked on

- Anything related to the AIR-11 cold start (dead-end, documented).
- Anything related to AIR-7 viscous (SU2 internal bug, documented).
- The Streamlit UI (parallel agent built it; don't depend on it).
- The academic paper draft (parallel agent wrote it).

Go.

---

## Why this prompt is what it is

The user has explicitly said: the surrogate is the unlock. Now that
v4 is publication-grade, the bottleneck moves from "training a fast
proxy" to "actually running the search." Sobol + BO is the standard
combo for this — Sobol fills the 47-D unit cube uniformly, BO
exploits the surrogate's smoothness to find optima quickly. With v4 at
0.01 ms/eval, even a 1M-candidate exhaustive scan takes ~10 s, but BO
should converge on a near-optimal mechanism in <5 K evaluations,
which is overkill-fast.

The verification-with-Cantera step (Phase 3) is the framework's
self-check: it quantifies how much the surrogate's ±1.5× error matters
in practice when ranking candidates. If the top-5 surrogate picks all
verify within Cantera's expected scatter, the framework is end-to-end
validated. If not, the data tells us where to retrain.

The CFD step (Phase 4) is deferred because the v7 run is hogging the VM
and we don't want competing CFD jobs. Once v7 finishes, top-5 CFD
validation is the path to the AIAA paper figures.
