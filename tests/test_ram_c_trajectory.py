"""Contract tests for plasmanet/ram_c_trajectory.py.

Two roles:
  1. Python module shape — RAM_C_TRAJECTORY exposes the four canonical
     points with the expected fields, and the helpers behave as
     documented.
  2. Drift detection — the auto-generated frontend JSON
     (frontend/src/data/ram_c_trajectory.json) is byte-equal in content
     to the Python module. If a future contributor edits the Python
     source without re-running scripts/sync_trajectory_json.py, this
     test fails on the next CI run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from plasmanet.ram_c_trajectory import (
    CANONICAL_RAMC_POINTS,
    RAM_C_TRAJECTORY,
    find_canonical_match,
    trajectory_altitudes,
    trajectory_machs,
)

JSON_PATH = (
    Path(__file__).parent.parent / "frontend" / "src" / "data" / "ram_c_trajectory.json"
)


# ── Python module shape ──────────────────────────────────────────────────────

class TestPythonModule:
    def test_four_canonical_points(self):
        assert len(RAM_C_TRAJECTORY) == 4

    def test_each_point_has_required_fields(self):
        required = {"altitude_km", "mach", "ne_peak_m3_published", "source"}
        for pt in RAM_C_TRAJECTORY:
            assert set(pt.keys()) >= required, f"missing fields in {pt}"

    def test_canonical_points_dict_complete(self):
        for expected in [(23.9, 81.0), (23.6, 71.0), (22.5, 61.0), (18.5, 47.0)]:
            assert expected in CANONICAL_RAMC_POINTS

    def test_canonical_points_ne_values(self):
        assert CANONICAL_RAMC_POINTS[(23.9, 81.0)] == pytest.approx(2.0e18)
        assert CANONICAL_RAMC_POINTS[(23.6, 71.0)] == pytest.approx(1.0e19)
        assert CANONICAL_RAMC_POINTS[(22.5, 61.0)] == pytest.approx(2.0e19)
        assert CANONICAL_RAMC_POINTS[(18.5, 47.0)] == pytest.approx(2.0e19)

    def test_trajectory_altitudes_ascending(self):
        alts = trajectory_altitudes()
        assert alts == sorted(alts)
        assert alts == [47.0, 61.0, 71.0, 81.0]

    def test_trajectory_machs_ascending(self):
        machs = trajectory_machs()
        assert machs == sorted(machs)
        assert machs == [18.5, 22.5, 23.6, 23.9]


# ── find_canonical_match ─────────────────────────────────────────────────────

class TestFindCanonicalMatch:
    def test_exact_match(self):
        assert find_canonical_match(22.5, 61.0) == (22.5, 61.0)
        assert find_canonical_match(23.9, 81.0) == (23.9, 81.0)
        assert find_canonical_match(18.5, 47.0) == (18.5, 47.0)

    def test_within_mach_tolerance(self):
        assert find_canonical_match(22.55, 61.0) == (22.5, 61.0)
        assert find_canonical_match(22.45, 61.0) == (22.5, 61.0)

    def test_within_altitude_tolerance(self):
        assert find_canonical_match(22.5, 61.5) == (22.5, 61.0)
        assert find_canonical_match(22.5, 60.5) == (22.5, 61.0)

    def test_combined_tolerance(self):
        # Off in both dimensions but each within its window.
        assert find_canonical_match(22.55, 60.5) == (22.5, 61.0)

    def test_outside_tolerance_returns_none(self):
        assert find_canonical_match(10.0, 35.0) is None
        assert find_canonical_match(22.5, 50.0) is None
        assert find_canonical_match(15.0, 61.0) is None
        assert find_canonical_match(22.7, 61.0) is None
        assert find_canonical_match(22.5, 62.5) is None

    def test_pdf_report_reexports_for_back_compat(self):
        """pdf_report.py re-exports the trajectory helpers so existing
        callers that do `from plasmanet.pdf_report import ...` keep working."""
        from plasmanet.pdf_report import (
            CANONICAL_RAMC_POINTS as PR_POINTS,
            find_canonical_match as pr_find,
        )
        assert PR_POINTS is CANONICAL_RAMC_POINTS
        assert pr_find is find_canonical_match


# ── Drift detection: JSON ⇄ Python ───────────────────────────────────────────

class TestJsonSync:
    def test_json_file_exists(self):
        assert JSON_PATH.exists(), (
            f"{JSON_PATH} missing — run scripts/sync_trajectory_json.py"
        )

    def test_json_points_match_python(self):
        """If this fails: edit plasmanet/ram_c_trajectory.py, then run
        `python scripts/sync_trajectory_json.py` and commit both files."""
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

        # Compare as parallel lists; field-level equality so a diff is readable.
        assert "points" in data, "JSON missing 'points' array"
        json_pts = data["points"]
        py_pts = [dict(pt) for pt in RAM_C_TRAJECTORY]

        assert len(json_pts) == len(py_pts), (
            f"JSON has {len(json_pts)} points, Python has {len(py_pts)}"
        )
        for i, (j, p) in enumerate(zip(json_pts, py_pts)):
            assert j == p, (
                f"point {i} drift:\n  json:   {j}\n  python: {p}\n"
                f"Re-run scripts/sync_trajectory_json.py."
            )

    def test_json_warning_present(self):
        """The auto-generated JSON carries an explicit warning so editors
        don't hand-edit it."""
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        assert "_warning" in data
        assert "AUTO-GENERATED" in data["_warning"]
