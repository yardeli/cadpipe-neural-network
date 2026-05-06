"""Radar / satellite signal-processing predictions.

Inputs:
    - electron-density field (analytical sheath OR CFD-extracted)
    - radar carrier frequency
    - viewing aspect (radar antenna position relative to vehicle)
Outputs:
    - per-aspect attenuation in dB
    - per-aspect detection status (DETECTABLE / DEGRADED / BLACKOUT)
    - line-of-sight ray geometry for paper figures

Re-exports the audited plasmanet.line_of_sight + plasma_wave primitives
under a stable namespace.
"""
from plasmanet.line_of_sight import (
    Ray, AxisymmetricField, CartesianGridField,
    integrate_los, scan_aspect, LOSResult,
)
from plasmanet.plasma_wave import (
    refractive_index, attenuation_rate_db_per_m, detection_status,
)

__all__ = [
    "Ray", "AxisymmetricField", "CartesianGridField",
    "integrate_los", "scan_aspect", "LOSResult",
    "refractive_index", "attenuation_rate_db_per_m", "detection_status",
]
