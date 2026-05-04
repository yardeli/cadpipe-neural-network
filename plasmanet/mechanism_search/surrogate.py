"""S-3 — PlasmaNet surrogate retrained on the mechanism axis.

Replaces Cantera 0D as the fast evaluator inside the search loop. PlasmaNet
inference is ~0.01 ms/sample vs Cantera's ~4 ms/sample, plus PlasmaNet runs
on GPU and batches naturally — enables searching millions of candidates
where Cantera 0D would take days.

Why retrain (vs use existing PlasmaNet)?
  Existing PlasmaNet at plasmanet/model.py was trained on (freestream
  conditions) → (ne field), using a single fixed equilibrium chemistry
  mechanism. It cannot distinguish two different mechanisms — the
  mechanism is baked in.

  The surrogate built here adds a "mechanism fingerprint" input vector
  (one bit per reaction in PARK_47 indicating inclusion). Output is the
  same ne field, but conditioned on which reactions are active.

Architecture:
    inputs:  freestream (T, P, M, alt) [4]
           + mechanism fingerprint (47 bits → 47 floats {0, 1}) [47]
           = 51-dim input vector
    backbone: 4 hidden layers, SiLU, BatchNorm (~50K params, similar
              to the existing equilibrium PlasmaNet)
    outputs: ne_peak [scalar], or full ne profile along reflectometer
             stations [N_stations]

Training data comes from S-2 (Cantera 0D evaluations) and S-5 (full CFD
validations of top-K). Each training sample is one (mechanism, condition,
ne_predicted) triple.

This file scaffolds the architecture. Training loop is in the calling
script (e.g., scripts/train_surrogate.py) — kept decoupled because
training requires data collection first.

Usage:
    from plasmanet.mechanism_search.surrogate import (
        MechanismFingerprint, MechanismSurrogate, train_surrogate
    )

    fp = MechanismFingerprint(park_air7(), base=PARK_47)
    print(fp.to_array())   # 47-d numpy bitstring
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

# Optional torch — module imports fine without it; runtime calls error.
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAVE_TORCH = True
except ImportError:
    HAVE_TORCH = False
    torch = None
    nn = type("nn", (), {"Module": object})  # placeholder

from .generator import Mechanism, PARK_47


# ──────────────────────────────────────────────────────────────────────────────
# Mechanism fingerprint — bitstring encoding for ML input
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MechanismFingerprint:
    """Encodes a mechanism as a fixed-length bitvector for ML consumption.

    The vector length equals the number of reactions in the BASE mechanism
    (typically PARK_47 → 47-dim). Each bit indicates whether that reaction
    is in the candidate. Standard for discrete-set ML inputs.
    """
    mechanism: Mechanism
    base: Mechanism = None    # default: PARK_47 ; set in __post_init__

    def __post_init__(self):
        if self.base is None:
            self.base = PARK_47

    def to_array(self) -> np.ndarray:
        """Return a (n_reactions,) numpy array of {0, 1} floats."""
        candidate_ids = {r.rxn_id for r in self.mechanism.reactions}
        return np.array(
            [1.0 if r.rxn_id in candidate_ids else 0.0
             for r in self.base.reactions],
            dtype=np.float32,
        )

    @property
    def vector_length(self) -> int:
        return self.base.n_reactions


def freestream_features(altitude_km: float, mach: float, T_inf: float = None,
                          P_inf: float = None) -> np.ndarray:
    """Return a 4-d freestream-condition vector (alt, mach, T, P).

    Used as the (non-mechanism) part of the surrogate's input.
    Default T_inf, P_inf use the U.S. Standard Atmosphere if unspecified.
    """
    if T_inf is None:
        T_inf = _us_standard_atmosphere_T(altitude_km)
    if P_inf is None:
        P_inf = _us_standard_atmosphere_P(altitude_km)
    # Normalize for ML input (rough scaling)
    return np.array([
        altitude_km / 100.0,    # 0..1 for 0-100km
        mach / 30.0,             # 0..1 for 0-30
        T_inf / 300.0,           # 0..1 for 0-300K freestream
        np.log10(max(P_inf, 1.0)) / 5.0,   # log-scaled
    ], dtype=np.float32)


def _us_standard_atmosphere_T(altitude_km: float) -> float:
    """Crude US Standard Atmosphere 1976 temperature (K)."""
    if altitude_km <= 11.0:
        return 288.15 - 6.5 * altitude_km
    elif altitude_km <= 20.0:
        return 216.65
    elif altitude_km <= 32.0:
        return 216.65 + 1.0 * (altitude_km - 20.0)
    elif altitude_km <= 47.0:
        return 228.65 + 2.8 * (altitude_km - 32.0)
    elif altitude_km <= 51.0:
        return 270.65
    elif altitude_km <= 71.0:
        return 270.65 - 2.8 * (altitude_km - 51.0)
    else:
        return max(214.65 - 2.0 * (altitude_km - 71.0), 180.0)


def _us_standard_atmosphere_P(altitude_km: float) -> float:
    """Crude US Standard Atmosphere 1976 pressure (Pa) via exp scaling."""
    h_scale = 8.5  # km
    return 101325.0 * np.exp(-altitude_km / h_scale)


# ──────────────────────────────────────────────────────────────────────────────
# Surrogate model architecture
# ──────────────────────────────────────────────────────────────────────────────

class MechanismSurrogate(nn.Module):
    """Neural network surrogate predicting ne_peak from
    (freestream conditions, mechanism fingerprint).

    Default architecture matches v4: 4 hidden layers × 512 units (819K
    params), SiLU + BatchNorm, output = scalar log10(ne_peak in m^-3).
    v3 weights load with the same arch but require hidden_dim=256.
    """

    def __init__(self, freestream_dim: int = 4, mechanism_dim: int = 47,
                  hidden_dim: int = 512, n_layers: int = 4):
        if not HAVE_TORCH:
            raise RuntimeError(
                "MechanismSurrogate requires PyTorch. "
                "Install via: pip install torch"
            )
        super().__init__()
        input_dim = freestream_dim + mechanism_dim
        layers = []
        prev_dim = input_dim
        for i in range(n_layers):
            layers.extend([
                nn.Linear(prev_dim, hidden_dim),
                nn.BatchNorm1d(hidden_dim),
                nn.SiLU(),
            ])
            prev_dim = hidden_dim
        layers.append(nn.Linear(hidden_dim, 1))   # log10(ne_peak)
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        """x: (batch, freestream_dim + mechanism_dim) → (batch,) log10(ne)."""
        return self.net(x).squeeze(-1)

    def predict_ne_m3(self, freestream: np.ndarray,
                       fingerprint: np.ndarray) -> float:
        """Single-sample inference: returns ne in m^-3 (not log10)."""
        self.eval()
        x = np.concatenate([freestream, fingerprint])
        x_t = torch.from_numpy(x).float().unsqueeze(0)
        with torch.no_grad():
            log10_ne = self.net(x_t).squeeze().item()
        return 10 ** log10_ne


# ──────────────────────────────────────────────────────────────────────────────
# Training data assembly + training loop
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TrainingExample:
    """One (mechanism, conditions) → ne_peak training point."""
    mechanism: Mechanism
    altitude_km: float
    mach: float
    T_inf: float
    P_inf: float
    ne_target_m3: float
    source: str = "cantera_0d"   # 'cantera_0d', 'cfd_su2nemo', 'plasmanet_v1'


def assemble_training_arrays(
    examples: list[TrainingExample],
    base: Mechanism = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert a list of TrainingExample to (X, y) arrays for fit.

    Args:
        examples: training examples
        base: base mechanism for fingerprinting (default: PARK_47)

    Returns:
        X: (N, 4 + base.n_reactions) input array
        y: (N,) target log10(ne) array
    """
    base = base or PARK_47
    X_rows = []
    y_rows = []
    for ex in examples:
        fp = MechanismFingerprint(ex.mechanism, base=base).to_array()
        fs = freestream_features(ex.altitude_km, ex.mach,
                                  T_inf=ex.T_inf, P_inf=ex.P_inf)
        X_rows.append(np.concatenate([fs, fp]))
        y_rows.append(np.log10(max(ex.ne_target_m3, 1.0)))
    return np.array(X_rows, dtype=np.float32), np.array(y_rows, dtype=np.float32)


def train_surrogate(
    examples: list[TrainingExample],
    n_epochs: int = 200,
    batch_size: int = 32,
    lr: float = 1e-3,
    val_frac: float = 0.2,
    seed: int = 42,
    save_path: Optional[Path] = None,
) -> tuple["MechanismSurrogate", dict]:
    """Train the surrogate on a list of (mechanism, conditions) → ne examples.

    Returns the trained model + a metrics dict (train/val loss curves,
    final MAE, etc.). Saves to disk if save_path is provided.
    """
    if not HAVE_TORCH:
        raise RuntimeError("PyTorch required for training.")

    if len(examples) < 10:
        raise ValueError(
            f"Need at least 10 training examples, got {len(examples)}. "
            f"Run more Cantera 0D / CFD evaluations first via "
            f"plasmanet.mechanism_search.search_loop or compute pool."
        )

    X, y = assemble_training_arrays(examples)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(X))
    n_val = int(val_frac * len(X))
    val_idx, train_idx = idx[:n_val], idx[n_val:]

    X_train = torch.from_numpy(X[train_idx]).float()
    y_train = torch.from_numpy(y[train_idx]).float()
    X_val = torch.from_numpy(X[val_idx]).float()
    y_val = torch.from_numpy(y[val_idx]).float()

    model = MechanismSurrogate(
        freestream_dim=4, mechanism_dim=PARK_47.n_reactions
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr,
                                    weight_decay=1e-4)
    loss_fn = nn.MSELoss()

    history = {"train_loss": [], "val_loss": []}
    best_val = float("inf")

    for epoch in range(n_epochs):
        # Mini-batch training
        model.train()
        perm = torch.randperm(len(X_train))
        total = 0.0
        for i in range(0, len(X_train), batch_size):
            b = perm[i: i + batch_size]
            optimizer.zero_grad()
            pred = model(X_train[b])
            loss = loss_fn(pred, y_train[b])
            loss.backward()
            optimizer.step()
            total += loss.item() * len(b)
        train_loss = total / len(X_train)

        # Validation
        model.eval()
        with torch.no_grad():
            val_pred = model(X_val) if len(X_val) > 0 else None
            val_loss = (loss_fn(val_pred, y_val).item()
                        if val_pred is not None else 0.0)

        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)

        if val_loss < best_val:
            best_val = val_loss
            if save_path is not None:
                torch.save(model.state_dict(), save_path)

        if epoch % 20 == 0 or epoch == n_epochs - 1:
            print(f"  epoch {epoch:3d}: train MSE = {train_loss:.4f}, "
                  f"val MSE = {val_loss:.4f}")

    return model, {**history, "best_val_mse": best_val}


# ──────────────────────────────────────────────────────────────────────────────
# Evaluator backend — wires surrogate into the scoring framework
# ──────────────────────────────────────────────────────────────────────────────

def register_surrogate_evaluator(model: MechanismSurrogate, name: str = "plasmanet_v4"):
    """Wire a trained surrogate into the scoring framework as an evaluator.

    After this, search_loop can use evaluator='plasmanet_v4' (or whichever
    name) and get inference-speed (sub-ms) evaluations.

    Default name bumped 2026-04-26 to match v4 weights (factor-of-1.52
    accuracy, 819K params, 4-layer 512-hidden). v3 weights load with the
    same arch but require hidden_dim=256 instead of 512.
    """
    if not HAVE_TORCH:
        raise RuntimeError("PyTorch required for surrogate inference.")

    from .scoring import register_evaluator

    def _surrogate_evaluator(input_data: dict, benchmark) -> dict:
        mech = input_data.get("mechanism")
        if mech is None:
            return {"ne_m3": 0.0, "db_by_freq_hz": {}}

        fp = MechanismFingerprint(mech, base=PARK_47).to_array()
        fs = freestream_features(
            benchmark.altitude_km, benchmark.mach,
            T_inf=benchmark.temperature_k, P_inf=benchmark.pressure_pa,
        )
        ne = model.predict_ne_m3(fs, fp)
        # Surrogate doesn't predict dB directly — use Saha-like estimate
        # from ne and a sheath path length from benchmark.vehicle.
        import math
        f_p = 8980 * math.sqrt(max(ne * 1e-6, 0))
        db = {}
        sheath_path = benchmark.vehicle.estimate_sheath_path_length(
            0.5 * benchmark.vehicle.body_length_m
        )
        for f_hz in benchmark.detection_status_by_freq_hz:
            if f_hz > f_p:
                # propagate, light attenuation
                db[f_hz] = 0.05 * sheath_path  # rough; surrogate would do better
            else:
                db[f_hz] = 100.0
        return {"ne_m3": ne, "db_by_freq_hz": db, "f_plasma_hz": f_p}

    register_evaluator(name, _surrogate_evaluator)


if __name__ == "__main__":
    import sys
    from .generator import park_air5, park_air7

    print("MechanismSurrogate scaffolding loaded.")
    print()

    # Demonstrate fingerprint encoding
    fp_air5 = MechanismFingerprint(park_air5())
    fp_air7 = MechanismFingerprint(park_air7())
    fp_park47 = MechanismFingerprint(PARK_47)
    print(f"Fingerprint vector length: {fp_air5.vector_length}")
    print(f"  Park_AIR5  has {int(fp_air5.to_array().sum())} active reactions")
    print(f"  Park_AIR7  has {int(fp_air7.to_array().sum())} active reactions")
    print(f"  Park_47    has {int(fp_park47.to_array().sum())} active reactions")
    print()

    if HAVE_TORCH:
        print("PyTorch available. Surrogate model can be trained.")
        # Minimal smoke test: instantiate model, run forward pass on random input
        m = MechanismSurrogate(freestream_dim=4,
                                mechanism_dim=PARK_47.n_reactions)
        x = torch.randn(2, 4 + PARK_47.n_reactions)
        with torch.no_grad():
            y = m(x)
        print(f"  Forward pass: input {x.shape} → output {y.shape} "
              f"(values: {y.tolist()})")
    else:
        print("PyTorch not installed. Install via `pip install torch` to "
              "actually train and use the surrogate.")
