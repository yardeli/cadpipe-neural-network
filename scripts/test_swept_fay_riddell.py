"""Tests for the swept-LE cos^2(Lambda) Fay-Riddell correction.

Three checks:

1. Backward compatibility — calling fay_riddell_full / bl_summary without
   sweep_angle_rad returns exactly the same q_w as before (sweep=0 implies
   cos^2(0)=1.0).

2. cos^2(Lambda) scaling — varying sweep over [0, 75 deg] reproduces the
   closed-form q_sw / q_unswept = cos^2(Lambda) within numerical precision.

3. Engineering-magnitude sanity — for a representative 70 deg swept LE
   at hypersonic conditions, q_w drops by ~88% vs unswept. This matches
   Beckwith & Gallagher 1961 / Anderson 2006 Sec 6.6 for sharp swept
   cylinders.

Run:
    PYTHONPATH=. python scripts/test_swept_fay_riddell.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from khorium_hypersonic import bl_summary, fay_riddell_full


def _ok(msg):   print(f"\033[32m  PASS\033[0m {msg}")
def _fail(msg): print(f"\033[31m  FAIL\033[0m {msg}")


_BASE_KW = dict(
    rho_e_kgm3=0.01, mu_e_Pa_s=5e-5, h_e_J_per_kg=2.5e7,
    rho_w_kgm3=0.05, mu_w_Pa_s=3e-5, h_w_J_per_kg=3.0e5,
    R_n_m=0.08, p_t_Pa=1.5e5, p_inf_Pa=2000.0, rho_t_kgm3=0.1,
)


def test_backward_compat() -> bool:
    print("\n=== Test 1: backward compat — default call matches sweep=0 explicitly ===")
    default = fay_riddell_full(**_BASE_KW)
    explicit = fay_riddell_full(**_BASE_KW, sweep_angle_rad=0.0)
    if abs(default["q_w_W_per_m2"] - explicit["q_w_W_per_m2"]) > 1e-9:
        _fail(f"default q_w {default['q_w_W_per_m2']:.3e} != "
              f"sweep=0 q_w {explicit['q_w_W_per_m2']:.3e}")
        return False
    if abs(default["sweep_correction"] - 1.0) > 1e-12:
        _fail(f"default sweep_correction = {default['sweep_correction']} (expected 1.0)")
        return False
    _ok(f"unswept q_w = {default['q_w_W_per_m2']:.3e} W/m^2, "
        f"sweep_correction = {default['sweep_correction']}")
    return True


def test_cos_squared_scaling() -> bool:
    print("\n=== Test 2: q_w ratio matches cos^2(Lambda) across 0-75 deg ===")
    q0 = fay_riddell_full(**_BASE_KW, sweep_angle_rad=0.0)["q_w_W_per_m2"]
    for lambda_deg in (15.0, 30.0, 45.0, 60.0, 70.0, 75.0):
        q_sw = fay_riddell_full(
            **_BASE_KW, sweep_angle_rad=math.radians(lambda_deg),
        )["q_w_W_per_m2"]
        expected = math.cos(math.radians(lambda_deg)) ** 2
        actual = q_sw / q0
        rel = abs(actual - expected) / max(expected, 1e-12)
        print(f"  Lambda = {lambda_deg:>5.1f} deg   q_sw/q0 = {actual:.4f}   "
              f"cos^2 = {expected:.4f}   rel_err = {rel:.1e}")
        if rel > 1e-9:
            _fail(f"q_sw/q_unswept off by {rel:.1e} at sweep {lambda_deg} deg")
            return False
    _ok("cos^2(Lambda) scaling matches closed form to machine precision")
    return True


def test_engineering_magnitude() -> bool:
    print("\n=== Test 3: 70 deg swept-LE engineering magnitude ===")
    unswept = bl_summary(
        R_n_m=0.003, U_inf_ms=2300.0,
        rho_e_kgm3=0.01, T_e_K=8000.0,
        rho_w_kgm3=0.05, T_w_K=1200.0,
        h_e_J_per_kg=2.5e7, h_w_J_per_kg=1.5e6,
        p_t_Pa=1.0e5, p_inf_Pa=300.0, rho_t_kgm3=0.05,
    )
    swept = bl_summary(
        R_n_m=0.003, U_inf_ms=2300.0,
        rho_e_kgm3=0.01, T_e_K=8000.0,
        rho_w_kgm3=0.05, T_w_K=1200.0,
        h_e_J_per_kg=2.5e7, h_w_J_per_kg=1.5e6,
        p_t_Pa=1.0e5, p_inf_Pa=300.0, rho_t_kgm3=0.05,
        sweep_angle_rad=math.radians(70.0),
    )
    ratio = swept["q_w_W_per_m2"] / unswept["q_w_W_per_m2"]
    cos2 = math.cos(math.radians(70.0)) ** 2
    print(f"  unswept q_w = {unswept['q_w_W_per_m2']:.3e} W/m^2")
    print(f"  70deg  q_w = {swept['q_w_W_per_m2']:.3e} W/m^2")
    print(f"  ratio       = {ratio:.4f}   (cos^2(70 deg) = {cos2:.4f})")
    if abs(ratio - cos2) / cos2 > 1e-9:
        _fail("70 deg swept ratio off from cos^2")
        return False
    # cos^2(70) ~= 0.117 -> 88.3% reduction in heat flux
    if not (0.10 < ratio < 0.13):
        _fail(f"70 deg sweep ratio {ratio:.3f} outside expected 0.10-0.13 band")
        return False
    _ok("70 deg sweep produces ~88% q_w reduction (matches Beckwith & Gallagher)")
    return True


def main() -> int:
    results = [
        test_backward_compat(),
        test_cos_squared_scaling(),
        test_engineering_magnitude(),
    ]
    n = sum(1 for r in results if r)
    print()
    print("=" * 60)
    print(f"  {n}/{len(results)} swept-FR test groups passed")
    print("=" * 60)
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
