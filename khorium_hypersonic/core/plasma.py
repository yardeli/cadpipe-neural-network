"""Plasma frequency + Appleton-Hartree wave-plasma interaction.

Cold-plasma dispersion relation for an EM wave through magnetized plasma
(B → 0 in our case → just collisional Appleton-Hartree). For a uniform
slab of length L:

    α_dB = 8.686 · α_Np · L

where α_Np depends on regime:
  - Below cutoff (ω < ω_p): wave is evanescent, α ≈ (ω/c)·√(ω_p²/ω² - 1)
  - Above cutoff (ω > ω_p): α ≈ (ω_p² · ν) / (2c · (ω² + ν²)), small.

Reference: Bekefi 1966 "Radiation Processes in Plasmas" §4.3, or Stix
1992 "Waves in Plasmas" Ch. 1. For RAM-class re-entry the radar bands
(VHF 225 MHz – Ku 12 GHz) sit BELOW f_p (250+ GHz at peak ne), so the
evanescent regime dominates and attenuation is large per meter.
"""
import math

from .constants import (
    K_B, M_E, E_CHARGE, EPS_0, C_LIGHT,
)


def plasma_frequency_Hz(ne_m3: float) -> float:
    """f_p = (1/2π)·√(n_e e² / (m_e ε_0))

    Equivalently: f_p ≈ 8.978 × √(n_e in cm⁻³) Hz.
    """
    if ne_m3 <= 0:
        return 0.0
    omega_p = math.sqrt(ne_m3 * E_CHARGE**2 / (M_E * EPS_0))
    return omega_p / (2 * math.pi)


def plasma_frequency_GHz(ne_m3: float) -> float:
    return plasma_frequency_Hz(ne_m3) / 1e9


def cutoff_ne_for_freq(f_Hz: float) -> float:
    """ne above which wave at f_Hz becomes evanescent."""
    omega = 2 * math.pi * f_Hz
    return omega**2 * M_E * EPS_0 / E_CHARGE**2


def appleton_hartree_attenuation_dB(
    ne_m3: float, nu_collision_Hz: float, f_Hz: float, path_length_m: float,
) -> dict:
    """One-way attenuation through a uniform plasma slab.

    Uses the FULL Appleton-Hartree complex refractive index — correct in
    all three regimes (collisionless evanescent, collisionless
    propagating, heavily collisional with ν > ω). For an unmagnetized
    cold plasma:

        n² = 1 - ω_p² / (ω(ω - iν))

    Splitting into real and imaginary parts:
        Re(n²) = 1 - ω_p²/(ω² + ν²)
        Im(n²) = -ω_p² ν / (ω(ω² + ν²))

    Then n_r² = ½[Re(n²) + |n²|], n_i² = ½[-Re(n²) + |n²|], and the
    power attenuation rate is α = 2·k_0·n_i in nepers/m, ×8.686 for dB/m.

    Regime classification (informational only — formula is unified):
      'evanescent'    : ω < ω_p, ν << ω_p  (overdense, mostly reflected)
      'collisional'   : ν > ω               (heavy collision damping;
                                             α ∝ √(ω·ω_p²/ν) → INCREASES
                                             with f; this is the regime
                                             VHF radar through hypersonic
                                             sheaths typically lives in)
      'propagating'   : ω > ω_p, ν << ω    (transparent, weak absorption)
    """
    if ne_m3 <= 0:
        return {"alpha_dB_per_m": 0.0, "atten_dB": 0.0,
                 "f_p_Hz": 0.0, "regime": "no plasma",
                 "detection_status": "DETECTABLE"}

    omega_p = math.sqrt(ne_m3 * E_CHARGE**2 / (M_E * EPS_0))
    omega = 2.0 * math.pi * f_Hz
    nu = max(nu_collision_Hz, 1e3)

    omega_p2 = omega_p * omega_p
    denom = omega * omega + nu * nu
    re_n2 = 1.0 - omega_p2 / denom
    im_n2 = -omega_p2 * nu / (omega * denom)
    abs_n2 = math.sqrt(re_n2 * re_n2 + im_n2 * im_n2)
    n_i = math.sqrt(max(0.5 * (-re_n2 + abs_n2), 0.0))
    k0 = omega / C_LIGHT
    alpha_np = 2.0 * k0 * n_i      # power, nepers/m
    alpha_dB = 8.686 * alpha_np    # power, dB/m
    atten = alpha_dB * path_length_m

    if nu > omega:
        regime = "collisional"
    elif omega < omega_p:
        regime = "evanescent"
    else:
        regime = "propagating"

    if atten >= 20.0:
        status = "BLACKOUT"
    elif atten >= 2.0:
        status = "DEGRADED"
    else:
        status = "DETECTABLE"

    return {"alpha_dB_per_m": alpha_dB, "atten_dB": atten,
             "f_p_Hz": omega_p / (2 * math.pi), "regime": regime,
             "detection_status": status}
