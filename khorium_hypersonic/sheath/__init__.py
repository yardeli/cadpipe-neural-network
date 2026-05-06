"""Sheath profile builders — analytical (Billig-anchored) and CFD-derived.

The sheath is the layer of ionized gas between the bow shock and the
body. For radar attenuation we need ne(r, z) along ray paths through it.

    AnalyticalSheath    — geometry-aware parametric model, anchored to
                          Billig 1967 standoff. Works on any Geometry.
    CFDSheath           — wraps a SU2-NEMO-extracted ne field (vtu)
"""
from .analytical import build_analytical_sheath_field
from .from_cfd import build_sheath_field_from_cfd

__all__ = [
    "build_analytical_sheath_field",
    "build_sheath_field_from_cfd",
]
