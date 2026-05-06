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

    Parameters
    ----------
    ne_m3 : electron number density (m⁻³)
    nu_collision_Hz : electron-neutral collision frequency
    f_Hz : radar carrier frequency
    path_length_m : thickness of plasma slab the ray traverses

    Returns
    -------
    dict with alpha_dB_per_m, atten_dB, f_p_Hz, regime ('evanescent' or
    'propagating') and detection_status string ('DETECTABLE'/'DEGRADED'/
    'BLACKOUT' using 2 dB and 20 dB thresholds).
    """
    if ne_m3 <= 0:
        return {"alpha_dB_per_m": 0.0, "atten_dB": 0.0,
                 "f_p_Hz": 0.0, "regime": "no plasma",
                 "detection_status": "DETECTABLE"}

    omega_p = math.sqrt(ne_m3 * E_CHARGE**2 / (M_E * EPS_0))
    omega = 2 * math.pi * f_Hz
    nu = max(nu_collision_Hz, 1e3)

    if omega < omega_p:
        # Evanescent: spatial decay ω/c · √(ω_p²/ω² - 1)
        # (collisionless limit; collisions reduce alpha slightly)
        k_imag = (omega / C_LIGHT) * math.sqrt(omega_p**2 / omega**2 - 1)
        alpha_np = k_imag
        regime = "evanescent"
    else:
        alpha_np = (omega_p**2 * nu) / (2 * C_LIGHT * (omega**2 + nu**2))
        regime = "propagating"

    alpha_dB = 8.686 * alpha_np
    atten = alpha_dB * path_length_m

    if atten >= 20.0:
        status = "BLACKOUT"
    elif atten >= 2.0:
        status = "DEGRADED"
    else:
        status = "DETECTABLE"

    return {"alpha_dB_per_m": alpha_dB, "atten_dB": atten,
             "f_p_Hz": omega_p / (2 * math.pi), "regime": regime,
             "detection_status": status}
