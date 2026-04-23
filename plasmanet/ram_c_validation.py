"""RAM-C II validation harness.

The RAM-C II flight experiment (1970) is the canonical in-flight dataset
for hypersonic plasma sheath electron density. A 2.54 m blunt-cone body
carrying five reflectometer probes was instrumented with microwave
reflectometers at 225 MHz, 450 MHz, and X-band (9.21 GHz). The reentry
trajectory produced measured n_e profiles at altitudes from 90 km down to
25 km at ~Mach 23.9.

This module provides:
1. Published reference measurements at selected altitudes
2. A canonical RAM-C body geometry
3. An evaluation harness that runs the current prediction stack against
   the RAM-C conditions and reports the error at each reflectometer station

If a prediction method cannot match RAM-C within a factor of a few (in ne)
and correctly predicts VHF-blackout / X-band partial attenuation, it
cannot be trusted for operational HGV detectability. This is the single
hardest external benchmark in the regime.

References
----------
- Grantham, W.L. (1970), "Flight Results of a 25000-foot-per-second
  Reentry Experiment Using Microwave Reflectometers to Measure Plasma
  Electron Density and Standoff Distance", NASA TN D-6062.
- Jones, W.L., Cross, A.E. (1972), "Electrostatic-Probe Measurements of
  Plasma Parameters for Two Reentry Flight Experiments at 25000 Feet
  Per Second", NASA TN D-6617.
- Huber, P.W., Evans, J.S., Schexnayder, C.J. (1971), "Comparison of
  Theoretical and Flight-Measured Ionization in a Blunt Body Re-entry
  Flowfield", AIAA Journal 9(6).
- Candler, G.V., MacCormack, R.W. (1988), "The Computation of Hypersonic
  Ionized Flows in Chemical and Thermal Nonequilibrium", AIAA paper
  88-0511 — DPLR-era CFD predictions of RAM-C.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .physics import full_analysis, plasma_frequency_ghz, standard_atmosphere
from .plasma_wave import (
    refractive_index, attenuation_rate_db_per_m, detection_status,
)
from .collision_frequency import nu_from_cantera_state


# ── Canonical RAM-C II geometry ──────────────────────────────────────

RAM_C_NOSE_RADIUS_M = 0.1524      # 6 inches
RAM_C_HALF_ANGLE_DEG = 9.0
RAM_C_BODY_LENGTH_M = 2.54         # 100 inches
RAM_C_REFLECTOMETER_FREQS_HZ = {
    "VHF_225": 225e6,
    "VHF_450": 450e6,
    "X_band": 9.21e9,
}
# Reflectometer station locations along body axis, fraction of body length.
# Values from Grantham (1970) Figure 1: five stations at approximately
# z/L = 0.14, 0.32, 0.48, 0.67, 0.88.
RAM_C_STATION_Z_OVER_L = [0.14, 0.32, 0.48, 0.67, 0.88]


# ── Published peak electron densities and attenuation by altitude ──────
# Table 1: peak ne in the sheath at each altitude (Jones & Cross 1972,
# Grantham 1970). These are at the stagnation region. Units: m⁻³.
# At higher altitudes the sheath is thicker but less dense; at lower
# altitudes it is thinner but much denser.

RAM_C_REFERENCE = {
    # altitude_km: {'ne_peak', 'ne_peak_lower', 'ne_peak_upper',
    #               'VHF_225_status', 'VHF_450_status', 'X_band_status'}
    81.0: {
        "ne_peak_m3": 2.0e18,
        "ne_peak_lower_m3": 1.0e18,
        "ne_peak_upper_m3": 3.5e18,
        "mach": 23.9,
        "velocity_ms": 7620.0,
        "VHF_225_status": "BLACKOUT",
        "VHF_450_status": "BLACKOUT",
        "X_band_status": "DETECTABLE",   # partial attenuation
    },
    71.0: {
        "ne_peak_m3": 1.0e19,
        "ne_peak_lower_m3": 5.0e18,
        "ne_peak_upper_m3": 2.0e19,
        "mach": 23.6,
        "velocity_ms": 7530.0,
        "VHF_225_status": "BLACKOUT",
        "VHF_450_status": "BLACKOUT",
        "X_band_status": "DEGRADED",
    },
    61.0: {
        "ne_peak_m3": 2.0e19,
        "ne_peak_lower_m3": 1.0e19,
        "ne_peak_upper_m3": 4.0e19,
        "mach": 22.5,
        "velocity_ms": 7100.0,
        "VHF_225_status": "BLACKOUT",
        "VHF_450_status": "BLACKOUT",
        "X_band_status": "BLACKOUT",
    },
    47.0: {
        "ne_peak_m3": 2.0e19,
        "ne_peak_lower_m3": 1.5e19,
        "ne_peak_upper_m3": 3.0e19,
        "mach": 18.5,
        "velocity_ms": 5890.0,
        "VHF_225_status": "BLACKOUT",
        "VHF_450_status": "BLACKOUT",
        "X_band_status": "DEGRADED",
    },
}


# ── Simple analytical shock-layer sheath model ────────────────────────

@dataclass
class SheathProfile:
    """Approximate ne(r, z) profile for a RAM-C-like body.

    This is a simplified analytical model used by the RAM-C validation
    harness when full CFD fields are unavailable. It captures the
    dominant behaviour:

    - Sheath thickness scales with normal stand-off distance δ(s) along
      body, which grows from ~R_n·ε at the nose (ε ≈ 0.06 at Mach 24) to
      ~R_n·ε·(1 + s/L) downstream.
    - Peak ne at the stagnation line; falls off downstream as T drops.
    - Radial profile across the shock layer: parabolic with peak at mid-layer.

    For operational use, this should be REPLACED by CFD-derived field
    interpolation (CartesianGridField / UnstructuredFieldFromVTU).
    """
    ne_peak_stag: float                  # m⁻³
    nose_radius_m: float = RAM_C_NOSE_RADIUS_M
    body_length_m: float = RAM_C_BODY_LENGTH_M
    half_angle_deg: float = RAM_C_HALF_ANGLE_DEG
    shock_density_ratio: float = 10.0     # ρ₂/ρ₁ at normal shock
    decay_constant_along_body: float = 3.0  # ne decay scale
    T_e_peak_K: float = 6000.0
    n_neutral_peak_m3: float = 5e21

    def _standoff(self, s_along_body: float) -> float:
        """Stand-off distance δ(s): shock-layer thickness at arc-length s."""
        # Simple model: δ grows from δ_0 ~ R_n·0.06 at nose to ~3×δ_0 at end
        delta_0 = self.nose_radius_m * 0.06 * self.shock_density_ratio / 10.0
        return delta_0 * (1.0 + 2.0 * s_along_body / self.body_length_m)

    def _body_surface(self, s: float) -> tuple[float, float]:
        """Return (r_body, z_body) at arc length s along body axis.

        Simple model: spherical nose (R=R_n) for s ∈ [0, R_n·π/4],
        then conical afterbody.
        """
        # Nose region
        s_nose_end = self.nose_radius_m * math.pi / 4.0
        if s <= s_nose_end:
            theta = s / self.nose_radius_m
            z = self.nose_radius_m * (1 - math.cos(theta))
            r = self.nose_radius_m * math.sin(theta)
            return r, z
        # Conical afterbody
        dz = s - s_nose_end
        ha = math.radians(self.half_angle_deg)
        z = self.nose_radius_m * (1 - math.cos(math.pi/4)) + dz * math.cos(ha)
        r = self.nose_radius_m * math.sin(math.pi/4) + dz * math.sin(ha)
        return r, z

    def ne_at_rz(self, r: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Axisymmetric ne(r, z) for this sheath profile."""
        r = np.asarray(r, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)
        # Map (r,z) to body arc-length s by finding closest body surface point
        # Simple approximation: use z directly as s for the conical afterbody,
        # and arc-length for the nose region.
        s_arr = np.where(z < self.nose_radius_m,
                         self.nose_radius_m * np.arcsin(np.clip(z / self.nose_radius_m, 0, 1)),
                         self.nose_radius_m * math.pi/4 + (z - self.nose_radius_m * (1 - math.cos(math.pi/4))) / math.cos(math.radians(self.half_angle_deg)))
        # Body surface radius at this s
        r_body_arr = np.zeros_like(s_arr)
        z_body_arr = np.zeros_like(s_arr)
        for i in np.ndindex(s_arr.shape):
            r_b, z_b = self._body_surface(float(s_arr[i]))
            r_body_arr[i] = r_b
            z_body_arr[i] = z_b
        delta = np.array([self._standoff(float(s)) for s in s_arr.ravel()]).reshape(s_arr.shape)
        # Distance normal to body (approx): r - r_body
        h = r - r_body_arr
        # In shock layer if 0 ≤ h ≤ δ
        in_layer = (h >= 0) & (h <= delta) & (z >= 0) & (z <= self.body_length_m)
        # Parabolic profile across layer (peak at h = δ/2)
        u = (h - delta/2.0) / (delta/2.0 + 1e-12)
        profile = np.maximum(1.0 - u * u, 0.0)
        # Decay along body: exp(-s/L_decay)
        along_body_decay = np.exp(-s_arr / (self.body_length_m / self.decay_constant_along_body))
        ne = self.ne_peak_stag * profile * along_body_decay
        return np.where(in_layer, ne, 0.0)

    def nu_at_rz(self, r: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Collision frequency field. Scaled to match nu_total at peak conditions."""
        ne = self.ne_at_rz(r, z)
        # Approximate: nu_c tracks ne density roughly (both follow shock
        # compression) with a minimum of nu_c floor
        mask = ne > 0
        # Compute nu at peak with full model
        from .collision_frequency import nu_total
        # Approximate post-shock composition: ~30% N, 10% O, 40% N2, 15% O2, 5% NO
        nu_peak = float(nu_total(
            self.T_e_peak_K, self.ne_peak_stag,
            n_N2=0.4 * self.n_neutral_peak_m3,
            n_O2=0.15 * self.n_neutral_peak_m3,
            n_NO=0.05 * self.n_neutral_peak_m3,
            n_O=0.10 * self.n_neutral_peak_m3,
            n_N=0.30 * self.n_neutral_peak_m3,
        ))
        nu_field = np.where(mask, nu_peak * (ne / max(self.ne_peak_stag, 1.0)), 0.0)
        return nu_field


# ── Validation harness ────────────────────────────────────────────────

@dataclass
class RAMCValidationReport:
    """Summary of RAM-C II validation results across altitudes and frequencies."""
    altitudes_km: list[float]
    ne_predicted_peak_m3: dict[float, float]
    ne_reference_peak_m3: dict[float, float]
    ne_log10_error: dict[float, float]
    attenuation_predicted_dB: dict[tuple[float, str], float]   # (alt, freq_label) → dB
    status_predicted: dict[tuple[float, str], str]
    status_reference: dict[tuple[float, str], str]
    status_match: dict[tuple[float, str], bool]
    overall_match_fraction: float
    notes: list[str] = field(default_factory=list)


def validate_against_ram_c(
    predict_ne_peak: Optional[callable] = None,
    verbose: bool = True,
) -> RAMCValidationReport:
    """Run RAM-C II validation.

    Parameters
    ----------
    predict_ne_peak : callable (altitude_km, velocity_ms) → predicted peak
        stagnation ne in m⁻³. If None, uses the current full_analysis()
        at standard atmosphere conditions.
    verbose : print progress.
    """
    ne_predicted: dict[float, float] = {}
    ne_reference: dict[float, float] = {}
    ne_log_error: dict[float, float] = {}
    attenuation_dB: dict[tuple[float, str], float] = {}
    status_pred: dict[tuple[float, str], str] = {}
    status_ref: dict[tuple[float, str], str] = {}
    status_match: dict[tuple[float, str], bool] = {}
    notes = []

    altitudes = sorted(RAM_C_REFERENCE.keys(), reverse=True)
    n_match_total = 0
    n_total = 0

    for alt_km in altitudes:
        ref = RAM_C_REFERENCE[alt_km]
        if predict_ne_peak is None:
            # Default: use current full_analysis at this Mach/altitude with
            # RAM-C nose radius. NOTE: the atmosphere model is only valid
            # below 71 km; at higher altitudes we extrapolate.
            try:
                r = full_analysis(ref["mach"], alt_km, RAM_C_NOSE_RADIUS_M,
                                   use_cantera=True, use_neq=False)
                ne_pred = r["ne_m3"]
            except Exception as e:
                ne_pred = 0.0
                notes.append(f"Alt {alt_km} km: full_analysis failed ({e})")
        else:
            ne_pred = float(predict_ne_peak(alt_km, ref["velocity_ms"]))
        ne_predicted[alt_km] = ne_pred
        ne_reference[alt_km] = ref["ne_peak_m3"]

        # Log-error vs midpoint (symmetric in log)
        log_err = (math.log10(max(ne_pred, 1e6)) -
                   math.log10(ref["ne_peak_m3"]))
        ne_log_error[alt_km] = log_err

        # Compute peak-condition attenuation estimate: thickness × α at peak
        # Approximation: use peak ne with a sheath thickness of R_n·0.06·ρratio
        thickness = RAM_C_NOSE_RADIUS_M * 0.06 * 10.0   # ~0.1 m
        # Post-shock composition (rough):
        n_neutral_total = 5e21  # m⁻³ at 70 km post-shock
        from .collision_frequency import nu_total as _nu_total
        nu = float(_nu_total(
            6000.0, ne_pred,
            n_N2=0.4*n_neutral_total, n_O2=0.15*n_neutral_total,
            n_NO=0.05*n_neutral_total, n_O=0.10*n_neutral_total,
            n_N=0.30*n_neutral_total,
        ))
        for freq_label, f_hz in RAM_C_REFLECTOMETER_FREQS_HZ.items():
            alpha = float(attenuation_rate_db_per_m(ne_pred, nu, f_hz))
            A_dB = alpha * thickness
            attenuation_dB[(alt_km, freq_label)] = A_dB
            status = detection_status(A_dB)
            status_pred[(alt_km, freq_label)] = status
            status_ref[(alt_km, freq_label)] = ref[f"{freq_label}_status"]
            matched = status == ref[f"{freq_label}_status"]
            status_match[(alt_km, freq_label)] = matched
            n_total += 1
            if matched:
                n_match_total += 1

        if verbose:
            print(f"  Alt={alt_km:5.1f} km (M={ref['mach']:.1f}): "
                  f"ne_pred={ne_pred:.2e}, ne_ref={ref['ne_peak_m3']:.2e}, "
                  f"log10-error={log_err:+.2f}")

    overall_match = n_match_total / max(n_total, 1)
    notes.append(f"Matched {n_match_total}/{n_total} frequency-altitude status categories.")
    notes.append(
        "Reference ne_peak values are peak sheath electron densities from "
        "Jones&Cross (1972) and Grantham (1970). Ranges span published upper/lower "
        "bounds — predictions within 1 order of magnitude are acceptable for "
        "equilibrium models; coupled-chemistry CFD can typically achieve within 0.3 orders."
    )

    return RAMCValidationReport(
        altitudes_km=altitudes,
        ne_predicted_peak_m3=ne_predicted,
        ne_reference_peak_m3=ne_reference,
        ne_log10_error=ne_log_error,
        attenuation_predicted_dB=attenuation_dB,
        status_predicted=status_pred,
        status_reference=status_ref,
        status_match=status_match,
        overall_match_fraction=overall_match,
        notes=notes,
    )


def print_ram_c_report(report: RAMCValidationReport) -> None:
    """Print a human-readable RAM-C validation report."""
    print("\n" + "=" * 78)
    print("RAM-C II Validation Report")
    print("=" * 78)
    print(f"\nElectron density at stagnation (peak sheath):")
    print(f"{'Alt (km)':>10} {'Mach':>6} {'Predicted':>14} {'Reference':>14} "
          f"{'Range':>26} {'log10 err':>10}")
    for alt in report.altitudes_km:
        ref = RAM_C_REFERENCE[alt]
        ne_p = report.ne_predicted_peak_m3[alt]
        ne_r = report.ne_reference_peak_m3[alt]
        err = report.ne_log10_error[alt]
        range_str = f"{ref['ne_peak_lower_m3']:.1e}-{ref['ne_peak_upper_m3']:.1e}"
        print(f"{alt:>10.1f} {ref['mach']:>6.1f} {ne_p:>14.3e} {ne_r:>14.3e} "
              f"{range_str:>26} {err:>+10.2f}")

    print(f"\nDetection status by altitude and reflectometer frequency:")
    print(f"{'Alt':>6} | {'VHF_225':<20} | {'VHF_450':<20} | {'X_band':<20}")
    for alt in report.altitudes_km:
        row = []
        for freq_label in ["VHF_225", "VHF_450", "X_band"]:
            pred = report.status_predicted[(alt, freq_label)]
            ref = report.status_reference[(alt, freq_label)]
            match = report.status_match[(alt, freq_label)]
            mark = "✓" if match else "✗"
            row.append(f"{pred}/{ref} {mark}".ljust(20))
        print(f"{alt:>6.1f} | {' | '.join(row)}")

    print(f"\nOverall status match: {report.overall_match_fraction*100:.0f}% "
          f"({sum(report.status_match.values())}/{len(report.status_match)})")
    if report.notes:
        print("\nNotes:")
        for note in report.notes:
            print(f"  - {note}")
    print("=" * 78 + "\n")
