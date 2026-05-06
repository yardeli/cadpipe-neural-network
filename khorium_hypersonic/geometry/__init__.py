"""Vehicle geometry abstractions — geometry-agnostic by design.

Geometry is exposed through a Protocol so any caller can plug their own
adapter. Built-in adapters:

    SphereCone   — parametric: nose_radius, half_angle, length
    Capsule      — Apollo-style blunt body (high half-angle, short length)
    MeshGeometry — bbox-derived from an STL/STEP/OBJ via meshio

The Protocol exposes the minimum surface needed by the rest of the
solver:
    - bounding_box() → (xmin, xmax, ymin, ymax, zmin, zmax) in m
    - effective_nose_radius_m() → for Billig standoff
    - characteristic_length_m()  → for residence-time / Reynolds estimates
    - body_radius_at_axial_station(z) → for sheath wrapping (axisymmetric)
"""
from .base import Geometry, BoundingBox
from .sphere_cone import SphereCone
from .capsule import Capsule
from .from_mesh import MeshGeometry
from .presets import GEOMETRY_PRESETS

__all__ = [
    "Geometry", "BoundingBox",
    "SphereCone", "Capsule", "MeshGeometry",
    "GEOMETRY_PRESETS",
]
