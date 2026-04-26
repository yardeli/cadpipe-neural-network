"""S-3 — train on the JSONL training data (307 examples from
collect_surrogate_training_data.py).

Run on VM:
    cd /home/yarden/plasmanet && PYTHONPATH=. python3 scripts/train_surrogate_v2.py
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np


def main():
    from plasmanet.mechanism_search import (
        PARK_47,
        BENCHMARKS,
        TrainingExample,
        train_surrogate,
        HAVE_TORCH,
        MechanismFingerprint,
        freestream_features,
        park_air5,
        park_air7,
        park_air11,
    )

    if not HAVE_TORCH:
        print("PyTorch not installed.")
        return 1

    JSONL = Path("/home/yarden/mechanism_search_results/training_data_v1.jsonl")
    if not JSONL.exists():
        print(f"Training data not found at {JSONL}. Run "
              f"collect_surrogate_training_data.py first.")
        return 1

    examples = []
    skipped = 0
    with open(JSONL) as f:
        for line in f:
            r = json.loads(line)
            ne = r["ne_m3"]
            # Filter implausible ne (Cantera occasionally returns 1e25+ from
            # numerical instability in stiff subsets)
            if ne <= 0 or ne > 1e25:
                skipped += 1
                continue
            mech = PARK_47.subset(reaction_ids=r["reaction_ids"])
            mech.name = r["mechanism_name"]
            examples.append(TrainingExample(
                mechanism=mech,
                altitude_km=r["altitude_km"],
                mach=r["mach"],
                T_inf=r["T_inf"],
                P_inf=r["P_inf"],
                ne_target_m3=ne,
                source="cantera_0d",
            ))

    print(f"Loaded {len(examples)} examples ({skipped} skipped for outliers)")
    ne_values = [ex.ne_target_m3 for ex in examples]
    print(f"  ne range: {min(ne_values):.2e} .. {max(ne_values):.2e}")
    print(f"  log10 ne range: {math.log10(min(ne_values)):.1f} .. "
          f"{math.log10(max(ne_values)):.1f}")
    print()

    save_path = Path("/home/yarden/mechanism_search_results/surrogate_v2.pt")
    print("Training...")
    model, history = train_surrogate(
        examples=examples,
        n_epochs=300,
        batch_size=32,
        lr=1e-3,
        val_frac=0.2,
        seed=42,
        save_path=save_path,
    )

    print()
    print(f"Best val MSE (log10 ne²): {history['best_val_mse']:.4f}")
    print(f"  → typical prediction error: ±{history['best_val_mse']**0.5:.2f} log10")

    # Test on held-out reference mechanisms
    print()
    print("=" * 70)
    print("Surrogate predictions vs Cantera 0D ground truth")
    print("=" * 70)
    bk = BENCHMARKS["ram_c_61km_M22.5"]
    fs = freestream_features(bk.altitude_km, bk.mach,
                              T_inf=bk.temperature_k, P_inf=bk.pressure_pa)
    from plasmanet.mechanism_search import score_candidate
    for mech in [park_air5(), park_air7(), park_air11()]:
        # Cantera ground truth at same residence time as training (1us)
        truth = score_candidate(
            mechanism_name=mech.name, evaluator="cantera_0d",
            evaluator_input={"mechanism": mech, "residence_time_s": 1e-6},
            benchmark="ram_c_61km_M22.5",
        ).per_benchmark[0].ne_predicted_m3
        # Surrogate prediction
        fp = MechanismFingerprint(mech, base=PARK_47).to_array()
        pred = model.predict_ne_m3(fs, fp)
        log10_diff = math.log10(pred / truth) if truth > 0 else float("nan")
        log10_err_jc = math.log10(pred / bk.ne_published_m3)
        print(f"  {mech.name:20s}")
        print(f"    Cantera truth: {truth:.2e}, Surrogate: {pred:.2e}")
        print(f"    Surrogate-vs-truth: {log10_diff:+.2f} log10")
        print(f"    Surrogate-vs-J&C:   {log10_err_jc:+.2f} log10")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
