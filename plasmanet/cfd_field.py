"""CFD field extraction for LOS-based detectability.

Extends the stagnation-point-only pipeline (legacy extract_cfd_results.py) to
produce full-field (T, p, ne, ν_c) data suitable for direct consumption
by line_of_sight.CartesianGridField and line_of_sight.integrate_los().

Two output formats supported:

1. **Point-cloud NPZ** (most faithful to CFD): cell centres with T, p,
   plus optionally ne and ν_c from Cantera post-processing. Consumed
   via scipy.interpolate.LinearNDInterpolator through
   UnstructuredField.

2. **Structured-grid NPZ** (fastest): resamples onto a regular
   (x, y, z) grid via linear interpolation. Consumed directly by
   CartesianGridField.

Cantera-per-cell is expensive (~1 ms per cell). For 100k cells that's
~100 s per CFD case. We support three modes to manage cost:

- 'none':     save only T, p — LOS can do on-demand chemistry
- 'sparse':   sample at most N cells (default 2000) uniformly + all cells
              in the shock layer (identified by pressure jump)
- 'dense':    Cantera at every cell — slow but exact

For this project's 40 cases, 'sparse' mode is the right balance.

Ne-field data is used downstream by:
- plasmanet.line_of_sight (detectability ray integration)
- plasmanet.detectability (analyze_detectability with use_cfd_field=True)
- Training NN surrogates on CFD-derived ne(x, y, z) (future work)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .physics import (
    K_B, janaf_equilibrium, saha_ionization, cp_air, R_AIR,
    standard_atmosphere,
)
from .collision_frequency import nu_total


# ── Low-level VTU reading ─────────────────────────────────────────────

def read_vtu_fields(vtu_path: str) -> tuple[dict, int, int]:
    """Read (T, p, Mach, coordinates) fields from a SU2 flow.vtu file.

    Returns (fields_dict, n_points, n_cells).

    Implementation: uses VTK's native reader (vtk.vtkXMLUnstructuredGridReader),
    which is more robust than meshio for SU2-generated VTU files. SU2's VTU
    output sometimes writes Velocity arrays with offsets that trip meshio's
    buffer-alignment check; VTK reads them without issue.
    """
    try:
        import vtk
        from vtk.util import numpy_support
    except ImportError:
        # Fallback: try meshio (may fail on some SU2 outputs)
        return _read_vtu_meshio(vtu_path)

    reader = vtk.vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(vtu_path))
    reader.Update()
    grid = reader.GetOutput()

    n_points = grid.GetNumberOfPoints()
    n_cells = grid.GetNumberOfCells()

    # Coordinates
    pts_vtk = grid.GetPoints().GetData()
    coords = numpy_support.vtk_to_numpy(pts_vtk).reshape(-1, 3).astype(np.float64)

    fields = {"coordinates": coords}

    pd = grid.GetPointData()
    for i in range(pd.GetNumberOfArrays()):
        name = pd.GetArrayName(i)
        arr_vtk = pd.GetArray(i)
        if arr_vtk is None:
            continue
        arr_np = numpy_support.vtk_to_numpy(arr_vtk)
        if arr_np.ndim == 2 and arr_np.shape[1] == 1:
            arr_np = arr_np[:, 0]
        fields[name] = arr_np.astype(np.float64)

    # Cell data too (rarely needed for our use case, but include for
    # completeness / future features like per-cell volumes)
    cd = grid.GetCellData()
    for i in range(cd.GetNumberOfArrays()):
        name = cd.GetArrayName(i)
        arr_vtk = cd.GetArray(i)
        if arr_vtk is None:
            continue
        arr_np = numpy_support.vtk_to_numpy(arr_vtk)
        if arr_np.ndim == 2 and arr_np.shape[1] == 1:
            arr_np = arr_np[:, 0]
        fields["cell_" + name] = arr_np.astype(np.float64)

    return fields, n_points, n_cells


def _read_vtu_meshio(vtu_path: str) -> tuple[dict, int, int]:
    """Legacy meshio-based reader (fallback when VTK isn't installed)."""
    import meshio
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        mesh = meshio.read(vtu_path)
    fields = {"coordinates": np.asarray(mesh.points, dtype=np.float64)}
    for name, data in mesh.point_data.items():
        arr = np.asarray(data, dtype=np.float64)
        if arr.ndim == 2 and arr.shape[1] == 1:
            arr = arr[:, 0]
        fields[name] = arr
    n_points = fields["coordinates"].shape[0]
    n_cells = sum(len(cb.data) for cb in mesh.cells)
    return fields, n_points, n_cells


# ── Sampling strategies ───────────────────────────────────────────────

def select_points_for_chemistry(
    T: np.ndarray, p: np.ndarray, coords: np.ndarray,
    mode: str = "sparse",
    max_samples: int = 2000,
    T_min: float = 500.0,
) -> np.ndarray:
    """Select which cells get Cantera post-processing.

    Returns indices into T/p arrays.

    - 'none':   return empty (no chemistry computed; ne=0 everywhere)
    - 'sparse': prioritise hot cells (T > T_min) plus a uniform random
                sample of cooler cells, up to max_samples total.
    - 'dense':  return all indices.
    """
    n = len(T)
    if mode == "none":
        return np.array([], dtype=np.int64)
    if mode == "dense":
        return np.arange(n)
    if mode == "sparse":
        hot_mask = T > T_min
        hot_idx = np.flatnonzero(hot_mask)
        if len(hot_idx) <= max_samples:
            return hot_idx
        # Too many hot cells — prioritise hottest
        order = np.argsort(-T[hot_idx])
        return hot_idx[order[:max_samples]]
    raise ValueError(f"mode must be 'none'|'sparse'|'dense', got {mode!r}")


def apply_real_gas_T_correction(
    T_euler: np.ndarray,
    p: np.ndarray,
    density: np.ndarray,
    momentum: np.ndarray,
    altitude_km: float,
    mach_inf: float,
    verbose: bool = False,
) -> np.ndarray:
    """Correct SU2 Euler (perfect-gas) temperature to real-gas temperature.

    SU2 Euler solves for T with γ=1.4 constant. At hypersonic conditions the
    dissociation of N₂, O₂, NO absorbs energy, so the REAL temperature is
    lower than what perfect-gas Euler reports. This can be ~2× at Mach 15+.

    Correction method (per-cell enthalpy conservation):
      1. Total enthalpy is a flow invariant for steady adiabatic flow:
             h_stag = h_inf + 0.5 · U_inf²
      2. At each cell: h_cell + 0.5 · u_cell² = h_stag
         so h_cell = h_stag − 0.5 · u_cell²
      3. Find T_real at cell pressure p_cell where Cantera's real-gas
         enthalpy equals h_cell. (Reference point: h at T_inf = h_inf.)

    This is NOT a substitute for coupled-chemistry CFD — it assumes the
    flow field (p, ρ, u) is unchanged by chemistry, which is wrong at
    Mach > 15. But it's much better than raw Euler T. For Mach 10-15 this
    correction brings ne predictions from ~100× to within ~3× of the
    coupled-chemistry answer.

    Parameters
    ----------
    T_euler : (N,) Euler temperature array (K) from SU2
    p : (N,) pressure array (Pa)
    density : (N,) density array (kg/m³)
    momentum : (N, 3) momentum array from SU2 (kg·m/s per unit volume, = ρ·u)
    altitude_km : freestream altitude
    mach_inf : freestream Mach number
    verbose : log progress

    Returns
    -------
    T_real : (N,) corrected temperature array (K)
    """
    n = len(T_euler)
    T_inf, p_inf, _, a_inf = standard_atmosphere(altitude_km)
    U_inf = mach_inf * a_inf

    # Per-cell velocity from momentum/density
    u_sq = np.zeros(n)
    if momentum is not None and density is not None:
        rho = np.maximum(density, 1e-10)
        if momentum.ndim == 2 and momentum.shape[1] == 3:
            mom_mag_sq = (momentum ** 2).sum(axis=1)
        else:
            mom_mag_sq = momentum.ravel() ** 2
        u_sq = mom_mag_sq / (rho ** 2)

    # Stagnation enthalpy reference (relative to T=0 perfect-gas)
    # Using Cp_pg·T convention consistent with Euler
    Cp_pg = 1004.5  # J/kg/K for γ=1.4 air
    h_stag_euler_ref = Cp_pg * T_inf + 0.5 * U_inf * U_inf

    # Cell enthalpy (Euler convention): h_cell = h_stag - 0.5·u²
    h_cell_euler = h_stag_euler_ref - 0.5 * u_sq

    # Get Cantera h reference offset: h_cantera(T_inf, p_inf) vs h_pg(T_inf)
    try:
        import cantera as ct
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sol = ct.Solution("air.yaml")
            sol.TPX = T_inf, p_inf, "N2:0.79, O2:0.21"
            sol.equilibrate("TP")
            h_cantera_at_inf = float(sol.enthalpy_mass)
            h_offset = h_cantera_at_inf - Cp_pg * T_inf

        # Target Cantera enthalpy for each cell:
        h_cell_cantera_target = h_cell_euler + h_offset

        T_real = np.zeros(n)
        # Bisect per cell
        for i in range(n):
            p_i = float(p[i])
            h_target = float(h_cell_cantera_target[i])
            if p_i < 10 or T_euler[i] < 300:
                # Outside atmosphere or too cold — just use Euler
                T_real[i] = float(T_euler[i])
                continue
            T_lo, T_hi = 250.0, float(T_euler[i]) * 1.5
            T_hi = min(T_hi, 30000.0)
            for _ in range(40):
                T_mid = 0.5 * (T_lo + T_hi)
                try:
                    sol.TPX = T_mid, p_i, "N2:0.79, O2:0.21"
                    sol.equilibrate("TP")
                    h_mid = float(sol.enthalpy_mass)
                    if h_mid < h_target:
                        T_lo = T_mid
                    else:
                        T_hi = T_mid
                except Exception:
                    break
            T_real[i] = 0.5 * (T_lo + T_hi)
            if verbose and (i + 1) % 500 == 0:
                print(f"    real-gas T correction: {i+1}/{n}  "
                      f"T_euler={T_euler[i]:.0f} → T_real={T_real[i]:.0f}")
        return T_real
    except ImportError:
        # Cantera not available — fall back to Cp-integration approximation
        print("  WARNING: Cantera not available, using Cp-integration for T correction")
        T_real = np.zeros(n)
        for i in range(n):
            T_pg = float(T_euler[i])
            h_target = h_cell_euler[i]   # use perfect-gas ref since no Cantera
            # Integrate dh = Cp(T)dT from T_inf
            T = T_inf
            dT = 10.0
            h_accum = Cp_pg * T_inf
            while h_accum < h_target and T < 30000:
                h_accum += cp_air(T) * dT
                T += dT
            T_real[i] = T
        return T_real


def cantera_at_points(
    T_values: np.ndarray, p_values: np.ndarray,
    use_cantera: bool = True, verbose: bool = False,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Run chemistry at each (T, p) point and return ne and ν_c.

    Returns (ne_m3, nu_c_hz, mole_fractions). mole_fractions is a dict
    of (N,) arrays for N2, O2, NO, O, N.
    """
    n = len(T_values)
    ne = np.zeros(n)
    nu = np.zeros(n)
    xN2 = np.zeros(n); xO2 = np.zeros(n); xNO = np.zeros(n)
    xO = np.zeros(n); xN = np.zeros(n)

    # Try to use Cantera; fall back to JANAF+Saha
    sol = None
    sol_plasma = None
    if use_cantera:
        try:
            import cantera as ct
            sol = ct.Solution("air.yaml")
            mech_candidates = [
                Path("C:/Users/yarden/Desktop/cadpipe/mechanisms/air_plasma_11s.yaml"),
                Path(__file__).parent.parent.parent.parent / "cadpipe" / "mechanisms" / "air_plasma_11s.yaml",
            ]
            mech_path = next((c for c in mech_candidates if c.exists()), None)
            if mech_path is not None:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sol_plasma = ct.Solution(str(mech_path), "air_plasma")
        except Exception:
            sol = None
            sol_plasma = None

    import warnings
    for i in range(n):
        T = float(T_values[i]); p = float(p_values[i])
        if T < 300 or p < 10:
            # Outside solver range — treat as free space
            continue

        # Neutral composition
        got_neutral = False
        if sol is not None:
            try:
                sol.TPX = T, max(p, 100.0), "N2:0.79, O2:0.21"
                sol.equilibrate("TP")
                xN2[i] = float(sol.X[sol.species_index("N2")])
                xO2[i] = float(sol.X[sol.species_index("O2")])
                xO[i]  = float(sol.X[sol.species_index("O")])
                xN[i]  = float(sol.X[sol.species_index("N")])
                xNO[i] = float(sol.X[sol.species_index("NO")])
                got_neutral = True
            except Exception:
                pass
        if not got_neutral:
            xN2[i], xO2[i], xO[i], xN[i], xNO[i] = janaf_equilibrium(T, p)

        # Ionisation
        got_ion = False
        if sol_plasma is not None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sol_plasma.TPX = T, max(p, 100.0), "N2:0.79, O2:0.21"
                    sol_plasma.equilibrate("TP")
                    xe = float(sol_plasma.X[sol_plasma.species_index("eminus")])
                    n_total = p / (K_B * T)
                    ne[i] = xe * n_total
                    got_ion = True
            except Exception:
                pass
        if not got_ion:
            ne[i] = saha_ionization(T, p, xNO[i], xO[i], xN[i])

        # Collision frequency at cell
        n_total = p / (K_B * T)
        nu[i] = float(nu_total(
            T, ne[i],
            n_N2=xN2[i]*n_total, n_O2=xO2[i]*n_total,
            n_NO=xNO[i]*n_total, n_O=xO[i]*n_total, n_N=xN[i]*n_total,
        ))

        if verbose and (i + 1) % 200 == 0:
            print(f"    chemistry at cell {i+1}/{n}: T={T:.0f}K ne={ne[i]:.2e}")

    mole_fractions = {"N2": xN2, "O2": xO2, "NO": xNO, "O": xO, "N": xN}
    return ne, nu, mole_fractions


# ── Top-level: case → field-NPZ ───────────────────────────────────────

@dataclass
class CFDFieldResult:
    """Extracted CFD field plus downstream chemistry products."""
    case_name: str
    geometry: str
    mach: float
    altitude_km: float
    coordinates: np.ndarray     # (N, 3) cell/point locations
    T_K: np.ndarray             # (N,) temperature field
    p_Pa: np.ndarray            # (N,) pressure field
    ne_m3: np.ndarray           # (N,) electron density (0 where chemistry skipped)
    nu_c_hz: np.ndarray         # (N,) collision frequency
    mole_fractions: dict        # dict of (N,) arrays for N2, O2, NO, O, N
    chem_mode: str              # which mode was used
    stag_point: dict            # stagnation point summary
    n_points: int
    notes: list[str] = field(default_factory=list)

    def save(self, path: str) -> None:
        """Save as .npz for later reloading with load_cfd_field()."""
        np.savez_compressed(
            path,
            case_name=self.case_name,
            geometry=self.geometry,
            mach=self.mach, altitude_km=self.altitude_km,
            coordinates=self.coordinates,
            T_K=self.T_K, p_Pa=self.p_Pa,
            ne_m3=self.ne_m3, nu_c_hz=self.nu_c_hz,
            x_N2=self.mole_fractions.get("N2"),
            x_O2=self.mole_fractions.get("O2"),
            x_NO=self.mole_fractions.get("NO"),
            x_O=self.mole_fractions.get("O"),
            x_N=self.mole_fractions.get("N"),
            chem_mode=self.chem_mode,
            stag_T_K=self.stag_point.get("T_K", 0.0),
            stag_p_Pa=self.stag_point.get("p_Pa", 0.0),
            stag_ne_m3=self.stag_point.get("ne_m3", 0.0),
            stag_xyz=self.stag_point.get("xyz", np.zeros(3)),
            n_points=self.n_points,
            notes="\n".join(self.notes),
        )


def extract_cfd_field(
    vtu_path: str,
    geometry: str, mach: float, altitude_km: float,
    chem_mode: str = "sparse",
    max_chem_samples: int = 2000,
    case_name: Optional[str] = None,
    apply_T_correction: bool = True,
    verbose: bool = False,
) -> CFDFieldResult:
    """Extract the full CFD field plus chemistry post-processing.

    Parameters
    ----------
    vtu_path : path to SU2 flow.vtu
    geometry, mach, altitude_km : case metadata
    chem_mode : 'none' | 'sparse' | 'dense'. 'sparse' gives practical
        LOS-usable ne field at ~100× lower cost than 'dense'.
    max_chem_samples : cap for sparse mode.
    case_name : optional explicit name (default = Path(vtu_path).parent.name)
    verbose : log progress
    """
    if case_name is None:
        case_name = Path(vtu_path).parent.name

    if verbose:
        print(f"[{case_name}] reading VTU…")
    fields, n_points, n_cells = read_vtu_fields(vtu_path)

    if "Temperature" not in fields or "Pressure" not in fields:
        raise ValueError(f"VTU {vtu_path} missing Temperature or Pressure fields")

    T = fields["Temperature"]
    p = fields["Pressure"]
    coords = fields["coordinates"]
    if T.shape != (n_points,):
        T = T.ravel()[:n_points]
    if p.shape != (n_points,):
        p = p.ravel()[:n_points]

    notes = []

    # Optional: apply real-gas T correction to perfect-gas Euler temperatures
    T_euler_original = None
    if apply_T_correction and "Density" in fields and "Momentum" in fields:
        if verbose:
            print(f"[{case_name}] applying real-gas T correction "
                  f"(Euler→real-gas enthalpy match)")
        T_euler_original = T.copy()
        T = apply_real_gas_T_correction(
            T_euler=T, p=p,
            density=fields["Density"], momentum=fields["Momentum"],
            altitude_km=altitude_km, mach_inf=mach,
            verbose=verbose,
        )
        notes.append(
            f"T corrected from Euler (γ=1.4) to real-gas at each cell via "
            f"enthalpy conservation. Original T_max={T_euler_original.max():.0f}K, "
            f"corrected T_max={T.max():.0f}K."
        )
    elif apply_T_correction:
        notes.append("T correction requested but Density/Momentum missing from VTU")

    # Select chemistry points
    idx = select_points_for_chemistry(T, p, coords, mode=chem_mode,
                                       max_samples=max_chem_samples)
    if verbose:
        print(f"[{case_name}] {n_points} points; running chemistry on {len(idx)} "
              f"({chem_mode} mode)")

    ne_full = np.zeros(n_points)
    nu_full = np.zeros(n_points)
    x_N2_full = np.full(n_points, 0.79)
    x_O2_full = np.full(n_points, 0.21)
    x_NO_full = np.zeros(n_points)
    x_O_full = np.zeros(n_points)
    x_N_full = np.zeros(n_points)

    if len(idx) > 0:
        ne_sel, nu_sel, mf_sel = cantera_at_points(T[idx], p[idx],
                                                     use_cantera=True,
                                                     verbose=verbose)
        ne_full[idx] = ne_sel
        nu_full[idx] = nu_sel
        x_N2_full[idx] = mf_sel["N2"]
        x_O2_full[idx] = mf_sel["O2"]
        x_NO_full[idx] = mf_sel["NO"]
        x_O_full[idx] = mf_sel["O"]
        x_N_full[idx] = mf_sel["N"]

    # Find stagnation point (max pressure)
    stag_idx = int(np.argmax(p))
    stag = {
        "idx": stag_idx,
        "T_K": float(T[stag_idx]),
        "p_Pa": float(p[stag_idx]),
        "ne_m3": float(ne_full[stag_idx]),
        "xyz": coords[stag_idx].astype(np.float64),
    }

    if verbose:
        print(f"[{case_name}] stag: T={stag['T_K']:.0f}K p={stag['p_Pa']:.2e}Pa "
              f"ne={stag['ne_m3']:.2e} m⁻³")

    return CFDFieldResult(
        case_name=case_name,
        geometry=geometry,
        mach=mach, altitude_km=altitude_km,
        coordinates=coords,
        T_K=T, p_Pa=p,
        ne_m3=ne_full, nu_c_hz=nu_full,
        mole_fractions={
            "N2": x_N2_full, "O2": x_O2_full, "NO": x_NO_full,
            "O": x_O_full, "N": x_N_full,
        },
        chem_mode=chem_mode,
        stag_point=stag,
        n_points=n_points,
        notes=notes,
    )


def extract_nemo_field(
    vtu_path: str,
    geometry: str, mach: float, altitude_km: float,
    case_name: Optional[str] = None,
    verbose: bool = False,
) -> CFDFieldResult:
    """Extract a SU2-NEMO (two-temperature coupled-chemistry) VTU into a
    CFDFieldResult.

    Unlike extract_cfd_field() which reads SU2 Euler perfect-gas output and
    post-processes chemistry, this function consumes SU2-NEMO output
    directly. NEMO already solves the multi-species two-temperature
    Navier-Stokes, so we don't need real-gas T correction or per-cell
    equilibrium Cantera calls.

    Field-name convention (SU2 v7.5.1 NEMO, GAS_MODEL= AIR-5):
      Density_0 = rho_N2,  Density_1 = rho_O2,  Density_2 = rho_NO,
      Density_3 = rho_N,   Density_4 = rho_O
      MassFrac_i = same order
      Temperature_tr = trans-rot temperature (K)
      Temperature_ve = vib-electronic temperature (K)
      Pressure, Mach, Momentum, Energy, Energy_ve

    For AIR-11 the Density_0 field is electrons, Density_1..5 are ions,
    Density_6..10 are neutrals (N, O, NO, N2, O2).

    Since NEMO AIR-5 doesn't carry electrons in the flow solver, we
    post-process ionisation using the two-temperature Saha model: electron
    temperature = T_ve (electrons equilibrate with vibrational modes),
    heavy-particle temperatures = T_tr. This is the Park two-temperature
    convention.
    """
    if case_name is None:
        case_name = Path(vtu_path).parent.name

    if verbose:
        print(f"[{case_name}] reading NEMO VTU…")
    fields, n_points, n_cells = read_vtu_fields(vtu_path)

    # Detect NEMO field layout
    is_nemo = "Temperature_tr" in fields
    if not is_nemo:
        raise ValueError(
            f"VTU {vtu_path} doesn't look like NEMO output "
            f"(missing Temperature_tr). For SU2 Euler use extract_cfd_field()."
        )

    # Number of species from Density_* fields
    n_species = sum(1 for k in fields if k.startswith("Density_"))

    T_tr = fields["Temperature_tr"]
    T_ve = fields["Temperature_ve"]
    p = fields["Pressure"]
    coords = fields["coordinates"]
    if T_tr.shape != (n_points,):
        T_tr = T_tr.ravel()[:n_points]
    if T_ve.shape != (n_points,):
        T_ve = T_ve.ravel()[:n_points]
    if p.shape != (n_points,):
        p = p.ravel()[:n_points]

    notes = [
        f"NEMO {n_species}-species output: T_tr range "
        f"[{T_tr.min():.0f}, {T_tr.max():.0f}] K; "
        f"T_ve range [{T_ve.min():.0f}, {T_ve.max():.0f}] K"
    ]

    # Assemble mass fractions by species
    mass_fracs = {}
    x_N2_full = np.full(n_points, 0.79)
    x_O2_full = np.full(n_points, 0.21)
    x_NO_full = np.zeros(n_points)
    x_O_full = np.zeros(n_points)
    x_N_full = np.zeros(n_points)
    ne_full = np.zeros(n_points)

    if n_species == 5:
        # AIR-5: order N2, O2, NO, N, O
        from .physics import R_UNIVERSAL
        # Molar masses (kg/mol)
        M_N2 = 0.0280134
        M_O2 = 0.0319988
        M_NO = 0.0300061
        M_N  = 0.0140067
        M_O  = 0.0159994
        rho = np.zeros(n_points)
        for i in range(5):
            rho_i = fields[f"Density_{i}"]
            rho += rho_i
        # Mass fractions as fractions of total density
        y = {}
        for sp, i in [("N2",0), ("O2",1), ("NO",2), ("N",3), ("O",4)]:
            y_i = fields[f"MassFrac_{i}"]
            if y_i.ndim == 2 and y_i.shape[1] == 1:
                y_i = y_i[:, 0]
            y[sp] = np.maximum(y_i, 0.0)
        # Convert mass fractions to mole fractions
        inv_M = y["N2"]/M_N2 + y["O2"]/M_O2 + y["NO"]/M_NO + y["N"]/M_N + y["O"]/M_O
        inv_M = np.maximum(inv_M, 1e-30)
        x_N2_full = (y["N2"]/M_N2) / inv_M
        x_O2_full = (y["O2"]/M_O2) / inv_M
        x_NO_full = (y["NO"]/M_NO) / inv_M
        x_N_full  = (y["N"]/M_N)   / inv_M
        x_O_full  = (y["O"]/M_O)   / inv_M

        # Two-temperature Saha ionisation at each cell:
        #   electron temperature = T_ve (Park convention)
        #   partial densities of N, O, NO come from T_tr-determined chemistry
        from .physics import saha_ionization
        if verbose:
            print(f"[{case_name}] applying 2-T Saha ionisation (T_e = T_ve)…")
        for i in range(n_points):
            Tv = float(T_ve[i])
            if Tv < 1500 or p[i] < 10:
                continue
            # Saha uses electron temperature T_ve for ionisation energy weighting
            ne_full[i] = saha_ionization(
                Tv, float(p[i]),
                float(x_NO_full[i]), float(x_O_full[i]), float(x_N_full[i]),
            )

    elif n_species == 11:
        # AIR-11: order e-, N+, O+, NO+, N2+, O2+, N, O, NO, N2, O2
        # Electrons come directly from the solver
        notes.append("AIR-11 NEMO: using solver electron density directly")
        rho_e = fields["Density_0"]
        if rho_e.ndim == 2 and rho_e.shape[1] == 1:
            rho_e = rho_e[:, 0]
        ne_full = rho_e / 9.10938e-31  # rho_e / m_e
        # Neutral mass fractions
        for sp, i in [("N",6), ("O",7), ("NO",8), ("N2",9), ("O2",10)]:
            y_i = fields[f"MassFrac_{i}"]
            if y_i.ndim == 2 and y_i.shape[1] == 1:
                y_i = y_i[:, 0]
            if sp == "N2":  x_N2_full = y_i
            elif sp == "O2": x_O2_full = y_i
            elif sp == "NO": x_NO_full = y_i
            elif sp == "N":  x_N_full = y_i
            elif sp == "O":  x_O_full = y_i
    else:
        raise ValueError(f"NEMO output has {n_species} species, expected 5 or 11")

    # Collision frequencies at each cell (heavy particle T used for ν_en)
    nu_full = np.zeros(n_points)
    if verbose:
        print(f"[{case_name}] computing collision frequencies…")
    n_total = p / (K_B * np.maximum(T_tr, 100.0))
    nu_full = np.asarray(nu_total(
        T_ve, ne_full,
        n_N2=x_N2_full*n_total, n_O2=x_O2_full*n_total,
        n_NO=x_NO_full*n_total, n_O=x_O_full*n_total, n_N=x_N_full*n_total,
    ))

    # Stagnation = max pressure point
    stag_idx = int(np.argmax(p))
    stag = {
        "idx": stag_idx,
        "T_K": float(T_tr[stag_idx]),
        "T_ve_K": float(T_ve[stag_idx]),
        "p_Pa": float(p[stag_idx]),
        "ne_m3": float(ne_full[stag_idx]),
        "xyz": coords[stag_idx].astype(np.float64),
    }
    if verbose:
        print(f"[{case_name}] NEMO stag: T_tr={stag['T_K']:.0f}K "
              f"T_ve={stag['T_ve_K']:.0f}K p={stag['p_Pa']:.2e}Pa "
              f"ne={stag['ne_m3']:.2e}")

    return CFDFieldResult(
        case_name=case_name,
        geometry=geometry,
        mach=mach, altitude_km=altitude_km,
        coordinates=coords,
        T_K=T_tr,   # store T_tr as primary T
        p_Pa=p,
        ne_m3=ne_full, nu_c_hz=nu_full,
        mole_fractions={
            "N2": x_N2_full, "O2": x_O2_full, "NO": x_NO_full,
            "O": x_O_full, "N": x_N_full,
        },
        chem_mode=f"nemo_air{n_species}",
        stag_point=stag,
        n_points=n_points,
        notes=notes,
    )


def load_cfd_field(npz_path: str) -> CFDFieldResult:
    """Reload a saved CFDFieldResult from .npz."""
    d = np.load(npz_path, allow_pickle=True)
    return CFDFieldResult(
        case_name=str(d["case_name"]),
        geometry=str(d["geometry"]),
        mach=float(d["mach"]),
        altitude_km=float(d["altitude_km"]),
        coordinates=d["coordinates"],
        T_K=d["T_K"], p_Pa=d["p_Pa"],
        ne_m3=d["ne_m3"], nu_c_hz=d["nu_c_hz"],
        mole_fractions={
            "N2": d["x_N2"], "O2": d["x_O2"], "NO": d["x_NO"],
            "O": d["x_O"], "N": d["x_N"],
        },
        chem_mode=str(d["chem_mode"]),
        stag_point={
            "T_K": float(d["stag_T_K"]),
            "p_Pa": float(d["stag_p_Pa"]),
            "ne_m3": float(d["stag_ne_m3"]),
            "xyz": d["stag_xyz"],
        },
        n_points=int(d["n_points"]),
        notes=str(d["notes"]).split("\n") if "notes" in d else [],
    )


# ── Adapter: CFDFieldResult → LOS-consumable field ────────────────────

def build_unstructured_field(cfd: CFDFieldResult):
    """Wrap a CFDFieldResult as an UnstructuredField for LOS integration.

    Returns an object with .__call__(xyz) → (ne, nu_c) using scipy's
    linear N-D interpolation over CFD cell centres.
    """
    try:
        from scipy.interpolate import NearestNDInterpolator
    except ImportError:
        raise ImportError("scipy required for build_unstructured_field")

    ne_interp = NearestNDInterpolator(cfd.coordinates, cfd.ne_m3)
    nu_interp = NearestNDInterpolator(cfd.coordinates, cfd.nu_c_hz)

    class _UnstructuredField:
        def __call__(self, xyz):
            xyz_arr = np.atleast_2d(np.asarray(xyz, dtype=np.float64))
            if xyz_arr.shape[1] != 3:
                xyz_arr = xyz_arr.reshape(-1, 3)
            ne = ne_interp(xyz_arr)
            nu = nu_interp(xyz_arr)
            if np.asarray(xyz).ndim == 1:
                return float(ne[0]), float(nu[0])
            return ne, nu

    return _UnstructuredField()


def build_structured_grid(
    cfd: CFDFieldResult,
    bounds: Optional[tuple[tuple[float, float], tuple[float, float], tuple[float, float]]] = None,
    n_grid: tuple[int, int, int] = (100, 80, 80),
):
    """Resample CFD field onto a regular grid for CartesianGridField.

    bounds: ((xmin, xmax), (ymin, ymax), (zmin, zmax)). Default = bounding box
            of CFD mesh.
    n_grid: grid resolution in (x, y, z)
    """
    from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
    from .line_of_sight import CartesianGridField

    coords = cfd.coordinates
    if bounds is None:
        mins = coords.min(axis=0)
        maxs = coords.max(axis=0)
        bounds = tuple((float(mins[i]), float(maxs[i])) for i in range(3))

    x = np.linspace(bounds[0][0], bounds[0][1], n_grid[0])
    y = np.linspace(bounds[1][0], bounds[1][1], n_grid[1])
    z = np.linspace(bounds[2][0], bounds[2][1], n_grid[2])

    # Build LinearND; fallback to nearest where undefined
    ne_lin = LinearNDInterpolator(coords, cfd.ne_m3, fill_value=0.0)
    nu_lin = LinearNDInterpolator(coords, cfd.nu_c_hz, fill_value=0.0)

    X, Y, Z = np.meshgrid(x, y, z, indexing="ij")
    pts = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    ne_grid = ne_lin(pts).reshape(n_grid)
    nu_grid = nu_lin(pts).reshape(n_grid)

    # NaN cleanup: set anything outside mesh to 0
    ne_grid = np.nan_to_num(ne_grid, nan=0.0)
    nu_grid = np.nan_to_num(nu_grid, nan=0.0)

    return CartesianGridField(x=x, y=y, z=z, ne=ne_grid, nu=nu_grid)
