"""S-3 — train PlasmaNet mechanism-surrogate on sweep evaluation data.

Pulls the saved (mechanism, ne) pairs from /home/yarden/mechanism_search_results/sweep/
on the VM, builds a list of TrainingExamples, trains MechanismSurrogate.

Run on VM:
    cd /home/yarden/plasmanet && PYTHONPATH=. python3 scripts/train_surrogate_from_sweeps.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def main():
    from plasmanet.mechanism_search import (
        PARK_47,
        Mechanism,
        Reaction,
        BENCHMARKS,
        TrainingExample,
        train_surrogate,
        HAVE_TORCH,
        MechanismFingerprint,
        freestream_features,
    )

    if not HAVE_TORCH:
        print("PyTorch not installed. Install via: pip install --user torch")
        return 1

    # ── Load all candidates from each sweep dir
    sweep_root = Path("/home/yarden/mechanism_search_results/sweep")
    if not sweep_root.exists():
        print(f"ERROR: sweep results not found at {sweep_root}")
        return 1

    examples: list[TrainingExample] = []
    n_skipped = 0
    n_loaded = 0

    for sweep_dir in sorted(sweep_root.iterdir()):
        if not sweep_dir.is_dir():
            continue
        # Each sweep dir has top_k/rank_NNN/{mechanism.json, score.json}
        top_k = sweep_dir / "top_k"
        if not top_k.exists():
            continue
        for rank_dir in sorted(top_k.iterdir()):
            mech_json = rank_dir / "mechanism.json"
            score_json = rank_dir / "score.json"
            if not (mech_json.exists() and score_json.exists()):
                n_skipped += 1
                continue

            try:
                m_data = json.loads(mech_json.read_text())
                s_data = json.loads(score_json.read_text())
            except Exception:
                n_skipped += 1
                continue

            # Reconstruct Mechanism from JSON
            reactions = [
                Reaction(
                    rxn_id=r["rxn_id"], formula=r["formula"],
                    reactants=r["reactants"], products=r["products"],
                    A=r["A"], n=r["n"], theta_a=r["theta_a"],
                    Tcf_a=r.get("Tcf_a", 0.5), Tcf_b=r.get("Tcf_b", 0.5),
                    Tcb_a=r.get("Tcb_a", 1.0), Tcb_b=r.get("Tcb_b", 0.0),
                    has_third_body=r.get("has_third_body", False),
                    is_ionization=r.get("is_ionization", False),
                    is_dissociation=r.get("is_dissociation", False),
                    is_exchange=r.get("is_exchange", False),
                    is_charge_transfer=r.get("is_charge_transfer", False),
                    notes=r.get("notes", ""),
                )
                for r in m_data["reactions"]
            ]
            mech = Mechanism(
                name=m_data["name"],
                species=m_data["species"],
                reactions=reactions,
            )

            # Get the benchmark this candidate was scored against
            for pb in s_data.get("per_benchmark", []):
                bk_name = pb["benchmark"]
                bk = BENCHMARKS.get(bk_name)
                if not bk:
                    continue
                ne = pb.get("ne_predicted_m3", 0.0)
                if ne <= 0:
                    continue   # skip Cantera-failed candidates
                examples.append(TrainingExample(
                    mechanism=mech,
                    altitude_km=bk.altitude_km,
                    mach=bk.mach,
                    T_inf=bk.temperature_k,
                    P_inf=bk.pressure_pa,
                    ne_target_m3=ne,
                    source="cantera_0d",
                ))
                n_loaded += 1

    print(f"Loaded {n_loaded} training examples ({n_skipped} skipped)")
    print()

    if n_loaded < 10:
        print("Too few examples to train. Need ≥10.")
        return 1

    # Show ne distribution
    ne_values = [ex.ne_target_m3 for ex in examples]
    print(f"ne target distribution:")
    print(f"  min:    {min(ne_values):.2e} m^-3")
    print(f"  median: {np.median(ne_values):.2e} m^-3")
    print(f"  max:    {max(ne_values):.2e} m^-3")
    print(f"  spread: {np.log10(max(ne_values) / max(min(ne_values), 1)):.1f} orders")
    print()

    # Train the surrogate
    print("=" * 70)
    print("Training MechanismSurrogate")
    print("=" * 70)
    save_path = Path("/home/yarden/mechanism_search_results/surrogate_v1.pt")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    model, history = train_surrogate(
        examples=examples,
        n_epochs=200,
        batch_size=16,
        lr=1e-3,
        val_frac=0.2,
        seed=42,
        save_path=save_path,
    )
    print()
    print(f"Best validation MSE (log10 ne): {history['best_val_mse']:.4f}")
    print(f"  → typical prediction error: ±{history['best_val_mse']**0.5:.2f} log10")
    print(f"Saved to {save_path}")

    # Quick prediction test on the reference mechanisms
    print()
    print("=" * 70)
    print("Surrogate predictions vs reference mechanisms (RAM-C 61km/M22.5)")
    print("=" * 70)
    from plasmanet.mechanism_search import park_air5, park_air7, park_air11
    bk = BENCHMARKS["ram_c_61km_M22.5"]
    fs = freestream_features(bk.altitude_km, bk.mach,
                              T_inf=bk.temperature_k, P_inf=bk.pressure_pa)
    for mech in [park_air5(), park_air7(), park_air11()]:
        fp = MechanismFingerprint(mech, base=PARK_47).to_array()
        ne_pred = model.predict_ne_m3(fs, fp)
        log10_err = np.log10(ne_pred / bk.ne_published_m3)
        print(f"  {mech.name:20s} ne_pred = {ne_pred:.2e}  "
              f"log10 err vs J&C = {log10_err:+.2f}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
