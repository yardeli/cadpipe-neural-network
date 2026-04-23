"""PlasmaNet v2 — Geometry-aware model.

Extends the original 4-input model to accept vehicle shape parameters:
  Inputs (6): Mach, altitude_km, nose_radius_m, half_angle_deg, body_length_m, log10(p_stag)
  Outputs (9): T_stag, x_N2, x_O2, x_O, x_N, x_NO, log10(ne), fp_GHz, status

The additional geometry inputs (half_angle_deg, body_length_m) allow the
model to learn how vehicle shape affects the stagnation temperature and
plasma distribution. These inputs only become meaningful when trained on
CFD data from multiple geometries.
"""
import math
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from .model import PlasmaNet as PlasmaNetV1, prepare_data as prepare_data_v1


class PlasmaNetV2(nn.Module):
    """Geometry-aware neural surrogate for hypersonic plasma prediction."""

    INPUT_FEATURES = [
        "mach", "altitude_km", "nose_radius_m",
        "half_angle_deg", "body_length_m", "log10_p_stag",
    ]
    OUTPUT_FEATURES = PlasmaNetV1.OUTPUT_FEATURES  # same outputs

    def __init__(self, hidden_sizes=(128, 256, 256, 128, 64), dropout=0.03):
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
        self._input_mean = None
        self._input_std = None
        self._output_mean = None
        self._output_std = None

    def forward(self, x):
        return self.net(x)

    def set_normalization(self, input_mean, input_std, output_mean, output_std):
        self._input_mean = input_mean
        self._input_std = input_std
        self._output_mean = output_mean
        self._output_std = output_std

    def predict_raw(self, x_raw):
        if self._input_mean is None:
            raise RuntimeError("Normalization not set")
        x_norm = (x_raw - self._input_mean) / self._input_std
        y_norm = self.forward(x_norm)
        return y_norm * self._output_std + self._output_mean


def prepare_cfd_data(dataset_path, test_fraction=0.1, val_fraction=0.1, seed=42):
    """Load CFD-derived dataset with geometry parameters.

    Expected NPZ arrays: mach, altitude_km, nose_radius_m, half_angle_deg,
    body_length_m, p_stag_Pa, T_stag_K, x_N2, x_O2, x_O, x_N, x_NO,
    ne_m3, fp_GHz, status_code
    """
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

    # Build input array (6 features)
    log10_p = np.log10(np.maximum(data["p_stag_Pa"], 1.0))
    half_angle = data.get("half_angle_deg", np.full(n, 15.0))
    body_length = data.get("body_length_m", np.full(n, 1.0))

    X = np.column_stack([
        data["mach"], data["altitude_km"], data["nose_radius_m"],
        half_angle, body_length, log10_p,
    ])

    # Build output array (same as v1)
    ne = data["ne_m3"]
    ne_clamped = np.clip(ne, 1.0, 1e26)
    log10_ne = np.log10(ne_clamped)
    fp = np.clip(data["fp_GHz"], 0.0, 1e6)
    T_stag_clamped = np.clip(data["T_stag_K"], 200.0, 20000.0)

    Y = np.column_stack([
        T_stag_clamped, data["x_N2"], data["x_O2"],
        data["x_O"], data["x_N"], data["x_NO"],
        log10_ne, fp, data["status_code"].astype(np.float64),
    ])

    # Filter outliers
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

    # Normalize
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
                torch.tensor(Y[idx], dtype=torch.float32))

    splits = {"train": to_tensors(train_idx), "val": to_tensors(val_idx),
              "test": to_tensors(test_idx)}
    norm = {"x_mean": torch.tensor(x_mean, dtype=torch.float32),
            "x_std": torch.tensor(x_std, dtype=torch.float32),
            "y_mean": torch.tensor(y_mean, dtype=torch.float32),
            "y_std": torch.tensor(y_std, dtype=torch.float32)}

    return splits, norm


def merge_equilibrium_and_cfd_data(equil_npz_path, cfd_npz_path, output_path):
    """Merge equilibrium training data (from generate_data.py) with
    CFD-derived training data (from extract_cfd_results.py).

    Adds default geometry columns to equilibrium data that doesn't have them.
    """
    equil = np.load(equil_npz_path)
    cfd = np.load(cfd_npz_path)

    n_equil = len(equil["mach"])
    n_cfd = len(cfd["mach"])

    merged = {}
    for key in ["mach", "altitude_km", "nose_radius_m", "T_stag_K", "p_stag_Pa",
                "x_N2", "x_O2", "x_O", "x_N", "x_NO", "ne_m3", "fp_GHz", "status_code"]:
        if key in equil and key in cfd:
            merged[key] = np.concatenate([equil[key], cfd[key]])
        elif key in equil:
            merged[key] = equil[key]

    # Geometry columns — add defaults for equilibrium data
    if "half_angle_deg" in cfd:
        equil_angle = np.full(n_equil, 15.0)  # default cone angle
        merged["half_angle_deg"] = np.concatenate([equil_angle, cfd["half_angle_deg"]])
    else:
        merged["half_angle_deg"] = np.full(n_equil + n_cfd, 15.0)

    if "body_length_m" in cfd:
        equil_length = np.full(n_equil, 1.0)  # default body length
        merged["body_length_m"] = np.concatenate([equil_length, cfd["body_length_m"]])
    else:
        merged["body_length_m"] = np.full(n_equil + n_cfd, 1.0)

    np.savez_compressed(output_path, **merged)
    print(f"Merged: {n_equil} equilibrium + {n_cfd} CFD = {n_equil + n_cfd} total")
    return output_path
