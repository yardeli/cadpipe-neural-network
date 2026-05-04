"""Smoke test: 10K-budget random search using surrogate v4.

Two purposes:
  1. End-to-end validation of the surrogate-as-evaluator pipeline through
     the search loop (catches integration regressions before BO touches it).
  2. Baseline number the other instance's Sobol+BO must beat to claim it
     learned anything beyond random sampling.

Output: best composite score, top-5 mechanism summaries, wall time.
"""
import time
import torch
from plasmanet.mechanism_search import (
    PARK_47, MechanismSurrogate, register_surrogate_evaluator,
)
from plasmanet.mechanism_search.search_loop import random_search


def main():
    print("loading v4 weights ...")
    t0 = time.time()
    model = MechanismSurrogate(freestream_dim=4, mechanism_dim=47,
                                hidden_dim=512, n_layers=4)
    model.load_state_dict(torch.load(
        "/home/yarden/mechanism_search_results/surrogate_v4.pt"))
    model.eval()
    register_surrogate_evaluator(model, name="plasmanet_v4")
    print(f"  loaded + registered in {time.time()-t0:.2f}s")

    BUDGET = 10000
    print(f"\nrandom_search budget={BUDGET}, evaluator=plasmanet_v4 ...")
    t0 = time.time()
    results = random_search(
        base_mechanism=PARK_47,
        evaluator="plasmanet_v4",
        budget=BUDGET,
        benchmarks=["ram_c_61km_M22.5"],
        min_reactions=3,
        max_reactions=40,
        seed=42,
    )
    dt = time.time() - t0
    print(f"  wall: {dt:.1f}s ({BUDGET/dt:.0f} evals/sec)")

    print(f"\nTop 5 (lowest composite score):")
    for i, (mech, sr) in enumerate(results[:5]):
        ne = sr.per_benchmark[0].ne_predicted_m3 if sr.per_benchmark else 0
        n_d = sum(1 for r in mech.reactions if r.is_dissociation)
        n_i = sum(1 for r in mech.reactions if r.is_ionization)
        print(f"  #{i}: score={sr.composite_score:.4f}  ne={ne:.2e}  "
              f"nrxn={mech.n_reactions} (d={n_d}, i={n_i})  {mech.name}")

    print(f"\nWorst 3 (highest composite score):")
    for i, (mech, sr) in enumerate(results[-3:]):
        ne = sr.per_benchmark[0].ne_predicted_m3 if sr.per_benchmark else 0
        print(f"  #{len(results)-3+i}: score={sr.composite_score:.4f}  "
              f"ne={ne:.2e}  nrxn={mech.n_reactions}  {mech.name}")

    valid = [r for _, r in results
             if r.composite_score != float("inf")]
    print(f"\nDistribution: {len(valid)}/{BUDGET} valid evaluations")
    if valid:
        scores = sorted(r.composite_score for r in valid)
        p = lambda q: scores[int(q * len(scores))]
        print(f"  score percentiles: "
              f"p1={p(0.01):.3f}  p10={p(0.10):.3f}  p50={p(0.50):.3f}  "
              f"p90={p(0.90):.3f}  p99={p(0.99):.3f}")
        print(f"  best={scores[0]:.4f}  worst={scores[-1]:.4f}")
    print("\nOK — random_search baseline established. BO must beat best={:.4f}".format(
        scores[0] if valid else float("nan")))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
