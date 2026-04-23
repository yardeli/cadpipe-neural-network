"""Plasma wave propagation — complex refractive index and attenuation.

Replaces the binary `fp > f_radar → BLACKOUT` criterion with a proper
treatment of wave propagation in a collisional plasma. For a plane wave of
angular frequency ω propagating through an unmagnetized electron-ion plasma
with electron-neutral collision frequency ν_c, the complex refractive index
squared is (Gurevich 1978, §2; Budden 1985, §3.5):

    n² = 1 − ω_p² / (ω(ω − iν_c))

where ω_p² = n_e e² / (m_e ε_0).

Rearranging into real and imaginary parts (ω > 0, ν_c ≥ 0, n_e ≥ 0):

    Re(n²) = 1 − ω_p² / (ω² + ν_c²)
    Im(n²) = − ω_p² ν_c / (ω (ω² + ν_c²))

so n = n_r + i·n_i with

    n_r² = ½ [ Re(n²) + √(Re² + Im²) ]
    n_i² = ½ [ −Re(n²) + √(Re² + Im²) ]

Attenuation rate (power, dB per metre) along a ray:
    α_dB/m = 8.686 · k_0 · n_i     where k_0 = ω/c

Phase delay rate (rad per metre):
    β = k_0 · n_r

These are the quantities that must be integrated along a radar line of sight
to compute the total one-way attenuation in dB and total phase shift. See
line_of_sight.py for the integrator.

This module is pure numpy — no external deps. All quantities in SI.

References
----------
- Gurevich, A.V. (1978), "Nonlinear Phenomena in the Ionosphere", Springer.
- Budden, K.G. (1985), "The Propagation of Radio Waves", Cambridge.
- Huber, P.W. (1967), NASA TN D-4750 — RAM-C flight data and analysis.
- Rybak & Churchill (1971), "Progress in reentry communications", IEEE Trans.
  Aerospace Electron. Systems AES-7(5).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .physics import K_B, M_E, E_CHARGE, EPS_0, C_LIGHT


def plasma_frequency_rad_s(n_e: np.ndarray | float) -> np.ndarray | float:
    """Electron plasma angular frequency ω_p (rad/s) from electron density (m⁻³).

    ω_p = sqrt(n_e · e² / (m_e · ε_0))
    """
    n_e = np.maximum(n_e, 0.0)
    return np.sqrt(n_e * E_CHARGE * E_CHARGE / (M_E * EPS_0))


def refractive_index(
    n_e: np.ndarray | float,
    nu_c: np.ndarray | float,
    f_hz: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Complex refractive index n = n_r + i·n_i in a collisional plasma.

    Parameters
    ----------
    n_e : electron density (m⁻³). Scalar or array.
    nu_c : electron-neutral collision frequency (s⁻¹). Scalar or array,
           broadcast-compatible with n_e.
    f_hz : radar frequency (Hz). Scalar. (Broadcasting over frequency is
           left to the caller; doing it here obscures the typical use case.)

    Returns
    -------
    n_r, n_i : arrays of the same shape as n_e/nu_c.
        n_r is the real refractive index (phase speed = c/n_r).
        n_i is the absorption index (power attenuation rate = 2·k_0·n_i).

    Notes
    -----
    - Below the collisionless cutoff (ω < ω_p, ν_c → 0) the wave is
      evanescent: n_r → 0, n_i → √(ω_p²/ω² − 1). The magnitude of the
      reflection coefficient → 1, i.e. a pure reflector.
    - Well above cutoff with ν_c = 0, n_r → √(1 − ω_p²/ω²), n_i → 0.
      Transparent, no absorption.
    - ν_c introduces absorption between those limits. Absorption is
      maximised roughly where ν_c ~ ω.
    """
    n_e_arr = np.asarray(n_e, dtype=np.float64)
    nu_c_arr = np.asarray(nu_c, dtype=np.float64)

    omega = 2.0 * math.pi * f_hz
    omega_p2 = n_e_arr * E_CHARGE * E_CHARGE / (M_E * EPS_0)
    denom = omega * omega + nu_c_arr * nu_c_arr

    # Guard against denom == 0 (occurs only when omega=0 and nu_c=0)
    denom_safe = np.where(denom > 0, denom, 1.0)
    re_n2 = 1.0 - omega_p2 / denom_safe
    # Im(n²) is defined with convention e^(−iωt); absorption → Im(n²) < 0
    im_n2 = -omega_p2 * nu_c_arr / (omega * denom_safe + 1e-300)

    abs_n2 = np.sqrt(re_n2 * re_n2 + im_n2 * im_n2)
    n_r2 = 0.5 * (re_n2 + abs_n2)
    n_i2 = 0.5 * (-re_n2 + abs_n2)
    # Clip tiny negatives from roundoff
    n_r = np.sqrt(np.maximum(n_r2, 0.0))
    n_i = np.sqrt(np.maximum(n_i2, 0.0))
    return n_r, n_i


def attenuation_rate_db_per_m(
    n_e: np.ndarray | float,
    nu_c: np.ndarray | float,
    f_hz: float,
) -> np.ndarray:
    """Power attenuation rate in dB/m. One-way (single traversal)."""
    _, n_i = refractive_index(n_e, nu_c, f_hz)
    k0 = 2.0 * math.pi * f_hz / C_LIGHT
    # 10·log10(e^(-2·k0·n_i·dx)) per metre = −20·log10(e)·k0·n_i = −8.6859·k0·n_i
    # The sign convention here: return positive number = attenuation magnitude.
    return 8.685889638065035 * 2.0 * k0 * n_i


def phase_rate_rad_per_m(
    n_e: np.ndarray | float,
    nu_c: np.ndarray | float,
    f_hz: float,
) -> np.ndarray:
    """Phase delay rate (rad/m) relative to free space."""
    n_r, _ = refractive_index(n_e, nu_c, f_hz)
    k0 = 2.0 * math.pi * f_hz / C_LIGHT
    return k0 * (n_r - 1.0)


def reflection_coefficient_normal(
    n_e: float,
    nu_c: float,
    f_hz: float,
) -> complex:
    """Fresnel reflection coefficient for normal incidence on a sharp
    vacuum→plasma interface. (Vehicle skin is a separate reflection
    problem — this is for estimating plasma-layer reflection at its
    outer boundary.) For a uniform plasma half-space the result is:
        r = (1 − n) / (1 + n)
    where n is the complex refractive index.
    """
    n_r, n_i = refractive_index(n_e, nu_c, f_hz)
    n_complex = complex(float(n_r), float(n_i))
    return (1.0 - n_complex) / (1.0 + n_complex)


@dataclass
class WaveResult:
    """Snapshot of wave properties at one point in the plasma."""
    n_e_m3: float
    nu_c_hz: float
    f_hz: float
    n_r: float
    n_i: float
    attenuation_db_per_m: float
    phase_rate_rad_per_m: float
    omega_p_rad_s: float
    regime: str  # 'vacuum', 'overdense', 'underdense', 'collisional'

    @classmethod
    def compute(cls, n_e: float, nu_c: float, f_hz: float) -> "WaveResult":
        n_r, n_i = refractive_index(n_e, nu_c, f_hz)
        omega_p = float(plasma_frequency_rad_s(n_e))
        omega = 2.0 * math.pi * f_hz
        if n_e < 1.0:
            regime = "vacuum"
        elif nu_c > 0.3 * omega:
            regime = "collisional"
        elif omega_p > omega:
            regime = "overdense"  # below cutoff: reflective
        else:
            regime = "underdense"  # above cutoff: transparent
        return cls(
            n_e_m3=float(n_e),
            nu_c_hz=float(nu_c),
            f_hz=f_hz,
            n_r=float(n_r),
            n_i=float(n_i),
            attenuation_db_per_m=float(attenuation_rate_db_per_m(n_e, nu_c, f_hz)),
            phase_rate_rad_per_m=float(phase_rate_rad_per_m(n_e, nu_c, f_hz)),
            omega_p_rad_s=omega_p,
            regime=regime,
        )


# ── Detectability thresholds ─────────────────────────────────────────────
# A radar link can handle some one-way attenuation before SNR collapses.
# Typical link-budget margins for satellite radar:
#   < 3 dB   — fully detectable, normal tracking
#   3 − 15 dB — degraded, tracking possible but uncertain
#   > 15 dB  — effective blackout; target below detection threshold
# The precise threshold depends on radar PRF, antenna gain, target RCS, etc.
# These cutoffs are a reasonable first cut for StarLink-class Ku-band and
# are the defensible replacement for the previous `fp > 12 GHz` binary.

THRESHOLD_DETECTABLE_DB = 3.0
THRESHOLD_BLACKOUT_DB = 15.0


def detection_status(attenuation_db: float) -> str:
    """Detection status from one-way path-integrated attenuation (dB).

    Parameters
    ----------
    attenuation_db : total one-way attenuation along the radar line of sight,
        integrated through the plasma sheath, in dB.

    Returns
    -------
    'DETECTABLE' | 'DEGRADED' | 'BLACKOUT'
    """
    if attenuation_db < THRESHOLD_DETECTABLE_DB:
        return "DETECTABLE"
    if attenuation_db < THRESHOLD_BLACKOUT_DB:
        return "DEGRADED"
    return "BLACKOUT"
