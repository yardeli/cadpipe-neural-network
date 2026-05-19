"""SimOps router integration test.

Spins up a FastAPI app with `create_router()` and exercises every
v0.3.x endpoint via TestClient. Confirms the schemas, code paths,
and wiring against the actual physics stack are all sound. Cantera
is optional — endpoints that need it fall back gracefully.

Run:
    PYTHONPATH=. python scripts/test_api_router_integration.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _ok(msg):   print(f"\033[32m  PASS\033[0m {msg}")
def _fail(msg): print(f"\033[31m  FAIL\033[0m {msg}")


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from khorium_hypersonic.api.router import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def test_presets():
    print("\n=== GET /api/hypersonic/presets ===")
    r = _client().get("/api/hypersonic/presets")
    if r.status_code != 200:
        _fail(f"status {r.status_code}: {r.text[:200]}"); return False
    presets = r.json()["geometry_presets"]
    names = {p["name"] for p in presets}
    if "ram_c" not in names or "capsule" not in names:
        _fail(f"expected ram_c + capsule in presets, got {names}"); return False
    _ok(f"{len(presets)} presets returned, includes ram_c + capsule")
    return True


def test_analyze_axial():
    print("\n=== POST /api/hypersonic/analyze/axial ===")
    r = _client().post("/api/hypersonic/analyze/axial", json={
        "geometry": {"preset_name": "ram_c"},
        "flight": {"mach": 22.5, "altitude_km": 61.0},
        "n_stations": 20, "chemistry_mode": "equilibrium",
    })
    if r.status_code != 200:
        _fail(f"status {r.status_code}: {r.text[:300]}"); return False
    body = r.json()
    n = len(body["stations"])
    if n != 20:
        _fail(f"expected 20 stations, got {n}"); return False
    if body["peak_ne_m3"] <= 0:
        _fail(f"peak ne not positive: {body['peak_ne_m3']}"); return False
    kinds = {s["shock_kind"] for s in body["stations"]}
    if kinds != {"normal", "oblique"} and kinds != {"normal"} and kinds != {"oblique"}:
        _fail(f"unexpected shock_kind set {kinds}"); return False
    _ok(f"ram_c 20-station profile, peak ne = {body['peak_ne_m3']:.2e}, shock kinds = {kinds}")
    return True


def test_analyze_strips_axisymmetric():
    print("\n=== POST /api/hypersonic/analyze/strips (axisymmetric) ===")
    r = _client().post("/api/hypersonic/analyze/strips", json={
        "geometry": {"preset_name": "blunt_cone"},
        "flight": {"mach": 15.0, "altitude_km": 35.0},
        "n_strips": 8, "n_axial_per_strip": 15, "chemistry_mode": "equilibrium",
    })
    if r.status_code != 200:
        _fail(f"status {r.status_code}: {r.text[:300]}"); return False
    body = r.json()
    if body["n_strips"] != 8:
        _fail(f"expected 8 strips, got {body['n_strips']}"); return False
    # Axisymmetric → every strip's peak_ne matches → ratio 1.0
    nes = [s["peak_ne_m3"] for s in body["strips"]]
    if max(nes) / max(min(nes), 1e-30) > 1.001:
        _fail(f"axisymmetric strips diverged: {nes}"); return False
    _ok(f"8 axisymmetric strips agree to 0.1%; windward/leeward ratio = "
        f"{body['windward_to_leeward_ratio']}")
    return True


def test_heat_transfer_swept():
    print("\n=== POST /api/hypersonic/heat_transfer (unswept vs 70deg) ===")
    import math
    c = _client()
    payload = {
        "geometry": {"preset_name": "sharp_narrow"},
        "flight": {"mach": 12.0, "altitude_km": 35.0},
        "wall_T_K": 1500.0,
    }
    r0 = c.post("/api/hypersonic/heat_transfer", json={**payload, "sweep_angle_deg": 0.0})
    r1 = c.post("/api/hypersonic/heat_transfer", json={**payload, "sweep_angle_deg": 70.0})
    if r0.status_code != 200 or r1.status_code != 200:
        _fail(f"status {r0.status_code} / {r1.status_code}"); return False
    q0 = r0.json()["q_w_W_per_m2"]; q70 = r1.json()["q_w_W_per_m2"]
    ratio = q70 / max(q0, 1e-30)
    cos2 = math.cos(math.radians(70.0)) ** 2
    print(f"  q_w 0deg  = {q0:.3e}")
    print(f"  q_w 70deg = {q70:.3e}")
    print(f"  ratio     = {ratio:.4f}  (cos^2(70) = {cos2:.4f})")
    if abs(ratio - cos2) / cos2 > 1e-6:
        _fail(f"cos^2 ratio off"); return False
    _ok("swept-LE correction wired through router correctly")
    return True


def test_shock_chain_scramjet():
    print("\n=== POST /api/hypersonic/shock_chain (scramjet inlet) ===")
    r = _client().post("/api/hypersonic/shock_chain", json={
        "flight": {"mach": 8.0, "altitude_km": 25.0},
        "stages": [
            {"kind": "oblique", "deflection_deg": 6.0},
            {"kind": "oblique", "deflection_deg": 12.0},
            {"kind": "oblique", "deflection_deg": 6.0},
            {"kind": "internal_duct", "length_m": 0.5},
        ],
    })
    if r.status_code != 200:
        _fail(f"status {r.status_code}: {r.text[:300]}"); return False
    body = r.json()
    machs = [s["mach"] for s in body["stages"]]
    if not all(machs[i] >= machs[i+1] for i in range(2)):
        _fail(f"Mach not monotonically decreasing through external compression: {machs}")
        return False
    isolator = body["stages"][-1]
    if not isolator["duct_residence_s"] or isolator["duct_residence_s"] <= 0:
        _fail(f"isolator duct_residence_s missing/zero: {isolator}")
        return False
    _ok(f"4-stage scramjet inlet: M = {[f'{m:.2f}' for m in machs]}, "
        f"isolator tau = {isolator['duct_residence_s']*1e6:.1f} us")
    return True


def test_invalid_geometry_returns_422():
    print("\n=== validation — bad geometry returns 422 ===")
    r = _client().post("/api/hypersonic/analyze/axial", json={
        "geometry": {"preset_name": "no_such_preset"},
        "flight": {"mach": 10.0, "altitude_km": 30.0},
        "n_stations": 10,
    })
    if r.status_code != 422:
        _fail(f"expected 422, got {r.status_code}: {r.text[:200]}"); return False
    _ok("unknown preset rejected with 422")
    return True


def main() -> int:
    tests = [
        test_presets,
        test_analyze_axial,
        test_analyze_strips_axisymmetric,
        test_heat_transfer_swept,
        test_shock_chain_scramjet,
        test_invalid_geometry_returns_422,
    ]
    results = [t() for t in tests]
    n = sum(1 for r in results if r)
    print()
    print("=" * 60)
    print(f"  {n}/{len(results)} router integration tests passed")
    print("=" * 60)
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
