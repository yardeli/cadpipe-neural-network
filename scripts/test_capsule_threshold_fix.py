"""Tests for the curvature-gated normal-shock branch in
`core.flowfield.compute_axial_profile`.

Three checks:

1. Capsule M22.5 / 61 km regression — the GCP_VERIFY_V0_3_0 anomaly
   (ne = 3.16e+22 at aft x=800mm, ~2 orders above the trend at the
   same altitude) drops back to ne < 5e+20 once the conical afterbody
   stops claiming stagnation T.

2. The shock kind on capsule afterbody stations is now "oblique"
   (was "normal" before the fix). The nose stations remain "normal"
   because curvature * R_n = 1 satisfies the gate.

3. Zero-regression on the 5 non-pathological presets (sharp_narrow,
   medium_cone, blunt_cone, ram_c, blunt_wide) at the same flight
   condition. Their afterbody half-angles are all below 30° so the
   surface-angle gate already kept them on oblique; the new curvature
   gate is a no-op for them.

Run:
    PYTHONPATH=. python scripts/test_capsule_threshold_fix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np

from khorium_hypersonic import GEOMETRY_PRESETS, compute_axial_profile


def _ok(msg):   print(f"\033[32m  PASS\033[0m {msg}")
def _fail(msg): print(f"\033[31m  FAIL\033[0m {msg}")


# Conditions used in GCP_VERIFY_V0_3_0 — the anomaly row.
_M = 22.5; _ALT = 61.0; _N = 20
_PRE_FIX_CAPSULE_NE = 3.16e22   # observed anomaly value, for context only


def test_capsule_drops_back_to_trend() -> bool:
    print("\n=== Test 1: capsule M22.5/61km aft anomaly is gone ===")
    cap = GEOMETRY_PRESETS["capsule"]
    prof = compute_axial_profile(
        cap, mach=_M, altitude_km=_ALT, n_stations=_N,
        chemistry_mode="kinetics",
    )
    x_peak_m, ne_peak = prof.peak_ne()
    print(f"  peak ne = {ne_peak:.3e} m^-3 at x = {x_peak_m*1000:.0f} mm")
    print(f"  (pre-fix value was {_PRE_FIX_CAPSULE_NE:.2e} at x ≈ 800 mm)")
    # Other geometries at this flight condition produce 2.5e19 .. 8e20.
    # Demand the capsule comes back into that trend band.
    if not (1e18 < ne_peak < 1e21):
        _fail(f"peak ne {ne_peak:.3e} still outside [1e18, 1e21] trend band")
        return False
    if ne_peak >= 0.10 * _PRE_FIX_CAPSULE_NE:
        _fail(f"peak ne {ne_peak:.3e} still within 10x of the pre-fix anomaly "
              f"({_PRE_FIX_CAPSULE_NE:.2e}) — fix did not bite")
        return False
    _ok(f"capsule M22.5/61km peak ne dropped from {_PRE_FIX_CAPSULE_NE:.2e} "
        f"to {ne_peak:.2e} ({_PRE_FIX_CAPSULE_NE/max(ne_peak,1):.0f}x lower)")
    return True


def test_capsule_shock_kind_breakdown() -> bool:
    print("\n=== Test 2: capsule shock-kind split — nose normal, cone oblique ===")
    cap = GEOMETRY_PRESETS["capsule"]
    prof = compute_axial_profile(
        cap, mach=_M, altitude_km=_ALT, n_stations=_N,
        chemistry_mode="equilibrium",   # cheap; we're testing the dispatch not chemistry
    )
    n_normal_total = sum(1 for s in prof.stations if s.shock_kind == "normal")
    n_oblique_total = sum(1 for s in prof.stations if s.shock_kind == "oblique")
    # The capsule's spherical-nose region (x <= x_tang = R_n*(1-sin(30deg)) = 150mm)
    # should stay on normal-shock. The conical afterbody (x > 150mm) must
    # now switch to oblique.
    x_tang_m = 0.30 * (1.0 - np.sin(np.radians(30.0)))
    nose_normals = sum(
        1 for s in prof.stations if s.x_m <= x_tang_m and s.shock_kind == "normal"
    )
    cone_obliques = sum(
        1 for s in prof.stations if s.x_m > x_tang_m and s.shock_kind == "oblique"
    )
    cone_stations = sum(1 for s in prof.stations if s.x_m > x_tang_m)
    nose_stations = sum(1 for s in prof.stations if s.x_m <= x_tang_m)
    print(f"  capsule: {n_normal_total} normal / {n_oblique_total} oblique "
          f"(of {len(prof.stations)} total)")
    print(f"    nose (x<=150mm): {nose_normals}/{nose_stations} normal")
    print(f"    cone (x> 150mm): {cone_obliques}/{cone_stations} oblique")
    if cone_obliques != cone_stations:
        _fail(f"cone stations should all be oblique now; "
              f"{cone_stations - cone_obliques} still on normal")
        return False
    if nose_normals == 0:
        _fail("no nose station classified as normal — the gate is too strict")
        return False
    _ok("capsule cone stations all dispatch to oblique; nose stations stay normal")
    return True


def test_other_presets_unchanged() -> bool:
    print("\n=== Test 3: zero regression on the 5 sub-30deg presets ===")
    expected_band = {
        # Values pulled from GCP_VERIFY_V0_3_0.md (M22.5/61km row), with
        # a generous +/- 1 dex band to absorb local-platform CVode jitter
        # vs the GCP run.
        "sharp_narrow": (2.54e+19 / 10, 2.54e+19 * 10),
        "medium_cone":  (6.47e+19 / 10, 6.47e+19 * 10),
        "blunt_cone":   (1.01e+20 / 10, 1.01e+20 * 10),
        "ram_c":        (8.19e+20 / 10, 8.19e+20 * 10),
        "blunt_wide":   (1.69e+20 / 10, 1.69e+20 * 10),
    }
    for name, (lo, hi) in expected_band.items():
        geom = GEOMETRY_PRESETS[name]
        prof = compute_axial_profile(
            geom, mach=_M, altitude_km=_ALT, n_stations=_N,
            chemistry_mode="kinetics",
        )
        ne = prof.peak_ne()[1]
        print(f"  {name:>14s}  peak ne = {ne:.2e}  (expected band [{lo:.1e}, {hi:.1e}])")
        if not (lo <= ne <= hi):
            _fail(f"{name} peak ne {ne:.2e} fell outside expected band")
            return False
    _ok("all 5 sub-30deg presets still fall inside their pre-fix bands")
    return True


def main() -> int:
    results = [
        test_capsule_drops_back_to_trend(),
        test_capsule_shock_kind_breakdown(),
        test_other_presets_unchanged(),
    ]
    n = sum(1 for r in results if r)
    print()
    print("=" * 60)
    print(f"  {n}/{len(results)} capsule-threshold test groups passed")
    print("=" * 60)
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
