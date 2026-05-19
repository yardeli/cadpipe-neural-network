"""Geometry-resolved axial flowfield.

Walks an axial discretization of the body and computes, at each station:
  - local edge-state (T, ρ, U) from local shock obliquity
  - local residence time τ(x) = δ_local / U_e_local
  - local electron density ne(x) from kinetics-mode chemistry

Replaces the "single stagnation-point estimator" mode of the v0.2.0
solver. Output is a full axial profile, which downstream code uses for:

  - sheath-wrapping with a non-uniform ne(r, z) field (instead of the
    smooth analytical decay)
  - LOS attenuation that captures the actual ne distribution along the
    body (different aspect angles see different parts of the body)
  - blackout interval detection (when does ne drop below f_p² along
    the trajectory?)

This module replaces the "stagnation-only" pipeline with a proper
geometry-resolved one, while still being callable for a single-point
analysis when n_stations=1.

References
----------
Anderson 2006 (Modern Compressible Flow): oblique shock relations.
Park 1990 (Nonequilibrium Hypersonic Aerothermodynamics): air-plasma
chemistry along blunt-body streamlines.
Bertin 1994 (Hypersonic Aerothermodynamics): local shock approx for
sphere-cone.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Literal, Optional

import numpy as np

from .atmosphere import standard_atmosphere
from .shock import normal_shock_frozen
from .stagnation import pitot_pressure, stagnation_T_real_gas
from .constants import GAMMA_AIR, R_AIR, K_B
from .standoff import billig_sphere_standoff
from .chemistry import saha_ne, janaf_air_equilibrium
from .kinetics import cantera_residence_time_ne


_NORMAL_SHOCK_THRESHOLD_DEG = 30.0   # surface-angle gate for the normal-shock branch
_NORMAL_SHOCK_CURVATURE_GATE = 0.5   # min (local_curvature × R_nose_eff) for the normal-shock branch:
                                     # only fire on regions with meaningful curvature (sphere-cap nose),
                                     # never on a flat conical face. Without this, every cone with
                                     # half-angle ≥ 30° (e.g. the `capsule` preset) silently picked up
                                     # stagnation T on every afterbody station, producing the
                                     # 3.16e+22 M22.5/61 km afterbody anomaly in GCP_VERIFY_V0_3_0 §4.


# ── Local shock helpers ──────────────────────────────────────────────

def oblique_shock_post(
    M1: float, theta_deflection_rad: float, gamma: float = GAMMA_AIR,
) -> dict:
    """Post-shock state behind an oblique shock at deflection angle θ.

    Iteratively solves the θ-β-M relation (Anderson 2006 Eq. 4.17):
        tan(θ) = 2·cot(β)·(M²·sin²β − 1)/(M²(γ + cos(2β)) + 2)
    for the shock-wave angle β, then applies normal-shock relations
    across the shock-normal Mach component.

    Returns dict with M2, p_ratio, T_ratio, rho_ratio, beta_rad, or
    None if the shock is detached (θ > θ_max — vertex of the θ-β-M
    polar). Detached → caller should fall back to normal-shock
    treatment of that station.
    """
    M = M1
    g = gamma
    th = theta_deflection_rad
    if th >= math.pi / 2 - 1e-3:
        # Effectively normal shock
        sh = normal_shock_frozen(M, T1_K=1.0, P1_Pa=1.0, rho1_kgm3=1.0, gamma=g)
        return {**sh, "beta_rad": math.pi / 2.0}

    # Bisect for β in [θ + tiny, π/2)
    beta_lo = th + 1e-4
    beta_hi = math.pi / 2.0 - 1e-4
    M2sq = M * M
    for _ in range(60):
        beta = 0.5 * (beta_lo + beta_hi)
        rhs = (2.0 / math.tan(beta)) * (M2sq * math.sin(beta)**2 - 1.0) \
              / (M2sq * (g + math.cos(2 * beta)) + 2.0)
        if rhs < math.tan(th):
            beta_lo = beta
        else:
            beta_hi = beta
    beta = 0.5 * (beta_lo + beta_hi)

    Mn1 = M * math.sin(beta)
    if Mn1 <= 1.0:
        return None     # shock is detached / not feasible at this θ
    Mn1sq = Mn1 * Mn1
    p_ratio = (2 * g * Mn1sq - (g - 1)) / (g + 1)
    rho_ratio = (g + 1) * Mn1sq / ((g - 1) * Mn1sq + 2)
    T_ratio = p_ratio / rho_ratio
    Mn2sq = ((g - 1) * Mn1sq + 2) / (2 * g * Mn1sq - (g - 1))
    Mn2 = math.sqrt(Mn2sq)
    M2 = Mn2 / math.sin(beta - th)
    return {
        "M2": M2, "p_ratio": p_ratio, "T_ratio": T_ratio,
        "rho_ratio": rho_ratio, "beta_rad": beta,
    }


# ── Profile dataclass ────────────────────────────────────────────────

@dataclass
class AxialStation:
    x_m: float
    surface_angle_deg: float
    local_radius_m: float
    local_curvature_per_m: float
    shock_kind: str       # 'normal' or 'oblique'
    T_e_K: float          # post-shock edge temperature
    P_e_Pa: float
    rho_e_kgm3: float
    U_e_ms: float
    delta_local_m: float  # local shock standoff / sheath thickness
    tau_residence_s: float
    ne_m3: float
    fp_GHz: float


@dataclass
class AxialProfile:
    """Geometry-resolved axial flowfield + chemistry."""
    stations: list[AxialStation] = field(default_factory=list)
    geometry_name: str = ""
    mach: float = 0.0
    altitude_km: float = 0.0
    chemistry_mode: str = "kinetics"

    @property
    def x_m(self) -> np.ndarray:
        return np.array([s.x_m for s in self.stations])

    @property
    def ne_m3(self) -> np.ndarray:
        return np.array([s.ne_m3 for s in self.stations])

    @property
    def T_e_K(self) -> np.ndarray:
        return np.array([s.T_e_K for s in self.stations])

    @property
    def tau_residence_s(self) -> np.ndarray:
        return np.array([s.tau_residence_s for s in self.stations])

    @property
    def delta_local_m(self) -> np.ndarray:
        return np.array([s.delta_local_m for s in self.stations])

    @property
    def fp_GHz(self) -> np.ndarray:
        return np.array([s.fp_GHz for s in self.stations])

    def peak_ne(self) -> tuple[float, float]:
        """Return (x_at_peak, ne_peak)."""
        if not self.stations:
            return (0.0, 0.0)
        i = int(np.argmax(self.ne_m3))
        return (self.stations[i].x_m, self.stations[i].ne_m3)


# ── Top-level driver ─────────────────────────────────────────────────

def compute_axial_profile(
    geometry,
    mach: float,
    altitude_km: float,
    n_stations: int = 50,
    chemistry_mode: Literal["equilibrium", "kinetics", "auto"] = "kinetics",
    rho_ratio_eq: float = 14.0,
    debug: bool = False,
) -> AxialProfile:
    """Build the axial flowfield for `geometry` at flight condition.

    Walks geometry.axial_stations(n_stations), and at each x:
      1. Reads geometry surface angle and curvature
      2. Picks normal-shock (blunt regions) or oblique-shock (slender)
         post-shock state from freestream
      3. Computes local sheath thickness from Billig-style scaling on
         the local effective radius (1/curvature for blunt regions,
         R_n for the nose, otherwise body radius)
      4. Computes local residence time τ = δ_local / U_e
      5. Calls cantera_residence_time_ne() at (T_e, P_e, τ) for ne

    Returns an AxialProfile carrying full per-station detail. Use
    profile.peak_ne() for stagnation-equivalent, profile.ne_m3 for the
    full distribution along the body.

    `chemistry_mode='auto'` falls back to equilibrium Saha if Cantera
    isn't available.
    """
    fs = standard_atmosphere(altitude_km)
    U_inf = mach * fs["a_ms"]

    # Stagnation-line baseline (for normal-shock fallback)
    sh_stag = normal_shock_frozen(mach, fs["T_K"], fs["P_Pa"], fs["rho_kgm3"])
    P_t = pitot_pressure(fs["P_Pa"], mach)

    # Real-gas stagnation T — chemistry absorbs ~70% of the kinetic energy at
    # M=22.5, so frozen T_2 ≈ 24,000 K drops to ~6,200 K under Cantera
    # equilibration. We use this T for normal-shock stations (the body
    # stagnation region) where the post-shock flow has decelerated to zero.
    rg = stagnation_T_real_gas(
        T_inf_K=fs["T_K"], P_inf_Pa=fs["P_Pa"], U_inf_ms=U_inf, P_t_Pa=P_t,
    )
    T_stag_real = rg.get("T_t_real_K", sh_stag["T2_K"])
    rho_e_stag = P_t / (R_AIR * max(T_stag_real, 300.0))

    # Pre-compute the real-gas post-shock T for the body's effective
    # oblique half-angle, mirroring T_stag_real on the normal branch.
    # The oblique-shock energy budget is ½(U_inf² − U_2²); we re-use the
    # stagnation Cantera bisection with an "effective" inflow velocity
    # ``U_eff = sqrt(U_inf² − U_2²)`` and the actual oblique post-shock
    # pressure. Without this the conical afterbody of high-half-angle
    # bodies (e.g. the capsule preset, half-angle 30°) carries a
    # **frozen** T ≈ 9000 K into the kinetics reactor — chemistry never
    # gets to absorb the dissociation enthalpy — and over-predicts ne
    # by an order of magnitude (GCP_VERIFY_V0_3_0 §4 anomaly).
    ha_eff_rad = math.radians(getattr(geometry, "effective_half_angle_deg",
                                       lambda: 9.0)())
    _ob_eff = oblique_shock_post(mach, ha_eff_rad)
    if _ob_eff is None:
        T_oblique_real = T_stag_real
    else:
        beta_eff = _ob_eff["beta_rad"]
        P_obl_eff = fs["P_Pa"] * _ob_eff["p_ratio"]
        U_n1 = U_inf * math.sin(beta_eff)
        U_n2 = U_n1 / max(_ob_eff["rho_ratio"], 1e-9)
        U_t = U_inf * math.cos(beta_eff)
        U_2 = math.sqrt(U_n2 * U_n2 + U_t * U_t)
        U_eff = math.sqrt(max(U_inf * U_inf - U_2 * U_2, 0.0))
        rg_obl = stagnation_T_real_gas(
            T_inf_K=fs["T_K"], P_inf_Pa=fs["P_Pa"],
            U_inf_ms=U_eff, P_t_Pa=P_obl_eff,
        )
        T_oblique_real = rg_obl.get(
            "T_t_real_K", max(fs["T_K"] * _ob_eff["T_ratio"], fs["T_K"]),
        )

    stations: list[AxialStation] = []
    xs = geometry.axial_stations(n_stations)

    for x in xs:
        # Geometry queries
        try:
            surf_angle_rad = geometry.surface_angle(x)
        except Exception:
            surf_angle_rad = math.pi / 2.0
        surf_deg = math.degrees(surf_angle_rad)
        try:
            r_local = geometry.local_radius(x)
        except Exception:
            r_local = 0.0
        try:
            curv = geometry.local_curvature(x)
        except Exception:
            curv = 0.0

        # Effective radius for local sheath standoff
        if curv > 1e-6:
            R_eff = 1.0 / curv
        elif r_local > 1e-6:
            R_eff = r_local
        else:
            R_eff = geometry.effective_nose_radius_m()

        # Local shock — pick normal vs oblique. Edge temperature uses
        # real-gas stagnation T for normal-shock regions (chemistry-
        # absorbs energy), real-gas-corrected T for oblique by scaling
        # the frozen oblique result by (T_real / T_frozen_normal).
        #
        # Normal-shock treatment is appropriate only at near-stagnation
        # points: surface highly normal to flow AND meaningful local
        # curvature. A conical afterbody at half-angle ≥ 30° has the
        # surface-angle criterion satisfied but ~zero meridional
        # curvature — flow is obliquely turned, not brought to rest —
        # so it falls through to the oblique branch.
        curvature_scale = curv * geometry.effective_nose_radius_m()
        if (surf_deg >= _NORMAL_SHOCK_THRESHOLD_DEG
                and curvature_scale >= _NORMAL_SHOCK_CURVATURE_GATE):
            shock_kind = "normal"
            T_e = T_stag_real
            P_e = P_t
            rho_e = rho_e_stag
            U_e = U_inf / sh_stag["rho_ratio"]
        else:
            theta = max(surf_angle_rad, 1e-3)
            ob = oblique_shock_post(mach, theta)
            if ob is None:
                shock_kind = "normal"
                T_e = T_stag_real; P_e = P_t
                rho_e = rho_e_stag; U_e = U_inf / sh_stag["rho_ratio"]
            else:
                shock_kind = "oblique"
                # Real-gas-corrected post-oblique-shock T. The frozen
                # value `fs_T × ob[T_ratio]` overstates the local T by
                # 30–50% on strong oblique shocks (e.g. M=22.5, θ=30°
                # gives 9070 K frozen vs ~5500 K equilibrated) because
                # N2 / O2 dissociation absorbs a large fraction of the
                # post-shock thermal enthalpy. ``T_oblique_real`` is the
                # body-effective real-gas value precomputed above; we
                # take the larger of it and the local-θ frozen T to keep
                # the small-angle-shock limit intact.
                T_frozen_local = max(fs["T_K"] * ob["T_ratio"], fs["T_K"])
                T_e = min(T_frozen_local, max(T_oblique_real, fs["T_K"]))
                P_e = fs["P_Pa"] * ob["p_ratio"]
                rho_e = P_e / (R_AIR * max(T_e, 300.0))
                U_e = U_inf * math.cos(ob["beta_rad"])  # tangential preserved

        # Local sheath thickness — Billig on R_eff
        bil = billig_sphere_standoff(M_inf=mach, R_n_m=R_eff,
                                       rho_ratio_eq=rho_ratio_eq)
        delta_local = bil["delta_eq_m"]

        # Residence time (avoid divide-by-zero)
        tau = delta_local / max(U_e, 1.0)

        # Chemistry — kinetics or equilibrium
        ne_local = _chemistry_at_station(
            T_e, P_e, tau, chemistry_mode,
        )

        from .plasma import plasma_frequency_GHz
        fp = plasma_frequency_GHz(ne_local)

        if debug:
            print(f"  x={x*1000:>7.1f}mm  angle={surf_deg:>5.1f}°  "
                  f"R_eff={R_eff*1000:>5.1f}mm  shock={shock_kind:>7s}  "
                  f"T_e={T_e:>5.0f}K  τ={tau*1e6:>5.1f}µs  "
                  f"ne={ne_local:.2e}  fp={fp:.1f}GHz")

        stations.append(AxialStation(
            x_m=x, surface_angle_deg=surf_deg,
            local_radius_m=r_local, local_curvature_per_m=curv,
            shock_kind=shock_kind,
            T_e_K=T_e, P_e_Pa=P_e, rho_e_kgm3=rho_e, U_e_ms=U_e,
            delta_local_m=delta_local, tau_residence_s=tau,
            ne_m3=ne_local, fp_GHz=fp,
        ))

    return AxialProfile(
        stations=stations, geometry_name=geometry.name,
        mach=mach, altitude_km=altitude_km,
        chemistry_mode=chemistry_mode,
    )


# ── Per-station chemistry dispatch ───────────────────────────────────

_CANTERA_AVAILABLE: Optional[bool] = None


def _check_cantera():
    global _CANTERA_AVAILABLE
    if _CANTERA_AVAILABLE is None:
        try:
            import cantera   # noqa: F401
            _CANTERA_AVAILABLE = True
        except ImportError:
            _CANTERA_AVAILABLE = False
    return _CANTERA_AVAILABLE


def _chemistry_at_station(
    T_K: float, P_Pa: float, tau_s: float,
    mode: Literal["equilibrium", "kinetics", "auto"],
) -> float:
    """Compute ne at one station via the requested chemistry mode."""
    if mode == "auto":
        # tau >> 100 µs → near equilibrium; Cantera kinetics otherwise
        if tau_s > 1e-3 or not _check_cantera():
            mode = "equilibrium"
        else:
            mode = "kinetics"

    if mode == "kinetics" and _check_cantera():
        kin = cantera_residence_time_ne(
            T_initial_K=T_K, P_initial_Pa=P_Pa,
            residence_time_s=tau_s, n_steps=20,
        )
        if "error" not in kin and kin.get("ne_m3", 0) > 0:
            return float(kin["ne_m3"])

    # Equilibrium fallback — Saha at JANAF mole fractions
    eq = janaf_air_equilibrium(T_K, P_Pa)
    s = saha_ne(T_K=T_K, P_Pa=P_Pa,
                  x_N=eq["x_N"], x_O=eq["x_O"], x_NO=eq["x_NO"])
    return float(s["ne_m3"])


# ── Axial profile → AxisymmetricField for LOS integration ────────────

def axial_profile_to_field(
    profile: AxialProfile,
    decay_normal: Literal["exp", "gauss"] = "gauss",
):
    """Wrap an AxialProfile as a callable axisymmetric (ne, ν_c) field.

    The body axis is aligned with z (consistent with
    plasmanet.line_of_sight). At radial distance r from the axis at
    axial position z, we:
      1. Look up ne(z) by linear interpolation on the profile
      2. Apply a Gaussian or exponential radial decay across δ_local(z)
         from peak ne at the body to ~0 at the shock front
      3. Set ν_c from the local edge state (P/k_B/T) × ν_collision_xs

    Returns an AxisymmetricField object compatible with
    plasmanet.line_of_sight.scan_aspect.
    """
    from plasmanet.line_of_sight import AxisymmetricField

    x_arr = np.array([s.x_m for s in profile.stations])
    ne_arr = np.array([s.ne_m3 for s in profile.stations])
    delta_arr = np.array([s.delta_local_m for s in profile.stations])
    T_arr = np.array([s.T_e_K for s in profile.stations])

    def ne_rz(r, z):
        r_arr = np.atleast_1d(np.asarray(r, dtype=np.float64))
        z_arr = np.atleast_1d(np.asarray(z, dtype=np.float64))
        ne_axis = np.interp(z_arr, x_arr, ne_arr, left=0.0, right=0.0)
        delta = np.interp(z_arr, x_arr, delta_arr, left=delta_arr[0], right=delta_arr[-1])
        delta = np.maximum(delta, 1e-6)
        if decay_normal == "gauss":
            decay = np.exp(-(r_arr / delta) ** 2)
        else:
            decay = np.exp(-r_arr / delta)
        out = ne_axis * decay
        if np.isscalar(r) and np.isscalar(z):
            return float(out[0])
        return out

    def nu_rz(r, z):
        z_arr = np.atleast_1d(np.asarray(z, dtype=np.float64))
        T = np.interp(z_arr, x_arr, T_arr, left=T_arr[0], right=T_arr[-1])
        # Approximate ν_collision ~ 10^10 · (P/atm); but we only have T from the profile.
        # Use the freestream-equivalent gas density × thermal velocity × cross-section.
        # For RAM-C-class hypersonic post-shock: ν ≈ 5e9 to 5e10 Hz.
        nu = 1e10 * np.ones_like(T)
        if np.isscalar(r):
            return float(nu[0])
        return nu * np.ones_like(np.atleast_1d(np.asarray(r, dtype=np.float64)))

    return AxisymmetricField(ne_rz=ne_rz, nu_rz=nu_rz)
