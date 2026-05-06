"""Trajectory-level simulation — time-evolving plasma + detectability.

The pointwise HypersonicSolver answers "what does the plasma look like
at THIS instant?". For mission planning the relevant question is "when
in the trajectory is the vehicle in blackout?" — which requires walking
a list of (t, M, h, AoA) waypoints and computing the plasma state +
attenuation at each.

This module wraps HypersonicSolver per-waypoint and returns a structured
TrajectoryResult with the time series of stagnation ne, peak attenuation
per band, blackout intervals, and per-band on/off transition timestamps.

Use cases:
  - "When does this re-entry vehicle leave Ku-band blackout?"
  - "What's the worst-case Ku-band attenuation for this trajectory?"
  - "Identify all distinct blackout windows and their durations"

Reference design: NASA TM-X-2104 (Apollo CM blackout window prediction).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from .geometry import Geometry, GEOMETRY_PRESETS
from .solver import (
    HypersonicSolver, SolverInput, GeometryInput, FlightCondition,
    DEFAULT_RADAR_BANDS, RadarBand,
)


# ── Trajectory inputs ────────────────────────────────────────────────

@dataclass
class TrajectoryPoint:
    """One waypoint in the flight trajectory.

    Attributes
    ----------
    t : seconds since some epoch (e.g. liftoff or entry interface)
    mach : freestream Mach number at this instant
    altitude_km : altitude AGL or above sea-level
    angle_of_attack_deg : optional vehicle attitude (default 0; the
        v0.3 solver doesn't yet incorporate AoA in shock geometry —
        passed through for downstream consumers and future use)
    """
    t: float
    mach: float
    altitude_km: float
    angle_of_attack_deg: float = 0.0


# ── Trajectory outputs ───────────────────────────────────────────────

@dataclass
class WaypointResult:
    t: float
    mach: float
    altitude_km: float
    ne_peak_m3: float
    fp_GHz: float
    T_stag_K: float
    q_w_W_per_m2: float | None
    residence_time_s: float | None
    chemistry_mode_used: str
    band_atten_dB: dict[str, float] = field(default_factory=dict)
    band_status: dict[str, str] = field(default_factory=dict)


@dataclass
class BlackoutInterval:
    band_label: str
    t_start: float
    t_end: float
    duration_s: float
    peak_atten_dB: float


@dataclass
class TrajectoryResult:
    waypoints: list[WaypointResult] = field(default_factory=list)
    blackout_intervals: list[BlackoutInterval] = field(default_factory=list)
    geometry_name: str = ""
    bands: list[str] = field(default_factory=list)

    @property
    def t(self) -> np.ndarray:
        return np.array([w.t for w in self.waypoints])

    @property
    def ne_peak_m3(self) -> np.ndarray:
        return np.array([w.ne_peak_m3 for w in self.waypoints])

    @property
    def fp_GHz(self) -> np.ndarray:
        return np.array([w.fp_GHz for w in self.waypoints])

    def attenuation_series(self, band_label: str) -> np.ndarray:
        return np.array([w.band_atten_dB.get(band_label, 0.0)
                          for w in self.waypoints])

    def status_series(self, band_label: str) -> list[str]:
        return [w.band_status.get(band_label, "DETECTABLE")
                for w in self.waypoints]


# ── Driver ───────────────────────────────────────────────────────────

def solve_trajectory(
    trajectory: list[TrajectoryPoint],
    geometry: Geometry | str,
    radar_bands: Optional[list[RadarBand]] = None,
    chemistry_mode: str = "auto",
    aspect_angles_deg: Optional[list[float]] = None,
    blackout_threshold_dB: float = 20.0,
    debug: bool = False,
) -> TrajectoryResult:
    """Run the pointwise solver at each TrajectoryPoint and assemble the
    time-series result.

    Parameters
    ----------
    trajectory : list of TrajectoryPoint, sorted by t (caller's
        responsibility — we don't sort)
    geometry : Geometry instance OR a preset name (str) like 'ram_c'
    radar_bands : if None, uses DEFAULT_RADAR_BANDS (VHF 225, VHF 450,
        X 9.2, Ku 12 GHz)
    chemistry_mode : passed through to HypersonicSolver
    aspect_angles_deg : LOS aspect angles (default 13-point sweep)
    blackout_threshold_dB : per-band atten ≥ this is BLACKOUT (default 20)
    debug : print per-waypoint diagnostics

    Returns
    -------
    TrajectoryResult with waypoint-by-waypoint state and a list of
    blackout intervals per band.
    """
    if isinstance(geometry, str):
        if geometry not in GEOMETRY_PRESETS:
            raise ValueError(f"unknown geometry preset {geometry!r}")
        geometry_obj = GEOMETRY_PRESETS[geometry]
    else:
        geometry_obj = geometry

    if radar_bands is None:
        radar_bands = list(DEFAULT_RADAR_BANDS)
    if aspect_angles_deg is None:
        aspect_angles_deg = [0, 30, 60, 90, 120, 150, 180]

    solver = HypersonicSolver()
    waypoints: list[WaypointResult] = []

    for i, point in enumerate(trajectory):
        try:
            out = solver.analyze(SolverInput(
                geometry=GeometryInput(
                    name=geometry_obj.name,
                    nose_radius_m=getattr(geometry_obj, "nose_radius_m", None),
                    half_angle_deg=getattr(geometry_obj, "half_angle_deg", None),
                    length_m=getattr(geometry_obj, "length_m", None),
                ),
                flight=FlightCondition(mach=point.mach,
                                          altitude_km=point.altitude_km),
                radar_bands=radar_bands,
                aspect_angles_deg=aspect_angles_deg,
                chemistry_mode=chemistry_mode,
            ))
        except Exception as exc:
            if debug:
                print(f"  t={point.t:.2f}s: solver failed - {exc}")
            continue

        band_atten = {b.label: b.peak_atten_dB for b in out.bands}
        band_status = {b.label: b.detection_status for b in out.bands}

        waypoints.append(WaypointResult(
            t=point.t, mach=point.mach, altitude_km=point.altitude_km,
            ne_peak_m3=out.stagnation.ne_peak_m3,
            fp_GHz=out.stagnation.fp_GHz,
            T_stag_K=out.stagnation.T_stag_K,
            q_w_W_per_m2=out.stagnation.q_w_W_per_m2,
            residence_time_s=out.stagnation.residence_time_s,
            chemistry_mode_used=out.stagnation.chemistry_mode_used,
            band_atten_dB=band_atten, band_status=band_status,
        ))
        if debug:
            print(f"  t={point.t:>6.1f}s  M={point.mach:>5.1f}  "
                  f"h={point.altitude_km:>5.1f}km  ne={out.stagnation.ne_peak_m3:.2e}  "
                  f"Ku={band_atten.get('Ku_12', 0):>5.1f}dB ({band_status.get('Ku_12', '?')})")

    intervals = _extract_blackout_intervals(waypoints, radar_bands,
                                             blackout_threshold_dB)
    return TrajectoryResult(
        waypoints=waypoints,
        blackout_intervals=intervals,
        geometry_name=geometry_obj.name,
        bands=[b.label for b in radar_bands],
    )


def _extract_blackout_intervals(
    waypoints: list[WaypointResult],
    radar_bands: list[RadarBand],
    threshold_dB: float,
) -> list[BlackoutInterval]:
    """Walk the waypoint series for each band; collect contiguous BLACKOUT runs."""
    intervals: list[BlackoutInterval] = []
    for band in radar_bands:
        in_blackout = False
        t_start = 0.0
        peak = 0.0
        for w in waypoints:
            atten = w.band_atten_dB.get(band.label, 0.0)
            if atten >= threshold_dB:
                if not in_blackout:
                    in_blackout = True
                    t_start = w.t
                    peak = atten
                else:
                    peak = max(peak, atten)
            else:
                if in_blackout:
                    intervals.append(BlackoutInterval(
                        band_label=band.label, t_start=t_start, t_end=w.t,
                        duration_s=w.t - t_start, peak_atten_dB=peak,
                    ))
                    in_blackout = False
        if in_blackout and waypoints:
            intervals.append(BlackoutInterval(
                band_label=band.label, t_start=t_start,
                t_end=waypoints[-1].t,
                duration_s=waypoints[-1].t - t_start,
                peak_atten_dB=peak,
            ))
    return intervals
