"""Tests for PlasmaNet physics module.

Validates all physics functions against known reference values.
"""
import math
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from plasmanet.physics import (
    standard_atmosphere, cp_air, stagnation_temperature_perfect,
    stagnation_pressure, janaf_equilibrium, saha_ionization,
    nonequilibrium_correction, plasma_frequency_hz, plasma_frequency_ghz,
    radar_status, full_analysis,
    K_B, M_E, E_CHARGE, EPS_0, EI_NO, EI_O, EI_N,
)


def test_constants():
    """Verify physical constants against NIST 2019 values."""
    assert abs(K_B - 1.380649e-23) < 1e-29, f"k_B wrong: {K_B}"
    assert abs(M_E - 9.1093837015e-31) < 1e-40, f"m_e wrong: {M_E}"
    assert abs(E_CHARGE - 1.602176634e-19) < 1e-28, f"e wrong: {E_CHARGE}"
    assert abs(EPS_0 - 8.8541878128e-12) < 1e-21, f"eps_0 wrong: {EPS_0}"
    # Ionization energies
    assert abs(EI_NO / E_CHARGE - 9.2642) < 0.001, f"Ei_NO wrong: {EI_NO/E_CHARGE}"
    assert abs(EI_O / E_CHARGE - 13.61806) < 0.001, f"Ei_O wrong: {EI_O/E_CHARGE}"
    assert abs(EI_N / E_CHARGE - 14.53414) < 0.001, f"Ei_N wrong: {EI_N/E_CHARGE}"
    print("  constants: PASS")


def test_standard_atmosphere():
    """Validate US Std Atm 1976 at known altitudes."""
    # Sea level
    T, p, rho, a = standard_atmosphere(0)
    assert abs(T - 288.15) < 0.1, f"T(0km)={T}"
    assert abs(p - 101325) < 10, f"p(0km)={p}"

    # 11 km (tropopause)
    T, p, rho, a = standard_atmosphere(11)
    assert abs(T - 216.65) < 0.5, f"T(11km)={T}"

    # 35 km (typical HGV flight)
    T, p, rho, a = standard_atmosphere(35)
    assert 230 < T < 260, f"T(35km)={T}"
    assert 500 < p < 700, f"p(35km)={p}"

    # 50 km
    T, p, rho, a = standard_atmosphere(50)
    assert 260 < T < 280, f"T(50km)={T}"

    print("  standard_atmosphere: PASS")


def test_cp_air():
    """Check Cp(T) at reference temperatures."""
    # Room temperature: should be ~1005 J/kg/K
    cp_300 = cp_air(300)
    assert 1000 < cp_300 < 1010, f"Cp(300K)={cp_300}"

    # High T: Cp increases due to vibrational modes
    cp_3000 = cp_air(3000)
    assert cp_3000 > cp_300, f"Cp(3000K)={cp_3000} should be > Cp(300K)"
    assert 1100 < cp_3000 < 1400, f"Cp(3000K)={cp_3000} out of range"

    print("  cp_air: PASS")


def test_stagnation_temperature():
    """Verify T_stag at known conditions."""
    # Mach 8 at 35 km: T_inf ~ 237K
    T_inf, _, _, _ = standard_atmosphere(35)
    T_stag = stagnation_temperature_perfect(T_inf, 8.0)
    # T_stag = 237 * (1 + 0.2*64) = 237 * 13.8 = 3270.6 K
    assert abs(T_stag - 3270) < 50, f"T_stag(M8)={T_stag}"

    # Mach 10: T_stag = 237 * (1 + 0.2*100) = 237 * 21 = 4977 K
    T_stag_10 = stagnation_temperature_perfect(T_inf, 10.0)
    assert abs(T_stag_10 - 4977) < 50, f"T_stag(M10)={T_stag_10}"

    print("  stagnation_temperature: PASS")


def test_janaf_equilibrium():
    """Check JANAF dissociation at known temperatures."""
    # At 3000K, 1 atm: O2 partially dissociated, N2 intact
    x_N2, x_O2, x_O, x_N, x_NO = janaf_equilibrium(3000, 101325)
    assert x_N2 > 0.7, f"x_N2(3000K)={x_N2} should be > 0.7"
    assert x_O2 < 0.21, f"x_O2(3000K)={x_O2} should be < 0.21"
    assert x_O > 0, f"x_O(3000K)={x_O} should be > 0"

    # At 5000K: significant O2 dissociation (~80% at 1 atm)
    x_N2, x_O2, x_O, x_N, x_NO = janaf_equilibrium(5000, 101325)
    assert x_O2 < 0.10, f"x_O2(5000K)={x_O2} should be < 0.10"
    assert x_O > 0.1, f"x_O(5000K)={x_O} should be > 0.1"

    # At 8000K: both dissociated
    x_N2, x_O2, x_O, x_N, x_NO = janaf_equilibrium(8000, 101325)
    assert x_N > 0.1, f"x_N(8000K)={x_N} should be > 0.1"

    print("  janaf_equilibrium: PASS")


def test_saha_ionization():
    """Validate Saha ne against Park (1990) reference data."""
    # At 4000K, 1 atm: ne should be ~1e17-1e18
    _, _, x_O, x_N, x_NO = janaf_equilibrium(4000, 101325)
    ne = saha_ionization(4000, 101325, x_NO, x_O, x_N)
    log10_ne = math.log10(max(ne, 1))
    # Park Table 7.3: ne ~ 1e17 at 4000K
    assert 15 < log10_ne < 20, f"ne(4000K)={ne:.2e}, log10={log10_ne:.1f}"

    # At 7000K: ne should be ~1e19-1e21
    _, _, x_O, x_N, x_NO = janaf_equilibrium(7000, 101325)
    ne = saha_ionization(7000, 101325, x_NO, x_O, x_N)
    log10_ne = math.log10(max(ne, 1))
    assert 18 < log10_ne < 22, f"ne(7000K)={ne:.2e}, log10={log10_ne:.1f}"

    # At 2000K: ne should be negligible
    _, _, x_O, x_N, x_NO = janaf_equilibrium(2000, 101325)
    ne = saha_ionization(2000, 101325, x_NO, x_O, x_N)
    assert ne < 1e15, f"ne(2000K)={ne:.2e} should be negligible"

    print("  saha_ionization: PASS")


def test_plasma_frequency():
    """Verify plasma frequency formula."""
    # At ne = 1.78e18: fp should be ~12 GHz (StarLink blackout threshold)
    fp = plasma_frequency_ghz(1.78e18)
    assert abs(fp - 12.0) < 0.5, f"fp(1.78e18)={fp} should be ~12 GHz"

    # At ne = 0: fp = 0
    assert plasma_frequency_hz(0) == 0
    assert plasma_frequency_hz(-1) == 0

    print("  plasma_frequency: PASS")


def test_radar_status():
    """Check detection classification."""
    assert radar_status(15.0) == "BLACKOUT"
    assert radar_status(5.0) == "ATTENUATED"
    assert radar_status(1.0) == "DETECTABLE"
    assert radar_status(0.0) == "DETECTABLE"
    print("  radar_status: PASS")


def test_nonequilibrium_correction():
    """Validate NEQ correction behavior."""
    # Below 3500K: no correction
    ne_raw = 1e18
    ne_corr = nonequilibrium_correction(3000, ne_raw)
    assert ne_corr == ne_raw, f"NEQ at 3000K should not correct"

    # At 5000K: significant correction (factor ~0.02)
    ne_corr = nonequilibrium_correction(5000, ne_raw)
    assert ne_corr < ne_raw * 0.1, f"NEQ at 5000K={ne_corr:.2e} should be much less"

    # Larger nose = closer to equilibrium
    ne_large = nonequilibrium_correction(5000, ne_raw, nose_radius_m=0.5)
    ne_small = nonequilibrium_correction(5000, ne_raw, nose_radius_m=0.02)
    assert ne_large > ne_small, f"Larger nose ({ne_large:.2e}) should have higher ne than small ({ne_small:.2e})"

    print("  nonequilibrium_correction: PASS")


def test_full_analysis():
    """End-to-end test of full_analysis."""
    # Mach 5, 30km: should be DETECTABLE
    r = full_analysis(5, 30, use_cantera=False)
    assert r["status"] == "DETECTABLE", f"M5 status={r['status']}"
    assert r["T_stag_K"] > 1000, f"T_stag too low: {r['T_stag_K']}"

    # Mach 15, 30km: should likely be BLACKOUT
    r = full_analysis(15, 30, use_cantera=False)
    assert r["T_stag_K"] > 5000, f"T_stag too low at M15: {r['T_stag_K']}"
    assert r["ne_m3"] > 0, f"ne should be positive at M15"

    print("  full_analysis: PASS")


def run_all_tests():
    """Run all physics tests."""
    print("\nPlasmaNet Physics Tests")
    print("=" * 40)
    test_constants()
    test_standard_atmosphere()
    test_cp_air()
    test_stagnation_temperature()
    test_janaf_equilibrium()
    test_saha_ionization()
    test_plasma_frequency()
    test_radar_status()
    test_nonequilibrium_correction()
    test_full_analysis()
    print("=" * 40)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run_all_tests()
