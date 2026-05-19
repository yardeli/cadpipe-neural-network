"""Validation tests for `khorium_hypersonic.geometry.raycast_mesh`.

Four checks, all using synthetic triangles (no meshio needed):

1. Convex sphere — outer-radius lookup at multiple x should agree
   with the analytical sphere radius within tessellation error.

2. Sphere-cone — RaycastMesh body radius and surface angle should
   track the parametric `SphereCone` baseline along the body.

3. Hollow duct — concentric tubes return 4 ray hits per (x, phi) and
   the inner/outer pair brackets the duct gap. Use case: scramjet
   isolator chemistry needs the inner-surface contour.

4. Probe-on-cone — a small probe offset in +y from a cone shows up
   at phi ≈ 0 (windward) but is invisible at phi ≈ π. The old axial-
   slice MeshGeometry would clobber both into the cone radius.

Run:
    PYTHONPATH=. python scripts/test_raycast_mesh.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np

from khorium_hypersonic import RaycastMesh, SphereCone


def _ok(msg):   print(f"\033[32m  PASS\033[0m {msg}")
def _fail(msg): print(f"\033[31m  FAIL\033[0m {msg}")


# ── Synthetic-mesh factories ────────────────────────────────────────

def make_sphere_tris(R: float, x_center: float, n_lat: int = 24, n_lon: int = 48) -> np.ndarray:
    """UV-sphere triangulation centered at (x_center, 0, 0)."""
    tris = []
    for i in range(n_lat):
        phi1 = math.pi * i / n_lat
        phi2 = math.pi * (i + 1) / n_lat
        for j in range(n_lon):
            t1 = 2 * math.pi * j / n_lon
            t2 = 2 * math.pi * (j + 1) / n_lon
            def P(phi, theta):
                return (x_center + R * math.cos(phi),
                        R * math.sin(phi) * math.cos(theta),
                        R * math.sin(phi) * math.sin(theta))
            a, b, c, d = P(phi1, t1), P(phi1, t2), P(phi2, t2), P(phi2, t1)
            tris.append([a, b, c])
            tris.append([a, c, d])
    return np.array(tris, dtype=np.float64)


def make_cylinder_tris(R: float, x_start: float, x_end: float, n_seg: int = 48) -> np.ndarray:
    """Open cylinder surface (no caps) along +x. Inward-facing duct walls
    are represented by passing R negative? No — both orientations work
    for ray-segment hits; we just need the geometry, not orientation."""
    tris = []
    for j in range(n_seg):
        t1 = 2 * math.pi * j / n_seg
        t2 = 2 * math.pi * (j + 1) / n_seg
        y1, z1 = R * math.cos(t1), R * math.sin(t1)
        y2, z2 = R * math.cos(t2), R * math.sin(t2)
        a = (x_start, y1, z1); b = (x_start, y2, z2)
        c = (x_end, y2, z2);   d = (x_end, y1, z1)
        tris.append([a, b, c])
        tris.append([a, c, d])
    return np.array(tris, dtype=np.float64)


# ── Tests ───────────────────────────────────────────────────────────

def test_convex_sphere() -> bool:
    print("\n=== Test 1: convex sphere — outer radius vs analytical ===")
    R = 0.5
    tris = make_sphere_tris(R, x_center=R)              # nose at x=0, aft at x=2R
    mesh = RaycastMesh(name="sphere", triangles=tris)
    xs = [0.10 * R, 0.50 * R, 0.90 * R, 1.50 * R]
    for x in xs:
        r_predicted = mesh.body_radius_at_axial_station(x)
        # Analytical: sphere of radius R centered at x=R → r(x) = sqrt(R² - (R-x)²)
        r_truth = math.sqrt(max(R * R - (R - x) ** 2, 0.0))
        rel = abs(r_predicted - r_truth) / max(r_truth, 1e-6)
        print(f"  x={x*1000:>6.1f}mm  truth r={r_truth*1000:>5.1f}mm  "
              f"predicted r={r_predicted*1000:>5.1f}mm  rel_err={rel:.1%}")
        if rel > 0.05:        # 5% tessellation tolerance at 24×48
            _fail(f"sphere radius off by {rel:.1%} at x={x:.3f}")
            return False
    _ok("sphere outer-radius envelope matches analytical within 5% (tessellation)")
    return True


def test_sphere_cone_matches_parametric() -> bool:
    print("\n=== Test 2: sphere-cone triangulated vs SphereCone analytical ===")
    R_n = 0.08; half_angle = 15.0; L = 0.50
    # Build sphere-cone surface: spherical cap from x=0 to x=R_n*(1-sin(α)),
    # then conical frustum out to x=L.
    alpha = math.radians(half_angle)
    x_tang = R_n * (1.0 - math.sin(alpha))
    r_tang = R_n * math.cos(alpha)
    r_base = r_tang + (L - x_tang) * math.tan(alpha)

    # Spherical-cap tris: subset of full sphere with x <= x_tang.
    full_sphere = make_sphere_tris(R_n, x_center=R_n)
    keep = (full_sphere[:, :, 0].max(axis=1) <= x_tang + 1e-9)
    cap_tris = full_sphere[keep]
    # Conical frustum tris
    n_seg = 48
    cone_tris = []
    for j in range(n_seg):
        t1 = 2 * math.pi * j / n_seg
        t2 = 2 * math.pi * (j + 1) / n_seg
        for (x_a, r_a), (x_b, r_b) in [((x_tang, r_tang), (L, r_base))]:
            a = (x_a, r_a * math.cos(t1), r_a * math.sin(t1))
            b = (x_a, r_a * math.cos(t2), r_a * math.sin(t2))
            c = (x_b, r_b * math.cos(t2), r_b * math.sin(t2))
            d = (x_b, r_b * math.cos(t1), r_b * math.sin(t1))
            cone_tris.append([a, b, c]); cone_tris.append([a, c, d])
    cone_tris = np.array(cone_tris, dtype=np.float64)
    tris = np.concatenate([cap_tris, cone_tris], axis=0)

    mesh = RaycastMesh(name="sphere_cone_mesh", triangles=tris)
    parametric = SphereCone("sc_baseline", nose_radius_m=R_n,
                             half_angle_deg=half_angle, length_m=L)

    xs = [0.005, 0.05, 0.10, 0.25, 0.40]
    for x in xs:
        r_mesh = mesh.body_radius_at_axial_station(x)
        r_truth = parametric.body_radius_at_axial_station(x)
        rel = abs(r_mesh - r_truth) / max(r_truth, 1e-6)
        print(f"  x={x*1000:>6.1f}mm  parametric r={r_truth*1000:>6.1f}mm  "
              f"raycast r={r_mesh*1000:>6.1f}mm  rel_err={rel:.1%}")
        if rel > 0.06:
            _fail(f"sphere-cone radius off by {rel:.1%} at x={x:.3f}")
            return False
    _ok("sphere-cone raycast envelope matches SphereCone parametric within 6%")
    return True


def test_hollow_duct() -> bool:
    print("\n=== Test 3: hollow duct — inner + outer surfaces both visible ===")
    R_out = 0.40; R_in = 0.20
    outer = make_cylinder_tris(R_out, x_start=0.0, x_end=1.0)
    inner = make_cylinder_tris(R_in,  x_start=0.0, x_end=1.0)
    tris = np.concatenate([outer, inner], axis=0)
    mesh = RaycastMesh(name="hollow_duct", triangles=tris)

    hits = mesh.intersections(x_m=0.5, phi_rad=0.0)
    print(f"  hits at (x=0.5, phi=0): {[f'{h:.3f}' for h in hits]}")
    if len(hits) != 4:
        _fail(f"expected 4 hits (outer-in/out + inner-in/out), got {len(hits)}: {hits}")
        return False
    r_inner_min, r_inner_max = hits[0], hits[1]
    r_outer_min, r_outer_max = hits[2], hits[3]
    if not (abs(r_inner_min - R_in) < 0.01 and abs(r_outer_min - R_out) < 0.01):
        _fail(f"inner/outer radii wrong: inner≈{r_inner_min}, outer≈{r_outer_min}")
        return False
    if not (abs(r_inner_max - R_in) < 0.01 and abs(r_outer_max - R_out) < 0.01):
        _fail("ray exiting the body should hit the same surface again at the symmetric radius")
        return False
    _ok(f"duct produces inner=({r_inner_min:.2f}, {r_inner_max:.2f}) "
        f"and outer=({r_outer_min:.2f}, {r_outer_max:.2f}) — both surfaces resolved")
    return True


def test_probe_on_cone() -> bool:
    print("\n=== Test 4: probe-on-cone — small probe visible only in +y ===")
    # Main cone: small SphereCone-style frustum, R_base=0.10, L=0.50
    cone = make_cylinder_tris(R=0.10, x_start=0.05, x_end=0.50)
    # Probe: 5mm-radius tube offset to (+y) by 30mm, in front of and over
    # the cone, from x=-0.10 to x=0.10.
    probe_local = make_cylinder_tris(R=0.005, x_start=-0.10, x_end=0.10, n_seg=24)
    probe_local[:, :, 1] += 0.030                       # shift in +y
    tris = np.concatenate([cone, probe_local], axis=0)
    mesh = RaycastMesh(name="probe_on_cone", triangles=tris)

    # In windward (+y) direction at x=0.05 (overlap region): probe is in
    # the way at ~25–35mm, cone surface at 100mm. Raycast should see
    # both.
    hits_wind = mesh.intersections(x_m=0.05, phi_rad=0.0)
    print(f"  hits at (x=50mm, phi=  0deg): {[f'{h*1000:.0f}mm' for h in hits_wind]}")
    # In leeward (-y) at the same x: no probe in the ray path; just the
    # cone wall.
    hits_lee = mesh.intersections(x_m=0.05, phi_rad=math.pi)
    print(f"  hits at (x=50mm, phi=180deg): {[f'{h*1000:.0f}mm' for h in hits_lee]}")

    if not any(0.020 < h < 0.040 for h in hits_wind):
        _fail("windward ray missed the probe (expected hit in [20, 40] mm)")
        return False
    if not any(0.095 < h < 0.105 for h in hits_wind):
        _fail("windward ray missed the main cone (expected hit near 100 mm)")
        return False
    if any(0.020 < h < 0.040 for h in hits_lee):
        _fail("leeward ray spuriously hit the probe — should be invisible from -y side")
        return False
    _ok("probe-on-cone: probe visible only on windward strip; the old "
        "axial-slice MeshGeometry would have collapsed both contours")
    return True


def main() -> int:
    results = [
        test_convex_sphere(),
        test_sphere_cone_matches_parametric(),
        test_hollow_duct(),
        test_probe_on_cone(),
    ]
    n = sum(1 for r in results if r)
    print()
    print("=" * 60)
    print(f"  {n}/{len(results)} raycast-mesh test groups passed")
    print("=" * 60)
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
