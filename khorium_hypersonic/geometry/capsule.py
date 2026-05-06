"""Capsule (Apollo / Mars-EDL-class) blunt body.

Sphere-cone with very high half-angle (25-35°) and short length.
Convenience constructor returns a SphereCone — Capsule is a callable
factory, not a separate class, to avoid dataclass inheritance pitfalls
(non-default fields can't follow default fields under @dataclass).
"""
from __future__ import annotations

from .sphere_cone import SphereCone


def Capsule(
    name: str = "capsule",
    nose_radius_m: float = 0.30,
    half_angle_deg: float = 30.0,
    length_m: float = 0.80,
) -> SphereCone:
    """Apollo-class blunt body factory. Returns a SphereCone.

    Defaults match the cadpipe `capsule` preset.
    """
    return SphereCone(
        name=name,
        nose_radius_m=nose_radius_m,
        half_angle_deg=half_angle_deg,
        length_m=length_m,
    )
