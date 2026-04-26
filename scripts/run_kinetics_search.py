"""Second search with SHORT residence time (1e-6 s = 1 μs) so chemistry
doesn't equilibrate — testing whether the framework can discriminate between
mechanisms when KINETICS matter, not just equilibrium.

The first search at residence_time=1e-4 s found all top candidates produced
identical ne (Saha equilibrium reached regardless of mechanism). This is
expected behavior at long times. To test the framework's actual
mechanism-discrimination ability, we run at 1 μs residence time — short
enough that the rate-limiting steps in each mechanism produce different ne.

Run on VM:
    cd /home/yarden/plasmanet && git pull
    PYTHONPATH=. python3 scripts/run_kinetics_search.py
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
from plasmanet.mechanism_search.cantera_evaluator import HAVE_CANTERA


def main():
    if not HAVE_CANTERA:
        print("Cantera not installed — run on VM where it is.")
        return 1

    RESIDENCE_TIME = 1e-6   # 1 us — too short for full equilibrium

    # Reference mechanisms at the new residence time
    print("=" * 70)
    print(f"Reference evaluations (residence_time = {RESIDENCE_TIME:.0e} s)")
    print(f"Should show LARGER variance than 100us run since kinetics matter")
    print("=" * 70)
    for mech in [park_air5(), park_air7(), park_air11()]:
        result = score_candidate(
            mechanism_name=mech.name,
            evaluator="cantera_0d",
            evaluator_input={"mechanism": mech, "residence_time_s": RESIDENCE_TIME},
            benchmark="ram_c_61km_M22.5",
        )
        for r in result.per_benchmark:
            print(f"  {mech.name:25s} ne={r.ne_predicted_m3:.2e} m^-3  "
                  f"score={r.score:.3f}")
    print()

    print("=" * 70)
    print("GA search at 1 us residence time — kinetics-discriminating")
    print("=" * 70)
    t0 = time.time()
    results = genetic_search(
        base_mechanism=PARK_47,
        evaluator="cantera_0d",
        evaluator_input_fn=lambda mech: {
            "mechanism": mech, "residence_time_s": RESIDENCE_TIME
        },
        budget=80,
        population_size=16,
        generations=5,
        mutation_rate=0.05,
        elitism=2,
        tournament_size=3,
        benchmarks=("ram_c_61km_M22.5",),
        seed=123,
        progress_callback=lambda p: None,
    )
    dt = time.time() - t0
    print(f"Search done in {dt:.1f}s ({len(results)} candidates)")
    print()

    # Variance analysis
    scores = [r[1].composite_score for r in results
              if r[1].composite_score < float("inf")]
    nes = [r[1].per_benchmark[0].ne_predicted_m3 for r in results
           if r[1].composite_score < float("inf")]
    print(f"Score range across all {len(scores)} candidates:")
    print(f"  min: {min(scores):.4f}")
    print(f"  max: {max(scores):.4f}")
    print(f"  unique scores (rounded to 4 dp): {len(set(round(s,4) for s in scores))}")
    print(f"  ne range: {min(nes):.2e} .. {max(nes):.2e} m^-3 "
          f"(spans {len(set('%.0e' % n for n in nes))} orders of magnitude)")
    print()

    # Top-10
    print("=" * 70)
    print("Top-10 ranked")
    print("=" * 70)
    for i, (mech, score) in enumerate(results[:10], 1):
        ne = score.per_benchmark[0].ne_predicted_m3
        log10err = score.per_benchmark[0].log10_err_ne
        print(f"  Rank {i:2d}: {mech.name:25s} {mech.n_reactions:2d} rxn  "
              f"ne={ne:.2e}  log10_err={log10err:+.2f}  score={score.composite_score:.3f}")

    # Save
    out_dir = Path("/home/yarden/mechanism_search_results/kinetics_run_1us")
    out_dir.mkdir(parents=True, exist_ok=True)
    save_results(results, out_dir, top_k=10)
    print(f"\nSaved to {out_dir}/")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
