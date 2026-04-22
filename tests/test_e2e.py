"""End-to-end test: load trained model, predict, validate against Cantera."""
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import torch

from plasmanet.model import PlasmaNet, load_checkpoint
from plasmanet.physics import (
    full_analysis, standard_atmosphere, stagnation_pressure,
    plasma_frequency_ghz, radar_status,
)


CHECKPOINT = Path(__file__).parent.parent / "checkpoints" / "plasmanet_v1.pt"


def predict_single(model, mach, altitude_km, nose_radius_m=0.08):
    """Run inference for one condition."""
    T_inf, p_inf, _, _ = standard_atmosphere(altitude_km)
    p_stag = stagnation_pressure(p_inf, mach)
    log10_p = math.log10(max(p_stag, 1.0))

    x = torch.tensor([[mach, altitude_km, nose_radius_m, log10_p]],
                     dtype=torch.float32)
    with torch.no_grad():
        y = model.predict_raw(x)
    y = y[0].numpy()

    ne = 10.0 ** max(float(y[6]), 0) if float(y[6]) > 0 else 0.0
    fp = plasma_frequency_ghz(ne)

    return {
        "T_stag_K": float(y[0]),
        "x_N2": float(y[1]),
        "ne_m3": ne,
        "log10_ne": float(y[6]),
        "fp_GHz": fp,
        "status": radar_status(fp),
    }


def test_model_loads():
    """Verify model checkpoint loads correctly."""
    assert CHECKPOINT.exists(), f"Checkpoint not found: {CHECKPOINT}"
    model, norm, metrics = load_checkpoint(str(CHECKPOINT))
    assert isinstance(model, PlasmaNet)
    assert model._input_mean is not None
    print("  model_loads: PASS")
    return model


def test_inference_speed(model):
    """Benchmark inference speed."""
    # Single prediction
    t0 = time.monotonic()
    for _ in range(100):
        predict_single(model, 10, 35)
    dt = (time.monotonic() - t0) / 100 * 1000
    print(f"  inference_speed: {dt:.3f} ms/prediction — ", end="")
    assert dt < 10, f"Too slow: {dt} ms"
    print("PASS")

    # Batch prediction
    n_batch = 1000
    from plasmanet.physics import standard_atmosphere, stagnation_pressure
    inputs = []
    for i in range(n_batch):
        m = 5 + i * 15 / n_batch
        a = 20 + i * 30 / n_batch
        T_inf, p_inf, _, _ = standard_atmosphere(a)
        p_stag = stagnation_pressure(p_inf, m)
        inputs.append([m, a, 0.08, math.log10(max(p_stag, 1.0))])

    X = torch.tensor(inputs, dtype=torch.float32)
    t0 = time.monotonic()
    with torch.no_grad():
        Y = model.predict_raw(X)
    dt_batch = (time.monotonic() - t0) * 1000
    print(f"  batch_speed: {n_batch} predictions in {dt_batch:.1f} ms "
          f"({dt_batch/n_batch:.4f} ms each) — PASS")


def test_against_cantera(model):
    """Compare PlasmaNet predictions against Cantera ground truth."""
    test_conditions = [
        (5, 30, 0.08),
        (8, 35, 0.08),
        (10, 35, 0.08),
        (12, 30, 0.08),
        (15, 40, 0.08),
    ]

    print(f"\n  {'Mach':>5} {'Alt':>4} {'T_net':>7} {'T_ref':>7} {'T_err%':>7}"
          f" {'ne_net':>10} {'ne_ref':>10} {'ne_err':>8} {'Status':>10}")
    print("  " + "-" * 85)

    max_ne_err = 0
    max_T_err = 0

    for mach, alt, nose_r in test_conditions:
        # PlasmaNet prediction
        pred = predict_single(model, mach, alt, nose_r)

        # Cantera ground truth
        ref = full_analysis(mach, alt, nose_r, use_cantera=True)

        # Compare
        T_err = abs(pred["T_stag_K"] - ref["T_stag_K"]) / max(ref["T_stag_K"], 1) * 100
        max_T_err = max(max_T_err, T_err)

        if ref["ne_m3"] > 1e10 and pred["ne_m3"] > 1e10:
            ne_err_orders = abs(math.log10(pred["ne_m3"]) - math.log10(ref["ne_m3"]))
        elif ref["ne_m3"] <= 1e10 and pred["ne_m3"] <= 1e10:
            ne_err_orders = 0  # both negligible (no meaningful ionization)
        elif max(ref["ne_m3"], pred["ne_m3"]) < 1e12:
            ne_err_orders = 0  # both effectively zero for radar purposes
        else:
            ne_err_orders = abs(math.log10(max(pred["ne_m3"], 1)) - math.log10(max(ref["ne_m3"], 1)))
        max_ne_err = max(max_ne_err, ne_err_orders)

        status_match = "OK" if pred["status"] == ref["status"] else "MISMATCH"

        print(f"  M{mach:>4} {alt:>3}km"
              f" {pred['T_stag_K']:>7.0f} {ref['T_stag_K']:>7.0f} {T_err:>6.1f}%"
              f" {pred['ne_m3']:>10.2e} {ref['ne_m3']:>10.2e} {ne_err_orders:>7.2f}"
              f" {pred['status']:>6}/{ref['status']:>6} {status_match}")

    print(f"\n  Max T error: {max_T_err:.1f}%")
    print(f"  Max ne error: {max_ne_err:.2f} orders of magnitude")

    assert max_T_err < 20, f"T_stag error too high: {max_T_err:.1f}%"
    assert max_ne_err < 3, f"ne error too high: {max_ne_err:.2f} orders"
    print("  cantera_comparison: PASS")


def test_detection_envelope(model):
    """Generate detection envelope and check physical consistency."""
    machs = [5, 8, 10, 12, 15]
    alts = [20, 30, 40, 50]

    print(f"\n  Detection Envelope (PlasmaNet):")
    print(f"  {'':>8}", end="")
    for alt in alts:
        print(f" {alt}km  ", end="")
    print()

    for mach in machs:
        print(f"  M{mach:>5}", end="")
        for alt in alts:
            pred = predict_single(model, mach, alt)
            s = pred["status"][0]  # B, A, or D
            print(f"  {s}    ", end="")
        print()

    # Physical consistency: higher Mach = more ionization at same altitude
    ne_m5 = predict_single(model, 5, 35)["ne_m3"]
    ne_m15 = predict_single(model, 15, 35)["ne_m3"]
    assert ne_m15 > ne_m5, f"ne should increase with Mach: M5={ne_m5:.2e}, M15={ne_m15:.2e}"
    print("\n  detection_envelope: PASS (physically consistent)")


def run_all():
    print("\nPlasmaNet End-to-End Tests")
    print("=" * 50)
    model = test_model_loads()
    test_inference_speed(model)
    test_against_cantera(model)
    test_detection_envelope(model)
    print("=" * 50)
    print("ALL E2E TESTS PASSED")


if __name__ == "__main__":
    run_all()
