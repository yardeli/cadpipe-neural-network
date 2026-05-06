"""CFD-derived sheath: load a CFD vtu and expose its ne field.

Three CFD-output paths supported:

  1. SU2-NEMO (two-temperature multi-species):
        chemistry is solved by NEMO directly. The vtu carries
        Density_i (per-species partial densities), Temperature_tr,
        Temperature_ve, MassFrac_i, Pressure, Mach. We read these
        directly. AIR-5 / AIR-7 / AIR-11 species layouts are
        auto-detected from the field-name pattern.

  2. SU2-Euler (perfect-gas single-temperature):
        chemistry is NOT in the vtu. We read T, P, Mach and run
        Cantera per cell to get post-processed ne. `chem_mode='sparse'`
        samples 2,000 cells to stay reasonable; `'dense'` runs Cantera
        on every cell (~100s for a 100k-cell mesh).

  3. OpenFOAM / Eilmer / external:
        Use the lower-level `plasmanet.cfd_field.read_vtu_fields(path)`
        to get raw point-data dict, then wrap manually. The mesh
        layout differs between OpenFOAM (`internalField`) and
        Eilmer (block-structured); see `plasmanet/cfd_field.py` for
        per-solver field-name mappings.

For all three the resulting AxisymmetricField (or
UnstructuredField via build_unstructured_field) plugs into
`signals.scan_aspect` for line-of-sight attenuation, identical to
the analytical sheath path.

Geometry handling
-----------------
The CFD vtu carries its own coordinate system. For axisymmetric bodies
the body axis is conventionally +x (nose at x=0, aft at +x); ray
geometry in `signals.scan_aspect` follows the same convention. If your
CFD frame is rotated/translated, transform the vtu before passing.

Returns
-------
A 2-tuple `(cfd, field)` where:
    cfd     : CFDFieldResult containing per-cell (xyz, T, P, ne, mole
              fractions, stagnation point summary, notes about
              extraction mode).
    field   : an UnstructuredField callable returning (ne, ν_c) at
              arbitrary xyz query points via scipy NearestND
              interpolation.

Use cfd to inspect the raw extraction; pass field directly to
`signals.scan_aspect` for the LOS step.
"""
from __future__ import annotations

from typing import Literal, Optional

from plasmanet.cfd_field import (
    extract_nemo_field, extract_cfd_field, build_unstructured_field,
    CFDFieldResult,
)


def build_sheath_field_from_cfd(
    vtu_path: str,
    cfd_solver: Literal["su2_nemo", "su2_euler", "auto"] = "auto",
    *,
    geometry_name: str = "custom",
    mach: float = 22.5,
    altitude_km: float = 61.0,
    chem_mode: Literal["none", "sparse", "dense"] = "sparse",
):
    """Load a CFD vtu and return (CFDFieldResult, UnstructuredField).

    Parameters
    ----------
    vtu_path : str
        Path to the CFD output file. Currently must be a VTU XML
        unstructured grid; SU2 / OpenFOAM / Eilmer all emit VTU.
    cfd_solver : 'su2_nemo' | 'su2_euler' | 'auto'
        Which extractor to use. 'auto' (default) reads the vtu's field
        names — if Temperature_tr is present it routes to NEMO,
        otherwise to Euler+Cantera.
    geometry_name : free-form vehicle label (stored in CFDFieldResult.case_name)
    mach, altitude_km : freestream conditions (stored as metadata; the
        Euler path uses these to recover edge enthalpy for the real-gas
        T-correction)
    chem_mode : Euler-path Cantera-per-cell sampling
        'none'   : skip chemistry (ne = 0 everywhere)
        'sparse' : 2000 cells, prioritise hot regions (default)
        'dense'  : every cell (slow)
    """
    if cfd_solver == "auto":
        try:
            from plasmanet.cfd_field import read_vtu_fields
            fields, _, _ = read_vtu_fields(vtu_path)
            cfd_solver = "su2_nemo" if "Temperature_tr" in fields else "su2_euler"
        except Exception:
            cfd_solver = "su2_euler"

    if cfd_solver == "su2_nemo":
        cfd: CFDFieldResult = extract_nemo_field(
            vtu_path, geometry=geometry_name,
            mach=mach, altitude_km=altitude_km,
        )
    elif cfd_solver == "su2_euler":
        cfd = extract_cfd_field(
            vtu_path, geometry=geometry_name,
            mach=mach, altitude_km=altitude_km,
            chem_mode=chem_mode,
        )
    else:
        raise ValueError(f"unknown cfd_solver={cfd_solver!r}; "
                          f"supported: 'su2_nemo' | 'su2_euler' | 'auto'")

    field = build_unstructured_field(cfd)
    return cfd, field
