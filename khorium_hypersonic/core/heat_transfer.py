"""Stagnation-point convective heat transfer (Fay-Riddell 1958).

The Fay-Riddell formula gives the wall heat flux at the stagnation point
of a blunt body in dissociated air:

    q_w = 0.94 · (ρ_e μ_e)^0.4 · (ρ_w μ_w)^0.1 · √(du_e/dx)|_stag
        · [h_aw - h_w] · [1 + (Le^a - 1) · (h_d / h_aw)]

For most engineering purposes the simplified Fay-Riddell-Sutton form is
used:

    q_w ≈ 0.763 · Pr^(-0.6) · (ρ_e μ_e)^0.5 · √(du_e/dx)|_stag
        · (h_aw - h_w)

with the velocity-gradient at the stagnation point obtained from
modified Newtonian theory:

    du_e/dx |_stag = (1/R_n) · √(2(p_t - p_∞)/ρ_t)

This makes q_w scale as **R_n^(-0.5)** — geometry enters chemistry via
this scaling: smaller nose → higher q_w → hotter wall → different
boundary-layer chemistry.

References
----------
- Fay, J.A., Riddell, F.R. (1958). "Theory of Stagnation Point Heat
  Transfer in Dissociated Air." J. Aero. Sci. 25(2), 73-85.
- Sutton, K. (1985). "Air radiation revisited." AIAA-85-1037.
- Anderson 2006, "Hypersonic and High-Temperature Gas Dynamics" §6.7.
"""
from __future__ import annotations

import math

from .constants import GAMMA_AIR


def fay_riddell_qw(
    rho_e_kgm3: float,
    mu_e_Pa_s: float,
    rho_w_kgm3: float,
    mu_w_Pa_s: float,
    h_aw_J_per_kg: float,
    h_w_J_per_kg: float,
    R_n_m: float,
    p_t_Pa: float,
    p_inf_Pa: float,
    rho_t_kgm3: float,
    Pr: float = 0.71,
    Le: float = 1.4,
    h_d_J_per_kg: float = 0.0,
    a: float = 0.52,
) -> dict:
    """Fay-Riddell stagnation-point convective heat flux.

    Parameters
    ----------
    rho_e_kgm3, mu_e_Pa_s : boundary-layer edge density / viscosity
        (post-shock, equilibrium-equilibrated state)
    rho_w_kgm3, mu_w_Pa_s : wall density / viscosity (at T_w)
    h_aw_J_per_kg : adiabatic wall enthalpy ≈ stagnation enthalpy
    h_w_J_per_kg  : actual wall enthalpy at T_w
    R_n_m : nose radius
    p_t_Pa : stagnation (Pitot) pressure
    p_inf_Pa : freestream pressure
    rho_t_kgm3 : stagnation density
    Pr : Prandtl number (default 0.71 for air)
    Le : Lewis number (default 1.4)
    h_d_J_per_kg : dissociation enthalpy contribution (default 0;
        set to ~0.5*h_aw for fully-dissociated stagnation)
    a : exponent on Lewis (0.52 for equilibrium catalytic wall, 0.63
        for fully-catalytic)

    Returns
    -------
    dict with q_w_W_per_m2, du_dx_stag (1/s), driving terms.

    For RAM-C M=22.5/61km/R_n=0.1524m typical numbers give q_w in the
    1-5 MW/m² range (matches NASA TM-X-2104 Apollo CM measurements).
    """
    # Velocity gradient at stagnation point (modified Newtonian)
    rho_t = max(rho_t_kgm3, 1e-12)
    pressure_diff = max(p_t_Pa - p_inf_Pa, 0.0)
    du_dx = (1.0 / R_n_m) * math.sqrt(2.0 * pressure_diff / rho_t)

    driving_h = max(h_aw_J_per_kg - h_w_J_per_kg, 0.0)

    # Lewis-number correction factor
    le_correction = 1.0
    if h_d_J_per_kg > 0 and h_aw_J_per_kg > 0:
        le_correction = 1.0 + (Le**a - 1.0) * (h_d_J_per_kg / h_aw_J_per_kg)

    # Fay-Riddell (catalytic wall form)
    q_w = (
        0.763 * Pr**(-0.6)
        * math.sqrt(rho_e_kgm3 * mu_e_Pa_s)
        * (rho_w_kgm3 * mu_w_Pa_s)**0.1 / (rho_e_kgm3 * mu_e_Pa_s)**0.1
        * math.sqrt(du_dx)
        * driving_h
        * le_correction
    )

    return {
        "q_w_W_per_m2": q_w,
        "du_dx_stag_per_s": du_dx,
        "driving_enthalpy_J_per_kg": driving_h,
        "lewis_correction": le_correction,
    }


def boundary_layer_residence_time_s(
    R_n_m: float,
    M_inf: float,
    U_inf_ms: float,
    rho_ratio_eq: float = 14.0,
) -> float:
    """Characteristic residence time of a fluid element in the stagnation BL.

    τ_res ≈ δ / U_e, where δ is the bow-shock standoff (Billig 1967)
    and U_e is the post-shock velocity at the BL edge ≈ U_∞ / ρ_ratio.

    For RAM-C M=22.5/61km/R_n=0.1524m: δ_eq ≈ 9.4mm, U_e ≈ 510 m/s,
    so τ_res ≈ 18 µs. This is the ballpark "kinetics regime"
    residence time the v4 surrogate is trained at (1 µs nominal).

    Geometry sensitivity: τ_res ∝ R_n (linear), so a 10× larger nose
    radius gives 10× more time for chemistry to equilibrate.
    """
    delta_frozen = 0.143 * math.exp(3.24 / (M_inf * M_inf)) * R_n_m
    rho_ratio_frozen = (GAMMA_AIR + 1.0) / (GAMMA_AIR - 1.0)
    delta_eq = delta_frozen * rho_ratio_frozen / rho_ratio_eq
    U_e = U_inf_ms / rho_ratio_eq
    return delta_eq / max(U_e, 1.0)
