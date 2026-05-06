"""CFD-derived sheath: load a SU2-NEMO vtu and expose its ne field.

Wraps plasmanet.cfd_field.extract_nemo_field for SU2-NEMO output. For
arbitrary CFD output (OpenFOAM, Eilmer, etc.), use extract_cfd_field
(perfect-gas Euler with on-the-fly Cantera) or the underlying
read_vtu_fields directly.
"""
from __future__ import annotations

from typing import Literal, Optional

from plasmanet.cfd_field import (
    extract_nemo_field, extract_cfd_field, build_unstructured_field,
    CFDFieldResult,
)


def build_sheath_field_from_cfd(
    vtu_path: str,
    cfd_solver: Literal["su2_nemo", "su2_euler", "openfoam"] = "su2_nemo",
    *,
    geometry_name: str = "custom",
    mach: float = 22.5,
    altitude_km: float = 61.0,
    chem_mode: Literal["none", "sparse", "dense"] = "sparse",
):
    """Load a CFD vtu and return (CFDFieldResult, AxisymmetricField).

    For SU2-NEMO (two-temperature, multi-species): chemistry is in the
    vtu. For SU2-Euler (perfect-gas single-T): we run Cantera per cell
    to compute ne (cost ~ ms per cell, sparse mode samples ~2000 cells).
    """
    if cfd_solver == "su2_nemo":
        cfd: CFDFieldResult = extract_nemo_field(
            vtu_path, geometry=geometry_name,
            mach=mach, altitude_km=altitude_km,
        )
    else:
        cfd = extract_cfd_field(
            vtu_path, geometry=geometry_name,
            mach=mach, altitude_km=altitude_km,
            chem_mode=chem_mode,
        )

    field = build_unstructured_field(cfd)
    return cfd, field
