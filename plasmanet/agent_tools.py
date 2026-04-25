"""LLM-callable tool wrappers for Pydantic AI / KhoriumAgents.

Roadmap milestone I-6: lets a Claude or GPT agent in KhoriumAgents answer
questions like "What's the detection status for Mach 18 at 50 km?" by
calling the deployed PlasmaNetService over HTTP.

Public surface
--------------
analyze_plasma(input)            async function — direct callable, returns
                                 AnalyzePlasmaOutput (typed summary).
generate_plasma_report(input)    async function — returns a one-page A4
                                 PDF as raw bytes, suitable for Slack
                                 attachment or S3 upload by the caller.
ANALYZE_PLASMA_TOOL              pydantic_ai.Tool wrapper for analyze_plasma
                                 (None if pydantic_ai not installed).
GENERATE_PLASMA_REPORT_TOOL      pydantic_ai.Tool wrapper for the report fn.

Soft dependency on pydantic_ai
------------------------------
pydantic_ai is *not* a dependency of plasmanet — it only matters in the
KhoriumAgents repo where this tool is registered. We import it inside a
try/except so importing this module from anywhere (server, tests, scripts)
works without pydantic_ai installed. ANALYZE_PLASMA_TOOL is None when the
import fails; KhoriumAgents pins pydantic_ai so the wrapper resolves there.

Configuration
-------------
PLASMANET_SERVICE_URL    Base URL of the inference service. Default:
                         http://localhost:8200 (mock_server.py)
PLASMANET_REQUEST_TIMEOUT_S
                         httpx timeout, default 10.0 seconds.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from pydantic import BaseModel, Field


# ── Soft pydantic_ai import ──────────────────────────────────────────────────

try:
    from pydantic_ai import Tool as _PydanticAITool   # type: ignore[import-not-found]
    _HAS_PYDANTIC_AI = True
except ImportError:                                   # pragma: no cover
    _PydanticAITool = None                            # type: ignore[assignment]
    _HAS_PYDANTIC_AI = False


# ── Tool input + output schemas ───────────────────────────────────────────────

class AnalyzePlasmaInput(BaseModel):
    """Inputs an LLM passes when calling analyze_plasma."""

    mach: float = Field(..., ge=1.0, le=30.0,
                        description="Mach number, 1–30")
    altitude_km: float = Field(..., ge=10.0, le=120.0,
                               description="Altitude in km, 10–120")
    vehicle_name: str = Field(
        "ram_c",
        description='Vehicle preset: "ram_c" or "generic_spherecone"',
    )
    radar_frequency_hz: float = Field(
        9.2e9, gt=0,
        description="Radar carrier frequency in Hz (default X-band 9.2 GHz)",
    )
    include_uq: bool = Field(
        True,
        description="Run 64-sample Monte-Carlo for the P05/P95 nₑ band",
    )


class StagnationSummary(BaseModel):
    T_tr_K: float
    T_ve_K: Optional[float] = None
    p_Pa: float
    ne_m3: float
    fp_GHz: float


class WorstCase(BaseModel):
    angle_deg: float
    attenuation_db: float
    status: str


class UQSummary(BaseModel):
    ne_P05_m3: float
    ne_P50_m3: float
    ne_P95_m3: float
    log10_ne_std: float


class AnalyzePlasmaOutput(BaseModel):
    """LLM-friendly summary of a DetectabilityReport — only the fields a
    downstream agent needs to answer detection questions in natural language."""

    stagnation: StagnationSummary
    overall_status: str
    worst_case: WorstCase
    uq_band: Optional[UQSummary] = None
    runtime_seconds: Optional[float] = None
    plasmanet_version: Optional[str] = None
    engine: Optional[str] = None


# ── Vehicle presets ───────────────────────────────────────────────────────────

_VEHICLE_PRESETS: dict[str, dict] = {
    "ram_c": {
        "nose_radius_m": 0.1524,
        "half_angle_deg": 9.0,
        "length_m": 1.295,
        "name": "ram_c",
    },
    "generic_spherecone": {
        "nose_radius_m": 0.08,
        "half_angle_deg": 15.0,
        "length_m": 2.5,
        "name": "generic_spherecone",
    },
}


# ── Tool implementation ──────────────────────────────────────────────────────

async def analyze_plasma(input: AnalyzePlasmaInput) -> AnalyzePlasmaOutput:
    """LLM-callable: returns plasma detectability for a flight condition.

    Calls the deployed PlasmaNetService at PLASMANET_SERVICE_URL via the
    standard /api/plasma/analyze contract. Returns the
    DetectabilityReport summary fields the agent needs to answer
    questions like "would a StarLink satellite see this vehicle?".

    Raises
    ------
    RuntimeError
        On HTTP error (non-2xx), connect/read timeout, or malformed
        response. The message includes the underlying httpx exception
        for diagnostics.
    """
    base_url = os.environ.get(
        "PLASMANET_SERVICE_URL", "http://localhost:8200"
    ).rstrip("/")
    timeout_s = float(os.environ.get("PLASMANET_REQUEST_TIMEOUT_S", "10.0"))

    vehicle = _VEHICLE_PRESETS.get(
        input.vehicle_name, _VEHICLE_PRESETS["generic_spherecone"]
    )

    payload = {
        "vehicle": vehicle,
        "flight": {
            "mach": input.mach,
            "altitude_km": input.altitude_km,
        },
        "radar": {
            "frequency_hz": input.radar_frequency_hz,
            # default angle grid covers nose-on through tail-on
            "aspect_angles_deg": [0, 30, 60, 90, 120, 150, 180],
        },
        "uncertainty": {"enabled": input.include_uq, "n_samples": 64},
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(f"{base_url}/api/plasma/analyze", json=payload)
            resp.raise_for_status()
            body = resp.json()
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"PlasmaNetService timed out after {timeout_s}s at {base_url}: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"PlasmaNetService returned HTTP {exc.response.status_code} at {base_url}: "
            f"{exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"PlasmaNetService request failed at {base_url}: {exc}"
        ) from exc

    try:
        return AnalyzePlasmaOutput(
            stagnation=StagnationSummary(**body["stagnation"]),
            overall_status=body["overall_status"],
            worst_case=WorstCase(**body["worst_case"]),
            uq_band=UQSummary(**body["uq"]) if body.get("uq") else None,
            runtime_seconds=body.get("runtime_seconds"),
            plasmanet_version=body.get("plasmanet_version"),
            engine=body.get("engine"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"PlasmaNetService returned a malformed response: {exc}"
        ) from exc


# ── Report generation tool ────────────────────────────────────────────────────

async def generate_plasma_report(input: AnalyzePlasmaInput) -> bytes:
    """LLM-callable: returns a one-page PDF detectability report as bytes.

    Calls POST /api/plasma/report on the deployed PlasmaNetService. The
    response is a complete A4 PDF (header, polar chart, station profile,
    detection status table, UQ band, optional RAM-C validation snippet).
    Suitable for Slack attachment or S3 upload by the calling agent.

    Production note: KhoriumAgents typically uploads the bytes to S3 and
    posts a presigned URL to the user — see roadmap I-6 for the upload
    contract. The mock server returns bytes directly to keep the agent
    tool deployable independently of the upload pipeline.

    Raises
    ------
    RuntimeError
        On HTTP error, timeout, or a response with the wrong Content-Type.
    """
    base_url = os.environ.get(
        "PLASMANET_SERVICE_URL", "http://localhost:8200"
    ).rstrip("/")
    # PDF generation is heavier than /analyze — allow a longer default.
    timeout_s = float(os.environ.get("PLASMANET_REPORT_TIMEOUT_S", "30.0"))

    vehicle = _VEHICLE_PRESETS.get(
        input.vehicle_name, _VEHICLE_PRESETS["generic_spherecone"]
    )

    payload = {
        "vehicle": vehicle,
        "flight": {
            "mach": input.mach,
            "altitude_km": input.altitude_km,
        },
        "radar": {
            "frequency_hz": input.radar_frequency_hz,
            "aspect_angles_deg": [0, 30, 60, 90, 120, 150, 180],
        },
        "uncertainty": {"enabled": input.include_uq, "n_samples": 64},
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(f"{base_url}/api/plasma/report", json=payload)
            resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise RuntimeError(
            f"PlasmaNetService /report timed out after {timeout_s}s at {base_url}: {exc}"
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"PlasmaNetService /report returned HTTP {exc.response.status_code} "
            f"at {base_url}: {exc.response.text[:200]}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"PlasmaNetService /report request failed at {base_url}: {exc}"
        ) from exc

    content_type = resp.headers.get("content-type", "")
    if not content_type.startswith("application/pdf"):
        raise RuntimeError(
            f"PlasmaNetService /report returned unexpected Content-Type "
            f"{content_type!r} (expected application/pdf)"
        )

    body = resp.content
    if body[:5] != b"%PDF-":
        raise RuntimeError(
            "PlasmaNetService /report returned a body that doesn't start "
            "with %PDF- magic bytes — response is not a valid PDF"
        )

    return body


# ── Pydantic AI tool registration ────────────────────────────────────────────

ANALYZE_PLASMA_TOOL = (
    _PydanticAITool(
        analyze_plasma,
        name="analyze_plasma",
        description=(
            "Predict radar detectability of a hypersonic vehicle at the given "
            "flight condition. Returns stagnation thermochemistry, peak "
            "attenuation across aspect angles, and an overall status of "
            "DETECTABLE / DEGRADED / BLACKOUT."
        ),
    )
    if _HAS_PYDANTIC_AI
    else None
)

GENERATE_PLASMA_REPORT_TOOL = (
    _PydanticAITool(
        generate_plasma_report,
        name="generate_plasma_report",
        description=(
            "Generate a one-page PDF detectability report for a hypersonic "
            "vehicle at the given flight condition. Returns the PDF bytes "
            "(header, polar attenuation chart, n_e station profile, "
            "detection status table, UQ band, references). Use when the "
            "user wants a shareable artifact rather than an inline answer."
        ),
    )
    if _HAS_PYDANTIC_AI
    else None
)


__all__ = [
    "AnalyzePlasmaInput",
    "AnalyzePlasmaOutput",
    "StagnationSummary",
    "WorstCase",
    "UQSummary",
    "analyze_plasma",
    "generate_plasma_report",
    "ANALYZE_PLASMA_TOOL",
    "GENERATE_PLASMA_REPORT_TOOL",
]
