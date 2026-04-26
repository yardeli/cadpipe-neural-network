"""First end-to-end search: GA over Park 47 reaction subsets with
Cantera 0D evaluator, scored against RAM-C 61km/M22.5.

Demonstrates the framework working from mechanism generation through
fast evaluation through composite scoring through search loop. Output:
ranked top-K candidates saved as YAML + JSON.

Run on VM (Cantera not on Windows):
    cd /home/yarden/plasmanet && git pull
    python3 scripts/run_first_search.py
"""
from __future__ import annotations

import time
from pathlib import Path

from plasmanet.mechanism_search import (
    PARK_47,
    park_air5,
    park_air7,
    park_air11,
    BENCHMARKS,
    score_candidate,
    genetic_search,
    save_results,
)
# This import auto-registers cantera_0d evaluator
from plasmanet.mechanism_search.cantera_evaluator import HAVE_CANTERA


def main():
    if not HAVE_CANTERA:
        print("Cantera not installed in this Python — run on VM where it is.")
        return 1

    # ── Sanity check: evaluate the three reference mechanisms first
    print("=" * 70)
    print("Reference mechanism evaluations (sanity check before search)")
    print("=" * 70)
    refs = [park_air5(), park_air7(), park_air11()]
    for mech in refs:
        t0 = time.time()
        result = score_candidate(
            mechanism_name=mech.name,
            evaluator="cantera_0d",
            evaluator_input={"mechanism": mech, "residence_time_s": 1e-4},
            benchmark="ram_c_61km_M22.5",
        )
        dt = time.time() - t0
        for r in result.per_benchmark:
            print(f"  {mech.name:25s} ne={r.ne_predicted_m3:.2e} m^-3  "
                  f"score={r.score:.3f}  ({dt:.2f}s)")
    print()

    # ── First GA search
    print("=" * 70)
    print("Genetic search: 5 generations × 10 individuals = ~50 evaluations")
    print("=" * 70)
    t0 = time.time()
    results = genetic_search(
        base_mechanism=PARK_47,
        evaluator="cantera_0d",
        evaluator_input_fn=lambda mech: {
            "mechanism": mech, "residence_time_s": 1e-4
        },
        budget=50,
        population_size=10,
        generations=5,
        mutation_rate=0.05,
        elitism=2,
        tournament_size=3,
        benchmarks=("ram_c_61km_M22.5",),
        seed=42,
        progress_callback=lambda p: None,    # silent
    )
    dt = time.time() - t0
    print(f"Search completed in {dt:.1f}s ({len(results)} candidates evaluated)")
    print()

    # ── Top-10 candidates
    print("=" * 70)
    print("Top-10 ranked candidates")
    print("=" * 70)
    for i, (mech, score_result) in enumerate(results[:10], 1):
        print(f"  Rank {i:2d}: {mech.name:30s} "
              f"score={score_result.composite_score:.3f}  "
              f"verdict={score_result.verdict:9s}")
    print()

    # ── Best candidate diagnostic
    best_mech, best_score = results[0]
    print("=" * 70)
    print(f"Best candidate: {best_mech.name}")
    print("=" * 70)
    print(f"  Reactions: {best_mech.n_reactions}")
    print(f"  Composite score: {best_score.composite_score:.3f}")
    for r in best_score.per_benchmark:
        print(f"  Benchmark {r.benchmark_name}:")
        print(f"    ne predicted = {r.ne_predicted_m3:.3e} m^-3")
        print(f"    log10 err    = {r.log10_err_ne:+.3f}")
        print(f"    dB verdicts  = {r.db_verdicts_by_freq_hz}")

    # ── Persist top-K
    out_dir = Path("/home/yarden/mechanism_search_results/first_run")
    if out_dir.parent.exists() or out_dir.parent == Path("/home/yarden"):
        save_results(results, out_dir, top_k=10)
        print(f"\nSaved top-10 to {out_dir}/")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
