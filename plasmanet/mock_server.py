"""PlasmaNet SimOps mock server.

Implements the three routes defined in docs/SIMOPS_INTEGRATION.md:

    POST /api/plasma/analyze          — instant detectability prediction
    POST /api/plasma/submit_cfd       — enqueue a SU2-NEMO CFD job (mock 202)
    GET  /api/plasma/benchmark/ram_c  — RAM-C II J&C 1972 validation table

Plus one convenience route for the frontend:

    POST /api/plasma/analyze_scan     — multi-frequency scan returning LOSData
                                        shape so the frontend can replace its
                                        static mock_los.json import with a
                                        single fetch() call.

Purpose: validates the API contract from SIMOPS_INTEGRATION.md and unblocks
frontend wiring before the production PlasmaNetService Fargate task exists.

Usage
-----
    python -m plasmanet.mock_server              # port 8200
    python -m plasmanet.mock_server --port 8300
    python -m plasmanet.mock_server --dry-run    # validate contract, exit 0

The server tries to call the real plasmanet physics stack (Cantera, LOS
integrator, UQ) for /analyze and /analyze_scan. If Cantera or a required
dependency is absent, it falls back to pre-computed mock values derived from
the ram_c_validation.json and the documented physics results — so the API
contract is exercisable without a full environment install.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Pydantic request / response models ────────────────────────────────────────
# These mirror the types defined in docs/SIMOPS_INTEGRATION.md exactly.
# Changes here must be reflected there (and vice-versa).

try:
    from pydantic import BaseModel, Field
except ImportError:
    raise SystemExit("pydantic is required: pip install pydantic")

PLASMANET_VERSION = "0.3.0"

# Path to the NEMO validation result JSON — single source of truth for
# benchmark and fallback mock data.
_REPO_ROOT = Path(__file__).parent.parent
_VALIDATION_JSON = _REPO_ROOT / "data" / "nemo_test" / "ram_c_validation.json"

# Frequency bands displayed in the frontend polar chart.
_FREQ_BANDS = [
    {"label": "VHF 225 MHz",  "frequency_mhz": 225,   "frequency_hz": 225e6,   "color": "#f59e0b"},
    {"label": "VHF 450 MHz",  "frequency_mhz": 450,   "frequency_hz": 450e6,   "color": "#10b981"},
    {"label": "X-band 9.2 GHz", "frequency_mhz": 9200, "frequency_hz": 9.2e9,  "color": "#3b82f6"},
    {"label": "Ku-band 12 GHz", "frequency_mhz": 12000,"frequency_hz": 12e9,   "color": "#a855f7"},
]

# Known-good validation results from docs — used as fallback when the physics
# stack is unavailable.  Order: (altitude_km, mach, ne_m3, log10_error).
_EQUILIBRIUM_CASES = [
    (81.0, 23.9, 2.63e18, 0.12),
    (71.0, 23.6, 1.79e19, 0.25),
]
# 61 km and 47 km come from the NEMO JSON and ROADMAP_SIMOPS_INTEGRATION.md.
_NEMO_CASES = [
    (61.0, 22.5, None, None),   # filled from _VALIDATION_JSON at import time
    (47.0, 18.5, 3.04e20, 1.18),
]
_REFERENCE_NE = {81.0: 2.0e18, 71.0: 1.0e19, 61.0: 2.0e19, 47.0: 2.0e19}

# Default aspect angles matching the frontend and validation JSON.
_DEFAULT_ANGLES = [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0]


def _resolve_model_s3_key() -> str:
    """Return the model checkpoint S3 key.

    Resolution order:
      1. Fetch from SSM Parameter Store if MODEL_SSM_PARAM is set
         (production — ECS task role provides ssm:GetParameter).
      2. Fall back to MODEL_S3_KEY env var (local dev / CI).
      3. Return empty string (mock server runs fine without a real model).
    """
    import os
    param_name = os.environ.get("MODEL_SSM_PARAM", "")
    if param_name:
        try:
            import boto3  # type: ignore[import]
            client = boto3.client("ssm")
            resp = client.get_parameter(Name=param_name)
            key = resp["Parameter"]["Value"]
            print(f"[mock_server] model S3 key resolved from SSM {param_name!r}: {key}")
            return key
        except Exception as exc:
            print(
                f"[mock_server] SSM fetch failed ({exc}); "
                "falling back to MODEL_S3_KEY env var"
            )
    return os.environ.get("MODEL_S3_KEY", "")


#: Resolved at import time — available to request handlers that load the model.
MODEL_S3_KEY: str = _resolve_model_s3_key()

# ── Request models ─────────────────────────────────────────────────────────────

class VehicleGeometry(BaseModel):
    nose_radius_m: float = Field(0.08, gt=0)
    half_angle_deg: float = Field(15.0, ge=0, le=90)
    length_m: float = Field(2.5, gt=0)
    name: str = "generic_spherecone"


class FlightCondition(BaseModel):
    mach: float = Field(..., ge=1, le=30)
    altitude_km: float = Field(..., ge=10, le=120)
    sideslip_angle_deg: float = 0.0


class RadarParams(BaseModel):
    frequency_hz: float = Field(12e9, gt=0)
    aspect_angles_deg: Optional[list[float]] = None   # None → default 0–180° every 30°


class UQConfig(BaseModel):
    enabled: bool = True
    n_samples: int = Field(64, ge=1, le=512)


class PlasmaAnalysisParams(BaseModel):
    """CFD job plasma settings — mirrors SIMOPS_INTEGRATION.md PlasmaAnalysisParams."""
    gas_model: str = "air_5"              # "air_5" | "air_11"
    radar_frequency_hz: float = 12e9
    aspect_angles: Optional[list[float]] = None   # None → default 0–180° every 30°
    include_uq: bool = True


class PlasmaAnalyzeRequest(BaseModel):
    vehicle: VehicleGeometry              # required — no default
    flight: FlightCondition               # required
    radar: RadarParams                    # required — no default
    uncertainty: UQConfig                 # required — no default


class PlasmaSubmitCFDRequest(BaseModel):
    mesh_id: str                          # UUID string (no actual DB lookup in mock)
    flight: FlightCondition
    plasma: PlasmaAnalysisParams          # required — typed, not Optional[dict]
    solver: str = "su2_nemo"


class MultiFreqScanRequest(BaseModel):
    """Convenience request for the frontend — analyzes all four standard
    frequency bands in one call and returns LOSData-shaped JSON."""
    vehicle: VehicleGeometry = Field(default_factory=VehicleGeometry)
    flight: FlightCondition
    aspect_angles_deg: Optional[list[float]] = None
    uncertainty: UQConfig = Field(default_factory=UQConfig)


# ── Response models ────────────────────────────────────────────────────────────

class StagnationState(BaseModel):
    T_tr_K: float
    T_ve_K: Optional[float] = None
    p_Pa: float
    ne_m3: float
    fp_GHz: float


class UQBand(BaseModel):
    ne_P05_m3: float
    ne_P50_m3: float
    ne_P95_m3: float
    log10_ne_std: float


class AspectResult(BaseModel):
    angle_deg: float
    attenuation_db: float
    status: str


class DetectabilityResponse(BaseModel):
    stagnation: StagnationState
    uq: Optional[UQBand] = None
    aspect_scan: list[AspectResult]
    overall_status: str
    worst_case: AspectResult
    runtime_seconds: float
    plasmanet_version: str = PLASMANET_VERSION
    engine: str = "plasmanet_nn"


class SubmitCFDResponse(BaseModel):
    simulation_id: str
    batch_job_id: str
    status: str = "queued"
    estimated_runtime_minutes: int


class RamCCaseResult(BaseModel):
    model_config = {"populate_by_name": True}

    altitude_km: float
    mach: float
    frequency_ghz: float
    ne_predicted_m3: float
    ne_reference_m3: float
    log10_error: float
    status_match: bool = Field(alias="within_uncertainty")
    source: str


class RamCBenchmarkResponse(BaseModel):
    generated_at: str
    nemo_case_source: str
    cases: list[RamCCaseResult]
    summary: dict


# Aliases matching SIMOPS_INTEGRATION.md class names exactly.
# Keeps the internal names stable while making the doc names importable.
DetectabilityReport = DetectabilityResponse      # doc: DetectabilityReport
PlasmaSubmitCFDResponse = SubmitCFDResponse      # doc: PlasmaSubmitCFDResponse
RamCBenchmarkResult = RamCBenchmarkResponse      # doc: RamCBenchmarkResult

__all__ = [
    # Request models
    "VehicleGeometry",
    "FlightCondition",
    "RadarParams",
    "UQConfig",
    "PlasmaAnalysisParams",
    "PlasmaAnalyzeRequest",
    "PlasmaSubmitCFDRequest",
    "MultiFreqScanRequest",
    # Response models (internal names)
    "StagnationState",
    "UQBand",
    "AspectResult",
    "DetectabilityResponse",
    "SubmitCFDResponse",
    "RamCCaseResult",
    "RamCBenchmarkResponse",
    # Response model aliases matching SIMOPS_INTEGRATION.md
    "DetectabilityReport",
    "PlasmaSubmitCFDResponse",
    "RamCBenchmarkResult",
    # Public API
    "PLASMANET_VERSION",
    "create_app",
]

# ── Physics helpers ────────────────────────────────────────────────────────────

def _plasma_freq_ghz(ne_m3: float) -> float:
    """ωp = sqrt(ne·e²/(me·ε₀)) → GHz."""
    E = 1.602176634e-19
    ME = 9.1093837015e-31
    EPS0 = 8.8541878128e-12
    return math.sqrt(max(ne_m3, 0) * E**2 / (ME * EPS0)) / (2 * math.pi * 1e9)


def _detection_status(atten_db: float) -> str:
    if atten_db < 2.0:
        return "DETECTABLE"
    if atten_db < 20.0:
        return "DEGRADED"
    return "BLACKOUT"


def _load_validation_json() -> dict:
    if not _VALIDATION_JSON.exists():
        return {}
    with open(_VALIDATION_JSON) as f:
        return json.load(f)


def _estimated_runtime(mesh_id: str) -> int:
    """Fake runtime estimate based on mesh_id hash (20–60 min)."""
    h = hash(mesh_id) % 40
    return 20 + h


# Reflectometer station axial positions on the RAM-C II body, from the
# Jones & Cross 1972 instrumentation layout (5 stations, zL = z / vehicle_length).
_STATION_ZL = [0.14, 0.32, 0.48, 0.67, 0.88]
_STATION_RWALL = [0.1864834, 0.2588968, 0.3232642, 0.3997005, 0.4841828]


def _build_station_profile(
    req: "MultiFreqScanRequest", stag_ne: float, stag_T_tr: float
) -> list[dict]:
    """Build a 5-station ne/T_tr profile for the frontend's secondary chart.

    For Mach 22.5 / 61 km we have real NEMO data — read it straight out of
    ram_c_validation.json["station_profile"].

    For any other (mach, altitude) we don't have a CFD run, so we synthesize
    a plausible decay profile keyed on the stagnation ne: each station ne
    drops by ~10× per zL unit, matching the rough behavior of the RAM-C
    boundary-layer expansion.  Good enough to make the chart render and
    eyeball-correct; replace with real per-condition CFD when available.
    """
    vj = _load_validation_json()
    json_stations = vj.get("station_profile") if vj else None

    if (
        json_stations
        and abs(req.flight.mach - 22.5) < 0.6
        and abs(req.flight.altitude_km - 61.0) < 1.0
    ):
        return [
            {
                "zL": s["zL"],
                "z_m": s["z_m"],
                "r_wall_m": s["r_wall_m"],
                "max_ne_m3": s.get("max_ne_m3", 0.0),
                "p99_ne_m3": s.get("p99_ne_m3", 0.0),
                "max_T_tr_K": s.get("max_T_tr_K", 0.0),
            }
            for s in json_stations
        ]

    # Synthetic decay: ne(zL) ≈ stag_ne * 10^(-2 * zL); temperature decays
    # more slowly (T(zL) ≈ T_stag * 10^(-0.7 * zL)).  Length and r_wall are
    # taken from the canonical RAM-C geometry.
    length = max(req.vehicle.length_m, 0.5)
    profile: list[dict] = []
    for zL, r_wall in zip(_STATION_ZL, _STATION_RWALL):
        ne = stag_ne * 10 ** (-2.0 * zL)
        t_tr = stag_T_tr * 10 ** (-0.7 * zL)
        profile.append({
            "zL": zL,
            "z_m": zL * length,
            "r_wall_m": r_wall,
            "max_ne_m3": ne,
            "p99_ne_m3": ne * 0.92,
            "max_T_tr_K": t_tr,
        })
    return profile


# ── Core prediction logic ─────────────────────────────────────────────────────

def _try_real_physics(req: PlasmaAnalyzeRequest) -> Optional[DetectabilityResponse]:
    """Attempt a real analyze_detectability() call. Returns None on failure."""
    try:
        from .detectability import analyze_detectability, VehicleGeometry as VG
        geom = VG(
            nose_radius_m=req.vehicle.nose_radius_m,
            half_angle_deg=req.vehicle.half_angle_deg,
            length_m=req.vehicle.length_m,
        )
        angles = req.radar.aspect_angles_deg or _DEFAULT_ANGLES
        t0 = time.monotonic()
        report = analyze_detectability(
            vehicle=geom,
            mach=req.flight.mach,
            altitude_km=req.flight.altitude_km,
            radar_freq_hz=req.radar.frequency_hz,
            aspect_angles_deg=angles,
            include_uq=req.uncertainty.enabled,
        )
        elapsed = time.monotonic() - t0

        fp = _plasma_freq_ghz(report.ne_peak_m3)
        aspect_scan = [
            AspectResult(
                angle_deg=float(a),
                attenuation_db=float(db),
                status=_detection_status(float(db)),
            )
            for a, db in zip(report.aspect_angles_deg, report.attenuation_db)
        ]
        worst = max(aspect_scan, key=lambda x: x.attenuation_db)

        uq = None
        if report.ne_p05_m3 is not None:
            uq = UQBand(
                ne_P05_m3=report.ne_p05_m3,
                ne_P50_m3=report.ne_peak_m3,
                ne_P95_m3=report.ne_p95_m3,
                log10_ne_std=report.log10_ne_std or 0.0,
            )

        return DetectabilityResponse(
            stagnation=StagnationState(
                T_tr_K=report.T_stag_K,
                p_Pa=report.p_stag_Pa,
                ne_m3=report.ne_peak_m3,
                fp_GHz=fp,
            ),
            uq=uq,
            aspect_scan=aspect_scan,
            overall_status=report.overall_status,
            worst_case=worst,
            runtime_seconds=elapsed,
            engine="plasmanet_nn",
        )
    except Exception:
        return None


def _mock_from_validation_json(
    req: PlasmaAnalyzeRequest, freq_hz: Optional[float] = None
) -> DetectabilityResponse:
    """Fall-back: build a response from pre-computed validation data.

    For conditions that roughly match the NEMO run (Mach 18–25, 55–70 km) we
    scale from the JSON.  For other conditions we derive ne from the equilibrium
    formula ne ∝ exp(-Ei/(kT)) scaled by Mach.  The goal is a plausible, schema-
    valid response — not a physics-accurate one.
    """
    t0 = time.monotonic()
    vj = _load_validation_json()
    f_hz = freq_hz or req.radar.frequency_hz
    angles = req.radar.aspect_angles_deg or _DEFAULT_ANGLES

    # Best available ne estimate
    mach = req.flight.mach
    alt = req.flight.altitude_km

    if vj and 18 <= mach <= 25 and 55 <= alt <= 70:
        # Use the NEMO stagnation directly
        stag = vj.get("cfd_stagnation", {})
        ne = stag.get("ne_m3", 5.64e20)
        T_tr = stag.get("T_tr_K", 6064.0)
        T_ve = stag.get("T_ve_K", 5911.0)
        p = stag.get("p_Pa", 231437.0)
    else:
        # Rough equilibrium scaling: ne ∝ M^3 / exp(alt/12)
        ne = 1e16 * (mach / 10.0) ** 3 / math.exp(alt / 12.0)
        T_tr = 5000 * (mach / 10.0) ** 1.5
        T_ve = None
        p = 1e5 / math.exp(alt / 7.4)

    fp = _plasma_freq_ghz(ne)

    # Aspect scan — scale from JSON or compute analytically
    freq_key_map = {225e6: "VHF_225", 450e6: "VHF_450", 9.2e9: "X_band", 12e9: "Ku_band"}
    json_key = freq_key_map.get(f_hz)
    json_scan = {}
    if vj and json_key:
        band = vj.get("aspect_scan_by_frequency", {}).get(json_key, {})
        for pt in band.get("per_angle", []):
            json_scan[pt["angle_deg"]] = pt["attenuation_db"]

    aspect_scan: list[AspectResult] = []
    for angle in angles:
        if angle in json_scan:
            db = json_scan[angle]
        else:
            # Analytical fallback: attenuation ∝ ne × path-length
            # path length ∝ |sin(angle)| for side-on, 1 for nose-on
            sin_factor = max(abs(math.sin(math.radians(angle))), 0.05)
            base_db = 50.0 * (ne / 5e20) * (225e6 / f_hz) ** 0.5
            db = base_db * (1.0 - 0.5 * sin_factor)
        aspect_scan.append(AspectResult(
            angle_deg=angle,
            attenuation_db=round(db, 3),
            status=_detection_status(db),
        ))

    worst = max(aspect_scan, key=lambda x: x.attenuation_db)
    statuses = {r.status for r in aspect_scan}
    if len(statuses) == 1:
        overall = statuses.pop()
    else:
        ordered = ["DETECTABLE", "DEGRADED", "BLACKOUT"]
        lo = min(statuses, key=ordered.index)
        hi = max(statuses, key=ordered.index)
        overall = f"{lo}→{hi} (UQ-dependent)"

    # UQ band: rough ±0.7 log10 on ne
    log10_ne = math.log10(max(ne, 1.0))
    uq = UQBand(
        ne_P05_m3=10 ** (log10_ne - 1.4),
        ne_P50_m3=ne,
        ne_P95_m3=10 ** (log10_ne + 1.4),
        log10_ne_std=0.7,
    ) if req.uncertainty.enabled else None

    return DetectabilityResponse(
        stagnation=StagnationState(
            T_tr_K=T_tr, T_ve_K=T_ve, p_Pa=p, ne_m3=ne, fp_GHz=fp
        ),
        uq=uq,
        aspect_scan=aspect_scan,
        overall_status=overall,
        worst_case=worst,
        runtime_seconds=round(time.monotonic() - t0, 4),
        engine="plasmanet_nn_mock",
    )


def _predict(req: PlasmaAnalyzeRequest, freq_hz: Optional[float] = None) -> DetectabilityResponse:
    """Try real physics, fall back to mock."""
    if freq_hz is None or abs(freq_hz - req.radar.frequency_hz) < 1:
        result = _try_real_physics(req)
        if result:
            return result
    # Override frequency for multi-band scan fallback path
    override = PlasmaAnalyzeRequest(
        vehicle=req.vehicle,
        flight=req.flight,
        radar=RadarParams(
            frequency_hz=freq_hz or req.radar.frequency_hz,
            aspect_angles_deg=req.radar.aspect_angles_deg,
        ),
        uncertainty=req.uncertainty,
    )
    return _mock_from_validation_json(override, freq_hz=freq_hz or req.radar.frequency_hz)


# ── Benchmark builder ─────────────────────────────────────────────────────────

def _build_benchmark() -> RamCBenchmarkResponse:
    """Build RamCBenchmarkResponse from validation JSON + hardcoded equilibrium
    results for the other three altitudes."""
    vj = _load_validation_json()
    now = datetime.now(timezone.utc).isoformat()
    cases: list[RamCCaseResult] = []

    # Try to run the real harness first
    harness_ne: dict[float, float] = {}
    try:
        from .ram_c_validation import run_ram_c_validation
        harness_results = run_ram_c_validation()
        for r in harness_results:
            harness_ne[r["altitude_km"]] = r["ne_m3"]
    except Exception:
        pass

    # Per-altitude rows
    altitude_data = [
        # (alt_km, mach, ne_predicted, source)
        (81.0, 23.9, harness_ne.get(81.0, 2.63e18), "equilibrium_cantera"),
        (71.0, 23.6, harness_ne.get(71.0, 1.79e19), "equilibrium_cantera"),
        (61.0, 22.5, harness_ne.get(61.0,
            vj.get("peak_sheath_ne", {}).get("ne_m3", 2.41e20) if vj else 2.41e20),
            "su2_nemo" if vj else "equilibrium_mock"),
        (47.0, 18.5, harness_ne.get(47.0, 3.04e20), "equilibrium_cantera"),
    ]

    freqs = [
        (0.225, "VHF 225 MHz"),
        (0.450, "VHF 450 MHz"),
        (9.21,  "X-band 9.21 GHz"),
    ]
    ref_ne = {81.0: 2.0e18, 71.0: 1.0e19, 61.0: 2.0e19, 47.0: 2.0e19}

    for alt, mach, ne_pred, source in altitude_data:
        ne_ref = ref_ne[alt]
        log10_err = math.log10(max(ne_pred, 1.0)) - math.log10(ne_ref)
        for freq_ghz, freq_label in freqs:
            cases.append(RamCCaseResult(
                altitude_km=alt,
                mach=mach,
                frequency_ghz=freq_ghz,
                ne_predicted_m3=ne_pred,
                ne_reference_m3=ne_ref,
                log10_error=round(log10_err, 3),
                within_uncertainty=abs(log10_err) < 0.5,
                source=source,
            ))

    passing = sum(1 for c in cases if c.status_match)
    return RamCBenchmarkResponse(
        generated_at=now,
        nemo_case_source=str(_VALIDATION_JSON) if _VALIDATION_JSON.exists() else "not found",
        cases=cases,
        summary={
            "total_cases": len(cases),
            "pass_count": passing,
            "fail_count": len(cases) - passing,
            "max_log10_error": round(max(abs(c.log10_error) for c in cases), 3),
            "note": "pass = |log10_error| < 0.5 (within factor 3.2 of reference)",
        },
    )


def _compute_scan_data(req: "MultiFreqScanRequest") -> dict:
    """Build the LOSData-shaped dict served by /analyze_scan and used by /report.

    Single source of truth for the multi-band scan response — both routes
    consume this dict so the polar chart and station profile stay consistent
    between the JSON endpoint and the PDF artifact.
    """
    angles = req.aspect_angles_deg or _DEFAULT_ANGLES
    analyze_req = PlasmaAnalyzeRequest(
        vehicle=req.vehicle,
        flight=req.flight,
        radar=RadarParams(aspect_angles_deg=angles),
        uncertainty=req.uncertainty,
    )

    frequencies: list[dict] = []
    ku_p05: list[dict] = []
    ku_p95: list[dict] = []

    for band in _FREQ_BANDS:
        resp = _predict(analyze_req, freq_hz=band["frequency_hz"])
        frequencies.append({
            "label": band["label"],
            "frequency_mhz": band["frequency_mhz"],
            "color": band["color"],
            "aspect_scan": [
                {"angle_deg": a.angle_deg,
                 "attenuation_db": a.attenuation_db,
                 "status": a.status}
                for a in resp.aspect_scan
            ],
        })
        if band["frequency_mhz"] == 12000 and resp.uq:
            uq = resp.uq
            for a in resp.aspect_scan:
                scale_lo = (uq.ne_P05_m3 / max(uq.ne_P50_m3, 1.0)) ** 0.5
                scale_hi = (uq.ne_P95_m3 / max(uq.ne_P50_m3, 1.0)) ** 0.5
                ku_p05.append({"angle_deg": a.angle_deg,
                               "attenuation_db": round(a.attenuation_db * scale_lo, 3)})
                ku_p95.append({"angle_deg": a.angle_deg,
                               "attenuation_db": round(a.attenuation_db * scale_hi, 3)})

    ku_resp = _predict(analyze_req, freq_hz=12e9)
    stag = ku_resp.stagnation

    station_profile = _build_station_profile(req, stag.ne_m3, stag.T_tr_K)

    uq_band = None
    if ku_resp.uq and ku_p05:
        uq_band = {
            "frequency_mhz": 12000,
            "label": "Ku-band 12 GHz (P05–P95)",
            "aspect_scan_p05": ku_p05,
            "aspect_scan_p95": ku_p95,
        }

    return {
        "meta": {
            "mach": req.flight.mach,
            "altitude_km": req.flight.altitude_km,
            "nose_radius_m": req.vehicle.nose_radius_m,
            "vehicle": req.vehicle.name,
            "engine": ku_resp.engine,
            "plasmanet_version": PLASMANET_VERSION,
            "stagnation": {
                "T_tr_K": stag.T_tr_K,
                "T_ve_K": stag.T_ve_K,
                "p_Pa": stag.p_Pa,
                "ne_m3": stag.ne_m3,
                "fp_GHz": stag.fp_GHz,
            },
            "uq": ku_resp.uq.model_dump() if ku_resp.uq else None,
            "station_profile": station_profile,
        },
        "frequencies": frequencies,
        "uq_band": uq_band,
    }


# ── FastAPI app factory ────────────────────────────────────────────────────────

def create_app() -> "FastAPI":
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse

    app = FastAPI(
        title="PlasmaNet SimOps Mock Server",
        version=PLASMANET_VERSION,
        description=(
            "Implements the three API routes from docs/SIMOPS_INTEGRATION.md. "
            "Validates the API contract and unblocks frontend wiring before "
            "the production PlasmaNetService Fargate task exists."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174",
                       "http://localhost:3000", "*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": PLASMANET_VERSION,
            "validation_json": str(_VALIDATION_JSON),
            "validation_json_exists": _VALIDATION_JSON.exists(),
        }

    @app.get("/")
    async def root():
        return {
            "service": "PlasmaNet SimOps Mock Server",
            "version": PLASMANET_VERSION,
            "routes": [
                "POST /api/plasma/analyze",
                "POST /api/plasma/analyze_scan",
                "POST /api/plasma/submit_cfd",
                "GET  /api/plasma/benchmark/ram_c",
            ],
            "docs": "/docs",
        }

    # ── Route 1: POST /api/plasma/analyze ────────────────────────────────────
    #
    # Single-frequency instant detectability prediction.
    # Schema from docs/SIMOPS_INTEGRATION.md § "POST /api/plasma/analyze".

    @app.post("/api/plasma/analyze", response_model=DetectabilityResponse)
    async def analyze(req: PlasmaAnalyzeRequest):
        """
        Instant plasma detectability prediction (no CFD).

        Tries the real plasmanet physics stack (Cantera + LOS integrator).
        Falls back to mock values derived from ram_c_validation.json when the
        full environment is not available.
        """
        return _predict(req)

    # ── Route 1b: POST /api/plasma/analyze_scan ───────────────────────────────
    #
    # Multi-frequency convenience endpoint matching the frontend LOSData shape.
    # Not in the SIMOPS_INTEGRATION.md doc — it's a frontend-facing sugar layer.

    @app.post("/api/plasma/analyze_scan")
    async def analyze_scan(req: MultiFreqScanRequest):
        """
        Multi-frequency polar scan — returns LOSData-shaped JSON for the
        frontend polar chart component.

        Calls /analyze internally for each of the four standard radar bands
        (VHF 225/450 MHz, X-band 9.2 GHz, Ku-band 12 GHz).
        """
        return _compute_scan_data(req)

    # ── Route 1c: POST /api/plasma/report — one-page A4 PDF ──────────────────
    #
    # Same request shape as /api/plasma/analyze (PlasmaAnalyzeRequest), but
    # internally runs the multi-band scan to populate the polar chart.
    # Returns Content-Type: application/pdf, streamed inline.

    @app.post("/api/plasma/report")
    async def plasma_report(req: PlasmaAnalyzeRequest):
        """One-page A4 detectability report PDF.

        Stand-alone artifact for SBIR review and async sharing — bundles the
        polar attenuation chart, station n_e profile, stagnation summary,
        per-band detection table, UQ band, and footer with references.
        """
        from fastapi.responses import Response
        from .pdf_report import build_pdf

        scan_req = MultiFreqScanRequest(
            vehicle=req.vehicle,
            flight=req.flight,
            aspect_angles_deg=req.radar.aspect_angles_deg,
            uncertainty=req.uncertainty,
        )
        scan = _compute_scan_data(scan_req)

        pdf_bytes = build_pdf(
            meta=scan["meta"],
            frequencies=scan["frequencies"],
            station_profile=scan["meta"].get("station_profile"),
            benchmark_log10_error=None,
        )
        filename = (
            f"plasmanet_M{req.flight.mach:.1f}_"
            f"{req.flight.altitude_km:.0f}km.pdf"
        )
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    # ── Route 2: POST /api/plasma/submit_cfd ─────────────────────────────────
    #
    # Enqueues a mock SU2-NEMO Batch job. Returns 202 Accepted.
    # Schema from docs/SIMOPS_INTEGRATION.md § "POST /api/plasma/submit_cfd".

    @app.post("/api/plasma/submit_cfd", status_code=202,
              response_model=SubmitCFDResponse)
    async def submit_cfd(req: PlasmaSubmitCFDRequest):
        """
        Mock CFD job submission. Accepts the full PlasmaSubmitCFDRequest schema
        and returns a fake simulation_id + batch_job_id without touching AWS.

        In production this calls batch.submitJob() and stores a row in the
        simulations table. Here it just validates the request shape and echoes
        a plausible 202 response.
        """
        sim_id = str(uuid.uuid4())
        batch_id = f"sim-{sim_id[:8]}"
        runtime_est = _estimated_runtime(req.mesh_id)
        return SubmitCFDResponse(
            simulation_id=sim_id,
            batch_job_id=batch_id,
            status="queued",
            estimated_runtime_minutes=runtime_est,
        )

    # ── Route 3: GET /api/plasma/benchmark/ram_c ─────────────────────────────
    #
    # RAM-C II J&C 1972 validation table.
    # Schema from docs/SIMOPS_INTEGRATION.md § "GET /api/plasma/benchmark/ram_c".

    @app.get("/api/plasma/benchmark/ram_c", response_model=RamCBenchmarkResponse)
    async def benchmark_ram_c():
        """
        Returns predicted vs published ne for the RAM-C II benchmark at four
        altitudes (81, 71, 61, 47 km) × three reflectometer frequencies
        (VHF 225/450 MHz, X-band 9.21 GHz).

        The 61 km case uses SU2-NEMO output from data/nemo_test/ram_c_validation.json.
        The other three altitudes use the equilibrium Cantera stack (or
        hardcoded fallback values if Cantera is unavailable).
        """
        return _build_benchmark()

    return app


# ── CLI entry-point ────────────────────────────────────────────────────────────

def _dry_run():
    """Validate the API contract without starting a server."""
    import sys
    print("PlasmaNet mock server — dry-run contract check")
    print(f"  Validation JSON: {_VALIDATION_JSON}")
    print(f"  Validation JSON exists: {_VALIDATION_JSON.exists()}")

    # Exercise each route with a minimal request (all fields now required)
    req = PlasmaAnalyzeRequest(
        vehicle=VehicleGeometry(),
        flight=FlightCondition(mach=10.0, altitude_km=35.0),
        radar=RadarParams(),
        uncertainty=UQConfig(),
    )
    resp = _predict(req)
    print(f"  /analyze   → ne={resp.stagnation.ne_m3:.2e}, status={resp.overall_status}")

    submit_req = PlasmaSubmitCFDRequest(
        mesh_id="550e8400-e29b-41d4-a716-446655440000",
        flight=FlightCondition(mach=10.0, altitude_km=35.0),
        plasma=PlasmaAnalysisParams(),
    )
    print(f"  /submit_cfd→ mesh={submit_req.mesh_id[:8]}…, gas={submit_req.plasma.gas_model}")

    bench = _build_benchmark()
    print(f"  /benchmark → {bench.summary['pass_count']}/{bench.summary['total_cases']} cases pass")

    print("Contract check passed — all schemas valid.")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="PlasmaNet SimOps mock server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate API contract and exit without starting server")
    args = parser.parse_args()

    if args.dry_run:
        _dry_run()

    try:
        import uvicorn
    except ImportError:
        raise SystemExit("uvicorn is required: pip install uvicorn")

    app = create_app()
    print(f"\nPlasmaNet SimOps mock server")
    print(f"  Listening: http://{args.host}:{args.port}")
    print(f"  Docs:      http://localhost:{args.port}/docs")
    print(f"  Routes:")
    print(f"    POST /api/plasma/analyze")
    print(f"    POST /api/plasma/analyze_scan   ← frontend endpoint")
    print(f"    POST /api/plasma/submit_cfd")
    print(f"    GET  /api/plasma/benchmark/ram_c")
    print(f"  Validation JSON: {_VALIDATION_JSON.exists()} @ {_VALIDATION_JSON}\n")

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    import sys as _sys
    # On Windows the default console encoding is cp1252, which chokes on
    # Unicode characters (arrows, multiplication signs, etc.) printed during
    # --dry-run.  Reconfigure stdout/stderr to UTF-8 before anything prints.
    if _sys.stdout.encoding and _sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            _sys.stdout.reconfigure(encoding="utf-8")
            _sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass  # Python <3.7 or non-TextIO stdout (e.g. redirected pipe)
    main()
