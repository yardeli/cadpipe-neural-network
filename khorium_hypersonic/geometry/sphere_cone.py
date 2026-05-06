"""Sphere-cone parametric geometry.

The canonical hypersonic test geometry — spherical nose blending into a
conical afterbody. Used for RAM-C, blunt cones, ballistic re-entry
vehicles. Three parameters fully describe it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .base import BoundingBox


@dataclass(frozen=True)
class SphereCone:
    name: str
    nose_radius_m: float
    half_angle_deg: float
    length_m: float

    def bounding_box(self) -> BoundingBox:
        # Body radius at base (x = length)
        ha = math.radians(self.half_angle_deg)
        # Tangent point of sphere → cone
        x_tang = self.nose_radius_m * (1.0 - math.sin(ha))
        r_tang = self.nose_radius_m * math.cos(ha)
        if self.length_m > x_tang:
            r_base = r_tang + (self.length_m - x_tang) * math.tan(ha)
        else:
            r_base = math.sqrt(max(self.nose_radius_m**2
                                    - (self.nose_radius_m - self.length_m)**2, 0.0))
        return BoundingBox(
            xmin=0.0, xmax=self.length_m,
            ymin=-r_base, ymax=r_base,
            zmin=-r_base, zmax=r_base,
        )

    def effective_nose_radius_m(self) -> float:
        return self.nose_radius_m

    def characteristic_length_m(self) -> float:
        return self.length_m

    def body_radius_at_axial_station(self, x_m: float) -> float:
        """Sphere-cone body radius at axial station x.

        Spherical nose for x ∈ [0, x_tangent], conical afterbody beyond.
        """
        if x_m <= 0:
            return 0.0
        if x_m >= self.length_m:
            x_m = self.length_m

        ha = math.radians(self.half_angle_deg)
        x_tang = self.nose_radius_m * (1.0 - math.sin(ha))

        if x_m <= x_tang:
            # Spherical nose
            return math.sqrt(max(self.nose_radius_m**2
                                  - (self.nose_radius_m - x_m)**2, 0.0))
        # Conical afterbody
        r_tang = self.nose_radius_m * math.cos(ha)
        return r_tang + (x_m - x_tang) * math.tan(ha)

    def effective_half_angle_deg(self) -> float:
        return self.half_angle_deg

    # ── Axial-resolved interface ──────────────────────────────────────

    def axial_stations(self, n: int = 100) -> list[float]:
        """Cosine-spaced sampling: dense near the nose, coarser aft.

        x_i = (L/2) · (1 - cos(π i/(n-1)))   for i = 0..n-1
        gives a Chebyshev-1 distribution that's much denser near the
        rapidly-varying spherical nose than uniform spacing would be.
        """
        n = max(n, 2)
        out = []
        for i in range(n):
            theta = math.pi * i / (n - 1)
            out.append(0.5 * self.length_m * (1.0 - math.cos(theta)))
        return out

    def local_radius(self, x_m: float) -> float:
        return self.body_radius_at_axial_station(x_m)

    def local_curvature(self, x_m: float) -> float:
        """Spherical nose: κ = 1/R_n. Conical afterbody: κ ≈ 0
        (meridional curvature; ignores axisymmetric circumferential).
        """
        ha = math.radians(self.half_angle_deg)
        x_tang = self.nose_radius_m * (1.0 - math.sin(ha))
        if x_m <= x_tang:
            return 1.0 / max(self.nose_radius_m, 1e-12)
        return 0.0

    def surface_angle(self, x_m: float) -> float:
        """Angle between surface tangent and body axis (radians).

        Spherical nose: angle increases from 0 at nose to (π/2 −
        half_angle) at the tangent point. Conical afterbody: equals
        half_angle.
        """
        ha = math.radians(self.half_angle_deg)
        x_tang = self.nose_radius_m * (1.0 - math.sin(ha))
        if x_m <= 0:
            return math.pi / 2.0     # at nose tip, surface ⊥ axis
        if x_m <= x_tang:
            # On the spherical nose, theta = arccos((R_n - x)/R_n)
            # surface tangent angle = π/2 - theta
            cos_theta = max(min((self.nose_radius_m - x_m) / self.nose_radius_m, 1.0), -1.0)
            theta = math.acos(cos_theta)
            return math.pi / 2.0 - theta
        return ha
