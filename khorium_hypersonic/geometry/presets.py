"""Catalog of named vehicle geometries (data only — no physics here).

These are convenience presets for quick demos; the solver works with
ANY Geometry implementation, not just these names.
"""
from .sphere_cone import SphereCone
from .capsule import Capsule

GEOMETRY_PRESETS: dict[str, SphereCone] = {
    # RAM-C II reflectometer experiment (Jones & Cross 1972, NASA TN D-6617)
    "ram_c":        SphereCone(name="ram_c",        nose_radius_m=0.1524, half_angle_deg=9.0,  length_m=1.295),
    # Cadpipe-test parametric geometries
    "sharp_narrow": SphereCone(name="sharp_narrow", nose_radius_m=0.02,   half_angle_deg=7.0,  length_m=0.50),
    "medium_cone":  SphereCone(name="medium_cone",  nose_radius_m=0.05,   half_angle_deg=15.0, length_m=0.50),
    "blunt_cone":   SphereCone(name="blunt_cone",   nose_radius_m=0.08,   half_angle_deg=15.0, length_m=0.50),
    "blunt_wide":   SphereCone(name="blunt_wide",   nose_radius_m=0.15,   half_angle_deg=25.0, length_m=0.60),
    # Apollo-class blunt body
    "capsule":      Capsule(),
}
