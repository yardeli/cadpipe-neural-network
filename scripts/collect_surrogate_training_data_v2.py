"""S-3 v2 — collect 100K+ Cantera 0D evaluations for surrogate training.

Improvements over v1 (which yielded only 307 valid from 1200 attempts):

1. Pre-filter: random mechanisms must have ≥1 dissociation + ≥1 ionization
   reaction to be physically capable of producing electrons. This cuts the
   ~75% failure rate of pure-random subsets to ~50%.

2. Multi-axis sweep:
     - 4 RAM-C benchmarks (47/61/71/81 km)
     - 3 residence times (1us, 10us, 100us)
     - Mechanism sizes 5..40 reactions, drawn from Park 47 valid pool
     - Multiple seeds for statistical coverage

3. Incremental JSONL writes so a kill at any point preserves progress.

4. Target: 200K attempts → ~100K valid → ±0.5 log10 surrogate accuracy
   after retrain.

Run on VM (3-6 hours unattended):
    cd /home/yarden/plasmanet && PYTHONPATH=. nohup setsid bash -c \\
        'python3 scripts/collect_surrogate_training_data_v2.py 2>/dev/null' \\
        > /home/yarden/collect_v2.log 2>&1 < /dev/null &
"""
from __future__ import annotations

import json
import math
import time
import random
from pathlib import Path

import numpy as np


def main():
    from plasmanet.mechanism_search import (
        PARK_47,
        BENCHMARKS,
        score_candidate,
    )

    OUT = Path("/home/yarden/mechanism_search_results/training_data_v2.jsonl")
    OUT.parent.mkdir(parents=True, exist_ok=True)

    benchmarks = ["ram_c_47km_M18.5", "ram_c_61km_M22.5",
                   "ram_c_71km_M23.6", "ram_c_81km_M23.9"]
    residence_times = [1e-6, 1e-5, 1e-4]
    target_valid = 100_000
    max_attempts = 200_000

    # ── Pre-classify Park 47 reactions for filter
    rxn_pool = [r for r in PARK_47.reactions if r.A > 0]
    dissoc_ids = [r.rxn_id for r in rxn_pool if r.is_dissociation]
    ion_ids = [r.rxn_id for r in rxn_pool if r.is_ionization]
    other_ids = [r.rxn_id for r in rxn_pool
                 if not r.is_dissociation and not r.is_ionization]

    print(f"Reaction pool: {len(rxn_pool)} valid, "
          f"{len(dissoc_ids)} dissoc, {len(ion_ids)} ioniz, "
          f"{len(other_ids)} other")
    print(f"Target: {target_valid} valid examples (max {max_attempts} attempts)")
    print(f"Output: {OUT}")
    print()

    n_collected = 0
    n_failed = 0
    n_attempts = 0
    seed = 0
    t0 = time.time()
    last_print = t0

    # Append mode so multiple invocations accumulate
    with open(OUT, "a") as f:
        while n_collected < target_valid and n_attempts < max_attempts:
            seed += 1
            n_attempts += 1
            rng = random.Random(seed)

            # ── Build a physically-valid random mechanism
            # Always include 1-3 dissoc + 1-3 ioniz, then sprinkle "other"
            n_dissoc = rng.randint(1, min(3, len(dissoc_ids)))
            n_ion = rng.randint(1, min(3, len(ion_ids)))
            n_other = rng.randint(0, min(34, len(other_ids)))
            chosen = (rng.sample(dissoc_ids, n_dissoc)
                      + rng.sample(ion_ids, n_ion)
                      + rng.sample(other_ids, n_other))
            mech = PARK_47.subset(reaction_ids=chosen)
            mech.name = f"v2_seed{seed}_n{len(chosen)}"

            # ── Random benchmark + residence time
            bk_name = rng.choice(benchmarks)
            tres = rng.choice(residence_times)
            bk = BENCHMARKS[bk_name]

            # ── Evaluate
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
                # Filter outliers / numerical instability
                if ne <= 1e10 or ne > 1e25:
                    n_failed += 1
                    continue

                record = {
                    "benchmark": bk_name,
                    "altitude_km": bk.altitude_km,
                    "mach": bk.mach,
                    "T_inf": bk.temperature_k,
                    "P_inf": bk.pressure_pa,
                    "residence_time_s": tres,
                    "mechanism_name": mech.name,
                    "n_reactions": mech.n_reactions,
                    "reaction_ids": chosen,
                    "ne_m3": ne,
                    "log10_ne": math.log10(max(ne, 1e-30)),
                    "score": result.composite_score,
                }
                f.write(json.dumps(record) + "\n")
                f.flush()
                n_collected += 1
            except Exception:
                n_failed += 1

            # Periodic progress
            now = time.time()
            if now - last_print > 30.0:
                rate = n_attempts / (now - t0)
                success = 100 * n_collected / max(n_attempts, 1)
                eta_s = (target_valid - n_collected) / max(
                    n_collected / max(now - t0, 1), 1
                )
                print(f"  [{now-t0:.0f}s] {n_collected} valid / {n_attempts} attempts "
                      f"({success:.1f}% success, {rate:.0f}/s, "
                      f"eta {eta_s/60:.1f} min)")
                last_print = now

    dt = time.time() - t0
    print()
    print(f"Done in {dt:.1f}s ({dt/60:.1f} min)")
    print(f"  collected: {n_collected}")
    print(f"  failed:    {n_failed}")
    print(f"  success:   {100 * n_collected / max(n_attempts, 1):.1f}%")
    print(f"  saved to:  {OUT}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
