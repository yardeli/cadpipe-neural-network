"""Raycast-based mesh adapter for non-convex hypersonic geometries.

Step 3 of the waverider / integrated-inlet plan
(`docs/WAVERIDER_INLET_PLAN.md`). Closes the limit on `MeshGeometry`
in `from_mesh.py`: that adapter takes the **max** radial point in a
±0.5%-length axial slab as the body radius, which collapses
non-convex cross-sections to a single outer envelope and silently
hides:

  - **hollow ducts** (scramjet isolators, intake throats) — the inner
    duct wall vanishes,
  - **probe-on-cone** (forebody probes / sensors offset from the
    main cone) — the cone radius eats the probe,
  - **asymmetric waveriders** at the lower compression surface — the
    leeward upper surface dominates the answer at the same x.

This adapter solves the cross-section properly: at axial station x
we build the 2-D contour by intersecting all spanning triangles with
the plane X=x, then in that 2-D plane we ray-cast outward from the
body axis at each requested φ. Hits arrive in increasing radius —
so a duct returns ``[r_outer_in, r_outer_out, r_inner_in, ...]`` and
a probe-on-cone returns multiple radii at the φ direction that
crosses both contours.

Public API
----------
``RaycastMesh(name, mesh_path=..., triangles=...)`` implements the
existing :class:`khorium_hypersonic.geometry.Geometry` protocol so
direct callers (`compute_axial_profile`, etc.) work unchanged. The
``body_radius_at_axial_station`` query returns the **outermost** ray
hit averaged over a φ sweep — strictly compatible with the v0.3.0
axisymmetric assumption.

For strip-mode callers (waveriders, asymmetric afterbodies), use
``mesh.meridian_at(phi)``: it returns a thin Geometry that exposes
the per-φ ``local_radius(x)`` slice, ready to feed into
``compute_azimuthal_strips``.

For internal-duct probes, ``mesh.intersections(x, phi)`` returns the
full sorted list of ray hits so callers can pick inner / outer
surfaces explicitly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from .base import BoundingBox


# ── Triangle plane-cut helper ───────────────────────────────────────

def _slice_triangles_at_x(
    tris: np.ndarray, x_m: float,
) -> np.ndarray:
    """Intersect triangles with the plane X=x_m. Returns Nx2x2 segments
    in (y, z) coordinates. Each row is one [(y1, z1), (y2, z2)] line
    segment from one triangle's intersection with the plane. Triangles
    that don't span x_m or are coplanar are dropped.
    """
    if tris.size == 0:
        return np.zeros((0, 2, 2), dtype=np.float64)
    # Signed distance of each triangle vertex to the plane X=x.
    dx = tris[:, :, 0] - x_m                          # (N, 3)
    # Keep triangles where vertices straddle the plane (sign change).
    spans = (dx.min(axis=1) <= 0.0) & (dx.max(axis=1) >= 0.0)
    if not np.any(spans):
        return np.zeros((0, 2, 2), dtype=np.float64)
    tris_in = tris[spans]
    dx_in = dx[spans]

    # For each triangle, find the two edges that cross the plane and
    # linearly interpolate the (y, z) crossing point per edge.
    segs = []
    for verts, d in zip(tris_in, dx_in):
        cross_pts = []
        for i in range(3):
            j = (i + 1) % 3
            di, dj = d[i], d[j]
            if di == 0.0 and dj == 0.0:
                continue                              # edge lies in plane — skip
            if di * dj > 0.0:
                continue                              # both same side — no crossing
            if di == 0.0:
                cross_pts.append((verts[i, 1], verts[i, 2]))
                continue
            if dj == 0.0:
                cross_pts.append((verts[j, 1], verts[j, 2]))
                continue
            t = di / (di - dj)                        # 0 < t < 1
            y = verts[i, 1] + t * (verts[j, 1] - verts[i, 1])
            z = verts[i, 2] + t * (verts[j, 2] - verts[i, 2])
            cross_pts.append((y, z))
        # A non-degenerate triangle gives exactly 2 crossings; degenerate
        # collinear / vertex-on-plane cases can give 1 or 3 — collapse to
        # the unique pair.
        uniq = []
        for p in cross_pts:
            if not any(abs(p[0] - q[0]) < 1e-12 and abs(p[1] - q[1]) < 1e-12 for q in uniq):
                uniq.append(p)
        if len(uniq) == 2:
            segs.append([uniq[0], uniq[1]])
    if not segs:
        return np.zeros((0, 2, 2), dtype=np.float64)
    return np.asarray(segs, dtype=np.float64)


def _ray_segment_hits(
    segs: np.ndarray, phi_rad: float,
) -> list[float]:
    """Cast a 2-D ray from (0, 0) along (cos φ, sin φ) and return sorted
    radial distances of every intersection with the segment set."""
    if segs.shape[0] == 0:
        return []
    dy, dz = math.cos(phi_rad), math.sin(phi_rad)
    radii: list[float] = []
    for (y1, z1), (y2, z2) in segs:
        # Ray P(t) = t·(dy, dz),  t >= 0
        # Segment Q(s) = (y1, z1) + s·((y2, z2) - (y1, z1)),  0 <= s <= 1
        ay, az = y2 - y1, z2 - z1
        det = dy * az - dz * ay                       # 2-D cross
        if abs(det) < 1e-15:
            continue                                  # parallel
        # Solve [t, s] from t·D - s·A = (y1, z1)
        t = (y1 * az - z1 * ay) / det
        s = (y1 * dz - z1 * dy) / det
        if t > 1e-9 and -1e-9 <= s <= 1.0 + 1e-9:
            radii.append(t)
    radii.sort()
    return radii


# ── Public adapter ──────────────────────────────────────────────────

@dataclass
class RaycastMesh:
    """Cross-section-slicing Geometry adapter.

    Pass ``mesh_path`` (STL/OBJ/MSH via meshio) or pass ``triangles``
    directly as a (N, 3, 3) array of (triangle, vertex, xyz). Body axis
    is +x by convention.
    """
    name: str
    mesh_path: Optional[str] = None
    triangles: Optional[np.ndarray] = None
    n_phi_for_envelope: int = 16
    _bbox: Optional[BoundingBox] = field(default=None, init=False, repr=False)
    _R_nose: Optional[float] = field(default=None, init=False, repr=False)
    _half_angle_deg: Optional[float] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if self.triangles is None and self.mesh_path is None:
            raise ValueError("RaycastMesh needs either triangles= or mesh_path=")
        if self.triangles is None:
            self.triangles = self._load_triangles(self.mesh_path)
        self.triangles = np.asarray(self.triangles, dtype=np.float64)
        if self.triangles.ndim != 3 or self.triangles.shape[1:] != (3, 3):
            raise ValueError(
                f"triangles must be (N, 3, 3); got {self.triangles.shape}")

    @staticmethod
    def _load_triangles(path: str) -> np.ndarray:
        ext = Path(path).suffix.lower()
        if ext not in {".stl", ".obj", ".msh", ".vtu", ".ply"}:
            raise ValueError(f"Unsupported mesh format for raycasting: {ext}")
        try:
            import meshio
        except ImportError as e:
            raise ImportError(
                f"Loading {ext} for raycasting requires meshio. "
                "pip install meshio") from e
        mesh = meshio.read(path)
        pts = np.asarray(mesh.points, dtype=np.float64)
        tris_idx = None
        for cb in mesh.cells:
            if cb.type == "triangle":
                tris_idx = np.asarray(cb.data, dtype=np.int64)
                break
        if tris_idx is None:
            raise ValueError(
                f"No triangle cells in {path}; raycasting needs a triangulated mesh")
        return pts[tris_idx]                          # (N, 3, 3)

    # ── Cross-section + raycast primitives ──────────────────────────

    def intersections(self, x_m: float, phi_rad: float) -> list[float]:
        """All ray-mesh hits at axial x, azimuth φ — sorted increasing.

        Hollow ducts: returns 4 hits (outer-in, outer-out, inner-in,
        inner-out). Probe-on-cone in the probe's φ direction returns
        the probe outer surface; otherwise the cone surface. A solid
        convex body returns exactly 2 hits (the two diameter crossings).
        """
        segs = _slice_triangles_at_x(self.triangles, x_m)
        return _ray_segment_hits(segs, phi_rad)

    # ── Geometry-protocol surface ───────────────────────────────────

    def bounding_box(self) -> BoundingBox:
        if self._bbox is None:
            pts = self.triangles.reshape(-1, 3)
            mins = pts.min(axis=0)
            maxs = pts.max(axis=0)
            self._bbox = BoundingBox(
                xmin=float(mins[0]), xmax=float(maxs[0]),
                ymin=float(mins[1]), ymax=float(maxs[1]),
                zmin=float(mins[2]), zmax=float(maxs[2]),
            )
        return self._bbox

    def effective_nose_radius_m(self) -> float:
        """Fit a sphere to the leading 5% of the body envelope.

        Uses the φ-averaged outer radius at the foremost few axial
        stations and inverts the spherical-cap relation
        ``R_n = (r² + (Δx)²) / (2 Δx)``.
        """
        if self._R_nose is None:
            bbox = self.bounding_box()
            x0 = bbox.xmin
            dx_window = 0.05 * bbox.length_m
            xs = np.linspace(x0 + 0.005 * bbox.length_m,
                              x0 + dx_window, 6)
            rs = [self.body_radius_at_axial_station(x) for x in xs]
            r_max = max(rs)
            dx = xs[int(np.argmax(rs))] - x0
            if r_max > 1e-9 and dx > 1e-9:
                self._R_nose = float((r_max ** 2 + dx ** 2) / (2.0 * dx))
            else:
                self._R_nose = float(bbox.max_radial_extent_m)
        return self._R_nose

    def characteristic_length_m(self) -> float:
        return self.bounding_box().length_m

    def body_radius_at_axial_station(self, x_m: float) -> float:
        """Outer envelope radius at x — φ-averaged max hit.

        For an axisymmetric convex body this is the body radius. For
        non-convex bodies, this is the convex-hull radius averaged
        over φ (a smooth proxy), preserving the v0.3.0 axisymmetric
        sheath-wrap behaviour.
        """
        bbox = self.bounding_box()
        if x_m <= bbox.xmin or x_m >= bbox.xmax:
            return 0.0
        segs = _slice_triangles_at_x(self.triangles, x_m)
        if segs.shape[0] == 0:
            return 0.0
        outers = []
        for k in range(self.n_phi_for_envelope):
            phi = 2.0 * math.pi * k / self.n_phi_for_envelope
            hits = _ray_segment_hits(segs, phi)
            if hits:
                outers.append(hits[-1])               # outermost hit
        return float(np.mean(outers)) if outers else 0.0

    def axial_stations(self, n: int = 100) -> list[float]:
        bbox = self.bounding_box()
        n = max(n, 2)
        return [
            bbox.xmin + 0.5 * bbox.length_m * (1.0 - math.cos(math.pi * i / (n - 1)))
            for i in range(n)
        ]

    def local_radius(self, x_m: float) -> float:
        return self.body_radius_at_axial_station(x_m)

    def local_curvature(self, x_m: float) -> float:
        bbox = self.bounding_box()
        h = max(0.005 * bbox.length_m, 1e-3)
        r0 = self.body_radius_at_axial_station(x_m - h)
        r1 = self.body_radius_at_axial_station(x_m)
        r2 = self.body_radius_at_axial_station(x_m + h)
        if r1 <= 1e-9:
            return 0.0
        d2 = (r0 - 2.0 * r1 + r2) / (h * h)
        dr = (r2 - r0) / (2.0 * h)
        return abs(d2) / (1.0 + dr * dr) ** 1.5

    def surface_angle(self, x_m: float) -> float:
        bbox = self.bounding_box()
        h = max(0.005 * bbox.length_m, 1e-3)
        r1 = self.body_radius_at_axial_station(x_m - h)
        r2 = self.body_radius_at_axial_station(x_m + h)
        if r2 - r1 < -1e-9:                           # body radius shrinking (aft taper)
            return math.atan(abs(r2 - r1) / (2.0 * h))
        return math.atan(max(r2 - r1, 0.0) / (2.0 * h))

    def effective_half_angle_deg(self) -> float:
        if self._half_angle_deg is None:
            bbox = self.bounding_box()
            x_nose_end = bbox.xmin + 0.10 * bbox.length_m
            x_aft = bbox.xmax - 0.05 * bbox.length_m
            r_a = self.body_radius_at_axial_station(x_aft)
            r_n = self.body_radius_at_axial_station(x_nose_end)
            dx = x_aft - x_nose_end
            if dx > 0 and r_a > r_n:
                self._half_angle_deg = math.degrees(math.atan2(r_a - r_n, dx))
            else:
                self._half_angle_deg = 9.0
        return self._half_angle_deg

    # ── Strip-mode helper ───────────────────────────────────────────

    def meridian_at(self, phi_rad: float) -> "RaycastMeshMeridian":
        """Return a Geometry adapter for the single φ-slice of the mesh.

        Suitable to feed directly into
        :func:`khorium_hypersonic.compute_azimuthal_strips` as the
        per-strip Geometry. Each meridian shares the parent's triangle
        array (no copy) and looks up ``local_radius`` by ray-casting at
        the fixed φ.
        """
        return RaycastMeshMeridian(parent=self, phi_rad=float(phi_rad))


@dataclass
class RaycastMeshMeridian:
    """One φ-slice of a :class:`RaycastMesh`, exposing the Geometry
    protocol for strip-mode chemistry calls."""
    parent: RaycastMesh
    phi_rad: float
    name: str = field(default="")

    def __post_init__(self):
        if not self.name:
            self.name = f"{self.parent.name}@φ={math.degrees(self.phi_rad):.0f}°"

    def bounding_box(self) -> BoundingBox:
        return self.parent.bounding_box()

    def effective_nose_radius_m(self) -> float:
        return self.parent.effective_nose_radius_m()

    def characteristic_length_m(self) -> float:
        return self.parent.characteristic_length_m()

    def body_radius_at_axial_station(self, x_m: float) -> float:
        hits = self.parent.intersections(x_m, self.phi_rad)
        return float(hits[-1]) if hits else 0.0       # outermost surface in this φ direction

    def axial_stations(self, n: int = 100) -> list[float]:
        return self.parent.axial_stations(n)

    def local_radius(self, x_m: float) -> float:
        return self.body_radius_at_axial_station(x_m)

    def local_curvature(self, x_m: float) -> float:
        bbox = self.bounding_box()
        h = max(0.005 * bbox.length_m, 1e-3)
        r0 = self.body_radius_at_axial_station(x_m - h)
        r1 = self.body_radius_at_axial_station(x_m)
        r2 = self.body_radius_at_axial_station(x_m + h)
        if r1 <= 1e-9:
            return 0.0
        d2 = (r0 - 2.0 * r1 + r2) / (h * h)
        dr = (r2 - r0) / (2.0 * h)
        return abs(d2) / (1.0 + dr * dr) ** 1.5

    def surface_angle(self, x_m: float) -> float:
        bbox = self.bounding_box()
        h = max(0.005 * bbox.length_m, 1e-3)
        r1 = self.body_radius_at_axial_station(x_m - h)
        r2 = self.body_radius_at_axial_station(x_m + h)
        return math.atan(max(r2 - r1, 0.0) / (2.0 * h))

    def effective_half_angle_deg(self) -> float:
        return self.parent.effective_half_angle_deg()
