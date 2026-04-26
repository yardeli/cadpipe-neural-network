"""Single-batch worker for parallel mechanism evaluation.

Runs N Cantera 0D evaluations with random seeds, writes to JSONL, exits
cleanly so all Mutation++ / Cantera state is freed (works around the
in-process memory accumulation that limited v2 collection to 76K examples).

Coordinator spawns multiple of these in parallel, then restarts them in
batches.

Usage (called by parallel_data_collection.py):
    python3 scripts/data_collection_worker.py \\
        --n 5000 --seed-base 12345 \\
        --out /tmp/worker_0_batch_0.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

# ── Suppress Cantera warning spam to keep output clean
import os
os.environ.setdefault("CT_QUIET", "1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5000,
                     help="Target number of valid evaluations to collect")
    ap.add_argument("--seed-base", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-attempts-multiplier", type=float, default=2.5,
                     help="Hard cap on attempts = n * multiplier (default 2.5)")
    args = ap.parse_args()

    from plasmanet.mechanism_search import PARK_47, BENCHMARKS, score_candidate

    benchmarks = ["ram_c_47km_M18.5", "ram_c_61km_M22.5",
                   "ram_c_71km_M23.6", "ram_c_81km_M23.9"]
    residence_times = [1e-6, 1e-5, 1e-4]

    rxn_pool = [r for r in PARK_47.reactions if r.A > 0]
    dissoc_ids = [r.rxn_id for r in rxn_pool if r.is_dissociation]
    ion_ids = [r.rxn_id for r in rxn_pool if r.is_ionization]
    other_ids = [r.rxn_id for r in rxn_pool
                 if not r.is_dissociation and not r.is_ionization]

    n_collected = 0
    n_failed = 0
    seed = args.seed_base
    max_attempts = int(args.n * args.max_attempts_multiplier)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        for attempt in range(max_attempts):
            seed += 1
            rng = random.Random(seed)

            # Physically valid: ≥1 dissoc + ≥1 ioniz
            n_dissoc = rng.randint(1, min(3, len(dissoc_ids)))
            n_ion = rng.randint(1, min(3, len(ion_ids)))
            n_other = rng.randint(0, min(34, len(other_ids)))
            chosen = (rng.sample(dissoc_ids, n_dissoc)
                      + rng.sample(ion_ids, n_ion)
                      + rng.sample(other_ids, n_other))
            mech = PARK_47.subset(reaction_ids=chosen)
            mech.name = f"w{args.seed_base}_s{seed}_n{len(chosen)}"

            bk_name = rng.choice(benchmarks)
            tres = rng.choice(residence_times)
            bk = BENCHMARKS[bk_name]

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
                n_collected += 1

                if n_collected >= args.n:
                    break
            except Exception:
                n_failed += 1

    print(f"WORKER seed_base={args.seed_base}: "
          f"collected {n_collected}, failed {n_failed}, "
          f"out={args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
