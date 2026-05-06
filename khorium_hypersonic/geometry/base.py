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
