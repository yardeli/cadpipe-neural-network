"""Contract tests for plasmanet.mock_server.

Validates:
  - Each route accepts the schema documented in SIMOPS_INTEGRATION.md
  - Response shapes match the documented Pydantic models
  - No drift between doc class names and plasmanet.mock_server.__all__

Run:
    pytest tests/test_mock_server_contract.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Ensure the repo root is on sys.path (matches existing test convention)
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from plasmanet.mock_server import create_app
from plasmanet.mock_server import __all__ as SERVER_ALL

DOCS_PATH = Path(__file__).parent.parent / "docs" / "SIMOPS_INTEGRATION.md"

app = create_app()
client = TestClient(app, raise_server_exceptions=True)


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _analyze_req(*, mach: float = 22.5, alt: float = 61.0, freq: float = 9.2e9,
                 angles: list[float] | None = None) -> dict:
    return {
        "vehicle": {"nose_radius_m": 0.1524, "half_angle_deg": 9.0,
                    "length_m": 1.295, "name": "ram_c"},
        "flight": {"mach": mach, "altitude_km": alt},
        "radar": {"frequency_hz": freq,
                  "aspect_angles_deg": angles or [0.0, 90.0, 180.0]},
        "uncertainty": {"enabled": True, "n_samples": 8},
    }


def _scan_req(*, mach: float = 22.5, alt: float = 61.0,
              angles: list[float] | None = None) -> dict:
    """Body for POST /api/plasma/analyze_scan (frontend convenience endpoint)."""
    return {
        "vehicle": {"nose_radius_m": 0.1524, "half_angle_deg": 9.0,
                    "length_m": 1.295, "name": "ram_c"},
        "flight": {"mach": mach, "altitude_km": alt},
        "aspect_angles_deg": angles or [0.0, 45.0, 90.0, 135.0, 180.0],
    }


def _submit_req() -> dict:
    return {
        "mesh_id": "550e8400-e29b-41d4-a716-446655440000",
        "flight": {"mach": 22.5, "altitude_km": 61.0},
        "plasma": {
            "gas_model": "air_5",
            "radar_frequency_hz": 9.2e9,
            "aspect_angles": [0.0, 90.0, 180.0],
            "include_uq": True,
        },
        "solver": "su2_nemo",
    }


# ── POST /api/plasma/analyze ──────────────────────────────────────────────────

class TestAnalyzeRoute:
    def test_valid_request_returns_200(self):
        resp = client.post("/api/plasma/analyze", json=_analyze_req())
        assert resp.status_code == 200

    def test_response_top_level_keys(self):
        body = client.post("/api/plasma/analyze", json=_analyze_req()).json()
        for key in ("stagnation", "aspect_scan", "overall_status",
                    "worst_case", "runtime_seconds", "plasmanet_version"):
            assert key in body, f"Missing top-level key: {key!r}"

    def test_stagnation_field_types(self):
        stag = client.post("/api/plasma/analyze", json=_analyze_req()).json()["stagnation"]
        assert isinstance(stag["T_tr_K"], (int, float))
        assert isinstance(stag["p_Pa"], (int, float))
        assert isinstance(stag["ne_m3"], (int, float))
        assert isinstance(stag["fp_GHz"], (int, float))

    def test_aspect_scan_entry_types(self):
        scan = client.post("/api/plasma/analyze", json=_analyze_req()).json()["aspect_scan"]
        assert isinstance(scan, list) and len(scan) > 0
        for pt in scan:
            assert isinstance(pt["angle_deg"], (int, float))
            assert isinstance(pt["attenuation_db"], (int, float))
            assert pt["status"] in ("DETECTABLE", "DEGRADED", "BLACKOUT")

    def test_aspect_scan_length_matches_requested_angles(self):
        angles = [0.0, 45.0, 90.0, 135.0, 180.0]
        body = client.post("/api/plasma/analyze",
                           json=_analyze_req(angles=angles)).json()
        assert len(body["aspect_scan"]) == len(angles)

    def test_worst_case_keys(self):
        wc = client.post("/api/plasma/analyze", json=_analyze_req()).json()["worst_case"]
        for key in ("angle_deg", "attenuation_db", "status"):
            assert key in wc

    def test_omitting_vehicle_returns_422(self):
        body = _analyze_req()
        del body["vehicle"]
        assert client.post("/api/plasma/analyze", json=body).status_code == 422

    def test_omitting_radar_returns_422(self):
        body = _analyze_req()
        del body["radar"]
        assert client.post("/api/plasma/analyze", json=body).status_code == 422

    def test_omitting_uncertainty_returns_422(self):
        body = _analyze_req()
        del body["uncertainty"]
        assert client.post("/api/plasma/analyze", json=body).status_code == 422

    def test_omitting_flight_returns_422(self):
        body = _analyze_req()
        del body["flight"]
        assert client.post("/api/plasma/analyze", json=body).status_code == 422


# ── POST /api/plasma/analyze_scan (frontend convenience endpoint) ───────────

class TestAnalyzeScanRoute:
    """Frontend-facing multi-band scan: shape must include meta.station_profile."""

    def test_returns_200(self):
        assert client.post("/api/plasma/analyze_scan",
                           json=_scan_req()).status_code == 200

    def test_top_level_keys(self):
        body = client.post("/api/plasma/analyze_scan", json=_scan_req()).json()
        for key in ("meta", "frequencies"):
            assert key in body, f"Missing top-level key: {key!r}"

    def test_meta_contains_station_profile(self):
        meta = client.post("/api/plasma/analyze_scan",
                           json=_scan_req()).json()["meta"]
        assert "station_profile" in meta, "meta missing station_profile"
        sp = meta["station_profile"]
        assert isinstance(sp, list) and len(sp) >= 5

    def test_station_entry_required_fields(self):
        sp = client.post("/api/plasma/analyze_scan",
                         json=_scan_req()).json()["meta"]["station_profile"]
        for station in sp:
            for field in ("zL", "z_m", "r_wall_m",
                          "max_ne_m3", "p99_ne_m3", "max_T_tr_K"):
                assert field in station, f"station missing field {field!r}: {station}"

    def test_station_zl_monotonic_increasing(self):
        sp = client.post("/api/plasma/analyze_scan",
                         json=_scan_req()).json()["meta"]["station_profile"]
        zls = [s["zL"] for s in sp]
        assert zls == sorted(zls), f"zL not monotonic increasing: {zls}"

    def test_frequencies_each_have_aspect_scan(self):
        body = client.post("/api/plasma/analyze_scan", json=_scan_req()).json()
        for band in body["frequencies"]:
            for field in ("label", "frequency_mhz", "color", "aspect_scan"):
                assert field in band, f"band missing {field!r}"
            assert isinstance(band["aspect_scan"], list)

    def test_synthetic_profile_for_non_nemo_condition(self):
        """Non-(M22.5, 61km) condition gets a synthetic profile, not the JSON one."""
        body = client.post(
            "/api/plasma/analyze_scan",
            json=_scan_req(mach=10.0, alt=35.0),
        ).json()
        sp = body["meta"]["station_profile"]
        # All required fields present; ne values should be > 0 (synthetic decay).
        assert all(s["max_ne_m3"] > 0 for s in sp)
        # zL values match the canonical RAM-C station grid.
        assert [s["zL"] for s in sp] == [0.14, 0.32, 0.48, 0.67, 0.88]


# ── POST /api/plasma/submit_cfd ───────────────────────────────────────────────

class TestSubmitCFDRoute:
    def test_valid_request_returns_202(self):
        resp = client.post("/api/plasma/submit_cfd", json=_submit_req())
        assert resp.status_code == 202

    def test_response_keys(self):
        body = client.post("/api/plasma/submit_cfd", json=_submit_req()).json()
        for key in ("simulation_id", "batch_job_id", "status",
                    "estimated_runtime_minutes"):
            assert key in body, f"Missing key: {key!r}"

    def test_status_is_queued(self):
        body = client.post("/api/plasma/submit_cfd", json=_submit_req()).json()
        assert body["status"] == "queued"

    def test_simulation_id_is_string(self):
        body = client.post("/api/plasma/submit_cfd", json=_submit_req()).json()
        assert isinstance(body["simulation_id"], str)
        assert len(body["simulation_id"]) > 0

    def test_runtime_estimate_is_int(self):
        body = client.post("/api/plasma/submit_cfd", json=_submit_req()).json()
        assert isinstance(body["estimated_runtime_minutes"], int)

    def test_omitting_plasma_returns_422(self):
        body = _submit_req()
        del body["plasma"]
        assert client.post("/api/plasma/submit_cfd", json=body).status_code == 422

    def test_plasma_gas_model_accepted(self):
        for gas in ("air_5", "air_11"):
            body = _submit_req()
            body["plasma"]["gas_model"] = gas
            assert client.post("/api/plasma/submit_cfd", json=body).status_code == 202

    def test_different_mesh_ids_get_different_simulation_ids(self):
        body_a = _submit_req()
        body_b = _submit_req()
        body_b["mesh_id"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        id_a = client.post("/api/plasma/submit_cfd", json=body_a).json()["simulation_id"]
        id_b = client.post("/api/plasma/submit_cfd", json=body_b).json()["simulation_id"]
        assert id_a != id_b


# ── GET /api/plasma/benchmark/ram_c ──────────────────────────────────────────

class TestBenchmarkRoute:
    def test_returns_200(self):
        assert client.get("/api/plasma/benchmark/ram_c").status_code == 200

    def test_top_level_keys(self):
        body = client.get("/api/plasma/benchmark/ram_c").json()
        for key in ("generated_at", "cases", "summary"):
            assert key in body, f"Missing key: {key!r}"

    def test_cases_is_nonempty_list(self):
        cases = client.get("/api/plasma/benchmark/ram_c").json()["cases"]
        assert isinstance(cases, list) and len(cases) > 0

    def test_case_required_fields(self):
        cases = client.get("/api/plasma/benchmark/ram_c").json()["cases"]
        for case in cases:
            for field in ("altitude_km", "mach", "frequency_ghz",
                          "ne_predicted_m3", "ne_reference_m3",
                          "log10_error", "within_uncertainty"):
                assert field in case, f"Case missing field {field!r}: {case}"

    def test_case_field_types(self):
        case = client.get("/api/plasma/benchmark/ram_c").json()["cases"][0]
        assert isinstance(case["altitude_km"], (int, float))
        assert isinstance(case["ne_predicted_m3"], (int, float))
        assert isinstance(case["log10_error"], (int, float))
        assert isinstance(case["within_uncertainty"], bool)

    def test_summary_counts_consistent(self):
        body = client.get("/api/plasma/benchmark/ram_c").json()
        s = body["summary"]
        assert s["pass_count"] + s["fail_count"] == s["total_cases"]
        assert s["total_cases"] == len(body["cases"])

    def test_four_altitudes_present(self):
        cases = client.get("/api/plasma/benchmark/ram_c").json()["cases"]
        alts = {c["altitude_km"] for c in cases}
        for expected in (81.0, 71.0, 61.0, 47.0):
            assert expected in alts, f"Missing altitude {expected} km in benchmark"


# ── GET /health ───────────────────────────────────────────────────────────────

def test_health_ok():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "validation_json_exists" in body


# ── Doc drift detection ───────────────────────────────────────────────────────

def test_doc_class_names_in_module_all():
    """Regex-extract Pydantic class definitions from SIMOPS_INTEGRATION.md and
    verify every extracted name appears in plasmanet.mock_server.__all__.

    This test catches future drift between the design doc and the implementation
    without requiring a manually maintained duplicate spec file.
    """
    assert DOCS_PATH.exists(), f"Design doc not found: {DOCS_PATH}"
    text = DOCS_PATH.read_text(encoding="utf-8")

    # Extract class names only from inside markdown code fences (```python ... ```)
    code_blocks = re.findall(r"```python(.*?)```", text, re.DOTALL)
    doc_classes: set[str] = set()
    for block in code_blocks:
        doc_classes.update(re.findall(r"class\s+(\w+)\s*\(BaseModel\)", block))

    assert doc_classes, "No Pydantic class definitions found in doc — regex may be broken"

    missing = doc_classes - set(SERVER_ALL)
    assert not missing, (
        f"Class(es) defined in SIMOPS_INTEGRATION.md §4 but absent from "
        f"plasmanet.mock_server.__all__:\n  {sorted(missing)}\n"
        f"Either add the class (or an alias) to the server, or update __all__."
    )
