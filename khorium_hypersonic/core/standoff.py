"""Bow-shock standoff distance (Billig 1967 + alternatives).

Reference: Billig 1967, AIAA-67-148, "Shock-wave shapes around
spherical- and cylindrical-nosed bodies", J. Spacecraft & Rockets
4(6), 822-823.

    δ_frozen / R_n = 0.143 · exp(3.24 / M²)

Equilibrium correction:
    δ_eq ≈ δ_frozen · (ρ_2_frozen / ρ_2_eq)

where ρ_2_frozen / ρ_∞ = (γ+1)/(γ-1) = 6 for γ = 1.4 in the strong-shock
limit, and ρ_2_eq / ρ_∞ ≈ 14 at M = 20+ when chemistry is fully
equilibrated.

This module is geometry-aware in that it accepts ANY nose radius. The
RAM-C-specific historical defaults are gone — the only parameter is R_n.
"""
import math

from .constants import GAMMA_AIR


def billig_sphere_standoff(
    M_inf: float, R_n_m: float,
    rho_ratio_eq: float = 14.0,
    gamma: float = GAMMA_AIR,
) -> dict:
    """Billig 1967 bow-shock standoff for a spherical nose.

    Parameters
    ----------
    M_inf : freestream Mach number
    R_n_m : nose radius (m)
    rho_ratio_eq : equilibrium post-shock density ratio ρ₂/ρ_∞
        Defaults to 14 (typical at M=20+ with full equilibrium chemistry).
        Set to 6 to recover the frozen-chemistry Billig result.

    Returns
    -------
    dict with delta_frozen_m, delta_eq_m, ratio_freeze_to_eq.
    """
    delta_frozen = 0.143 * math.exp(3.24 / (M_inf * M_inf)) * R_n_m
    rho_ratio_frozen = (gamma + 1) / (gamma - 1)   # = 6 for γ=1.4
    delta_eq = delta_frozen * rho_ratio_frozen / rho_ratio_eq
    return {
        "delta_frozen_m": delta_frozen,
        "delta_eq_m": delta_eq,
        "rho_ratio_eq": rho_ratio_eq,
        "rho_ratio_frozen": rho_ratio_frozen,
    }
