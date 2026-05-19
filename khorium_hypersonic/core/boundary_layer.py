"""Boundary layer model — viscous heating + thickness + ne profile.

Closes the gap between the inviscid stagnation estimate and the wall-
resolved chemistry that flight reflectometers actually measure.

Three pieces:

(A) Fay-Riddell stagnation heating — full form with Pr / Le / dissoc
    enthalpy. q_w ∝ R_n^(-0.5), wires geometry into wall heat flux
    and (downstream) into BL chemistry.

(B) Compressible-laminar BL thickness — δ(x) ~ √(μ_e x / (ρ_e U_e))
    on flat-plate-like afterbody, plus a stagnation-region scaling
    δ_stag ~ √(μ_e R_n / (ρ_e U_e)).

(C) Electron-density profile correction — given the inviscid n_e at
    the BL edge, decay smoothly to a near-wall value (recombination-
    dominated) using an erf or exponential profile across δ.

References
----------
Fay & Riddell (1958)              J. Aero. Sci. 25(2), 73-85.
Anderson (2006)                   §6.7 (Hypersonic and High-Temp Gas Dyn).
Park (1990)                       §7.4 — air-plasma BL chemistry.
Sutherland (1893)                 viscosity µ(T) law.
Blottner et al. (1971)            multi-species hypersonic BL coefficients.
"""
from __future__ import annotations

import math
from typing import Literal

import numpy as np

from .constants import GAMMA_AIR, R_AIR


# ── Sutherland's viscosity law (air) ─────────────────────────────────

_MU_REF = 1.716e-5     # Pa·s at T_ref
_T_REF = 273.15        # K
_T_S = 110.4           # K  (Sutherland constant for air)


def air_viscosity(T_K: float) -> float:
    """Sutherland viscosity for air. Valid 200 K - 2000 K (~10% drift
    above; for hypersonic BL edge T > 2000 K consider Blottner)."""
    T_K = max(T_K, 100.0)
    return _MU_REF * (T_K / _T_REF) ** 1.5 * (_T_REF + _T_S) / (T_K + _T_S)


# ── (A) Fay-Riddell stagnation heating ───────────────────────────────

def fay_riddell_full(
    rho_e_kgm3: float, mu_e_Pa_s: float, h_e_J_per_kg: float,
    rho_w_kgm3: float, mu_w_Pa_s: float, h_w_J_per_kg: float,
    R_n_m: float,
    p_t_Pa: float, p_inf_Pa: float, rho_t_kgm3: float,
    Pr: float = 0.71,
    Le: float = 1.4,
    h_d_J_per_kg: float = 0.0,
    catalytic: bool = True,
    sweep_angle_rad: float = 0.0,
) -> dict:
    """Full Fay-Riddell stagnation point heat flux.

    For a fully-catalytic wall:
        q_w = 0.94 · (ρ_e μ_e)^0.4 · (ρ_w μ_w)^0.1 · √(du_e/dx|_stag)
            · (h_e − h_w) · [1 + (Le^a − 1) · h_d / h_e]

    For a non-catalytic wall, replace 0.94 → 0.763 · Pr^(-0.6) and drop
    the Lewis correction (a → 0).

    The velocity-gradient at the stagnation point comes from modified
    Newtonian theory:
        du_e/dx|_stag = (1/R_n) · √(2(p_t - p_∞)/ρ_t)

    Swept-leading-edge attachment-line correction (Beckwith & Gallagher
    1961, NASA TN D-6135; Anderson 2006 §6.6): only the freestream
    component normal to the leading edge drives the bow shock, so the
    stagnation-region velocity gradient — and therefore q_w — scale as
    cos²Λ. With ``sweep_angle_rad = 0`` (the default) the prefactor is
    1.0 and behaviour is identical to the pre-correction form.

    All inputs in SI. Returns dict with q_w (W/m²), du_e_dx (1/s),
    driving_h (J/kg), Le_correction (dimensionless), the regime flag
    ('catalytic' or 'non_catalytic'), and ``sweep_correction`` (cos²Λ)
    for diagnostics.

    The driving enthalpy h_e ≈ h_aw at hypersonic — it's the freestream
    stagnation enthalpy (h_∞ + ½U_∞²), of which the kinetic term
    dominates by 10–100×.
    """
    rho_t = max(rho_t_kgm3, 1e-12)
    dp = max(p_t_Pa - p_inf_Pa, 0.0)
    du_dx = (1.0 / R_n_m) * math.sqrt(2.0 * dp / rho_t)

    driving = max(h_e_J_per_kg - h_w_J_per_kg, 0.0)

    if catalytic:
        prefactor = 0.94
        a_lewis = 0.52
    else:
        prefactor = 0.763 * Pr ** (-0.6)
        a_lewis = 0.0

    # Exponent split: edge-dominated (×0.4) and wall-dominated (×0.1)
    edge_term = (rho_e_kgm3 * mu_e_Pa_s) ** 0.4
    wall_term = (rho_w_kgm3 * mu_w_Pa_s) ** 0.1

    le_correction = 1.0
    if catalytic and h_d_J_per_kg > 0 and h_e_J_per_kg > 0:
        le_correction = 1.0 + (Le ** a_lewis - 1.0) * (h_d_J_per_kg / h_e_J_per_kg)

    sweep = max(min(math.cos(sweep_angle_rad), 1.0), 0.0)
    sweep_correction = sweep * sweep

    q_w = (prefactor * edge_term * wall_term * math.sqrt(du_dx)
           * driving * le_correction * sweep_correction)

    return {
        "q_w_W_per_m2": q_w,
        "du_e_dx_per_s": du_dx,
        "driving_enthalpy_J_per_kg": driving,
        "lewis_correction": le_correction,
        "sweep_correction": sweep_correction,
        "regime": "catalytic" if catalytic else "non_catalytic",
    }


# ── (B) Boundary-layer thickness scalings ────────────────────────────

def bl_thickness_compressible_laminar(
    x_m: float, U_e_ms: float,
    rho_e_kgm3: float, mu_e_Pa_s: float,
    correction: float = 5.0,
) -> float:
    """Blasius-type compressible-laminar BL thickness.

    δ(x) = correction · √(μ_e · x / (ρ_e · U_e))

    For an incompressible flat plate, the prefactor is 5.0 (99% velocity
    boundary layer). For hypersonic compressible flow with strong
    cooling, ~3.0; with strong heating, ~6.0. Caller can override.
    """
    if x_m <= 0 or U_e_ms <= 0 or rho_e_kgm3 <= 0:
        return 0.0
    return correction * math.sqrt(mu_e_Pa_s * x_m / (rho_e_kgm3 * U_e_ms))


def bl_thickness_stagnation(
    R_n_m: float, U_inf_ms: float,
    rho_e_kgm3: float, mu_e_Pa_s: float,
    correction: float = 0.5,
) -> float:
    """Stagnation-region BL thickness (Lees 1956; Anderson 2006 §6.6).

    δ_stag ≈ correction · √(μ_e · R_n / (ρ_e · U_∞))

    Different from the flat-plate scaling because the stagnation flow
    has a velocity gradient set by R_n, not a leading-edge x. The
    correction prefactor depends on Pr and wall-temperature ratio;
    0.5 is a reasonable default for re-entry conditions.
    """
    if R_n_m <= 0 or U_inf_ms <= 0 or rho_e_kgm3 <= 0:
        return 0.0
    return correction * math.sqrt(mu_e_Pa_s * R_n_m / (rho_e_kgm3 * U_inf_ms))


# ── (C) Electron-density profile correction ──────────────────────────

def apply_boundary_layer_correction(
    ne_edge_m3: float, y_m: float | np.ndarray, delta_m: float,
    profile: Literal["exp", "erf"] = "exp",
    wall_fraction: float = 0.05,
) -> float | np.ndarray:
    """Decay ne(y) from edge value to a near-wall value across δ.

    Boundary layer recombination + cold-wall quenching reduce ne at
    the wall to ~5% of edge value (RAM-C reflectometer measurements,
    Huber 1967). We model the profile as a smooth decay from y=δ (edge)
    to y=0 (wall).

    Parameters
    ----------
    ne_edge_m3 : ne at the BL outer edge (the "stagnation" inviscid
        prediction)
    y_m : distance from wall (m). Scalar or array. y=0 at wall.
    delta_m : BL thickness
    profile : 'exp' for ne(y) = ne_w + (ne_e - ne_w) · (1 - exp(-3y/δ))
              'erf' for ne(y) = ne_w + (ne_e - ne_w) · erf(2y/δ)
    wall_fraction : ne_w / ne_e at the wall (0.05 default; RAM-C-class)

    Returns
    -------
    ne(y) — same type as y_m input.
    """
    ne_w = wall_fraction * ne_edge_m3
    if delta_m <= 0:
        return np.full_like(np.asarray(y_m, dtype=np.float64), ne_edge_m3)

    y = np.asarray(y_m, dtype=np.float64)
    eta = np.clip(y / delta_m, 0.0, 1.0)

    if profile == "exp":
        # Saturates at edge value; inverse-exp from wall
        weight = 1.0 - np.exp(-3.0 * eta)
    elif profile == "erf":
        from scipy.special import erf
        weight = erf(2.0 * eta)
    else:
        raise ValueError(f"profile must be 'exp' or 'erf', got {profile!r}")

    out = ne_w + (ne_edge_m3 - ne_w) * weight
    if np.isscalar(y_m):
        return float(out)
    return out


def bl_summary(
    R_n_m: float, U_inf_ms: float,
    rho_e_kgm3: float, T_e_K: float,
    rho_w_kgm3: float, T_w_K: float,
    h_e_J_per_kg: float, h_w_J_per_kg: float,
    p_t_Pa: float, p_inf_Pa: float, rho_t_kgm3: float,
    h_d_J_per_kg: float = 0.0,
    Pr: float = 0.71, Le: float = 1.4,
    sweep_angle_rad: float = 0.0,
) -> dict:
    """One-shot bundle: q_w, δ_stag, BL edge state. Used by solver.py.

    Pass ``sweep_angle_rad`` for swept-LE strips; 0 keeps the unswept
    behaviour. The strip aggregator wires per-strip local sweep angle
    through here so attachment-line heating is no longer over-predicted
    by a factor of (1 − cos²Λ) ≈ 0.75 – 0.93 on 60 – 75° swept LEs.
    """
    mu_e = air_viscosity(T_e_K)
    mu_w = air_viscosity(T_w_K)
    qw = fay_riddell_full(
        rho_e_kgm3=rho_e_kgm3, mu_e_Pa_s=mu_e, h_e_J_per_kg=h_e_J_per_kg,
        rho_w_kgm3=rho_w_kgm3, mu_w_Pa_s=mu_w, h_w_J_per_kg=h_w_J_per_kg,
        R_n_m=R_n_m, p_t_Pa=p_t_Pa, p_inf_Pa=p_inf_Pa,
        rho_t_kgm3=rho_t_kgm3,
        Pr=Pr, Le=Le, h_d_J_per_kg=h_d_J_per_kg,
        catalytic=True,
        sweep_angle_rad=sweep_angle_rad,
    )
    delta_stag = bl_thickness_stagnation(R_n_m, U_inf_ms, rho_e_kgm3, mu_e)
    return {
        **qw,
        "delta_stag_m": delta_stag,
        "mu_e_Pa_s": mu_e,
        "mu_w_Pa_s": mu_w,
    }
