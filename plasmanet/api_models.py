"""Pydantic request / response models for the PlasmaNet SimOps API.

Single source of truth for the schemas defined in
docs/SIMOPS_INTEGRATION.md §4.  Imported by:

  - plasmanet.mock_server (the FastAPI app that serves them)
  - plasmanet.pdf_report  (reads stagnation / aspect data into the PDF)
  - plasmanet.agent_tools (Pydantic AI tool input/output typing)
  - tests/test_mock_server_contract.py (drift-detection assertion that
    every doc-defined class name appears in this module's __all__)

Changes here MUST be reflected in docs/SIMOPS_INTEGRATION.md (and vice
versa).  The drift detector enforces class-name parity; field-level drift
is caught by the contract tests.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

PLASMANET_VERSION = "0.3.0"


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
# Keep the internal names stable while making the doc names importable.
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
    # Module constants
    "PLASMANET_VERSION",
]
