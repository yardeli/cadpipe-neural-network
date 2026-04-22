"""Continuous training loop: generate data -> train -> evaluate -> repeat.

Runs nonstop, progressively building a larger dataset and better model.
Each iteration:
1. Generate 500 new Cantera data points (focused on uncertain regions)
2. Merge with existing dataset
3. Retrain best model architecture (v4 deep: 128-256-256-128-64)
4. Evaluate and log improvement
5. Save checkpoint if improved
6. Run reaction search with new model to test Aaron's vision
7. Repeat
"""
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from plasmanet.model import PlasmaNet, prepare_data, train_model, evaluate_model, save_checkpoint, load_checkpoint
from plasmanet.physics import full_analysis, standard_atmosphere, stagnation_pressure, plasma_frequency_ghz
from plasmanet.active_learning import compute_uncertainty_map, acquire_new_data, merge_datasets


def run_reaction_search_with_plasmanet(model, norm):
    """Run a quick reaction search using PlasmaNet as evaluator.

    This is Aaron's vision: use the neural surrogate to instantly evaluate
    mechanism variants across many conditions.
    """
    # Flight conditions to test
    conditions = []
    for mach in [5, 8, 10, 12, 15]:
        for alt in [20, 30, 40, 50]:
            conditions.append((mach, alt))

    # Evaluate full mechanism (all species present)
    baseline_ne = {}
    for mach, alt in conditions:
        T_inf, p_inf, _, _ = standard_atmosphere(alt)
        p_stag = stagnation_pressure(p_inf, mach)
        log10_p = math.log10(max(p_stag, 1.0))

        x = torch.tensor([[mach, alt, 0.08, log10_p]], dtype=torch.float32)
        with torch.no_grad():
            y = model.predict_raw(x)
        log10_ne = float(y[0, 6])
        baseline_ne[(mach, alt)] = log10_ne

    # Now test: what if we reduce ne by removing NO+ (simulating R06 removal)?
    # At T < 7000K, NO+ is ~90% of ionization. Removing R06 means ne drops ~10x.
    # We can't directly modulate PlasmaNet (it predicts all species), but we can
    # compare the sensitivity: how much does ne change across conditions?
    results = {
        "baseline_ne": {f"M{m}_A{a}": round(v, 2) for (m, a), v in baseline_ne.items()},
        "detection_boundary": [],
    }

    for mach, alt in conditions:
        ne_log = baseline_ne[(mach, alt)]
        ne = 10 ** ne_log if ne_log > 0 else 0
        fp = plasma_frequency_ghz(ne)
        status = "BLACKOUT" if fp > 12 else "ATTENUATED" if fp > 3 else "DETECT"
        results["detection_boundary"].append({
            "mach": mach, "alt_km": alt, "log10_ne": round(ne_log, 2),
            "fp_GHz": round(fp, 1), "status": status,
        })

    return results


def continuous_training_loop(
    start_data="data/training_data_10k.npz",
    start_model="checkpoints/plasmanet_v4_deep.pt",
    output_dir="checkpoints",
    max_iterations=100,
    points_per_iter=500,
    train_epochs=500,
    patience=80,
):
    """Run continuous training: generate -> train -> evaluate -> repeat."""

    output_dir = Path(output_dir)
    log_path = output_dir / "training_log.json"
    log_entries = []

    # Load current best model
    try:
        model, norm, best_metrics = load_checkpoint(start_model)
        best_ne_mae = best_metrics.get("ne_orders_mae", 999)
        print(f"Starting from {start_model}: ne MAE = {best_ne_mae:.4f} orders")
    except Exception:
        best_ne_mae = 999
        print("No starting model, training from scratch")

    current_data = start_data

    for iteration in range(1, max_iterations + 1):
        iter_start = time.monotonic()
        print(f"\n{'='*60}")
        print(f"  ITERATION {iteration}/{max_iterations}")
        print(f"{'='*60}")

        # Step 1: Active learning — find uncertain regions and acquire data
        print(f"\n  Step 1: Active learning ({points_per_iter} new points)...")
        try:
            model_for_unc, _, _ = load_checkpoint(
                str(output_dir / f"plasmanet_best.pt") if (output_dir / "plasmanet_best.pt").exists()
                else start_model)

            conditions, unc = compute_uncertainty_map(
                model_for_unc, n_probe=5000, n_mc=20,
                seed=42 + iteration * 7)

            print(f"    Top uncertainty: {unc[0]:.4f} orders")
            print(f"    Median: {np.median(unc):.4f}, Mean: {unc.mean():.4f}")

            # Acquire new data at uncertain points
            new_data = acquire_new_data(conditions, n_acquire=points_per_iter, use_cantera=True)
            if new_data is not None:
                merged_path = str(Path(current_data).parent / f"training_iter{iteration}.npz")
                merge_datasets(current_data, new_data, merged_path)
                current_data = merged_path
        except Exception as e:
            print(f"    Active learning failed: {e}")
            # Fall back to generating random new data
            from plasmanet.generate_data import generate_dataset, save_dataset
            print(f"    Generating {points_per_iter} random points instead...")
            ds, _ = generate_dataset(points_per_iter, seed=iteration * 13)
            rand_path = str(Path(current_data).parent / f"training_rand{iteration}.npz")
            save_dataset(ds, rand_path)
            merged_path = str(Path(current_data).parent / f"training_iter{iteration}.npz")
            merge_datasets(current_data, ds, merged_path)
            current_data = merged_path

        # Step 2: Train
        print(f"\n  Step 2: Training (up to {train_epochs} epochs)...")
        splits, new_norm = prepare_data(current_data)
        n_train = splits["train"][0].shape[0]
        print(f"    Training set: {n_train} points")

        # Use v4 architecture (best performer)
        new_model = PlasmaNet(hidden_sizes=(128, 256, 256, 128, 64), dropout=0.03)
        train_model(new_model, splits, new_norm, epochs=train_epochs,
                    lr=5e-4, batch_size=256, patience=patience, verbose=True)

        # Step 3: Evaluate
        print(f"\n  Step 3: Evaluating...")
        metrics = evaluate_model(new_model, splits, new_norm)
        ne_mae = metrics.get("ne_orders_mae", 999)
        ne_max = metrics.get("ne_orders_max", 999)
        status_acc = metrics.get("status_accuracy_pct", 0)

        # Step 4: Save if improved
        improved = ne_mae < best_ne_mae
        if improved:
            best_ne_mae = ne_mae
            new_model.set_normalization(new_norm["x_mean"], new_norm["x_std"],
                                        new_norm["y_mean"], new_norm["y_std"])
            save_checkpoint(new_model, new_norm, metrics,
                          str(output_dir / "plasmanet_best.pt"))
            save_checkpoint(new_model, new_norm, metrics,
                          str(output_dir / f"plasmanet_iter{iteration}.pt"))
            print(f"\n  NEW BEST MODEL: ne MAE = {ne_mae:.4f} orders (was {best_ne_mae:.4f})")
        else:
            print(f"\n  No improvement: {ne_mae:.4f} >= {best_ne_mae:.4f}")

        # Step 5: Run reaction search demo
        print(f"\n  Step 5: Testing Aaron's vision (reaction search with PlasmaNet)...")
        try:
            test_model = new_model if improved else model_for_unc
            test_model.eval()
            search_results = run_reaction_search_with_plasmanet(test_model, new_norm)

            # Print detection boundary
            print(f"\n    Detection Boundary (PlasmaNet):")
            print(f"    {'':>8}", end="")
            for alt in [20, 30, 40, 50]:
                print(f" {alt}km  ", end="")
            print()
            for mach in [5, 8, 10, 12, 15]:
                print(f"    M{mach:>4}", end="")
                for entry in search_results["detection_boundary"]:
                    if entry["mach"] == mach:
                        s = entry["status"][0]
                        print(f"   {s}  ", end="")
                print()
        except Exception as e:
            search_results = {"error": str(e)}
            print(f"    Search failed: {e}")

        # Log
        iter_time = time.monotonic() - iter_start
        entry = {
            "iteration": iteration,
            "n_train": n_train,
            "ne_mae": round(ne_mae, 4),
            "ne_max": round(ne_max, 4),
            "status_acc": round(status_acc, 1),
            "improved": improved,
            "best_ne_mae": round(best_ne_mae, 4),
            "duration_sec": round(iter_time, 1),
        }
        log_entries.append(entry)
        with open(log_path, "w") as f:
            json.dump(log_entries, f, indent=2)

        print(f"\n  Iteration {iteration} complete in {iter_time:.0f}s")
        print(f"  ne MAE: {ne_mae:.4f} | best: {best_ne_mae:.4f} | "
              f"status: {status_acc:.1f}% | data: {n_train}")

    print(f"\n{'='*60}")
    print(f"  TRAINING COMPLETE: {max_iterations} iterations")
    print(f"  Best ne MAE: {best_ne_mae:.4f} orders")
    print(f"{'='*60}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PlasmaNet Continuous Training Loop")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--points-per-iter", type=int, default=500)
    parser.add_argument("--epochs", type=int, default=500)
    args = parser.parse_args()

    continuous_training_loop(
        max_iterations=args.iterations,
        points_per_iter=args.points_per_iter,
        train_epochs=args.epochs,
    )
