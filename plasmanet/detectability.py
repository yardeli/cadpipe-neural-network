"""Top-level detectability API.

This module ties together the physics stack into a single user-facing
function: "is this vehicle detectable by this radar from this viewing
geometry under this flight condition, and with what error bars?"

Replaces the legacy binary `fp > 12 GHz → BLACKOUT` check with:

1. Real-gas post-shock stagnation conditions (pitot + Cantera)
2. Sheath electron density prediction with UQ bands
3. Line-of-sight attenuation through the sheath along specified radar rays
4. Aspect-dependent detection status with quantified uncertainty

The function returns a structured report that callers (SimOps UI,
JSON API, RAM-C validation) can consume uniformly.

Example
-------
>>> from plasmanet.detectability import analyze_detectability, VehicleGeometry
>>> geom = VehicleGeometry(nose_radius_m=0.08, half_angle_deg=15, length_m=2.5)
>>> report = analyze_detectability(
...     vehicle=geom,
...     mach=10.0, altitude_km=35.0,
...     radar_freq_hz=12e9,
...     aspect_angles_deg=[0, 30, 60, 90, 120, 150, 180],
...     include_uq=True,
... )
>>> report.summary()
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .physics import (
    full_analysis, standard_atmosphere, pitot_pressure,
    plasma_frequency_ghz, K_B,
)
from .plasma_wave import (
    detection_status, THRESHOLD_DETECTABLE_DB, THRESHOLD_BLACKOUT_DB,
)
from .line_of_sight import (
    Ray, AxisymmetricField, scan_aspect, integrate_los,
)
from .collision_frequency import nu_total
from .chemistry_uq import (
    ChemistryUQConfig, run_uq, UQResult,
)
from .ram_c_validation import SheathProfile


# ── Input/output structs ───────────────────────────────────────────────

@dataclass
class VehicleGeometry:
    """Parametric sphere-cone vehicle."""
    nose_radius_m: float = 0.08
    half_angle_deg: float = 15.0
    length_m: float = 2.5
    name: str = "generic_spherecone"


@dataclass
class DetectabilityReport:
    """Aspect- and frequency-resolved detectability assessment."""
    # Flight condition
    mach: float
    altitude_km: float
    vehicle: VehicleGeometry
    radar_freq_hz: float

    # Chemistry prediction at stagnation (median of UQ ensemble if UQ enabled)
    T_stag_K: float
    p_stag_Pa: float
    ne_peak_m3: float
    fp_GHz: float

    # LOS integration results
    aspect_angles_deg: np.ndarray
    attenuation_db: np.ndarray
    phase_shift_rad: np.ndarray
    detection_by_aspect: list[str]

    # UQ (optional)
    ne_p05_m3: Optional[float] = None
    ne_p95_m3: Optional[float] = None
    log10_ne_std: Optional[float] = None
    attenuation_p05_db: Optional[np.ndarray] = None
    attenuation_p95_db: Optional[np.ndarray] = None

    # Summary
    worst_aspect_deg: float = 0.0
    worst_aspect_attenuation_db: float = 0.0
    overall_status: str = "UNKNOWN"

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            "=" * 70,
            f"Detectability Analysis: {self.vehicle.name}",
            "=" * 70,
            f"  Flight: Mach {self.mach:.1f} @ {self.altitude_km:.1f} km alt",
            f"  Vehicle: R_nose={self.vehicle.nose_radius_m:.3f} m, "
            f"half-angle={self.vehicle.half_angle_deg:.0f}°, "
            f"L={self.vehicle.length_m:.2f} m",
            f"  Radar: {self.radar_freq_hz/1e9:.2f} GHz",
            "",
            f"  Stagnation conditions:",
            f"    T_stag  = {self.T_stag_K:.0f} K",
            f"    p_stag  = {self.p_stag_Pa:.2e} Pa ({self.p_stag_Pa/101325:.2f} atm)",
            f"    ne_peak = {self.ne_peak_m3:.2e} m⁻³",
            f"    fp_peak = {self.fp_GHz:.2f} GHz",
        ]
        if self.ne_p05_m3 is not None:
            lines.extend([
                f"    ne UQ:  P05={self.ne_p05_m3:.2e}  P95={self.ne_p95_m3:.2e}  "
                f"(log10 std = {self.log10_ne_std:.2f})",
            ])
        lines.extend([
            "",
            f"  Line-of-sight attenuation by aspect angle:",
            f"    {'Angle':>7} {'Attenuation':>14} {'Status':>12}",
        ])
        for i, ang in enumerate(self.aspect_angles_deg):
            att = self.attenuation_db[i]
            stat = self.detection_by_aspect[i]
            s_uq = ""
            if self.attenuation_p05_db is not None:
                s_uq = f" [{self.attenuation_p05_db[i]:.1f}-{self.attenuation_p95_db[i]:.1f}]"
            lines.append(f"    {ang:>7.0f}°  {att:>12.1f} dB {s_uq:>12s}  {stat}")
        lines.extend([
            "",
            f"  Worst case: aspect {self.worst_aspect_deg:.0f}° "
            f"= {self.worst_aspect_attenuation_db:.1f} dB",
            f"  Overall status: {self.overall_status}",
            "=" * 70,
        ])
        return "\n".join(lines)


# ── Field construction from stagnation prediction ─────────────────────

def build_sheath_field_from_analysis(
    analysis: dict, vehicle: VehicleGeometry,
) -> AxisymmetricField:
    """Construct an axisymmetric plasma-field model from a scalar stagnation
    prediction, using the analytical SheathProfile geometry.

    This is the "best we can do without CFD fields" path. When CFD output is
    available, use CartesianGridField directly and skip this.

    Parameters
    ----------
    analysis : dict from full_analysis() — supplies ne_m3, T_stag_K, etc.
    vehicle : VehicleGeometry with body shape parameters

    Returns
    -------
    AxisymmetricField with ne, nu_c callables for (r, z) inputs.
    """
    ne_peak = max(analysis.get("ne_m3", 0.0), 1.0)
    T_e = analysis.get("T_stag_K", 3000.0)

    # Approximate post-shock total neutral density from the stagnation state
    p_stag = analysis.get("p_stag_Pa", 1e5)
    n_total_peak = p_stag / (K_B * max(T_e, 300.0))

    # Post-shock composition — rough partition based on typical Mach 10-15 air
    x_N2 = analysis.get("x_N2", 0.4)
    x_O2 = analysis.get("x_O2", 0.1)
    x_NO = analysis.get("x_NO", 0.05)
    x_O  = analysis.get("x_O",  0.25)
    x_N  = analysis.get("x_N",  0.2)

    # Peak collision frequency
    nu_peak = float(nu_total(
        T_e, ne_peak,
        n_N2=x_N2 * n_total_peak,
        n_O2=x_O2 * n_total_peak,
        n_NO=x_NO * n_total_peak,
        n_O=x_O * n_total_peak,
        n_N=x_N * n_total_peak,
    ))

    profile = SheathProfile(
        ne_peak_stag=ne_peak,
        nose_radius_m=vehicle.nose_radius_m,
        body_length_m=vehicle.length_m,
        half_angle_deg=vehicle.half_angle_deg,
        T_e_peak_K=T_e,
        n_neutral_peak_m3=n_total_peak,
        mach_freestream=analysis.get("mach", 12.0),
    )

    def ne_rz(r, z):
        return profile.ne_at_rz(r, z)

    def nu_rz(r, z):
        # nu_c tracks ne in this simple model (both shock-compressed)
        ne = profile.ne_at_rz(r, z)
        return np.where(ne > 0, nu_peak * (ne / max(ne_peak, 1.0)), 0.0)

    return AxisymmetricField(
        ne_rz=ne_rz, nu_rz=nu_rz,
        axis=np.array([1.0, 0.0, 0.0]),
        origin=np.zeros(3),
    )


# ── Main API ───────────────────────────────────────────────────────────

def analyze_detectability(
    vehicle: VehicleGeometry,
    mach: float,
    altitude_km: float,
    radar_freq_hz: float = 12e9,
    aspect_angles_deg: Optional[list[float]] = None,
    include_uq: bool = True,
    uq_config: Optional[ChemistryUQConfig] = None,
    source_distance_m: float = 500.0,   # typical ground radar slant range
    use_cantera: bool = True,
    use_neq: bool = False,
    cfd_field_npz: Optional[str] = None,  # path to saved CFDFieldResult
    verbose: bool = False,
) -> DetectabilityReport:
    """Predict radar detectability of a vehicle under given conditions.

    Parameters
    ----------
    vehicle : VehicleGeometry
    mach, altitude_km : flight condition
    radar_freq_hz : radar frequency (default 12 GHz, StarLink Ku-band)
    aspect_angles_deg : list of viewing angles (deg from body axis). Default
        = 19 angles every 10° from 0 to 180.
    include_uq : if True, run chemistry UQ and report ne/attenuation bands
    uq_config : override default UQ config
    source_distance_m : notional radar stand-off distance (500 m default).
    use_cantera, use_neq : passed to full_analysis

    Returns
    -------
    DetectabilityReport with aspect-dependent attenuation and status.
    """
    if aspect_angles_deg is None:
        aspect_angles_deg = list(range(0, 181, 10))
    aspect_angles_deg = np.asarray(aspect_angles_deg, dtype=np.float64)

    # Step 1: stagnation prediction
    analysis = full_analysis(
        mach=mach, altitude_km=altitude_km,
        nose_radius_m=vehicle.nose_radius_m,
        use_cantera=use_cantera, use_neq=use_neq,
    )
    ne_peak = analysis["ne_m3"]
    T_stag = analysis["T_stag_K"]
    p_stag = analysis["p_stag_Pa"]
    fp = analysis["fp_GHz"]

    # Step 2: build plasma field.
    # - If a CFD field NPZ is provided, use real CFD-derived ne(x,y,z).
    # - Otherwise, build the analytical SheathProfile from stagnation values.
    if cfd_field_npz is not None:
        from .cfd_field import load_cfd_field, build_unstructured_field
        cfd = load_cfd_field(cfd_field_npz)
        field_median = build_unstructured_field(cfd)
        # Use CFD stagnation for reporting
        ne_peak = cfd.stag_point["ne_m3"]
        T_stag = cfd.stag_point["T_K"]
        p_stag = cfd.stag_point["p_Pa"]
        fp = plasma_frequency_ghz(ne_peak)
        target_override = np.asarray(cfd.stag_point["xyz"], dtype=np.float64)
    else:
        field_median = build_sheath_field_from_analysis(analysis, vehicle)
        target_override = None

    # Step 3: LOS scan across aspect angles.
    # Integrate only the near-field region around the vehicle (plasma is zero
    # outside ~3 body lengths). This prevents under-sampling of the thin
    # (~1 cm) shock layer when the full source-to-target path is 500+ m.
    # We still quote source_distance in the report as context, but the
    # integration window is bounded to 3×L of the vehicle centre.
    if target_override is not None:
        target_pos = target_override
    else:
        target_pos = np.array([vehicle.length_m / 2.0, 0.0, 0.0])
    integration_length = min(source_distance_m, 3.0 * vehicle.length_m + 2.0)
    scan_median = scan_aspect(
        field_median, target_position=target_pos,
        f_hz=radar_freq_hz,
        source_distance=integration_length,
        angles_deg=aspect_angles_deg, plane="xz",
        n_samples=2000,  # 3 mm spacing across the ~6 m integration window.
                         # The analytical sheath is ~3-30 mm thick depending
                         # on geometry; coarser sampling (600) caused
                         # angle-dependent dips when rays at certain aspects
                         # missed the densest sheath layer (visible as
                         # non-monotonic 30 dB dips in lobes that should be
                         # smooth). Combined with the cubic clustering in
                         # scan_aspect, this gives ~30% of samples in the
                         # last 10% of ray length — high enough density
                         # near the body to resolve the sheath robustly.
        adaptive=True,
    )
    att_median = np.array([r.attenuation_db for r in scan_median])
    phase_median = np.array([r.phase_shift_rad for r in scan_median])
    status_median = [r.detection for r in scan_median]

    # Step 4: UQ bands (optional — runs UQ on ne then re-integrates LOS)
    ne_p05 = ne_p95 = None
    log10_std = None
    att_p05 = att_p95 = None
    if include_uq:
        cfg = uq_config or ChemistryUQConfig(n_samples=64)
        uq = run_uq(
            mach=mach, altitude_km=altitude_km,
            nose_radius_m=vehicle.nose_radius_m,
            config=cfg, use_cantera=use_cantera, use_neq=use_neq,
        )
        ne_p05 = uq.ne_m3_p05
        ne_p95 = uq.ne_m3_p95
        log10_std = uq.log10_ne_std

        # Build low- and high-ne fields and scan
        analysis_low = dict(analysis); analysis_low["ne_m3"] = ne_p05
        analysis_high = dict(analysis); analysis_high["ne_m3"] = ne_p95
        field_low = build_sheath_field_from_analysis(analysis_low, vehicle)
        field_high = build_sheath_field_from_analysis(analysis_high, vehicle)
        scan_low = scan_aspect(
            field_low, target_position=target_pos,
            f_hz=radar_freq_hz, source_distance=integration_length,
            angles_deg=aspect_angles_deg, plane="xz",
            n_samples=2000, adaptive=True,
        )
        scan_high = scan_aspect(
            field_high, target_position=target_pos,
            f_hz=radar_freq_hz, source_distance=integration_length,
            angles_deg=aspect_angles_deg, plane="xz",
            n_samples=2000, adaptive=True,
        )
        att_p05 = np.array([r.attenuation_db for r in scan_low])
        att_p95 = np.array([r.attenuation_db for r in scan_high])

    # Worst-case aspect (highest attenuation)
    worst_idx = int(np.argmax(att_median))

    # Overall status based on worst-case aspect attenuation of the median
    # prediction. "UNKNOWN" if UQ band straddles the category boundary.
    overall = detection_status(float(att_median[worst_idx]))
    if include_uq and att_p05 is not None and att_p95 is not None:
        low_status = detection_status(float(att_p05[worst_idx]))
        high_status = detection_status(float(att_p95[worst_idx]))
        if low_status != high_status:
            overall = f"{low_status}→{high_status} (UQ-dependent)"

    return DetectabilityReport(
        mach=mach, altitude_km=altitude_km, vehicle=vehicle,
        radar_freq_hz=radar_freq_hz,
        T_stag_K=T_stag, p_stag_Pa=p_stag,
        ne_peak_m3=ne_peak, fp_GHz=fp,
        aspect_angles_deg=aspect_angles_deg,
        attenuation_db=att_median,
        phase_shift_rad=phase_median,
        detection_by_aspect=status_median,
        ne_p05_m3=ne_p05, ne_p95_m3=ne_p95, log10_ne_std=log10_std,
        attenuation_p05_db=att_p05, attenuation_p95_db=att_p95,
        worst_aspect_deg=float(aspect_angles_deg[worst_idx]),
        worst_aspect_attenuation_db=float(att_median[worst_idx]),
        overall_status=overall,
    )


def detection_envelope(
    vehicle: VehicleGeometry,
    mach_grid: np.ndarray,
    altitude_grid: np.ndarray,
    radar_freq_hz: float = 12e9,
    aspect_angles_deg: Optional[list[float]] = None,
    include_uq: bool = False,
    use_cantera: bool = True,
    verbose: bool = False,
) -> dict:
    """Compute detection envelope across Mach × altitude grid.

    Returns a dict of result arrays shape (len(mach), len(alt)) with the
    worst-case LOS attenuation at each grid point. Useful for producing
    operational envelope maps.

    This is the honest 'detection map' replacement for the legacy
    fp-threshold envelope — it accounts for viewing geometry.
    """
    M_grid = np.asarray(mach_grid, dtype=np.float64)
    H_grid = np.asarray(altitude_grid, dtype=np.float64)
    shape = (len(M_grid), len(H_grid))

    att_worst = np.zeros(shape)
    att_best = np.zeros(shape)
    ne_peak = np.zeros(shape)
    fp_peak = np.zeros(shape)

    for i, M in enumerate(M_grid):
        for j, H in enumerate(H_grid):
            try:
                rpt = analyze_detectability(
                    vehicle=vehicle, mach=float(M), altitude_km=float(H),
                    radar_freq_hz=radar_freq_hz,
                    aspect_angles_deg=aspect_angles_deg,
                    include_uq=include_uq,
                    use_cantera=use_cantera,
                )
                att_worst[i, j] = rpt.attenuation_db.max()
                att_best[i, j] = rpt.attenuation_db.min()
                ne_peak[i, j] = rpt.ne_peak_m3
                fp_peak[i, j] = rpt.fp_GHz
            except Exception as e:
                if verbose:
                    print(f"  ({M}, {H}): failed - {e}")
                att_worst[i, j] = np.nan
                att_best[i, j] = np.nan

    return {
        "mach": M_grid, "altitude_km": H_grid,
        "attenuation_worst_dB": att_worst,
        "attenuation_best_dB": att_best,
        "ne_peak_m3": ne_peak,
        "fp_GHz": fp_peak,
        "radar_freq_hz": radar_freq_hz,
        "vehicle": vehicle,
    }
