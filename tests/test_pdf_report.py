"""Contract tests for POST /api/plasma/report.

Verifies the route produces a real PDF (magic bytes + Content-Type) and
that the content shape stays consistent with the rest of the API.

Heavy assertions on the rendered chart pixels are out of scope — matplotlib
output is not deterministic across versions.  We confirm the bytes are a
valid PDF document and reach a plausible size.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from plasmanet.mock_server import create_app

app = create_app()
client = TestClient(app, raise_server_exceptions=True)


def _report_req() -> dict:
    return {
        "vehicle": {"nose_radius_m": 0.1524, "half_angle_deg": 9.0,
                    "length_m": 1.295, "name": "ram_c"},
        "flight": {"mach": 22.5, "altitude_km": 61.0},
        "radar": {"frequency_hz": 9.2e9,
                  "aspect_angles_deg": [0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0]},
        "uncertainty": {"enabled": True, "n_samples": 8},
    }


class TestReportRoute:
    def test_returns_200(self):
        assert client.post("/api/plasma/report",
                           json=_report_req()).status_code == 200

    def test_content_type_is_pdf(self):
        resp = client.post("/api/plasma/report", json=_report_req())
        assert resp.headers["content-type"].startswith("application/pdf")

    def test_body_starts_with_pdf_magic(self):
        resp = client.post("/api/plasma/report", json=_report_req())
        assert resp.content[:5] == b"%PDF-", (
            f"expected %PDF- magic bytes, got: {resp.content[:8]!r}"
        )

    def test_body_ends_with_eof_marker(self):
        # PDFs end with "%%EOF" optionally followed by a newline.
        resp = client.post("/api/plasma/report", json=_report_req())
        tail = resp.content.rstrip(b"\r\n").decode("latin-1", errors="replace")
        assert tail.endswith("%%EOF"), (
            f"expected %%EOF marker at end of PDF, got: {tail[-32:]!r}"
        )

    def test_pdf_is_plausibly_sized(self):
        """Sanity check: a one-pager with two embedded charts should be
        well over 5 KB. Catches regressions where chart embedding silently
        fails and produces a tiny text-only PDF."""
        resp = client.post("/api/plasma/report", json=_report_req())
        size = len(resp.content)
        assert size > 5_000, f"PDF suspiciously small: {size} bytes"
        # Upper bound is loose — matplotlib PNGs at 120 DPI come in around
        # 50–150 KB combined; total PDF ≈ 200 KB is normal.
        assert size < 2_000_000, f"PDF suspiciously large: {size} bytes"

    def test_content_disposition_includes_filename(self):
        resp = client.post("/api/plasma/report", json=_report_req())
        cd = resp.headers.get("content-disposition", "")
        assert "filename=" in cd, f"missing filename in Content-Disposition: {cd!r}"
        assert "M22.5" in cd, f"expected Mach in filename: {cd!r}"
        assert "61km" in cd, f"expected altitude in filename: {cd!r}"

    def test_omitting_required_field_returns_422(self):
        body = _report_req()
        del body["radar"]
        assert client.post("/api/plasma/report", json=body).status_code == 422
