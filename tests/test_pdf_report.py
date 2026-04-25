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


# ── Canonical RAM-C trajectory point matching ────────────────────────────────

class TestCanonicalMatching:
    """find_canonical_match() — the tolerance check that decides whether the
    PDF Validation section auto-populates."""

    def test_exact_match_returns_point(self):
        from plasmanet.pdf_report import find_canonical_match
        assert find_canonical_match(22.5, 61.0) == (22.5, 61.0)
        assert find_canonical_match(23.9, 81.0) == (23.9, 81.0)

    def test_within_mach_tolerance(self):
        from plasmanet.pdf_report import find_canonical_match
        assert find_canonical_match(22.55, 61.0) == (22.5, 61.0)
        assert find_canonical_match(22.45, 61.0) == (22.5, 61.0)

    def test_within_altitude_tolerance(self):
        from plasmanet.pdf_report import find_canonical_match
        assert find_canonical_match(22.5, 61.5) == (22.5, 61.0)
        assert find_canonical_match(22.5, 60.5) == (22.5, 61.0)

    def test_outside_tolerance_returns_none(self):
        from plasmanet.pdf_report import find_canonical_match
        # Wrong Mach
        assert find_canonical_match(10.0, 61.0) is None
        # Wrong altitude
        assert find_canonical_match(22.5, 35.0) is None
        # Just outside Mach window
        assert find_canonical_match(22.7, 61.0) is None
        # Just outside altitude window
        assert find_canonical_match(22.5, 62.5) is None

    def test_canonical_points_dict_complete(self):
        from plasmanet.pdf_report import CANONICAL_RAMC_POINTS
        # Four trajectory points from Jones & Cross 1972
        assert (23.9, 81.0) in CANONICAL_RAMC_POINTS
        assert (23.6, 71.0) in CANONICAL_RAMC_POINTS
        assert (22.5, 61.0) in CANONICAL_RAMC_POINTS
        assert (18.5, 47.0) in CANONICAL_RAMC_POINTS
        assert len(CANONICAL_RAMC_POINTS) == 4


# ── Validation section auto-population ────────────────────────────────────────

class TestValidationSectionAutofill:
    """The /report route auto-fills the Validation section at canonical points."""

    def _post_at(self, mach: float, alt: float) -> bytes:
        body = {
            "vehicle": {"nose_radius_m": 0.1524, "half_angle_deg": 9.0,
                        "length_m": 1.295, "name": "ram_c"},
            "flight": {"mach": mach, "altitude_km": alt},
            "radar": {"frequency_hz": 9.2e9,
                      "aspect_angles_deg": [0.0, 90.0, 180.0]},
            "uncertainty": {"enabled": True, "n_samples": 8},
        }
        resp = client.post("/api/plasma/report", json=body)
        assert resp.status_code == 200
        return resp.content

    def test_canonical_point_pdf_well_formed(self):
        """At every canonical point the route still produces a valid PDF."""
        for mach, alt in [(23.9, 81.0), (23.6, 71.0), (22.5, 61.0), (18.5, 47.0)]:
            content = self._post_at(mach, alt)
            assert content[:5] == b"%PDF-", f"bad PDF magic at M{mach}/{alt}km"
            assert content.rstrip(b"\r\n").endswith(b"%%EOF"), (
                f"missing %%EOF at M{mach}/{alt}km"
            )

    def test_resolve_benchmark_error_canonical_returns_tuple(self):
        """At every canonical trajectory point the dispatcher returns
        (log10_error, (matched_mach, matched_alt)) — both fields populated."""
        from plasmanet.mock_server import _resolve_benchmark_error
        for mach, alt in [(23.9, 81.0), (23.6, 71.0), (22.5, 61.0), (18.5, 47.0)]:
            result = _resolve_benchmark_error(mach, alt)
            assert result is not None, f"None at canonical M{mach}/{alt}km"
            log10_err, point = result
            assert isinstance(log10_err, (int, float))
            assert point == (mach, alt), (
                f"matched point should equal the exact canonical key, "
                f"got {point} for input M{mach}/{alt}km"
            )

    def test_resolve_benchmark_error_off_grid_returns_none(self):
        """Outside the ±0.1 Mach / ±1 km window the dispatcher returns None
        so build_pdf hides the Validation section."""
        from plasmanet.mock_server import _resolve_benchmark_error
        assert _resolve_benchmark_error(10.0, 35.0) is None
        assert _resolve_benchmark_error(22.5, 50.0) is None      # wrong altitude
        assert _resolve_benchmark_error(15.0, 61.0) is None      # wrong Mach
        assert _resolve_benchmark_error(22.7, 61.0) is None      # just-outside Mach
        assert _resolve_benchmark_error(22.5, 62.5) is None      # just-outside alt

    def test_build_pdf_renders_attribution_when_canonical_point_provided(self):
        """build_pdf must render the explicit attribution block ("Model
        accuracy at nearest canonical RAM-C point — M22.5 @ 61 km | Reference:
        Jones & Cross 1972 / Grantham 1970 | log10 error = …") when both
        benchmark_log10_error and benchmark_canonical_point are supplied.

        Uses pypdf to extract the page text rather than scanning raw bytes —
        reportlab's content streams use compound filters (ASCII85+Flate) that
        a naive scan can't decode.
        """
        import io
        import pypdf
        from plasmanet.pdf_report import build_pdf

        pdf_bytes = build_pdf(
            meta={
                "mach": 22.5, "altitude_km": 61.0,
                "vehicle": "ram_c", "engine": "plasmanet_nn_mock",
                "plasmanet_version": "test",
                "stagnation": {
                    "T_tr_K": 6064.0, "T_ve_K": 5911.0,
                    "p_Pa": 231437.0, "ne_m3": 5.64e20, "fp_GHz": 213.0,
                },
                "uq": None,
            },
            frequencies=[{
                "label": "VHF 225 MHz", "frequency_mhz": 225, "color": "#f59e0b",
                "aspect_scan": [
                    {"angle_deg": 0.0,   "attenuation_db": 100.0, "status": "BLACKOUT"},
                    {"angle_deg": 90.0,  "attenuation_db": 200.0, "status": "BLACKOUT"},
                    {"angle_deg": 180.0, "attenuation_db": 150.0, "status": "BLACKOUT"},
                ],
            }],
            station_profile=None,
            benchmark_log10_error=1.08,
            benchmark_canonical_point=(22.5, 61.0),
        )

        text = pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()
        for needle in [
            "Model accuracy at nearest canonical RAM-C point",
            "M22.5 @ 61 km",
            "Jones & Cross 1972",
            "log10 error",
        ]:
            assert needle in text, (
                f"missing attribution text {needle!r} in rendered PDF\n"
                f"extracted text:\n{text}"
            )

    def test_build_pdf_omits_attribution_when_canonical_point_missing(self):
        """When build_pdf is called without benchmark_canonical_point, no
        attribution block renders (off-grid request path)."""
        import io
        import pypdf
        from plasmanet.pdf_report import build_pdf

        pdf_bytes = build_pdf(
            meta={
                "mach": 10.0, "altitude_km": 35.0,
                "vehicle": "generic", "engine": "plasmanet_nn_mock",
                "plasmanet_version": "test",
                "stagnation": {
                    "T_tr_K": 5000.0, "T_ve_K": None,
                    "p_Pa": 50000.0, "ne_m3": 1.0e18, "fp_GHz": 9.0,
                },
                "uq": None,
            },
            frequencies=[{
                "label": "X-band 9.2 GHz", "frequency_mhz": 9200, "color": "#3b82f6",
                "aspect_scan": [
                    {"angle_deg": 0.0,   "attenuation_db": 5.0,  "status": "DEGRADED"},
                    {"angle_deg": 180.0, "attenuation_db": 3.0,  "status": "DEGRADED"},
                ],
            }],
            station_profile=None,
            benchmark_log10_error=None,
            benchmark_canonical_point=None,
        )

        text = pypdf.PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()
        assert "Model accuracy at nearest canonical" not in text
        assert "log10 error" not in text

    def test_resolve_benchmark_error_within_tolerance_returns_canonical_point(self):
        """Inputs slightly off the canonical point resolve to that point and
        the returned matched-point tuple is the *canonical* (mach, alt), not
        the request's. This is what build_pdf's attribution depends on."""
        from plasmanet.mock_server import _resolve_benchmark_error

        # ±0.1 Mach window — request is M22.55, canonical is M22.5
        result = _resolve_benchmark_error(22.55, 61.0)
        assert result is not None
        _err, point = result
        assert point == (22.5, 61.0)

        # ±1 km window — request is 60.5 km, canonical is 61 km
        result = _resolve_benchmark_error(22.5, 60.5)
        assert result is not None
        _err, point = result
        assert point == (22.5, 61.0)
