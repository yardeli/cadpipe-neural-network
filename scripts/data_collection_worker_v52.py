"""v5.2 multi-fuel data-collection worker (STAGED, NOT LAUNCHED).

Worker template for the v5.2 surrogate. Extends the v5 worker pattern
(parallel_data_collection_v5.py + data_collection_worker_v5.py) along
two new axes:

  - **Fuel kind** (3 levels): AIR, H2, CH4. AIR replays the v5_prime
    pure-air axis 1:1; H2 and CH4 sample combustion chemistry.
  - **Equivalence ratio φ_fuel** (continuous, 0 → 4): only sampled
    when fuel_kind != AIR. φ=1 is stoichiometric; > 1 is fuel-rich.

The 7-d freestream feature vector for v5.2 is:
    (alt, mach, T_inf, P_inf, log10(τ), φ_fuel/4.0, fuel_kind_id/2.0)

Sampling envelope (matches v5_prime where possible):
    alt        ∈ [20, 95] km            (USSA76)
    mach       ∈ [5, 25]                (HGV → terminal scramjet)
    τ          ∈ [10⁻⁷, 10⁻³] s         (kinetics → equilibrium)
    φ_fuel     ∈ [0.5, 3.0]             (lean → fuel-rich)
    fuel_kind  ∈ {AIR, H2, CH4}

Target counts (per the SURROGATE_V5_2_PLAN.md):
    AIR:    1,000,000 records  (regression-anchor vs v5_prime)
    H2:     2,000,000 records  (full envelope × 5 φ values)
    CH4:    2,000,000 records  (full envelope × 5 φ values)
    Total:  5,000,000 records  (matches v5 / v5_prime corpus size)

DO NOT LAUNCH WITHOUT EXPLICIT AUTHORISATION. Estimated cost on the
existing 4-worker c2d-highcpu-16 setup is ~4 hours wall time for the
data collection alone (~530 evals/s aggregate × 5e6 records), plus
~4 hours for the training run. This is billable VM time.

To launch (after authorisation):
    PYTHONPATH=. python scripts/parallel_data_collection_v52.py \\
        --output /home/yarden/mechanism_search_results/training_data_v52.jsonl \\
        --workers 4 --target 5000000

Prereqs (gating tasks):
    1. Add NASA-9 thermo polynomials for fuel-species to
       plasmanet/mechanism_search/thermo_data.NASA9_THERMO:
         H2/O2 set: H2, OH, HO2, H2O2, H2O   (5 species not already in DB)
         CH4 set:   CH4, CH3, CH2O, HCO, CO, CO2   (6 species)
       Source: NASA Glenn coefficients TP-2002-211556 (free, public).
    2. Verify Cantera loads both H2 and CH4 composite mechanism YAMLs
       via scripts/test_fuel_axis.py — test 4 must report 0 missing.
    3. Sanity check: composite reactor at φ=1, T=2500K, P=1atm produces
       OH+H+H2O > 5e-3 mole fraction within 1 ms (verifies kinetics).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def sample_record(rng: random.Random, fuel_kind, phi: float) -> dict:
    """Generate one random (mechanism, freestream, τ, fuel) record."""
    from plasmanet.mechanism_search import (
        PARK_47, FuelKind, composite_air_fuel_mechanism, random_subset,
    )

    alt_km = rng.uniform(20.0, 95.0)
    mach = rng.uniform(5.0, 25.0)
    log10_tau = rng.uniform(-7.0, -3.0)
    tau_s = 10 ** log10_tau

    # Random Park subset (the 47-bit mechanism axis), like v5/v5_prime
    n_rxn = rng.randint(8, 47)
    air_subset = random_subset(n_reactions=n_rxn, seed=rng.randint(0, 2**31 - 1))

    composite = composite_air_fuel_mechanism(air_subset, fuel_kind, phi)
    # Bit-fingerprint: 47 bits for Park; v5.2 extends to (47 + fuel_kind_id)
    fingerprint = [int(r.rxn_id in {x.rxn_id for x in composite.reactions})
                    for r in PARK_47.reactions]

    return {
        "name": composite.name,
        "alt_km": alt_km,
        "mach": mach,
        "log10_tau_s": log10_tau,
        "phi_fuel": phi,
        "fuel_kind_id": fuel_kind.value,
        "fingerprint": fingerprint,
        "n_reactions": composite.n_reactions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="v5.2 data collection worker — DO NOT LAUNCH WITHOUT AUTH",
    )
    parser.add_argument("--output", required=True, help="JSONL output path")
    parser.add_argument("--target", type=int, default=10,
                         help="Records to generate (default 10 — dry-run smoke)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no-evaluate", action="store_true",
                         help="Skip Cantera evaluation (record schema only — "
                              "useful for testing the worker pipeline without "
                              "burning compute)")
    args = parser.parse_args()

    from plasmanet.mechanism_search import FuelKind

    if args.target > 1000 and not args.no_evaluate:
        print(f"ERROR: --target {args.target} > 1000 must be paired with "
              f"--no-evaluate OR run on the GCP VM with authorisation. "
              f"This script defaults to a 10-record smoke run.",
              file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fuel_kinds = [FuelKind.AIR, FuelKind.H2, FuelKind.CH4]

    t0 = time.time()
    n = 0
    with out_path.open("w") as fh:
        for _ in range(args.target):
            fk = rng.choice(fuel_kinds)
            phi = 0.0 if fk == FuelKind.AIR else rng.uniform(0.5, 3.0)
            rec = sample_record(rng, fk, phi)
            if not args.no_evaluate:
                # Placeholder for cantera_evaluator.evaluate(...) hook —
                # left intentionally unimplemented at this framework stage
                # so the worker can't accidentally consume cloud budget.
                raise RuntimeError(
                    "Cantera evaluation hook is intentionally not wired in the "
                    "framework worker. Pass --no-evaluate for a smoke run.")
            fh.write(json.dumps(rec) + "\n")
            n += 1
            if n % 1000 == 0:
                print(f"  {n}/{args.target} records  "
                      f"({n/(time.time()-t0):.0f}/s)", flush=True)

    dt = time.time() - t0
    print(f"Wrote {n} records to {out_path}  ({dt:.1f}s, {n/dt:.0f}/s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
