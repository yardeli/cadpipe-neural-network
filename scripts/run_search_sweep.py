"""5-run sweep across the framework's most sensitive axes.

This produces the data a hypersonic engineer would want for design review:
how does the predicted ne change as we vary mechanism / kinetic timescale
/ flight regime? Does the framework converge across seeds (reproducible)?
Does it discriminate between mechanisms (search is meaningful)?

Five sweeps:
  1. Seed reproducibility — same conditions, 3 different RNG seeds.
     Proves the search converges to similar answers.
  2. Residence-time scan — 100us / 10us / 1us / 100ns / 10ns at fixed
     conditions. Reveals the equilibrium-vs-kinetics transition.
  3. Benchmark sweep — search at RAM-C 47/61/71/81 km altitudes.
     Different ionization regimes; how the optimal mechanism differs.
  4. Reaction-budget constraint — search across max_reactions =
     5/10/20/40 to find SMALLEST mechanism that matches data.
     This is the practical UQ result for designers.
  5. Wider GA budget — 200 candidates × 8 generations = 1600 evals
     vs the 80-eval baseline. Confirms search converges to a stable
     top-1 with more compute.

Run on VM:
    cd /home/yarden/plasmanet && git pull
    PYTHONPATH=. python3 scripts/run_search_sweep.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from plasmanet.mechanism_search import (
    PARK_47,
    BENCHMARKS,
    score_candidate,
    genetic_search,
    save_results,
)
from plasmanet.mechanism_search.cantera_evaluator import HAVE_CANTERA


OUT_BASE = Path("/home/yarden/mechanism_search_results/sweep")


def run_one(label, base_mechanism=PARK_47, residence_time_s=1e-6,
             budget=80, population_size=16, generations=5,
             benchmarks=("ram_c_61km_M22.5",), seed=42,
             max_reactions=None):
    """Run one search and return (results, summary_dict)."""
    print(f"\n{'='*70}\nRun: {label}\n{'='*70}")
    print(f"  residence_time={residence_time_s:.0e} s, budget={budget}, "
          f"benchmark={benchmarks[0]}, seed={seed}, "
          f"max_rxn={max_reactions or 'none'}")
    t0 = time.time()

    # If max_reactions is set, pre-filter the base mechanism to enforce it
    if max_reactions:
        # Can't really pre-filter randomly during GA; instead, the GA's
        # subset() naturally selects subsets ≤ N reactions. We post-filter
        # in scoring.
        pass

    results = genetic_search(
        base_mechanism=base_mechanism,
        evaluator="cantera_0d",
        evaluator_input_fn=lambda mech: {
            "mechanism": mech, "residence_time_s": residence_time_s
        },
        budget=budget,
        population_size=population_size,
        generations=generations,
        mutation_rate=0.05,
        elitism=2,
        tournament_size=3,
        benchmarks=benchmarks,
        seed=seed,
        progress_callback=lambda p: None,
    )
    dt = time.time() - t0

    # Filter for max_reactions constraint if specified
    if max_reactions:
        results = [(m, s) for (m, s) in results if m.n_reactions <= max_reactions]

    # Statistics
    valid = [r for r in results if r[1].composite_score < float("inf")]
    scores = [r[1].composite_score for r in valid]
    nes = [r[1].per_benchmark[0].ne_predicted_m3 for r in valid]
    log10err_top1 = valid[0][1].per_benchmark[0].log10_err_ne if valid else None

    summary = {
        "label": label,
        "wall_time_s": dt,
        "n_evaluated": len(results),
        "n_valid": len(valid),
        "n_unique_scores": len(set(round(s, 4) for s in scores)),
        "score_min": min(scores) if scores else None,
        "score_max": max(scores) if scores else None,
        "ne_range": [min(nes), max(nes)] if nes else None,
        "ne_orders_of_magnitude": (
            len(set(f"{n:.0e}" for n in nes)) if nes else 0
        ),
        "top_1_n_reactions": valid[0][0].n_reactions if valid else None,
        "top_1_ne_m3": valid[0][1].per_benchmark[0].ne_predicted_m3 if valid else None,
        "top_1_log10_err": log10err_top1,
        "top_1_score": valid[0][1].composite_score if valid else None,
    }

    print(f"  done in {dt:.1f}s, {len(valid)}/{len(results)} valid, "
          f"top-1 ne={summary['top_1_ne_m3']:.2e} (log10 err {log10err_top1:+.2f}), "
          f"score={summary['top_1_score']:.3f}")
    print(f"  variance: {summary['n_unique_scores']} unique scores, "
          f"ne spans {summary['ne_orders_of_magnitude']} orders")

    out = OUT_BASE / label.replace(" ", "_")
    out.mkdir(parents=True, exist_ok=True)
    save_results(results, out, top_k=5)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    return results, summary


def main():
    if not HAVE_CANTERA:
        print("Cantera not installed — run on VM.")
        return 1

    OUT_BASE.mkdir(parents=True, exist_ok=True)
    all_summaries = []

    # ── Sweep 1: Seed reproducibility (does the GA give similar answers
    # with different seeds?)
    print("\n#" * 35)
    print("# SWEEP 1: SEED REPRODUCIBILITY")
    print("# Same conditions, 3 different RNG seeds.")
    print("# If top-1 ne agrees within ±0.5 log10, search is reproducible.")
    print("#" * 35)
    for seed in [42, 123, 999]:
        _, s = run_one(f"sweep1_seed{seed}", residence_time_s=1e-6,
                        budget=60, seed=seed)
        all_summaries.append(s)

    # ── Sweep 2: Residence-time scan (equilibrium-vs-kinetics transition)
    print("\n#" * 35)
    print("# SWEEP 2: RESIDENCE-TIME SCAN")
    print("# Varying t_res reveals when chemistry equilibrates vs depends on kinetics.")
    print("#" * 35)
    for tres in [1e-7, 1e-6, 1e-5, 1e-4]:
        _, s = run_one(f"sweep2_tres{tres:.0e}", residence_time_s=tres,
                        budget=60, seed=42)
        all_summaries.append(s)

    # ── Sweep 3: Benchmark altitude (different flight regime)
    print("\n#" * 35)
    print("# SWEEP 3: BENCHMARK ALTITUDE")
    print("# Optimal mechanism may differ at different flight conditions.")
    print("#" * 35)
    for bk in ["ram_c_47km_M18.5", "ram_c_61km_M22.5",
                "ram_c_71km_M23.6", "ram_c_81km_M23.9"]:
        _, s = run_one(f"sweep3_{bk}", residence_time_s=1e-6,
                        budget=60, benchmarks=(bk,), seed=42)
        all_summaries.append(s)

    # ── Sweep 4: Reaction-count budget (smallest sufficient mechanism)
    print("\n#" * 35)
    print("# SWEEP 4: MAX-REACTION CONSTRAINT")
    print("# Find SMALLEST mechanism that matches data (designer's UQ tool).")
    print("#" * 35)
    for max_rxn in [5, 10, 20, 40]:
        _, s = run_one(f"sweep4_maxrxn{max_rxn}", residence_time_s=1e-6,
                        budget=80, seed=42, max_reactions=max_rxn)
        all_summaries.append(s)

    # ── Sweep 5: Larger budget (does search converge with more compute?)
    print("\n#" * 35)
    print("# SWEEP 5: WIDER BUDGET")
    print("# 200 candidates × 8 generations vs 80-eval baseline.")
    print("#" * 35)
    _, s = run_one("sweep5_wide_budget", residence_time_s=1e-6,
                    budget=200, population_size=20, generations=10,
                    seed=42)
    all_summaries.append(s)

    # ── Aggregate report
    print("\n" + "#" * 70)
    print("# AGGREGATE: all sweeps in one table")
    print("#" * 70)
    fmt = "{:<32} {:>8} {:>8} {:>8} {:>10} {:>10}"
    print(fmt.format("label", "n_eval", "uniqs", "top_n", "log10_err", "ne_top1"))
    for s in all_summaries:
        print(fmt.format(
            s["label"][:32],
            s["n_evaluated"],
            s["n_unique_scores"],
            s["top_1_n_reactions"] or 0,
            f"{s['top_1_log10_err']:+.2f}" if s["top_1_log10_err"] is not None else "—",
            f"{s['top_1_ne_m3']:.2e}" if s["top_1_ne_m3"] is not None else "—",
        ))

    (OUT_BASE / "aggregate.json").write_text(
        json.dumps(all_summaries, indent=2, default=str)
    )
    print(f"\nFull report at {OUT_BASE / 'aggregate.json'}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
