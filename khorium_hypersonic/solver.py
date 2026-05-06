"""Top-level orchestrator: HypersonicSolver.

Single entry-point that takes a Geometry + FlightCondition (+ optional
Mechanism / radar config) and walks the full physics stack:

    USSA76 freestream
        → frozen normal-shock RH
        → Pitot pressure
        → real-gas T_stag via Cantera enthalpy iteration
        → equilibrium chemistry composition
        → Saha ne (or Cantera air-plasma if YAML provided)
        → Billig bow-shock standoff
        → analytical / CFD-derived sheath profile
        → LOS scan over aspect angles for each radar band
        → per-band attenuation + detection verdicts

All inputs and outputs are Pydantic models so the solver drops cleanly
into a FastAPI route. See khorium_hypersonic.api.create_router for the
HTTP integration.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from .core import (
    standard_atmosphere, normal_shock_frozen,
    pitot_pressure, stagnation_T_perfect, stagnation_T_real_gas,
    saha_ne, plasma_frequency_GHz,
    appleton_hartree_attenuation_dB, billig_sphere_standoff,
)
from .geometry import Geometry, GEOMETRY_PRESETS
from .signals import scan_aspect, Ray
from .sheath import build_analytical_sheath_field
from .core.constants import K_B


# ── Pydantic schemas — KhoriumBackend integration surface ────────────

class FlightCondition(BaseModel):
    mach: float = Field(..., ge=1.0, le=40.0)
    altitude_km: float = Field(..., ge=0.0, le=100.0)


class GeometryInput(BaseModel):
    """Either a preset name OR explicit sphere-cone parameters OR a mesh path."""
    preset_name: Optional[str] = None
    nose_radius_m: Optional[float] = None
    half_angle_deg: Optional[float] = None
    length_m: Optional[float] = None
    mesh_path: Optional[str] = None
    name: str = "custom"


class RadarBand(BaseModel):
    label: str
    frequency_Hz: float


DEFAULT_RADAR_BANDS = [
    RadarBand(label="VHF_225",  frequency_Hz=225e6),
    RadarBand(label="VHF_450",  frequency_Hz=450e6),
    RadarBand(label="X_9.2",    frequency_Hz=9.2e9),
    RadarBand(label="Ku_12",    frequency_Hz=12.0e9),
]


class SolverInput(BaseModel):
    geometry: GeometryInput
    flight: FlightCondition
    radar_bands: list[RadarBand] = Field(default_factory=lambda: list(DEFAULT_RADAR_BANDS))
    aspect_angles_deg: list[float] = Field(
        default_factory=lambda: [0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180]
    )


class StagnationOutput(BaseModel):
    T_stag_K: float
    P_stag_Pa: float
    ne_peak_m3: float
    fp_GHz: float
    composition_x: dict[str, float]


class BandResult(BaseModel):
    label: str
    frequency_Hz: float
    peak_atten_dB: float
    peak_aspect_deg: float
    detection_status: str
    aspect_scan: list[dict]


class GeometryOutput(BaseModel):
    name: str
    nose_radius_m: float
    half_angle_deg: float
    length_m: float
    bow_shock_standoff_eq_mm: float


class FreestreamOutput(BaseModel):
    T_inf_K: float
    P_inf_Pa: float
    rho_inf_kgm3: float
    a_inf_ms: float
    U_inf_ms: float


class SolverOutput(BaseModel):
    freestream: FreestreamOutput
    geometry: GeometryOutput
    stagnation: StagnationOutput
    bands: list[BandResult]
    notes: list[str] = Field(default_factory=list)


# ── HypersonicSolver class ────────────────────────────────────────────

def _resolve_geometry(g: GeometryInput) -> Geometry:
    if g.preset_name:
        if g.preset_name not in GEOMETRY_PRESETS:
            raise ValueError(
                f"Unknown preset {g.preset_name!r}; "
                f"available: {list(GEOMETRY_PRESETS.keys())}"
            )
        return GEOMETRY_PRESETS[g.preset_name]
    if g.mesh_path:
        from .geometry import MeshGeometry
        return MeshGeometry(name=g.name, mesh_path=g.mesh_path)
    if (g.nose_radius_m is not None and g.half_angle_deg is not None
            and g.length_m is not None):
        from .geometry import SphereCone
        return SphereCone(
            name=g.name,
            nose_radius_m=g.nose_radius_m,
            half_angle_deg=g.half_angle_deg,
            length_m=g.length_m,
        )
    raise ValueError(
        "GeometryInput must specify preset_name, OR mesh_path, OR "
        "explicit (nose_radius_m, half_angle_deg, length_m)."
    )


class HypersonicSolver:
    """Stateless orchestrator. Construct once, call analyze() per request.

    Example
    -------
    >>> from khorium_hypersonic import HypersonicSolver, SolverInput
    >>> from khorium_hypersonic.solver import GeometryInput, FlightCondition
    >>> solver = HypersonicSolver()
    >>> output = solver.analyze(SolverInput(
    ...     geometry=GeometryInput(preset_name="ram_c"),
    ...     flight=FlightCondition(mach=22.5, altitude_km=61.0),
    ... ))
    >>> print(output.stagnation.ne_peak_m3, output.bands[0].peak_atten_dB)
    """

    def analyze(self, request: SolverInput) -> SolverOutput:
        geom = _resolve_geometry(request.geometry)

        # 1. Freestream
        fs = standard_atmosphere(request.flight.altitude_km)
        U_inf = request.flight.mach * fs["a_ms"]

        # 2. Frozen normal shock (for reference)
        _shock = normal_shock_frozen(
            M1=request.flight.mach,
            T1_K=fs["T_K"], P1_Pa=fs["P_Pa"], rho1_kgm3=fs["rho_kgm3"],
        )

        # 3. Stagnation pressure (Pitot)
        P_t = pitot_pressure(fs["P_Pa"], request.flight.mach)
        T_t_pg = stagnation_T_perfect(fs["T_K"], request.flight.mach)

        # 4. Real-gas T_stag + composition via Cantera enthalpy
        rg = stagnation_T_real_gas(
            T_inf_K=fs["T_K"], P_inf_Pa=fs["P_Pa"],
            U_inf_ms=U_inf, P_t_Pa=P_t,
        )
        T_stag = rg.get("T_t_real_K", T_t_pg)
        composition = {
            "N2": rg.get("x_N2", 0.79), "O2": rg.get("x_O2", 0.21),
            "NO": rg.get("x_NO", 0.0),
            "N":  rg.get("x_N", 0.0),  "O":  rg.get("x_O", 0.0),
        }

        # 5. Saha ne
        saha = saha_ne(
            T_K=T_stag, P_Pa=P_t,
            x_N=composition["N"], x_O=composition["O"],
            x_NO=composition["NO"],
        )
        ne_peak = saha["ne_m3"]
        fp_GHz_val = plasma_frequency_GHz(ne_peak)

        # 6. Billig standoff
        billig = billig_sphere_standoff(
            M_inf=request.flight.mach,
            R_n_m=geom.effective_nose_radius_m(),
        )

        # 7. Build sheath field + LOS scan
        n_neutral_peak = P_t / (K_B * max(T_stag, 300.0))
        sheath_field = build_analytical_sheath_field(
            geometry=geom,
            ne_peak_stag=ne_peak, T_e_peak_K=T_stag,
            n_neutral_peak_m3=n_neutral_peak,
            mach_freestream=request.flight.mach,
        )

        bands_out: list[BandResult] = []
        bbox = geom.bounding_box()
        target = np.array([0.5 * bbox.length_m, 0.0, 0.0])
        integration_length = max(3.0 * bbox.length_m + 2.0, 0.1)

        for band in request.radar_bands:
            results = scan_aspect(
                sheath_field, target_position=target,
                f_hz=band.frequency_Hz,
                source_distance=integration_length,
                angles_deg=np.asarray(request.aspect_angles_deg),
                plane="xz",
                integration_length=integration_length,
                n_samples=2000, adaptive=True,
            )
            scan_dicts = [
                {"angle_deg": float(a),
                 "atten_dB": float(r.attenuation_db),
                 "status": r.detection}
                for a, r in zip(request.aspect_angles_deg, results)
            ]
            peak = max(scan_dicts, key=lambda d: d["atten_dB"])
            if peak["atten_dB"] >= 20:
                status = "BLACKOUT"
            elif peak["atten_dB"] >= 2:
                status = "DEGRADED"
            else:
                status = "DETECTABLE"
            bands_out.append(BandResult(
                label=band.label,
                frequency_Hz=band.frequency_Hz,
                peak_atten_dB=peak["atten_dB"],
                peak_aspect_deg=peak["angle_deg"],
                detection_status=status,
                aspect_scan=scan_dicts,
            ))

        notes = []
        if "error" in rg:
            notes.append(f"Real-gas stagnation Cantera unavailable: {rg['error']}. "
                          f"Using perfect-gas T_t = {T_t_pg:.0f} K.")
        notes.append(
            "Stagnation chemistry is geometry-independent under perfect-gas Pitot. "
            "Geometry effects flow through Billig standoff (sheath thickness) and "
            "the LOS path through the analytical sheath."
        )

        return SolverOutput(
            freestream=FreestreamOutput(
                T_inf_K=fs["T_K"], P_inf_Pa=fs["P_Pa"],
                rho_inf_kgm3=fs["rho_kgm3"], a_inf_ms=fs["a_ms"],
                U_inf_ms=U_inf,
            ),
            geometry=GeometryOutput(
                name=geom.name,
                nose_radius_m=geom.effective_nose_radius_m(),
                half_angle_deg=geom.effective_half_angle_deg(),
                length_m=geom.characteristic_length_m(),
                bow_shock_standoff_eq_mm=billig["delta_eq_m"] * 1000.0,
            ),
            stagnation=StagnationOutput(
                T_stag_K=T_stag, P_stag_Pa=P_t,
                ne_peak_m3=ne_peak, fp_GHz=fp_GHz_val,
                composition_x=composition,
            ),
            bands=bands_out,
            notes=notes,
        )
