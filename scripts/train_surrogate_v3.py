"""S-3 v3 — train MechanismSurrogate on the 100K JSONL dataset.

Improvements over v2 trainer:
* Loads training_data_v2.jsonl (target: 100K examples)
* Mini-batch size 128 (was 32)
* Cosine learning rate schedule
* Early stopping on val plateau
* Train/val/test 70/15/15 split (not just 80/20)
* Reports both MSE (log10²) and median absolute error in m^-3 / Cantera

Run on VM:
    cd /home/yarden/plasmanet && PYTHONPATH=. python3 scripts/train_surrogate_v3.py
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np


def main():
    from plasmanet.mechanism_search import (
        PARK_47,
        BENCHMARKS,
        TrainingExample,
        HAVE_TORCH,
        MechanismFingerprint,
        MechanismSurrogate,
        freestream_features,
        park_air5,
        park_air7,
        park_air11,
        score_candidate,
    )

    if not HAVE_TORCH:
        print("PyTorch not installed.")
        return 1

    import torch
    import torch.nn as nn

    JSONL = Path("/home/yarden/mechanism_search_results/training_data_v2.jsonl")
    if not JSONL.exists():
        print(f"Dataset not found at {JSONL}. Run "
              f"collect_surrogate_training_data_v2.py first.")
        return 1

    # ── Load + filter
    examples = []
    skipped = 0
    with open(JSONL) as f:
        for line in f:
            r = json.loads(line)
            ne = r.get("ne_m3", 0.0)
            if ne <= 1e10 or ne > 1e25:
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

    if len(examples) < 100:
        print(f"Only {len(examples)} examples — too few.")
        return 1

    print(f"Loaded {len(examples)} examples ({skipped} skipped for outliers)")
    ne_values = [ex.ne_target_m3 for ex in examples]
    log10_ne = np.log10(np.array(ne_values))
    print(f"  log10 ne: mean {log10_ne.mean():.2f}, "
          f"std {log10_ne.std():.2f}, "
          f"range {log10_ne.min():.1f} .. {log10_ne.max():.1f}")
    print()

    # ── Build (X, y) arrays
    X_list = []
    y_list = []
    for ex in examples:
        fp = MechanismFingerprint(ex.mechanism, base=PARK_47).to_array()
        fs = freestream_features(ex.altitude_km, ex.mach,
                                  T_inf=ex.T_inf, P_inf=ex.P_inf)
        X_list.append(np.concatenate([fs, fp]))
        y_list.append(np.log10(max(ex.ne_target_m3, 1e10)))
    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.float32)

    # 70/15/15 split
    rng = np.random.default_rng(42)
    idx = rng.permutation(len(X))
    n = len(X)
    n_train = int(0.70 * n)
    n_val = int(0.15 * n)
    train_idx = idx[:n_train]
    val_idx = idx[n_train:n_train + n_val]
    test_idx = idx[n_train + n_val:]
    print(f"  train/val/test = {n_train}/{n_val}/{len(test_idx)}")
    print()

    Xt = torch.from_numpy(X[train_idx]).float()
    yt = torch.from_numpy(y[train_idx]).float()
    Xv = torch.from_numpy(X[val_idx]).float()
    yv = torch.from_numpy(y[val_idx]).float()
    Xs = torch.from_numpy(X[test_idx]).float()
    ys = torch.from_numpy(y[test_idx]).float()

    model = MechanismSurrogate(
        freestream_dim=4, mechanism_dim=PARK_47.n_reactions,
        hidden_dim=256, n_layers=4
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3,
                                    weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=300, eta_min=1e-5
    )
    loss_fn = nn.MSELoss()
    batch_size = 128

    save_path = Path("/home/yarden/mechanism_search_results/surrogate_v3.pt")
    save_path.parent.mkdir(parents=True, exist_ok=True)

    best_val = float("inf")
    patience = 20
    bad_epochs = 0
    t0 = time.time()

    print("=" * 70)
    print(f"Training MechanismSurrogate v3 (256 hidden, 4 layers, batch={batch_size})")
    print("=" * 70)
    for epoch in range(300):
        model.train()
        perm = torch.randperm(len(Xt))
        total = 0.0
        for i in range(0, len(Xt), batch_size):
            b = perm[i: i + batch_size]
            optimizer.zero_grad()
            pred = model(Xt[b])
            loss = loss_fn(pred, yt[b])
            loss.backward()
            optimizer.step()
            total += loss.item() * len(b)
        train_loss = total / len(Xt)
        scheduler.step()

        model.eval()
        with torch.no_grad():
            val_pred = model(Xv)
            val_loss = loss_fn(val_pred, yv).item()

        if val_loss < best_val:
            best_val = val_loss
            torch.save(model.state_dict(), save_path)
            bad_epochs = 0
        else:
            bad_epochs += 1
            if bad_epochs >= patience:
                print(f"  Early stopping at epoch {epoch}")
                break

        if epoch % 10 == 0 or epoch == 299:
            print(f"  epoch {epoch:3d}: train MSE={train_loss:.3f}, "
                  f"val MSE={val_loss:.3f}, lr={optimizer.param_groups[0]['lr']:.2e}")

    print(f"\nBest val MSE (log10²): {best_val:.4f}")
    print(f"  → typical prediction error: ±{best_val**0.5:.2f} log10")
    dt = time.time() - t0
    print(f"  Trained in {dt:.1f}s")

    # ── Test on held-out set
    model.load_state_dict(torch.load(save_path))
    model.eval()
    with torch.no_grad():
        test_pred = model(Xs)
    test_mse = ((test_pred - ys) ** 2).mean().item()
    test_mae = (test_pred - ys).abs().mean().item()
    print(f"\nTest set ({len(ys)} examples):")
    print(f"  MSE (log10²): {test_mse:.4f}")
    print(f"  MAE (log10):  {test_mae:.3f}")
    print(f"  → median prediction within factor of {10**test_mae:.2f} of truth")

    # ── Reference mechanism comparison
    print()
    print("=" * 70)
    print("Surrogate vs Cantera 0D ground-truth (1us residence)")
    print("=" * 70)
    bk = BENCHMARKS["ram_c_61km_M22.5"]
    fs = freestream_features(bk.altitude_km, bk.mach,
                              T_inf=bk.temperature_k, P_inf=bk.pressure_pa)
    for mech in [park_air5(), park_air7(), park_air11()]:
        truth = score_candidate(
            mechanism_name=mech.name, evaluator="cantera_0d",
            evaluator_input={"mechanism": mech, "residence_time_s": 1e-6},
            benchmark="ram_c_61km_M22.5",
        ).per_benchmark[0].ne_predicted_m3
        fp = MechanismFingerprint(mech, base=PARK_47).to_array()
        pred = model.predict_ne_m3(fs, fp)
        if truth > 0:
            log10_diff = math.log10(pred / truth)
            print(f"  {mech.name:20s}  truth={truth:.2e}, pred={pred:.2e}, "
                  f"diff={log10_diff:+.2f} log10")
        else:
            print(f"  {mech.name:20s}  truth=0 (no ions in mech), pred={pred:.2e}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
