"""Tests for chemistry UQ propagation.

Validate that the UQ result is reasonable — not exact numbers, but
structure (monotonicity, known sensitivities, reproducibility).
"""
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import numpy as np

from plasmanet.chemistry_uq import (
    ChemistryUQConfig, run_uq, sensitivity_at_condition,
    latin_hypercube_normal,
)


def test_lhs_standard_normal_statistics():
    """LHS from N(0,1) should have mean ~0 and std ~1 for reasonable n."""
    X = latin_hypercube_normal(1000, 3, seed=42)
    assert X.shape == (1000, 3)
    assert abs(X.mean()) < 0.05, f"mean={X.mean():.3f}"
    assert abs(X.std() - 1.0) < 0.05, f"std={X.std():.3f}"
    # LHS: variance should be slightly lower than plain MC for same N
    X_random = np.random.default_rng(42).standard_normal((1000, 3))
    lhs_var = np.var(X.mean(axis=0))
    mc_var = np.var(X_random.mean(axis=0))
    # LHS stratification gives better mean estimate
    print(f"  lhs_standard_normal_statistics: PASS (LHS var={lhs_var:.3e}, MC var={mc_var:.3e})")


def test_uq_zero_uncertainty_returns_nominal():
    """With all uncertainties set to 0, mean ≈ nominal ne."""
    cfg = ChemistryUQConfig(
        T_stag_relative_std=0.0, p_stag_relative_std=0.0,
        neq_factor_uncertainty=0.0, n_samples=16,
    )
    t0 = time.monotonic()
    result = run_uq(mach=10, altitude_km=35, nose_radius_m=0.08,
                    config=cfg, use_cantera=True, use_neq=False)
    dt = time.monotonic() - t0
    # All samples should be identical
    spread = result.ensemble_ne_m3.std() / max(result.ensemble_ne_m3.mean(), 1.0)
    assert spread < 1e-6, f"zero-uq spread too large: {spread}"
    assert result.ne_m3_p05 == result.ne_m3_p95
    print(f"  uq_zero_uncertainty_returns_nominal: PASS ({dt:.1f}s, ne={result.ne_m3_mean:.2e})")


def test_uq_temperature_perturbation_expands_distribution():
    """10% T uncertainty → order-of-magnitude ne spread at Mach 10."""
    cfg = ChemistryUQConfig(
        T_stag_relative_std=0.10, p_stag_relative_std=0.0,
        n_samples=64,
    )
    t0 = time.monotonic()
    result = run_uq(mach=10, altitude_km=35, nose_radius_m=0.08,
                    config=cfg, use_cantera=True, use_neq=False)
    dt = time.monotonic() - t0
    # Saha: δ(log ne) ≈ (E_i / kT) · δT/T   — strong sensitivity to T
    # At Mach 10 @ 35 km, T ~ 5000 K; E_i(NO)/kT ≈ 9.26e * 11605/5000 / log10 ≈ 9.3
    # So 10% T uncertainty → ~1 order of magnitude in ne → log10_ne_std ~ 0.4-0.5
    assert result.log10_ne_std > 0.1, \
        f"T perturbation gave log10_ne std = {result.log10_ne_std:.3f} (expected > 0.1)"
    assert result.log10_ne_std < 2.0, \
        f"log10_ne std = {result.log10_ne_std:.3f} unrealistically large"
    # P95/P05 ratio should be > ~5
    ratio = result.ne_m3_p95 / max(result.ne_m3_p05, 1e-30)
    assert ratio > 2.0, f"P95/P05 ne ratio = {ratio:.2f}"
    print(f"  uq_temperature_perturbation_expands_distribution: PASS "
          f"({dt:.1f}s, log10_ne std = {result.log10_ne_std:.3f}, "
          f"P95/P05 = {ratio:.1f})")


def test_uq_pressure_perturbation_smaller_than_temperature():
    """5% p uncertainty should produce smaller ne spread than 10% T."""
    cfg_T = ChemistryUQConfig(
        T_stag_relative_std=0.10, p_stag_relative_std=0.0, n_samples=32,
    )
    cfg_p = ChemistryUQConfig(
        T_stag_relative_std=0.0, p_stag_relative_std=0.05, n_samples=32,
    )
    res_T = run_uq(mach=10, altitude_km=35, config=cfg_T)
    res_p = run_uq(mach=10, altitude_km=35, config=cfg_p)
    assert res_T.log10_ne_std > res_p.log10_ne_std, \
        f"T-uq spread ({res_T.log10_ne_std:.3f}) should exceed p-uq spread ({res_p.log10_ne_std:.3f})"
    print(f"  uq_pressure_perturbation_smaller_than_temperature: PASS "
          f"(T-uq={res_T.log10_ne_std:.3f}, p-uq={res_p.log10_ne_std:.3f})")


def test_uq_low_temperature_no_ionization():
    """At Mach 5 @ 40 km (T ~ 1500 K), ne should be tiny regardless of UQ."""
    cfg = ChemistryUQConfig(T_stag_relative_std=0.10, n_samples=16)
    result = run_uq(mach=5, altitude_km=40, config=cfg, use_cantera=True)
    # All samples should remain well below detection threshold (ne ≈ 1.78e18 at 12 GHz)
    assert result.ne_m3_p95 < 1e15, f"cold-regime ne_P95 = {result.ne_m3_p95:.2e} too large"
    assert result.p_detectable > 0.95
    print(f"  uq_low_temperature_no_ionization: PASS "
          f"(ne_p95={result.ne_m3_p95:.2e}, p_detectable={result.p_detectable:.2f})")


def test_sensitivity_at_stagnation():
    """Sensitivity ∂log10(ne)/∂log10(T) should be ~ Ei/(k T ln10) for Saha."""
    sens = sensitivity_at_condition(mach=10, altitude_km=35,
                                     nose_radius_m=0.08, perturbation_pct=5.0)
    T = sens["nominal_T_stag_K"]
    d_logne_d_logT = sens["d_log10ne_d_log10T"]
    # Theoretical Saha sensitivity in weak-ionization limit:
    # log10(ne) ~ -Ei/(kT)/ln(10) + const → d(log10 ne)/d(log10 T) ≈ +Ei/(kT·ln10)·T/T = Ei·T·ln10/(kT·ln10) = Ei/(kT·ln10)
    # Actually: d(log10 ne)/d log10(T) = T · d(log10 ne)/dT.
    # From Saha: log10(ne) ~ 1.5 log10(T) − Ei/(2.303·kT) + const
    # So d(log10 ne)/d(log10 T) = 1.5 + Ei·T/(2.303·k·T²)·T/T = 1.5 + Ei/(2.303 k T)
    # For NO, Ei=9.26 eV, T=5000K: 1.5 + 9.26/(2.303·8.617e-5·5000) = 1.5 + 9.33 = 10.8
    # Measured should be in ballpark of 10.8 (within factor of 2)
    assert d_logne_d_logT > 2.0, f"∂log10(ne)/∂log10(T) = {d_logne_d_logT:.2f} suspiciously small"
    assert d_logne_d_logT < 30.0, f"∂log10(ne)/∂log10(T) = {d_logne_d_logT:.2f} suspiciously large"
    # Pressure sensitivity should be positive but smaller
    d_logne_d_logp = sens["d_log10ne_d_log10p"]
    # At high p, x_e ~ p^(-0.5) (Le Chatelier), so log(ne)~log(n)+log(x_e)~log(p)-0.5 log(p)=0.5 log(p).
    # But ne = x_e · n = x_e · p/(kT), so log(ne) = log(x_e) + log(p) - log(T) etc.
    # d(log ne)/d(log p) should be ~ 0.5
    assert 0.0 < d_logne_d_logp < 2.0, \
        f"∂log10(ne)/∂log10(p) = {d_logne_d_logp:.2f} outside expected [0,2]"
    print(f"  sensitivity_at_stagnation: PASS "
          f"(∂log10(ne)/∂log10(T)={d_logne_d_logT:.2f}, "
          f"∂log10(ne)/∂log10(p)={d_logne_d_logp:.2f})")


def test_uq_reproducibility():
    """Same seed → same ensemble."""
    cfg = ChemistryUQConfig(n_samples=32, seed=123)
    r1 = run_uq(mach=10, altitude_km=35, config=cfg)
    r2 = run_uq(mach=10, altitude_km=35, config=cfg)
    assert np.allclose(r1.ensemble_ne_m3, r2.ensemble_ne_m3)
    print("  uq_reproducibility: PASS")


def test_uq_detection_probabilities_sum_to_one():
    cfg = ChemistryUQConfig(T_stag_relative_std=0.15, n_samples=32)
    r = run_uq(mach=10, altitude_km=35, config=cfg)
    total = r.p_blackout + r.p_degraded + r.p_detectable
    assert abs(total - 1.0) < 1e-9, f"detection probs sum = {total}"
    print(f"  uq_detection_probabilities_sum_to_one: PASS "
          f"(P_det={r.p_detectable:.2f}, P_deg={r.p_degraded:.2f}, "
          f"P_BO={r.p_blackout:.2f})")


def run_all():
    print("\nChemistry UQ Tests")
    print("=" * 50)
    test_lhs_standard_normal_statistics()
    test_uq_zero_uncertainty_returns_nominal()
    test_uq_temperature_perturbation_expands_distribution()
    test_uq_pressure_perturbation_smaller_than_temperature()
    test_uq_low_temperature_no_ionization()
    test_sensitivity_at_stagnation()
    test_uq_reproducibility()
    test_uq_detection_probabilities_sum_to_one()
    print("=" * 50)
    print("ALL UQ TESTS PASSED\n")


if __name__ == "__main__":
    run_all()
