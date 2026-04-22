"""Active learning loop for PlasmaNet.

Uses Monte Carlo dropout to identify high-uncertainty regions in the
parameter space, runs Cantera at those points, and retrains the model.
"""
import argparse
import math
import time
from pathlib import Path

import numpy as np
import torch

from .model import PlasmaNet, load_checkpoint, save_checkpoint, prepare_data, train_model, evaluate_model
from .physics import full_analysis, standard_atmosphere, stagnation_pressure


def sample_random_conditions(n, seed=None):
    """Generate random flight conditions for uncertainty probing."""
    rng = np.random.default_rng(seed)
    machs = np.exp(rng.uniform(np.log(3), np.log(25), n))
    alts = rng.uniform(15, 60, n)
    nose_rs = np.exp(rng.uniform(np.log(0.01), np.log(1.0), n))
    return machs, alts, nose_rs


def compute_uncertainty_map(model, n_probe=10000, n_mc=30, seed=None):
    """Find high-uncertainty regions via Monte Carlo dropout.

    Returns (conditions, uncertainties) sorted by decreasing uncertainty.
    """
    machs, alts, nose_rs = sample_random_conditions(n_probe, seed=seed)

    # Build input tensor
    inputs = []
    for i in range(n_probe):
        T_inf, p_inf, _, _ = standard_atmosphere(float(alts[i]))
        p_stag = stagnation_pressure(p_inf, float(machs[i]))
        log10_p = math.log10(max(p_stag, 1.0))
        inputs.append([machs[i], alts[i], nose_rs[i], log10_p])

    X = torch.tensor(inputs, dtype=torch.float32)

    # MC dropout
    model.train()  # enable dropout
    predictions = []
    with torch.no_grad():
        for _ in range(n_mc):
            y = model.predict_raw(X)
            predictions.append(y[:, 6].numpy())  # log10(ne) column
    model.eval()

    preds = np.array(predictions)  # (n_mc, n_probe)
    uncertainties = preds.std(axis=0)  # std of log10(ne) across MC samples

    # Sort by uncertainty (descending)
    order = np.argsort(-uncertainties)

    conditions = [(float(machs[i]), float(alts[i]), float(nose_rs[i]))
                  for i in order]
    unc = uncertainties[order]

    return conditions, unc


def acquire_new_data(conditions, n_acquire=50, use_cantera=True):
    """Run Cantera at the specified conditions to get ground truth."""
    results = []
    for i, (mach, alt, nose_r) in enumerate(conditions[:n_acquire]):
        try:
            r = full_analysis(mach, alt, nose_r, use_cantera=use_cantera)
            results.append(r)
        except Exception as e:
            print(f"  Error at M={mach:.1f} alt={alt:.0f}: {e}")

    if not results:
        return None

    # Convert to arrays matching training data format
    n = len(results)
    dataset = {
        "mach": np.array([r["mach"] for r in results]),
        "altitude_km": np.array([r["altitude_km"] for r in results]),
        "nose_radius_m": np.array([r["nose_radius_m"] for r in results]),
        "p_stag_Pa": np.array([r["p_stag_Pa"] for r in results]),
        "T_stag_K": np.array([r["T_stag_K"] for r in results]),
        "x_N2": np.array([r["x_N2"] for r in results]),
        "x_O2": np.array([r["x_O2"] for r in results]),
        "x_O": np.array([r["x_O"] for r in results]),
        "x_N": np.array([r["x_N"] for r in results]),
        "x_NO": np.array([r["x_NO"] for r in results]),
        "ne_m3": np.array([r["ne_m3"] for r in results]),
        "fp_GHz": np.array([r["fp_GHz"] for r in results]),
        "status_code": np.array([{"DETECTABLE": 0, "ATTENUATED": 1, "BLACKOUT": 2}
                                  .get(r["status"], 0) for r in results], dtype=np.int32),
    }
    return dataset


def merge_datasets(existing_path, new_data, output_path):
    """Merge existing training data with newly acquired points."""
    existing = np.load(existing_path)

    merged = {}
    for key in existing.files:
        if key in new_data:
            merged[key] = np.concatenate([existing[key], new_data[key]])
        else:
            merged[key] = existing[key]

    np.savez_compressed(output_path, **merged)
    n_old = len(existing["mach"])
    n_new = len(new_data["mach"])
    print(f"  Merged: {n_old} + {n_new} = {n_old + n_new} total points")
    return output_path


def run_active_learning(model_path, data_path, output_model_path,
                        n_iterations=5, n_probe=10000, n_acquire=50,
                        retrain_epochs=200, use_cantera=True, verbose=True):
    """Run the active learning loop.

    Each iteration:
    1. Probe uncertainty across parameter space (MC dropout)
    2. Select highest-uncertainty points
    3. Run Cantera at those points
    4. Merge with existing training data
    5. Retrain model
    6. Report improvement
    """
    model, norm, prev_metrics = load_checkpoint(model_path)
    current_data_path = data_path

    log = print if verbose else lambda *a: None

    log(f"\n{'='*60}")
    log(f"  ACTIVE LEARNING")
    log(f"  Starting model: ne MAE = {prev_metrics.get('ne_orders_mae', '?')} orders")
    log(f"  Iterations: {n_iterations}, acquire {n_acquire} pts each")
    log(f"{'='*60}\n")

    for iteration in range(1, n_iterations + 1):
        log(f"--- Iteration {iteration}/{n_iterations} ---")

        # Step 1: Find uncertain regions
        log(f"  Probing uncertainty ({n_probe} points, MC dropout)...")
        conditions, unc = compute_uncertainty_map(
            model, n_probe=n_probe, n_mc=30,
            seed=42 + iteration)

        log(f"  Top uncertainty: {unc[0]:.4f} orders (log10 ne)")
        log(f"  Median uncertainty: {np.median(unc):.4f} orders")
        log(f"  Top condition: M={conditions[0][0]:.1f}, "
            f"alt={conditions[0][1]:.0f}km, R={conditions[0][2]:.3f}m")

        # Step 2: Acquire ground truth
        log(f"  Running Cantera at {n_acquire} points...")
        new_data = acquire_new_data(conditions, n_acquire, use_cantera)
        if new_data is None:
            log("  No new data acquired. Stopping.")
            break

        # Step 3: Merge
        merged_path = str(Path(current_data_path).with_suffix(f".iter{iteration}.npz"))
        merge_datasets(current_data_path, new_data, merged_path)
        current_data_path = merged_path

        # Step 4: Retrain
        log(f"  Retraining ({retrain_epochs} epochs)...")
        splits, new_norm = prepare_data(current_data_path)
        model = PlasmaNet()
        train_model(model, splits, new_norm, epochs=retrain_epochs,
                    patience=30, verbose=False)

        # Step 5: Evaluate
        metrics = evaluate_model(model, splits, new_norm, verbose=False)
        ne_mae = metrics.get("ne_orders_mae", float("inf"))
        ne_prev = prev_metrics.get("ne_orders_mae", float("inf"))
        improvement = ne_prev - ne_mae if isinstance(ne_prev, (int, float)) else 0

        log(f"  ne MAE: {ne_mae:.4f} orders "
            f"({'improved' if improvement > 0 else 'no improvement'}: "
            f"{improvement:+.4f})")
        log(f"  Status accuracy: {metrics.get('status_accuracy_pct', 0):.1f}%")

        prev_metrics = metrics
        norm = new_norm

    # Save final model
    model.set_normalization(norm["x_mean"], norm["x_std"],
                           norm["y_mean"], norm["y_std"])
    save_checkpoint(model, norm, prev_metrics, output_model_path)
    log(f"\nFinal model saved to {output_model_path}")
    log(f"Final ne MAE: {prev_metrics.get('ne_orders_mae', '?')} orders")

    return model, prev_metrics


def main():
    parser = argparse.ArgumentParser(description="PlasmaNet Active Learning")
    parser.add_argument("--model", type=str, default="checkpoints/plasmanet_v1.pt")
    parser.add_argument("--data", type=str, default="data/training_data.npz")
    parser.add_argument("--output", type=str, default="checkpoints/plasmanet_v2.pt")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--budget", type=int, default=200,
                        help="Total new points to acquire")
    parser.add_argument("--no-cantera", action="store_true")
    args = parser.parse_args()

    n_per_iter = max(10, args.budget // args.iterations)

    run_active_learning(
        model_path=args.model,
        data_path=args.data,
        output_model_path=args.output,
        n_iterations=args.iterations,
        n_acquire=n_per_iter,
        use_cantera=not args.no_cantera,
    )


if __name__ == "__main__":
    main()
