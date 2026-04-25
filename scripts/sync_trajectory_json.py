#!/usr/bin/env python3
"""Regenerate frontend/src/data/ram_c_trajectory.json from the Python source.

The frontend's FlightSelectors imports the JSON directly. A pytest contract
test (tests/test_ram_c_trajectory.py::test_json_matches_python_module)
asserts the two stay in sync — if you change RAM_C_TRAJECTORY in
plasmanet/ram_c_trajectory.py, run this script and commit the regenerated
JSON together with the Python edit.

Usage:
    python scripts/sync_trajectory_json.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from the repo root or any subdirectory.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from plasmanet.ram_c_trajectory import RAM_C_TRAJECTORY

OUT_PATH = (
    REPO_ROOT / "frontend" / "src" / "data" / "ram_c_trajectory.json"
)


def main() -> None:
    payload = {
        "_warning": (
            "AUTO-GENERATED. Do not edit by hand. "
            "Edit plasmanet/ram_c_trajectory.py and re-run "
            "scripts/sync_trajectory_json.py."
        ),
        "points": [dict(pt) for pt in RAM_C_TRAJECTORY],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['points'])} trajectory points to {OUT_PATH}")


if __name__ == "__main__":
    main()
