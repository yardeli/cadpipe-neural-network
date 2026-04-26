"""Collect 1000+ Cantera 0D evaluations as training data for the
PlasmaNet surrogate. Saves all (mechanism, conditions, ne) triples.

Coverage strategy:
  - All 4 RAM-C benchmarks (47, 61, 71, 81 km)
  - Multiple residence times (1us, 10us, 100us)
  - Random subsets of Park 47 with varied densities (10%-80%)
  - Multiple seeds for statistical coverage

Total: 4 benchmarks × 3 residence times × 100 random mechanisms = 1200 evals.
Wall time on VM: ~1 minute.

Run on VM:
    cd /home/yarden/plasmanet && PYTHONPATH=. python3 scripts/collect_surrogate_training_data.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from plasmanet.mechanism_search import (
    PARK_47,
    BENCHMARKS,
    score_candidate,
    random_subset,
)


def main():
    OUT = Path("/home/yarden/mechanism_search_results/training_data_v1.jsonl")
    OUT.parent.mkdir(parents=True, exist_ok=True)

    # Sweep grid
    benchmarks = ["ram_c_47km_M18.5", "ram_c_61km_M22.5",
                   "ram_c_71km_M23.6", "ram_c_81km_M23.9"]
    residence_times = [1e-6, 1e-5, 1e-4]
    n_per_combo = 100   # 4 × 3 × 100 = 1200 total

    print(f"Collecting {len(benchmarks)} × {len(residence_times)} × "
          f"{n_per_combo} = {len(benchmarks)*len(residence_times)*n_per_combo} "
          f"training examples")

    n_collected = 0
    n_failed = 0
    t0 = time.time()
    seed = 1

    with open(OUT, "w") as f:
        for bk_name in benchmarks:
            bk = BENCHMARKS[bk_name]
            for tres in residence_times:
                for i in range(n_per_combo):
                    seed += 1
                    # Random mechanism with size 5-40
                    import random
                    rng = random.Random(seed)
                    n_rxn = rng.randint(5, 40)
                    valid_ids = [r.rxn_id for r in PARK_47.reactions if r.A > 0]
                    chosen_ids = rng.sample(valid_ids, min(n_rxn, len(valid_ids)))
                    mech = PARK_47.subset(reaction_ids=chosen_ids)
                    mech.name = f"random_seed{seed}_n{n_rxn}"

                    try:
                        result = score_candidate(
                            mechanism_name=mech.name,
                            evaluator="cantera_0d",
                            evaluator_input={
                                "mechanism": mech, "residence_time_s": tres
                            },
                            benchmark=bk_name,
                        )
                        if result.composite_score == float("inf"):
                            n_failed += 1
                            continue
                        ne = result.per_benchmark[0].ne_predicted_m3
                        if ne <= 0:
                            n_failed += 1
                            continue

                        # Persist as JSON line for easy reload
                        record = {
                            "benchmark": bk_name,
                            "altitude_km": bk.altitude_km,
                            "mach": bk.mach,
                            "T_inf": bk.temperature_k,
                            "P_inf": bk.pressure_pa,
                            "residence_time_s": tres,
                            "mechanism_name": mech.name,
                            "n_reactions": mech.n_reactions,
                            "reaction_ids": chosen_ids,
                            "ne_m3": ne,
                            "log10_ne": __import__("math").log10(max(ne, 1e-30)),
                            "score": result.composite_score,
                        }
                        f.write(json.dumps(record) + "\n")
                        n_collected += 1
                    except Exception as exc:
                        n_failed += 1

                    if (n_collected + n_failed) % 100 == 0:
                        rate = (n_collected + n_failed) / (time.time() - t0)
                        print(f"  {n_collected} collected, {n_failed} failed "
                              f"({rate:.0f}/s)")

    dt = time.time() - t0
    print()
    print(f"Done in {dt:.1f}s")
    print(f"  collected: {n_collected}")
    print(f"  failed:    {n_failed}")
    print(f"  saved to:  {OUT}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
