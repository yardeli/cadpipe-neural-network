"""Training data generation for PlasmaNet.

Generates a Latin Hypercube sample across (Mach, altitude, nose_radius) and
computes full plasma analysis at each point using Cantera (or JANAF fallback).
"""
import argparse
import json
import math
import time
from pathlib import Path

import numpy as np

from .physics import full_analysis, standard_atmosphere


def latin_hypercube(n, d, rng=None):
    """Generate n points in d dimensions using Latin Hypercube Sampling.

    Returns array of shape (n, d) with values in [0, 1].
    """
    if rng is None:
        rng = np.random.default_rng(42)
    result = np.zeros((n, d))
    for j in range(d):
        perm = rng.permutation(n)
        for i in range(n):
            result[perm[i], j] = (i + rng.uniform()) / n
    return result


def generate_conditions(n_points, mach_range=(3, 20), alt_range=(15, 55),
                        nose_r_range=(0.01, 1.0), seed=42):
    """Generate flight conditions via Latin Hypercube Sampling.

    Mach and nose_radius use log-uniform sampling for better coverage
    at lower values where physics changes rapidly.
    """
    rng = np.random.default_rng(seed)
    lhs = latin_hypercube(n_points, 3, rng)

    # Mach: log-uniform in [mach_min, mach_max]
    log_mach_min = math.log(mach_range[0])
    log_mach_max = math.log(mach_range[1])
    machs = np.exp(log_mach_min + lhs[:, 0] * (log_mach_max - log_mach_min))

    # Altitude: uniform in [alt_min, alt_max]
    alts = alt_range[0] + lhs[:, 1] * (alt_range[1] - alt_range[0])

    # Nose radius: log-uniform in [r_min, r_max]
    log_r_min = math.log(nose_r_range[0])
    log_r_max = math.log(nose_r_range[1])
    nose_rs = np.exp(log_r_min + lhs[:, 2] * (log_r_max - log_r_min))

    return machs, alts, nose_rs


def generate_dataset(n_points=2000, use_cantera=True, use_neq=False, seed=42, verbose=True):
    """Generate the full training dataset.

    Returns dict of numpy arrays ready for model training.
    """
    machs, alts, nose_rs = generate_conditions(n_points, seed=seed)

    # Pre-allocate output arrays
    T_stag = np.zeros(n_points)
    x_N2 = np.zeros(n_points)
    x_O2 = np.zeros(n_points)
    x_O = np.zeros(n_points)
    x_N = np.zeros(n_points)
    x_NO = np.zeros(n_points)
    ne = np.zeros(n_points)
    fp = np.zeros(n_points)
    p_stag = np.zeros(n_points)
    status_codes = np.zeros(n_points, dtype=np.int32)  # 0=DETECT, 1=ATTEN, 2=BLACKOUT

    status_map = {"DETECTABLE": 0, "ATTENUATED": 1, "BLACKOUT": 2}
    sources = []
    errors = []
    t0 = time.monotonic()

    for i in range(n_points):
        try:
            result = full_analysis(
                float(machs[i]), float(alts[i]), float(nose_rs[i]),
                use_cantera=use_cantera, use_neq=use_neq)

            T_stag[i] = result["T_stag_K"]
            x_N2[i] = result["x_N2"]
            x_O2[i] = result["x_O2"]
            x_O[i] = result["x_O"]
            x_N[i] = result["x_N"]
            x_NO[i] = result["x_NO"]
            ne[i] = result["ne_m3"]
            fp[i] = result["fp_GHz"]
            p_stag[i] = result["p_stag_Pa"]
            status_codes[i] = status_map.get(result["status"], 0)
            sources.append(result["source"])
        except Exception as e:
            errors.append((i, float(machs[i]), float(alts[i]), str(e)))
            sources.append("error")

        if verbose and (i + 1) % 100 == 0:
            elapsed = time.monotonic() - t0
            rate = (i + 1) / elapsed
            eta = (n_points - i - 1) / rate
            print(f"  [{i+1}/{n_points}] {rate:.0f} pts/sec, ETA {eta:.0f}s "
                  f"| M={machs[i]:.1f} alt={alts[i]:.0f}km "
                  f"T={T_stag[i]:.0f}K ne={ne[i]:.2e}")

    elapsed = time.monotonic() - t0
    if verbose:
        print(f"\nGenerated {n_points} points in {elapsed:.1f}s ({n_points/elapsed:.0f} pts/sec)")
        if errors:
            print(f"  {len(errors)} errors (see errors list)")
        src_counts = {}
        for s in sources:
            src_counts[s] = src_counts.get(s, 0) + 1
        print(f"  Sources: {src_counts}")

        # Summary stats
        ne_nonzero = ne[ne > 0]
        print(f"  T_stag range: {T_stag.min():.0f} - {T_stag.max():.0f} K")
        if len(ne_nonzero) > 0:
            print(f"  ne range: {ne_nonzero.min():.2e} - {ne_nonzero.max():.2e} m^-3")
        print(f"  Blackout fraction: {(status_codes == 2).sum() / n_points:.1%}")

    dataset = {
        # Inputs
        "mach": machs,
        "altitude_km": alts,
        "nose_radius_m": nose_rs,
        "p_stag_Pa": p_stag,
        # Outputs
        "T_stag_K": T_stag,
        "x_N2": x_N2,
        "x_O2": x_O2,
        "x_O": x_O,
        "x_N": x_N,
        "x_NO": x_NO,
        "ne_m3": ne,
        "fp_GHz": fp,
        "status_code": status_codes,
    }

    return dataset, errors


def save_dataset(dataset, path, errors=None):
    """Save dataset as .npz file."""
    np.savez_compressed(path, **dataset)
    print(f"Saved dataset to {path} ({Path(path).stat().st_size / 1024:.0f} KB)")

    if errors:
        err_path = Path(path).with_suffix(".errors.json")
        with open(err_path, "w") as f:
            json.dump([{"idx": e[0], "mach": e[1], "alt": e[2], "error": e[3]}
                       for e in errors], f, indent=2)
        print(f"Saved {len(errors)} errors to {err_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate PlasmaNet training data")
    parser.add_argument("--n-points", type=int, default=2000)
    parser.add_argument("--output", type=str, default="data/training_data.npz")
    parser.add_argument("--no-cantera", action="store_true",
                        help="Use JANAF fallback instead of Cantera")
    parser.add_argument("--neq", action="store_true",
                        help="Apply non-equilibrium correction (default: off for clean data)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    print(f"Generating {args.n_points} training points...")
    print(f"  Cantera: {'disabled' if args.no_cantera else 'enabled (preferred)'}")
    print(f"  NEQ correction: {'enabled' if args.neq else 'disabled (clean equilibrium data)'}")

    dataset, errors = generate_dataset(
        n_points=args.n_points,
        use_cantera=not args.no_cantera,
        use_neq=args.neq,
        seed=args.seed)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_dataset(dataset, str(out_path), errors)


if __name__ == "__main__":
    main()
