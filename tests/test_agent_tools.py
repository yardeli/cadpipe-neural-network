"""Integration tests for plasmanet/agent_tools.py.

Mocks the upstream PlasmaNetService via an in-process httpx-served HTTP
server (pytest-httpserver) so the real network is never touched.

Coverage:
  test_analyze_plasma_happy_path        Valid response → AnalyzePlasmaOutput
  test_analyze_plasma_request_url       POST goes to /api/plasma/analyze
  test_analyze_plasma_request_payload   vehicle preset + UQ flag round-trip
  test_analyze_plasma_uq_optional       missing uq → uq_band is None
  test_http_error_raises_runtime        500 → RuntimeError with status code
  test_timeout_raises_runtime           slow server → RuntimeError mentioning timeout
  test_malformed_response_raises_runtime  missing required key → RuntimeError
  test_vehicle_preset_dispatch          ram_c vs generic_spherecone vs unknown
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from plasmanet.agent_tools import (
    AnalyzePlasmaInput,
    AnalyzePlasmaOutput,
    analyze_plasma,
    _VEHICLE_PRESETS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _sample_response() -> dict:
    """Mirrors the DetectabilityResponse shape from plasmanet.mock_server."""
    return {
        "stagnation": {
            "T_tr_K": 6063.9,
            "T_ve_K": 5910.6,
            "p_Pa": 231437.3,
            "ne_m3": 5.64e20,
            "fp_GHz": 213.0,
        },
        "uq": {
            "ne_P05_m3": 1.2e19,
            "ne_P50_m3": 5.64e20,
            "ne_P95_m3": 2.6e21,
            "log10_ne_std": 0.74,
        },
        "aspect_scan": [
            {"angle_deg": 0,   "attenuation_db": 1900, "status": "BLACKOUT"},
            {"angle_deg": 90,  "attenuation_db": 990,  "status": "BLACKOUT"},
            {"angle_deg": 180, "attenuation_db": 740,  "status": "BLACKOUT"},
        ],
        "overall_status": "BLACKOUT",
        "worst_case": {"angle_deg": 0, "attenuation_db": 1900, "status": "BLACKOUT"},
        "runtime_seconds": 0.42,
        "plasmanet_version": "0.3.0",
        "engine": "plasmanet_nn",
    }


@pytest.fixture
def service_env(httpserver, monkeypatch):
    """Point the agent tool at the in-process httpserver."""
    monkeypatch.setenv(
        "PLASMANET_SERVICE_URL", httpserver.url_for("").rstrip("/")
    )
    monkeypatch.setenv("PLASMANET_REQUEST_TIMEOUT_S", "5.0")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if not _is_event_loop_running() \
        else asyncio.run(coro)


def _is_event_loop_running() -> bool:
    try:
        loop = asyncio.get_event_loop()
        return loop.is_running()
    except RuntimeError:
        return False


# ── Happy path ────────────────────────────────────────────────────────────────

def test_analyze_plasma_happy_path(service_env, httpserver):
    httpserver.expect_request(
        "/api/plasma/analyze", method="POST"
    ).respond_with_json(_sample_response())

    out = asyncio.run(analyze_plasma(
        AnalyzePlasmaInput(mach=22.5, altitude_km=61.0)
    ))

    assert isinstance(out, AnalyzePlasmaOutput)
    assert out.overall_status == "BLACKOUT"
    assert out.stagnation.T_tr_K == pytest.approx(6063.9)
    assert out.stagnation.T_ve_K == pytest.approx(5910.6)
    assert out.worst_case.attenuation_db == pytest.approx(1900)
    assert out.uq_band is not None
    assert out.uq_band.ne_P95_m3 == pytest.approx(2.6e21)
    assert out.runtime_seconds == pytest.approx(0.42)
    assert out.plasmanet_version == "0.3.0"


def test_analyze_plasma_request_url(service_env, httpserver):
    """Call goes to /api/plasma/analyze on the configured service URL."""
    httpserver.expect_request(
        "/api/plasma/analyze", method="POST"
    ).respond_with_json(_sample_response())

    asyncio.run(analyze_plasma(
        AnalyzePlasmaInput(mach=10.0, altitude_km=35.0)
    ))

    log = httpserver.log
    assert len(log) == 1
    request, _response = log[0]
    assert request.path == "/api/plasma/analyze"
    assert request.method == "POST"


def test_analyze_plasma_request_payload(service_env, httpserver):
    """Vehicle preset, UQ flag, and frequency round-trip into the request body."""
    httpserver.expect_request(
        "/api/plasma/analyze", method="POST"
    ).respond_with_json(_sample_response())

    asyncio.run(analyze_plasma(AnalyzePlasmaInput(
        mach=18.5,
        altitude_km=47.0,
        vehicle_name="ram_c",
        radar_frequency_hz=12e9,
        include_uq=False,
    )))

    body = json.loads(httpserver.log[0][0].get_data())
    assert body["vehicle"]["name"] == "ram_c"
    assert body["vehicle"]["nose_radius_m"] == pytest.approx(0.1524)
    assert body["flight"]["mach"] == pytest.approx(18.5)
    assert body["flight"]["altitude_km"] == pytest.approx(47.0)
    assert body["radar"]["frequency_hz"] == pytest.approx(12e9)
    assert body["uncertainty"]["enabled"] is False


def test_analyze_plasma_uq_optional(service_env, httpserver):
    """Response without uq block → uq_band is None on the output."""
    response = _sample_response()
    response["uq"] = None
    httpserver.expect_request(
        "/api/plasma/analyze", method="POST"
    ).respond_with_json(response)

    out = asyncio.run(analyze_plasma(
        AnalyzePlasmaInput(mach=22.5, altitude_km=61.0, include_uq=False)
    ))
    assert out.uq_band is None


# ── Error handling ────────────────────────────────────────────────────────────

def test_http_error_raises_runtime(service_env, httpserver):
    httpserver.expect_request(
        "/api/plasma/analyze", method="POST"
    ).respond_with_data("internal server error", status=500)

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(analyze_plasma(
            AnalyzePlasmaInput(mach=22.5, altitude_km=61.0)
        ))
    assert "500" in str(exc.value)


def test_timeout_raises_runtime(monkeypatch, httpserver):
    """A slow upstream surfaces as RuntimeError mentioning the timeout."""
    monkeypatch.setenv(
        "PLASMANET_SERVICE_URL", httpserver.url_for("").rstrip("/")
    )
    monkeypatch.setenv("PLASMANET_REQUEST_TIMEOUT_S", "0.5")

    def slow_handler(request):
        time.sleep(2.0)   # sleep longer than the configured timeout
        from werkzeug.wrappers import Response
        return Response(json.dumps(_sample_response()), mimetype="application/json")

    httpserver.expect_request(
        "/api/plasma/analyze", method="POST"
    ).respond_with_handler(slow_handler)

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(analyze_plasma(
            AnalyzePlasmaInput(mach=22.5, altitude_km=61.0)
        ))
    assert "timed out" in str(exc.value).lower() or "timeout" in str(exc.value).lower()


def test_malformed_response_raises_runtime(service_env, httpserver):
    """Missing required key in response → RuntimeError with diagnostic message."""
    httpserver.expect_request(
        "/api/plasma/analyze", method="POST"
    ).respond_with_json({"unexpected": "shape"})

    with pytest.raises(RuntimeError) as exc:
        asyncio.run(analyze_plasma(
            AnalyzePlasmaInput(mach=22.5, altitude_km=61.0)
        ))
    assert "malformed" in str(exc.value).lower()


# ── Vehicle preset dispatch ──────────────────────────────────────────────────

def test_vehicle_preset_dispatch(service_env, httpserver):
    """Each known preset selects its own geometry; unknown name falls back."""
    httpserver.expect_request(
        "/api/plasma/analyze", method="POST"
    ).respond_with_json(_sample_response())

    # Known preset
    asyncio.run(analyze_plasma(AnalyzePlasmaInput(
        mach=22.5, altitude_km=61.0, vehicle_name="ram_c",
    )))
    body = json.loads(httpserver.log[-1][0].get_data())
    assert body["vehicle"] == _VEHICLE_PRESETS["ram_c"]

    # Other known preset
    asyncio.run(analyze_plasma(AnalyzePlasmaInput(
        mach=10.0, altitude_km=35.0, vehicle_name="generic_spherecone",
    )))
    body = json.loads(httpserver.log[-1][0].get_data())
    assert body["vehicle"] == _VEHICLE_PRESETS["generic_spherecone"]

    # Unknown name → fall back to generic_spherecone (safe default)
    asyncio.run(analyze_plasma(AnalyzePlasmaInput(
        mach=15.0, altitude_km=40.0, vehicle_name="hgv_delta",
    )))
    body = json.loads(httpserver.log[-1][0].get_data())
    assert body["vehicle"] == _VEHICLE_PRESETS["generic_spherecone"]
