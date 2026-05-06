"""Geometry Protocol — the contract every vehicle adapter satisfies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class BoundingBox:
    xmin: float; xmax: float
    ymin: float; ymax: float
    zmin: float; zmax: float

    @property
    def length_m(self) -> float:
        return self.xmax - self.xmin

    @property
    def max_radial_extent_m(self) -> float:
        return max(
            abs(self.ymax), abs(self.ymin),
            abs(self.zmax), abs(self.zmin),
        )


@runtime_checkable
class Geometry(Protocol):
    """Minimum interface every vehicle must satisfy.

    All distances in meters. Body axis is conventionally aligned to +x;
    nose at x=0, aft at x=length. Adapters that don't fit this convention
    must internally rotate/translate before answering queries.
    """

    name: str

    def bounding_box(self) -> BoundingBox:
        """Body bounding box in vehicle-frame meters."""
        ...

    def effective_nose_radius_m(self) -> float:
        """Equivalent sphere radius at the stagnation point.

        For a parametric sphere-cone this is exactly the nose radius.
        For an arbitrary mesh, fit a sphere to the most-forward few
        percent of the body and return its radius. This drives Billig.
        """
        ...

    def characteristic_length_m(self) -> float:
        """Body length used for Reynolds / residence-time estimates."""
        ...

    def body_radius_at_axial_station(self, x_m: float) -> float:
        """Body radius (perpendicular to body axis) at axial position x.

        Used by the analytical sheath wrapper to construct an
        axisymmetric ne(r, z) field. For non-axisymmetric bodies, return
        the equivalent-circular cross-section radius (i.e., sqrt(area/π)).
        """
        ...

    def effective_half_angle_deg(self) -> float:
        """Effective afterbody half-angle in degrees.

        For a sphere-cone, this is the cone half-angle. For a capsule or
        arbitrary mesh, return the slope of the body envelope downstream
        of the spherical nose region.

        Method (not a field) so dataclass adapters can keep
        `half_angle_deg` as a positional field without name collision.
        """
        ...

    # ── Axial-resolved interface (v0.3.0+) ────────────────────────────
    # Used by core.flowfield for geometry-aware axial profiles. Adapters
    # that don't implement these inherit safe default fallbacks via
    # core.flowfield._axial_stations_default.

    def axial_stations(self, n: int = 100) -> list[float]:
        """Sample n axial coordinates from nose to aft, biased toward
        the nose where curvature changes fastest (Chebyshev or sine spacing
        recommended). Default uniform spacing if not overridden."""
        ...

    def local_radius(self, x_m: float) -> float:
        """Body radius perpendicular to the axis at axial station x.

        Alias for body_radius_at_axial_station; provided for the v0.3.0
        flowfield API consistency.
        """
        ...

    def local_curvature(self, x_m: float) -> float:
        """1/radius_of_curvature at axial station x (1/m).

        For a spherical nose, equals 1/R_n. For a conical afterbody,
        approaches 0 (flat in the meridional sense). Drives local shock
        standoff scaling for non-spherical regions of the body.
        """
        ...

    def surface_angle(self, x_m: float) -> float:
        """Angle between the body surface and the freestream flow (rad).

        At the stagnation point, surface_angle ≈ π/2 (normal). On the
        conical afterbody, surface_angle = half_angle_deg in radians.
        Used to switch between normal-shock (blunt regions where angle
        > 30°) and oblique-shock (slender regions) approximations in
        core.flowfield.
        """
        ...
