"""PlasmaNet neural surrogate model.

Architecture: 4-layer fully connected network with SiLU activations,
batch normalization, and optional dropout for uncertainty estimation.

Inputs (4): Mach, altitude_km, nose_radius_m, log10(p_stag)
Outputs (9): T_stag, x_N2, x_O2, x_O, x_N, x_NO, log10(ne), fp_GHz, status
"""
import argparse
import math
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn


class PlasmaNet(nn.Module):
    """Neural surrogate for hypersonic plasma prediction."""

    # Input/output feature names for documentation and serving
    INPUT_FEATURES = ["mach", "altitude_km", "nose_radius_m", "log10_p_stag"]
    OUTPUT_FEATURES = [
        "T_stag_K", "x_N2", "x_O2", "x_O", "x_N", "x_NO",
        "log10_ne", "fp_GHz", "status_logit",
    ]

    # Physical bounds for input normalization
    INPUT_BOUNDS = {
        "mach": (3.0, 25.0),
        "altitude_km": (15.0, 60.0),
        "nose_radius_m": (0.01, 1.0),
        "log10_p_stag": (2.0, 8.0),  # 100 Pa to 100 MPa
    }

    def __init__(self, hidden_sizes=(64, 128, 128, 64), dropout=0.05):
        super().__init__()
        n_in = len(self.INPUT_FEATURES)
        n_out = len(self.OUTPUT_FEATURES)

        layers = []
        prev_size = n_in
        for h in hidden_sizes:
            layers.append(nn.Linear(prev_size, h))
            layers.append(nn.BatchNorm1d(h))
            layers.append(nn.SiLU())
            layers.append(nn.Dropout(dropout))
            prev_size = h
        layers.append(nn.Linear(prev_size, n_out))

        self.net = nn.Sequential(*layers)
        self.dropout_rate = dropout

        # Store normalization parameters
        self._input_mean = None
        self._input_std = None
        self._output_mean = None
        self._output_std = None

    def forward(self, x):
        """Forward pass. Input shape: (batch, 4). Output shape: (batch, 9)."""
        return self.net(x)

    def set_normalization(self, input_mean, input_std, output_mean, output_std):
        """Store normalization parameters for inference."""
        self._input_mean = input_mean
        self._input_std = input_std
        self._output_mean = output_mean
        self._output_std = output_std

    def predict_raw(self, x_raw):
        """Predict from un-normalized inputs. Returns un-normalized outputs."""
        if self._input_mean is None:
            raise RuntimeError("Normalization parameters not set. Call set_normalization() first.")

        x_norm = (x_raw - self._input_mean) / self._input_std
        y_norm = self.forward(x_norm)
        y_raw = y_norm * self._output_std + self._output_mean
        return y_raw

    @torch.no_grad()
    def predict_with_uncertainty(self, x_raw, n_samples=50):
        """Monte Carlo dropout for uncertainty estimation.

        Returns (mean_prediction, std_prediction).
        """
        self.train()  # enable dropout
        predictions = []
        for _ in range(n_samples):
            y = self.predict_raw(x_raw)
            predictions.append(y)
        self.eval()

        preds = torch.stack(predictions)
        return preds.mean(dim=0), preds.std(dim=0)


def prepare_data(dataset_path, test_fraction=0.1, val_fraction=0.1, seed=42):
    """Load dataset and prepare train/val/test splits with normalization."""
    data = np.load(dataset_path)
    rng = np.random.default_rng(seed)

    n = len(data["mach"])
    indices = rng.permutation(n)
    n_test = int(n * test_fraction)
    n_val = int(n * val_fraction)
    n_train = n - n_test - n_val

    train_idx = indices[:n_train]
    val_idx = indices[n_train:n_train + n_val]
    test_idx = indices[n_train + n_val:]

    # Build input array: [mach, altitude, nose_radius, log10(p_stag)]
    p_stag = data["p_stag_Pa"]
    log10_p = np.log10(np.maximum(p_stag, 1.0))

    X = np.column_stack([data["mach"], data["altitude_km"],
                         data["nose_radius_m"], log10_p])

    # Build output array: [T_stag, x_N2, x_O2, x_O, x_N, x_NO, log10(ne), fp, status]
    ne = data["ne_m3"]
    # Clamp ne to physically meaningful range [1, 1e26]
    # Below 1 is effectively zero ionization, above 1e26 is beyond full ionization
    ne_clamped = np.clip(ne, 1.0, 1e26)
    log10_ne = np.log10(ne_clamped)

    # Clamp fp to reasonable range
    fp = np.clip(data["fp_GHz"], 0.0, 1e6)

    # Clamp T_stag — above 20000K is beyond mechanism validity
    T_stag_clamped = np.clip(data["T_stag_K"], 200.0, 20000.0)

    Y = np.column_stack([
        T_stag_clamped, data["x_N2"], data["x_O2"],
        data["x_O"], data["x_N"], data["x_NO"],
        log10_ne, fp, data["status_code"].astype(np.float64),
    ])

    # Filter out extreme outliers: remove points where T_stag > 20000
    # or log10_ne > 26 (these are extrapolation artifacts)
    valid_mask = (data["T_stag_K"] <= 20000) & (log10_ne <= 26) & (log10_ne >= 0)
    if valid_mask.sum() < len(valid_mask):
        n_removed = len(valid_mask) - valid_mask.sum()
        print(f"  Filtered {n_removed} outlier points ({n_removed/len(valid_mask)*100:.1f}%)")
        X = X[valid_mask]
        Y = Y[valid_mask]
        n = valid_mask.sum()
        indices = rng.permutation(n)
        n_test = int(n * test_fraction)
        n_val = int(n * val_fraction)
        n_train = n - n_test - n_val
        train_idx = indices[:n_train]
        val_idx = indices[n_train:n_train + n_val]
        test_idx = indices[n_train + n_val:]

    # Normalize using training set statistics
    X_train = X[train_idx]
    Y_train = Y[train_idx]

    x_mean = X_train.mean(axis=0)
    x_std = X_train.std(axis=0)
    x_std = np.where(x_std < 1e-8, 1.0, x_std)

    y_mean = Y_train.mean(axis=0)
    y_std = Y_train.std(axis=0)
    y_std = np.where(y_std < 1e-8, 1.0, y_std)

    X_norm = (X - x_mean) / x_std
    Y_norm = (Y - y_mean) / y_std

    def to_tensors(idx):
        return (torch.tensor(X_norm[idx], dtype=torch.float32),
                torch.tensor(Y_norm[idx], dtype=torch.float32),
                torch.tensor(Y[idx], dtype=torch.float32))  # raw Y for evaluation

    splits = {
        "train": to_tensors(train_idx),
        "val": to_tensors(val_idx),
        "test": to_tensors(test_idx),
    }
    norm = {
        "x_mean": torch.tensor(x_mean, dtype=torch.float32),
        "x_std": torch.tensor(x_std, dtype=torch.float32),
        "y_mean": torch.tensor(y_mean, dtype=torch.float32),
        "y_std": torch.tensor(y_std, dtype=torch.float32),
    }

    return splits, norm


def train_model(model, splits, norm, epochs=500, lr=1e-3, batch_size=128,
                patience=50, verbose=True):
    """Train the model with early stopping on validation loss."""
    X_train, Y_train, _ = splits["train"]
    X_val, Y_val, _ = splits["val"]

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    # Custom loss: MSE on all outputs + extra weight on log10(ne) and status
    def loss_fn(pred, target):
        mse = (pred - target) ** 2
        # Weight log10(ne) (index 6) 5x more — it's the primary output
        weights = torch.ones(pred.shape[1])
        weights[0] = 2.0   # T_stag
        weights[6] = 5.0   # log10(ne) — most critical
        weights[7] = 2.0   # fp
        weights[8] = 2.0   # status classification
        return (mse * weights).mean()

    best_val_loss = float("inf")
    best_state = None
    wait = 0
    history = {"train_loss": [], "val_loss": []}

    t0 = time.monotonic()
    for epoch in range(epochs):
        model.train()
        # Mini-batch training
        n = X_train.shape[0]
        perm = torch.randperm(n)
        epoch_loss = 0.0
        n_batches = 0

        for start in range(0, n, batch_size):
            end = min(start + batch_size, n)
            idx = perm[start:end]
            x_batch = X_train[idx]
            y_batch = Y_train[idx]

            pred = model(x_batch)
            loss = loss_fn(pred, y_batch)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            epoch_loss += loss.item()
            n_batches += 1

        scheduler.step()
        avg_train_loss = epoch_loss / n_batches

        # Validation
        model.eval()
        with torch.no_grad():
            val_pred = model(X_val)
            val_loss = loss_fn(val_pred, Y_val).item()

        history["train_loss"].append(avg_train_loss)
        history["val_loss"].append(val_loss)

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
            wait = 0
        else:
            wait += 1

        if verbose and (epoch + 1) % 50 == 0:
            elapsed = time.monotonic() - t0
            print(f"  Epoch {epoch+1:>4}/{epochs} | train={avg_train_loss:.6f} "
                  f"val={val_loss:.6f} | best={best_val_loss:.6f} | "
                  f"{elapsed:.0f}s | lr={scheduler.get_last_lr()[0]:.2e}")

        if wait >= patience:
            if verbose:
                print(f"  Early stopping at epoch {epoch+1} (patience={patience})")
            break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)

    # Store normalization
    model.set_normalization(norm["x_mean"], norm["x_std"],
                           norm["y_mean"], norm["y_std"])

    return history


def evaluate_model(model, splits, norm, verbose=True):
    """Evaluate model on test set. Returns metrics dict."""
    _, _, Y_test_raw = splits["test"]
    X_test_norm, _, _ = splits["test"]

    model.eval()
    with torch.no_grad():
        Y_pred_norm = model(X_test_norm)
        Y_pred_raw = Y_pred_norm * norm["y_std"] + norm["y_mean"]

    Y_true = Y_test_raw.numpy()
    Y_pred = Y_pred_raw.numpy()

    metrics = {}
    for i, name in enumerate(PlasmaNet.OUTPUT_FEATURES):
        true = Y_true[:, i]
        pred = Y_pred[:, i]

        # MAE
        mae = np.abs(true - pred).mean()
        # Relative error (where true > 0)
        mask = np.abs(true) > 1e-6
        if mask.sum() > 0:
            rel_err = np.abs((true[mask] - pred[mask]) / true[mask]).mean() * 100
        else:
            rel_err = 0.0

        metrics[name] = {"mae": float(mae), "rel_err_pct": float(rel_err)}

        if verbose:
            print(f"  {name:>15}: MAE={mae:.4f}, RelErr={rel_err:.2f}%")

    # Special metric: ne accuracy (the most important output)
    ne_true = Y_true[:, 6]  # log10(ne)
    ne_pred = Y_pred[:, 6]
    ne_mae_orders = np.abs(ne_true - ne_pred).mean()
    ne_max_err = np.abs(ne_true - ne_pred).max()
    metrics["ne_orders_mae"] = float(ne_mae_orders)
    metrics["ne_orders_max"] = float(ne_max_err)

    # Status classification accuracy
    status_true = np.round(Y_true[:, 8]).astype(int).clip(0, 2)
    status_pred = np.round(Y_pred[:, 8]).astype(int).clip(0, 2)
    accuracy = (status_true == status_pred).mean() * 100
    metrics["status_accuracy_pct"] = float(accuracy)

    if verbose:
        print(f"\n  ne prediction: MAE={ne_mae_orders:.3f} orders, max={ne_max_err:.3f} orders")
        print(f"  Status classification: {accuracy:.1f}% accuracy")

    return metrics


def save_checkpoint(model, norm, metrics, path):
    """Save model checkpoint with normalization and metrics."""
    # Extract hidden sizes from the model architecture
    hidden_sizes = []
    for module in model.net:
        if isinstance(module, nn.Linear) and module.out_features != len(PlasmaNet.OUTPUT_FEATURES):
            hidden_sizes.append(module.out_features)
    checkpoint = {
        "model_state": model.state_dict(),
        "norm": {k: v.numpy().tolist() for k, v in norm.items()},
        "metrics": metrics,
        "hidden_sizes": hidden_sizes,
        "dropout": model.dropout_rate,
        "input_features": PlasmaNet.INPUT_FEATURES,
        "output_features": PlasmaNet.OUTPUT_FEATURES,
        "version": "1.1",
    }
    torch.save(checkpoint, path)
    size_kb = Path(path).stat().st_size / 1024
    print(f"Saved checkpoint to {path} ({size_kb:.0f} KB)")


def load_checkpoint(path, device="cpu"):
    """Load model from checkpoint."""
    checkpoint = torch.load(path, map_location=device, weights_only=False)
    hidden_sizes = tuple(checkpoint.get("hidden_sizes", (64, 128, 128, 64)))
    dropout = checkpoint.get("dropout", 0.05)
    model = PlasmaNet(hidden_sizes=hidden_sizes, dropout=dropout)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    norm = {}
    for k, v in checkpoint["norm"].items():
        norm[k] = torch.tensor(v, dtype=torch.float32)
    model.set_normalization(norm["x_mean"], norm["x_std"],
                           norm["y_mean"], norm["y_std"])

    return model, norm, checkpoint.get("metrics", {})


def main():
    parser = argparse.ArgumentParser(description="Train PlasmaNet")
    parser.add_argument("--data", type=str, default="data/training_data.npz")
    parser.add_argument("--output", type=str, default="checkpoints/plasmanet_v1.pt")
    parser.add_argument("--epochs", type=int, default=500)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--patience", type=int, default=50)
    args = parser.parse_args()

    print(f"Loading data from {args.data}...")
    splits, norm = prepare_data(args.data)
    n_train = splits["train"][0].shape[0]
    n_val = splits["val"][0].shape[0]
    n_test = splits["test"][0].shape[0]
    print(f"  Train: {n_train}, Val: {n_val}, Test: {n_test}")

    model = PlasmaNet()
    n_params = sum(p.numel() for p in model.parameters())
    print(f"  Model: {n_params:,} parameters")

    print(f"\nTraining for up to {args.epochs} epochs...")
    history = train_model(model, splits, norm, epochs=args.epochs,
                          lr=args.lr, batch_size=args.batch_size,
                          patience=args.patience)

    print(f"\nEvaluating on test set ({n_test} points):")
    metrics = evaluate_model(model, splits, norm)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_checkpoint(model, norm, metrics, str(out_path))

    print("\nDone.")


if __name__ == "__main__":
    main()
