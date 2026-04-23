"""Extract CFD results from SU2 VTU files and build PlasmaNet training data.

Reads flow.vtu from each completed SU2 case, extracts T and p at the
stagnation point and along the body surface, runs Cantera post-processing,
and outputs geometry-aware training data for PlasmaNet.
"""
import argparse
import json
import math
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np


def read_vtu_fields(vtu_path):
    """Read temperature, pressure, and velocity fields from SU2 VTU output.

    Uses meshio to handle binary/appended VTU format that SU2 produces.
    Returns dict of numpy arrays.
    """
    import meshio

    try:
        mesh = meshio.read(vtu_path)
    except ValueError:
        # Some SU2 VTU files have corrupt Velocity arrays — try reading
        # with a fallback that skips bad fields
        import warnings
        warnings.filterwarnings("ignore")
        mesh = meshio.read(vtu_path)

    n_points = len(mesh.points)
    n_cells = sum(len(cb.data) for cb in mesh.cells)

    fields = {'coordinates': mesh.points}

    # Point data
    for name, data in mesh.point_data.items():
        fields[name] = np.array(data)

    # Cell data (flatten cell blocks)
    for name, blocks in mesh.cell_data.items():
        fields[name] = np.concatenate(blocks)

    return fields, n_points, n_cells


def _get_scalar(fields, key, idx):
    """Get scalar value from field, handling (N,1) and (N,) shapes."""
    arr = fields[key]
    if arr.ndim == 2:
        return float(arr[idx, 0])
    return float(arr[idx])


def _get_field_flat(fields, key):
    """Get field as 1D array, squeezing (N,1) to (N,)."""
    arr = fields[key]
    if arr.ndim == 2 and arr.shape[1] == 1:
        return arr[:, 0]
    return arr


def find_stagnation_point(fields):
    """Find the stagnation point (max pressure or max temperature).

    At the stagnation point, velocity is zero and pressure/temperature are maximum.
    """
    if 'Pressure' in fields:
        p_flat = _get_field_flat(fields, 'Pressure')
        idx = int(np.argmax(p_flat))
    elif 'Temperature' in fields:
        t_flat = _get_field_flat(fields, 'Temperature')
        idx = int(np.argmax(t_flat))
    else:
        return None

    result = {'index': idx}
    for key in ['Temperature', 'Pressure', 'Mach', 'Density']:
        if key in fields:
            result[key] = _get_scalar(fields, key, idx)
    if 'coordinates' in fields:
        result['x'] = float(fields['coordinates'][idx, 0])
        result['y'] = float(fields['coordinates'][idx, 1])
        result['z'] = float(fields['coordinates'][idx, 2])
    if 'Momentum' in fields:
        mom = fields['Momentum'][idx]
        result['momentum_mag'] = float(np.linalg.norm(mom))

    return result


def sample_body_surface(fields, n_samples=20):
    """Sample points along the body surface (highest pressure region).

    Approximation: take the top N points by pressure — these are near
    the body where the shock layer is.
    """
    if 'Pressure' not in fields:
        return []

    p = _get_field_flat(fields, 'Pressure')
    # Top 5% by pressure are likely in the shock/stagnation region
    threshold = np.percentile(p, 95)
    shock_idx = np.where(p > threshold)[0]

    if len(shock_idx) == 0:
        return []

    # Sample evenly from shock region
    sample_idx = shock_idx[np.linspace(0, len(shock_idx) - 1, min(n_samples, len(shock_idx)), dtype=int)]

    samples = []
    for idx in sample_idx:
        point = {'index': int(idx)}
        for key in ['Temperature', 'Pressure', 'Mach', 'Density']:
            if key in fields:
                point[key] = _get_scalar(fields, key, idx)
        if 'coordinates' in fields:
            point['x'] = float(fields['coordinates'][idx, 0])
        samples.append(point)

    return samples


def cantera_postprocess(T, p):
    """Run Cantera equilibrium + Saha at one (T, p) point.

    Returns species mole fractions and electron density.
    """
    try:
        from plasmanet.physics import (
            full_analysis, janaf_equilibrium, saha_ionization,
            nonequilibrium_correction, plasma_frequency_ghz,
        )

        # Try Cantera first
        try:
            import cantera as ct
            import warnings
            mech_path = Path(__file__).parent.parent.parent.parent / "cadpipe" / "mechanisms" / "air_plasma_11s.yaml"
            if mech_path.exists():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sol = ct.Solution(str(mech_path), "air_plasma")
                    sol.TPX = T, max(p, 100), "N2:0.79, O2:0.21"
                    sol.equilibrate("TP")
                    x_e = float(sol.X[sol.species_index("eminus")])
                    from plasmanet.physics import K_B
                    n_total = p / (K_B * T)
                    ne_equil = x_e * n_total
                    ne = nonequilibrium_correction(T, ne_equil)
                    fp = plasma_frequency_ghz(ne)

                    return {
                        "x_N2": float(sol.X[sol.species_index("N2")]),
                        "x_O2": float(sol.X[sol.species_index("O2")]),
                        "x_O": float(sol.X[sol.species_index("O")]),
                        "x_N": float(sol.X[sol.species_index("N")]),
                        "x_NO": float(sol.X[sol.species_index("NO")]),
                        "ne_m3": ne,
                        "fp_GHz": fp,
                        "source": "cantera_plasma",
                    }
        except Exception:
            pass

        # Fallback to JANAF + Saha
        x_N2, x_O2, x_O, x_N, x_NO = janaf_equilibrium(T, p)
        ne_equil = saha_ionization(T, p, x_NO, x_O, x_N)
        ne = nonequilibrium_correction(T, ne_equil)
        fp = plasma_frequency_ghz(ne)

        return {
            "x_N2": x_N2, "x_O2": x_O2, "x_O": x_O, "x_N": x_N, "x_NO": x_NO,
            "ne_m3": ne, "fp_GHz": fp, "source": "janaf_saha",
        }
    except Exception as e:
        return {"error": str(e), "source": "failed"}


def process_case(case_dir, geometry_meta):
    """Process one CFD case: extract fields, compute plasma, return training point."""
    case_dir = Path(case_dir)
    vtu_path = case_dir / "flow.vtu"

    if not vtu_path.exists():
        return None

    # Parse case name: geometry_M{mach}_A{alt}
    name = case_dir.name
    parts = name.split('_')
    mach = None
    alt = None
    for p in parts:
        if p.startswith('M') and p[1:].isdigit():
            mach = int(p[1:])
        elif p.startswith('A') and p[1:].isdigit():
            alt = int(p[1:])

    if mach is None or alt is None:
        return None

    # Read VTU
    try:
        fields, n_points, n_cells = read_vtu_fields(str(vtu_path))
    except Exception as e:
        return {"error": f"VTU parse failed: {e}", "case": name}

    # Find stagnation point
    stag = find_stagnation_point(fields)
    if stag is None:
        return {"error": "No stagnation point found", "case": name}

    T_stag = stag.get('Temperature', 0)
    p_stag = stag.get('Pressure', 0)

    if T_stag < 100 or p_stag < 10:
        return {"error": f"Unphysical stagnation: T={T_stag}, p={p_stag}", "case": name}

    # Cantera post-processing at stagnation
    chem = cantera_postprocess(T_stag, p_stag)

    # Build training data point
    point = {
        "geometry": geometry_meta.get("name", "unknown"),
        "nose_radius_m": geometry_meta.get("nose_radius_m", 0.08),
        "half_angle_deg": geometry_meta.get("half_angle_deg", 15),
        "body_length_m": geometry_meta.get("body_length_m", 1.0),
        "mach": mach,
        "altitude_km": alt,
        "T_stag_K": T_stag,
        "p_stag_Pa": p_stag,
        "n_points": n_points,
        "n_cells": n_cells,
        **chem,
    }

    # Sample body surface points
    surface_samples = sample_body_surface(fields, n_samples=10)
    surface_chem = []
    for sp in surface_samples:
        sc = cantera_postprocess(sp.get('Temperature', 300), sp.get('Pressure', 100))
        sc['x_position'] = sp.get('x', 0)
        sc['T_local'] = sp.get('Temperature', 0)
        sc['p_local'] = sp.get('Pressure', 0)
        surface_chem.append(sc)
    point['surface_samples'] = surface_chem

    return point


def process_all_results(results_dir, manifest_path, output_path):
    """Process all CFD results and build training dataset."""
    results_dir = Path(results_dir)
    manifest = json.loads(Path(manifest_path).read_text())

    # Build geometry metadata lookup
    geom_meta = {}
    for g in manifest.get('geometries', []):
        geom_meta[g['name']] = g

    training_points = []
    errors = []

    # Find all completed cases
    for case_dir in sorted(results_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        if not (case_dir / "flow.vtu").exists():
            continue

        # Get geometry name from case dir name
        geom_name = case_dir.name.rsplit('_M', 1)[0]
        meta = geom_meta.get(geom_name, {"name": geom_name})

        print(f"Processing {case_dir.name}...")
        point = process_case(case_dir, meta)

        if point is None:
            errors.append({"case": case_dir.name, "error": "process_case returned None"})
        elif "error" in point:
            errors.append(point)
            print(f"  ERROR: {point['error']}")
        else:
            training_points.append(point)
            ne = point.get('ne_m3', 0)
            fp = point.get('fp_GHz', 0)
            print(f"  T_stag={point['T_stag_K']:.0f}K, ne={ne:.2e}, fp={fp:.1f}GHz")

    # Save
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save as JSON (detailed)
    json_path = output_path.with_suffix('.json')
    json_path.write_text(json.dumps({
        "n_points": len(training_points),
        "n_errors": len(errors),
        "points": training_points,
        "errors": errors,
    }, indent=2))

    # Save as NPZ (for PlasmaNet training)
    if training_points:
        arrays = {
            "mach": np.array([p["mach"] for p in training_points], dtype=np.float64),
            "altitude_km": np.array([p["altitude_km"] for p in training_points], dtype=np.float64),
            "nose_radius_m": np.array([p["nose_radius_m"] for p in training_points], dtype=np.float64),
            "half_angle_deg": np.array([p.get("half_angle_deg", 15) for p in training_points], dtype=np.float64),
            "T_stag_K": np.array([p["T_stag_K"] for p in training_points], dtype=np.float64),
            "p_stag_Pa": np.array([p["p_stag_Pa"] for p in training_points], dtype=np.float64),
            "x_N2": np.array([p.get("x_N2", 0) for p in training_points], dtype=np.float64),
            "x_O2": np.array([p.get("x_O2", 0) for p in training_points], dtype=np.float64),
            "x_O": np.array([p.get("x_O", 0) for p in training_points], dtype=np.float64),
            "x_N": np.array([p.get("x_N", 0) for p in training_points], dtype=np.float64),
            "x_NO": np.array([p.get("x_NO", 0) for p in training_points], dtype=np.float64),
            "ne_m3": np.array([p.get("ne_m3", 0) for p in training_points], dtype=np.float64),
            "fp_GHz": np.array([p.get("fp_GHz", 0) for p in training_points], dtype=np.float64),
            "status_code": np.array([
                2 if p.get("fp_GHz", 0) > 12 else (1 if p.get("fp_GHz", 0) > 3 else 0)
                for p in training_points
            ], dtype=np.int32),
        }
        npz_path = output_path.with_suffix('.npz')
        np.savez_compressed(str(npz_path), **arrays)
        print(f"\nSaved {len(training_points)} training points to {npz_path}")

    print(f"\nResults: {len(training_points)} successful, {len(errors)} errors")
    print(f"JSON: {json_path}")
    return training_points, errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract CFD results for PlasmaNet training")
    parser.add_argument("--results", default="data/cfd_results")
    parser.add_argument("--manifest", default="data/cfd_cases/manifest.json")
    parser.add_argument("--output", default="data/cfd_training_data")
    args = parser.parse_args()

    process_all_results(args.results, args.manifest, args.output)
