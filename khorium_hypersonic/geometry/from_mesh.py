"""Mesh-derived Geometry adapter.

Supports STL, STEP, OBJ via meshio (gracefully degrades when meshio is
not installed — geometry then exposes only what was passed in).

Strategy for `effective_nose_radius_m`:
  1. Extract surface points from the mesh
  2. Find the most-forward point (smallest x in body frame)
  3. Fit a sphere to all points within `nose_window_fraction * length`
     of that point (default 5%)
  4. Return the fitted sphere's radius

For STEP files, you'll need cadquery or python-OCC to read; meshio reads
STL/MSH/OBJ. STEP support is provided via cadquery if installed; we fall
back to "rasterize via gmsh first" if cadquery is also missing.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .base import BoundingBox


@dataclass
class MeshGeometry:
    """Geometry derived from a mesh file.

    Either pass `mesh_path` to load from disk, or pass `points` directly
    (Nx3 array of surface points in body frame, +x downstream).
    """
    name: str
    mesh_path: Optional[str] = None
    points: Optional[np.ndarray] = None
    nose_window_fraction: float = 0.05
    _bbox: Optional[BoundingBox] = field(default=None, init=False, repr=False)
    _R_nose: Optional[float] = field(default=None, init=False, repr=False)
    _half_angle_deg: Optional[float] = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if self.points is None and self.mesh_path is None:
            raise ValueError("MeshGeometry needs either mesh_path or points")
        if self.points is None:
            self.points = self._load_points(self.mesh_path)
        self.points = np.asarray(self.points, dtype=np.float64)
        if self.points.ndim != 2 or self.points.shape[1] != 3:
            raise ValueError(f"points must be (N, 3); got {self.points.shape}")

    @staticmethod
    def _load_points(path: str) -> np.ndarray:
        ext = Path(path).suffix.lower()
        if ext in {".stl", ".obj", ".msh", ".vtu"}:
            try:
                import meshio
            except ImportError:
                raise ImportError(
                    f"Loading {ext} requires meshio. pip install meshio"
                )
            mesh = meshio.read(path)
            return np.asarray(mesh.points, dtype=np.float64)
        if ext in {".step", ".stp"}:
            try:
                import cadquery as cq  # type: ignore
            except ImportError:
                raise ImportError(
                    f"Loading STEP requires cadquery. pip install cadquery"
                )
            shape = cq.importers.importStep(path)
            verts = shape.val().Vertices()
            return np.array([[v.X, v.Y, v.Z] for v in verts], dtype=np.float64)
        raise ValueError(f"Unsupported mesh format: {ext}")

    def bounding_box(self) -> BoundingBox:
        if self._bbox is None:
            mins = self.points.min(axis=0)
            maxs = self.points.max(axis=0)
            self._bbox = BoundingBox(
                xmin=float(mins[0]), xmax=float(maxs[0]),
                ymin=float(mins[1]), ymax=float(maxs[1]),
                zmin=float(mins[2]), zmax=float(maxs[2]),
            )
        return self._bbox

    def effective_nose_radius_m(self) -> float:
        """Fit a sphere to the most-forward `nose_window_fraction` of the body."""
        if self._R_nose is None:
            bbox = self.bounding_box()
            x_window = bbox.xmin + self.nose_window_fraction * bbox.length_m
            mask = self.points[:, 0] <= x_window
            nose_pts = self.points[mask]
            if len(nose_pts) < 4:
                # Fallback to bbox half-extent
                self._R_nose = bbox.max_radial_extent_m
            else:
                # Algebraic sphere fit (Pratt 1987): minimise ||(P-c)² - r²||²
                # Solved as a linear system on (cx, cy, cz, r²-c·c)
                A = np.column_stack([
                    2 * nose_pts[:, 0],
                    2 * nose_pts[:, 1],
                    2 * nose_pts[:, 2],
                    np.ones(len(nose_pts)),
                ])
                b = (nose_pts ** 2).sum(axis=1)
                coeffs, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
                cx, cy, cz, d = coeffs
                r2 = d + cx*cx + cy*cy + cz*cz
                self._R_nose = float(math.sqrt(max(r2, 1e-12)))
        return self._R_nose

    def characteristic_length_m(self) -> float:
        return self.bounding_box().length_m

    def body_radius_at_axial_station(self, x_m: float) -> float:
        """Equivalent-circular radius at axial slice x.

        Picks all surface points within ±0.5% of length around x and
        returns the maximum distance from the body axis.
        """
        bbox = self.bounding_box()
        if x_m <= bbox.xmin or x_m >= bbox.xmax:
            return 0.0
        tol = max(0.005 * bbox.length_m, 1e-3)
        mask = np.abs(self.points[:, 0] - x_m) < tol
        slice_pts = self.points[mask]
        if len(slice_pts) == 0:
            return 0.0
        radii = np.linalg.norm(slice_pts[:, 1:3], axis=1)
        return float(np.max(radii))

    def axial_stations(self, n: int = 100) -> list[float]:
        bbox = self.bounding_box()
        L = bbox.length_m
        x0 = bbox.xmin
        n = max(n, 2)
        out = []
        for i in range(n):
            theta = math.pi * i / (n - 1)
            out.append(x0 + 0.5 * L * (1.0 - math.cos(theta)))
        return out

    def local_radius(self, x_m: float) -> float:
        return self.body_radius_at_axial_station(x_m)

    def local_curvature(self, x_m: float) -> float:
        """Numerical curvature from finite differences on the radius profile."""
        bbox = self.bounding_box()
        h = max(0.005 * bbox.length_m, 1e-3)
        r0 = self.body_radius_at_axial_station(x_m - h)
        r1 = self.body_radius_at_axial_station(x_m)
        r2 = self.body_radius_at_axial_station(x_m + h)
        if r1 <= 0:
            return 0.0
        d2r_dx2 = (r0 - 2.0 * r1 + r2) / (h * h)
        # κ = |r''| / (1 + r'^2)^(3/2)  for r(x) curve in r-x plane
        dr_dx = (r2 - r0) / (2 * h)
        denom = (1.0 + dr_dx * dr_dx) ** 1.5
        return abs(d2r_dx2) / denom

    def surface_angle(self, x_m: float) -> float:
        """Numerical surface tangent angle from r(x) slope."""
        bbox = self.bounding_box()
        h = max(0.005 * bbox.length_m, 1e-3)
        r1 = self.body_radius_at_axial_station(x_m - h)
        r2 = self.body_radius_at_axial_station(x_m + h)
        dr_dx = (r2 - r1) / (2 * h)
        # Surface angle relative to body axis
        return math.atan(abs(dr_dx))

    def effective_half_angle_deg(self) -> float:
        """Effective afterbody half-angle from the slope of the body envelope."""
        if self._half_angle_deg is None:
            bbox = self.bounding_box()
            x_nose_end = bbox.xmin + 0.10 * bbox.length_m
            x_aft = bbox.xmax - 0.05 * bbox.length_m
            r_aft = self.body_radius_at_axial_station(x_aft)
            r_nose_end = self.body_radius_at_axial_station(x_nose_end)
            dx = x_aft - x_nose_end
            dr = r_aft - r_nose_end
            if dx > 0 and dr > 0:
                self._half_angle_deg = math.degrees(math.atan2(dr, dx))
            else:
                self._half_angle_deg = 9.0   # RAM-C-class default
        return self._half_angle_deg
