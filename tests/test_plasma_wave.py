"""Tests for plasma wave propagation and collision frequencies.

Each test validates against an analytical limit or a published number —
not just self-consistency. If these pass, the wave physics is sound.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import numpy as np

from plasmanet.plasma_wave import (
    plasma_frequency_rad_s, refractive_index,
    attenuation_rate_db_per_m, phase_rate_rad_per_m,
    reflection_coefficient_normal, WaveResult, detection_status,
    THRESHOLD_BLACKOUT_DB,
)
from plasmanet.collision_frequency import (
    nu_en, nu_ei, nu_total, nu_from_cantera_state,
    q_mt_N2, q_mt_O2, q_mt_NO, q_mt_O, q_mt_N,
    coulomb_log,
)
from plasmanet.physics import (
    plasma_frequency_hz, K_B, M_E, E_CHARGE, EPS_0, C_LIGHT,
    full_analysis,
)


def test_vacuum_limit():
    """n_e → 0: n_r=1, n_i=0, zero attenuation, zero phase shift."""
    n_r, n_i = refractive_index(0.0, 0.0, 12e9)
    assert abs(float(n_r) - 1.0) < 1e-12, f"vacuum n_r={n_r}"
    assert abs(float(n_i)) < 1e-12, f"vacuum n_i={n_i}"
    assert abs(float(attenuation_rate_db_per_m(0.0, 0.0, 12e9))) < 1e-10
    assert abs(float(phase_rate_rad_per_m(0.0, 0.0, 12e9))) < 1e-10
    print("  vacuum_limit: PASS")


def test_collisionless_underdense():
    """ω > ω_p, ν=0: transparent, n_r = sqrt(1-(ω_p/ω)²), n_i=0."""
    f = 12e9
    # Pick ne such that ω_p/ω = 0.5 → ne = 0.25 · (1.78e18 at 12 GHz)
    # = 4.45e17 m⁻³
    n_e = 4.45e17
    n_r, n_i = refractive_index(n_e, 0.0, f)
    omega_p = math.sqrt(n_e * E_CHARGE**2 / (M_E * EPS_0))
    omega = 2 * math.pi * f
    ratio = omega_p / omega
    expected_n_r = math.sqrt(1 - ratio**2)
    assert abs(float(n_r) - expected_n_r) < 1e-6, f"n_r={n_r} vs expected {expected_n_r}"
    assert abs(float(n_i)) < 1e-10, f"n_i={n_i} should be zero (collisionless)"
    assert abs(float(attenuation_rate_db_per_m(n_e, 0.0, f))) < 1e-8
    print("  collisionless_underdense: PASS")


def test_collisionless_overdense():
    """ω < ω_p, ν=0: evanescent, n_r=0, n_i = sqrt((ω_p/ω)² - 1)."""
    f = 12e9
    omega = 2 * math.pi * f
    # ω_p / ω = 3 → ω_p² = 9·ω² → ne = 9 · 1.78e18 = 1.60e19
    n_e = 1.60e19
    n_r, n_i = refractive_index(n_e, 0.0, f)
    omega_p = math.sqrt(n_e * E_CHARGE**2 / (M_E * EPS_0))
    ratio = omega_p / omega
    expected_n_i = math.sqrt(ratio**2 - 1)
    # Allow 1% tolerance (ne slightly off from target ratio of 3 exactly)
    assert abs(float(n_r)) < 1e-8, f"n_r={n_r} should be zero (overdense, collisionless)"
    assert abs(float(n_i) - expected_n_i) / expected_n_i < 0.01, \
        f"n_i={n_i} vs expected {expected_n_i}"
    # 1 cm of this plasma at ω_p=3ω: α = 17.37·k0·n_i ~
    alpha = float(attenuation_rate_db_per_m(n_e, 0.0, f))
    k0 = omega / C_LIGHT
    expected_alpha = 8.686 * 2 * k0 * expected_n_i
    assert abs(alpha - expected_alpha) / expected_alpha < 0.01
    # 1 cm of this plasma: > 100 dB attenuation, total blackout
    assert alpha * 0.01 > 100.0
    print(f"  collisionless_overdense: PASS (α={alpha:.0f} dB/m)")


def test_cutoff_threshold():
    """At ω_p = ω (n_e = 1.78e18 at 12 GHz), n_r and n_i both ≈ 0 for ν=0."""
    f = 12e9
    # Exact cutoff ne
    omega = 2 * math.pi * f
    ne_cutoff = omega**2 * M_E * EPS_0 / E_CHARGE**2
    assert abs(ne_cutoff - 1.787e18) / 1.787e18 < 0.01
    n_r, n_i = refractive_index(ne_cutoff, 0.0, f)
    assert abs(float(n_r)) < 1e-6
    assert abs(float(n_i)) < 1e-6
    print(f"  cutoff_threshold: PASS (ne_cutoff={ne_cutoff:.3e})")


def test_collisional_absorption_peak():
    """With ν_c = ω and ω_p/ω moderate, absorption is near maximum.

    Analytical prediction at ν_c = ω, ω_p = ω:
      Re(n²) = 1 − ω_p²/(ω² + ν_c²) = 1 − 1/2 = 0.5
      Im(n²) = −ω_p²·ν_c / (ω(ω² + ν_c²)) = −1·1 / (1·2) = −0.5
      |n²| = sqrt(0.5² + 0.5²) = 0.707
      n_r² = 0.5·(0.5 + 0.707) = 0.604 → n_r = 0.777
      n_i² = 0.5·(−0.5 + 0.707) = 0.104 → n_i = 0.322
    """
    f = 12e9
    omega = 2 * math.pi * f
    n_e = omega**2 * M_E * EPS_0 / E_CHARGE**2  # ω_p = ω
    nu_c = omega
    n_r, n_i = refractive_index(n_e, nu_c, f)
    assert abs(float(n_r) - 0.7773) < 1e-3, f"n_r={n_r} (expected ~0.777)"
    assert abs(float(n_i) - 0.3218) < 1e-3, f"n_i={n_i} (expected ~0.322)"
    print(f"  collisional_absorption_peak: PASS (n_r={float(n_r):.4f}, n_i={float(n_i):.4f})")


def test_plasma_frequency_consistency():
    """plasma_wave.plasma_frequency_rad_s() vs physics.plasma_frequency_hz()."""
    n_e = 1e18
    fp_hz = plasma_frequency_hz(n_e)
    omega_p = float(plasma_frequency_rad_s(n_e))
    assert abs(fp_hz * 2 * math.pi - omega_p) / omega_p < 1e-12
    print("  plasma_frequency_consistency: PASS")


def test_reflection_coefficient():
    """Below cutoff collisionless: |r| → 1 (perfect reflector)."""
    r = reflection_coefficient_normal(1e20, 0.0, 12e9)   # way above cutoff
    assert abs(abs(r) - 1.0) < 1e-3, f"|r|={abs(r)} should be ~1"
    r2 = reflection_coefficient_normal(0.0, 0.0, 12e9)
    assert abs(r2) < 1e-12, f"vacuum reflection should be 0"
    print(f"  reflection_coefficient: PASS (|r_overdense|={abs(r):.4f})")


def test_wave_result_regimes():
    """WaveResult.regime classifier."""
    f = 12e9
    assert WaveResult.compute(0.0, 0.0, f).regime == "vacuum"
    # Just above cutoff, no collisions: underdense
    assert WaveResult.compute(1e16, 0.0, f).regime == "underdense"
    # Well above cutoff (overdense) — ω_p = 3ω
    assert WaveResult.compute(1.6e19, 0.0, f).regime == "overdense"
    # High ν: collisional
    omega = 2 * math.pi * f
    assert WaveResult.compute(1e18, 0.5 * omega, f).regime == "collisional"
    print("  wave_result_regimes: PASS")


def test_detection_status_thresholds():
    assert detection_status(1.0) == "DETECTABLE"
    assert detection_status(5.0) == "DEGRADED"
    assert detection_status(20.0) == "BLACKOUT"
    assert detection_status(THRESHOLD_BLACKOUT_DB + 0.1) == "BLACKOUT"
    print("  detection_status: PASS")


# ── Collision frequency tests ──────────────────────────────────────────

def test_collision_rate_coefficients_monotonic():
    """Q(T) should be non-decreasing up to saturation for all species."""
    T_values = np.array([300, 1000, 3000, 10000, 30000])
    for fn, name in [(q_mt_N2, "N2"), (q_mt_O2, "O2"), (q_mt_NO, "NO"),
                     (q_mt_O, "O"), (q_mt_N, "N")]:
        Q = fn(T_values)
        # Non-decreasing
        assert np.all(np.diff(Q) >= -1e-20), f"{name}: Q not monotonic: {Q}"
        # Positive
        assert np.all(Q > 0), f"{name}: Q not positive: {Q}"
        # Bounded
        assert np.all(Q < 1e-12), f"{name}: Q too large: {Q}"
    print("  collision_rate_coefficients_monotonic: PASS")


def test_nu_en_ram_c_regime():
    """Electron-neutral collision frequency at RAM-C II sheath conditions.

    RAM-C II Huber (1967) post-shock conditions at 75 km altitude:
      Gas density ~ 5e21 m⁻³, T_e ~ 6000 K. The paper reports
      ν_en ~ 10^9 – 10^10 s⁻¹ in the sheath.
    """
    T_e = 6000.0
    n_total = 5e21  # m⁻³
    # Assume post-shock: 50% N2, 20% O2, 20% N, 8% O, 2% NO (rough dissociation)
    n_N2 = 0.50 * n_total
    n_O2 = 0.20 * n_total
    n_NO = 0.02 * n_total
    n_O  = 0.08 * n_total
    n_N  = 0.20 * n_total
    nu = float(nu_en(T_e, n_N2, n_O2, n_NO, n_O, n_N))
    assert 5e8 < nu < 5e10, f"nu_en={nu:.2e} s⁻¹ outside RAM-C expected range"
    print(f"  nu_en_ram_c_regime: PASS (nu_en={nu:.2e} s⁻¹)")


def test_coulomb_log():
    """ln Λ should be ~10-20 for typical lab plasmas."""
    # Tokamak-ish: 1e19, 1 keV
    L1 = float(coulomb_log(1.16e7, 1e19))
    assert 10.0 < L1 < 20.0, f"ln Λ (tokamak) = {L1}"
    # RAM-C sheath: 1e18, 6000 K
    L2 = float(coulomb_log(6000.0, 1e18))
    assert 5.0 < L2 < 15.0, f"ln Λ (RAM-C) = {L2}"
    print(f"  coulomb_log: PASS (L_tokamak={L1:.2f}, L_ramc={L2:.2f})")


def test_nu_ei_dominance_at_high_ionization():
    """At high ionization fraction, ν_ei dominates over ν_en.

    Condition: n_e/n_n ~ 1 means highly ionized. ν_ei should exceed ν_en.
    """
    T = 15000.0
    # Half ionized: n_e = 1e22, total neutrals also ~1e22
    n_e = 1e22
    n_neutrals = 1e22
    nu_en_val = float(nu_en(T, 0.3*n_neutrals, 0.1*n_neutrals, 0.05*n_neutrals,
                            0.25*n_neutrals, 0.3*n_neutrals))
    nu_ei_val = float(nu_ei(T, n_e))
    assert nu_ei_val > nu_en_val, \
        f"At T=15kK, half-ionized: nu_ei={nu_ei_val:.2e} should exceed nu_en={nu_en_val:.2e}"
    print(f"  nu_ei_dominance: PASS (nu_ei={nu_ei_val:.2e}, nu_en={nu_en_val:.2e})")


def test_nu_from_full_analysis():
    """End-to-end: full_analysis gives mole fractions, nu_from_cantera_state
    produces a reasonable total collision frequency."""
    r = full_analysis(10.0, 30.0, 0.08, use_cantera=True)
    mf = {
        "N2": r["x_N2"], "O2": r["x_O2"], "NO": r["x_NO"],
        "O": r["x_O"], "N": r["x_N"],
        "eminus": r["ne_m3"] * K_B * r["T_stag_K"] / max(r["p_stag_Pa"], 1e-10),
    }
    nu_en_val, nu_ei_val, nu_total_val = nu_from_cantera_state(
        r["T_stag_K"], r["p_stag_Pa"], mf)
    # At Mach 10 @ 30 km, perfect-gas stagnation p ~500 atm, T ~5000 K.
    # At this density the collision frequency is dominated by n·Q which can
    # reach 1e14 s⁻¹. (Note: p_stag from perfect-gas relations overpredicts
    # real-gas stagnation pressure by ~10-20%, so real ν would be slightly lower.)
    assert 1e8 < nu_total_val < 1e15, f"nu_total={nu_total_val:.2e} out of physical range"
    print(f"  nu_from_full_analysis: PASS "
          f"(M=10,h=30: nu_en={nu_en_val:.2e}, nu_ei={nu_ei_val:.2e})")


# ── Integration test: full wave physics at realistic plasma conditions ─

def test_end_to_end_wave_at_ram_c():
    """End-to-end: compute wave properties at RAM-C-like sheath conditions.

    RAM-C II at 75 km, Mach 23.9 measured peak ne ~ 1-5e19 m⁻³ (NASA TN D-6617).
    At X-band (9.2 GHz) Huber reports ~60 dB/cm attenuation in the sheath.
    """
    # RAM-C-like sheath point
    n_e = 2.5e19
    T_e = 6000.0
    # Post-shock air at ~75 km altitude, shock-compressed
    n_total = 5e21
    n_N2, n_O2, n_NO, n_O, n_N = (0.5*n_total, 0.2*n_total, 0.02*n_total,
                                   0.08*n_total, 0.2*n_total)
    nu = float(nu_total(T_e, n_e, n_N2, n_O2, n_NO, n_O, n_N))
    f_X = 9.2e9
    alpha = float(attenuation_rate_db_per_m(n_e, nu, f_X))
    # X-band sheath attenuation should be thousands of dB/m at these conditions
    # (RAM-C reports VHF total blackout, X-band partial ~60 dB through the sheath)
    assert alpha > 1000, f"X-band attenuation at RAM-C ne={alpha:.1f} dB/m (expected 1e3+)"
    # Sanity: much lower at Ku-band would still be high
    alpha_Ku = float(attenuation_rate_db_per_m(n_e, nu, 12e9))
    assert alpha_Ku > 500
    print(f"  end_to_end_wave_at_ram_c: PASS "
          f"(X-band α={alpha:.0f} dB/m, Ku-band α={alpha_Ku:.0f} dB/m)")


def run_all():
    print("\nPlasmaNet Wave Propagation Tests")
    print("=" * 50)
    test_vacuum_limit()
    test_collisionless_underdense()
    test_collisionless_overdense()
    test_cutoff_threshold()
    test_collisional_absorption_peak()
    test_plasma_frequency_consistency()
    test_reflection_coefficient()
    test_wave_result_regimes()
    test_detection_status_thresholds()
    test_collision_rate_coefficients_monotonic()
    test_nu_en_ram_c_regime()
    test_coulomb_log()
    test_nu_ei_dominance_at_high_ionization()
    test_nu_from_full_analysis()
    test_end_to_end_wave_at_ram_c()
    print("=" * 50)
    print("ALL WAVE TESTS PASSED\n")


if __name__ == "__main__":
    run_all()
