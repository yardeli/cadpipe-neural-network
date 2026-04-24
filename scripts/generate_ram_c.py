"""Generate RAM-C II geometry, mesh, and SU2-NEMO config.

RAM-C II (1968 NASA flight experiment) is the canonical in-flight
hypersonic plasma dataset. The vehicle geometry:
  nose radius R_n = 0.1524 m (6 inches)
  half-angle  9 deg
  body length 2.54 m (100 inches)

Flight trajectory reference points used by our validation harness:
  81 km / Mach 23.9
  71 km / Mach 23.6
  61 km / Mach 22.5     <-- primary target (where equilibrium fails hardest)
  47 km / Mach 18.5

The mesh and config produced here are uploaded to the GCP VM and run
with SU2-NEMO. See docs/SU2_NEMO_FIX.md for the run recipe.

Usage:
    python scripts/generate_ram_c.py                 # all four altitudes
    python scripts/generate_ram_c.py --alt 61        # single altitude
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import numpy as np

from plasmanet.generate_geometries import (
    generate_sphere_cone, create_flow_domain,
)
from plasmanet.nemo_config import write_nemo_config


def mesh_domain_hypersonic(
    domain_step_path: str,
    body_length_m: float,
    near_body_mm: float = 3.0,
    far_field_mm: float = 150.0,
    refinement_radius_m: float = 0.5,
    output_format: str = "su2",
) -> str:
    """Mesh with size field: fine near body (for shock), coarse far away.

    Essential for Mach 22+ where the bow shock is only ~3-5 mm thick.
    A globally-uniform mesh is either too fine (billions of cells) or
    too coarse (shock numerically smeared).

    Uses Gmsh's Distance + Threshold fields to grow cells away from the
    body surface.
    """
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.occ.importShapes(domain_step_path)
    gmsh.model.occ.synchronize()

    # Classify surfaces by area
    surfaces = gmsh.model.getEntities(2)
    areas = []
    for dim, tag in surfaces:
        mass = gmsh.model.occ.getMass(dim, tag)
        areas.append((tag, mass))
    areas.sort(key=lambda x: -x[1])

    # Largest = farfield (outer sphere)
    farfield_tag = areas[0][0]
    body_tags = [t for t, _ in areas[1:]]

    gmsh.model.addPhysicalGroup(2, body_tags, name="body")
    gmsh.model.addPhysicalGroup(2, [farfield_tag], name="farfield")

    volumes = gmsh.model.getEntities(3)
    vol_tags = [t for _, t in volumes]
    gmsh.model.addPhysicalGroup(3, vol_tags, name="fluid")

    # Size field: Distance from body surfaces
    dist_field = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(dist_field, "FacesList", body_tags)

    # Threshold: near → near_body_mm, far → far_field_mm
    thresh_field = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(thresh_field, "InField", dist_field)
    gmsh.model.mesh.field.setNumber(thresh_field, "SizeMin", near_body_mm / 1000.0)
    gmsh.model.mesh.field.setNumber(thresh_field, "SizeMax", far_field_mm / 1000.0)
    gmsh.model.mesh.field.setNumber(thresh_field, "DistMin", 0.0)
    gmsh.model.mesh.field.setNumber(thresh_field, "DistMax", refinement_radius_m)

    gmsh.model.mesh.field.setAsBackgroundMesh(thresh_field)

    # Turn off default size
    gmsh.option.setNumber("Mesh.CharacteristicLengthExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.CharacteristicLengthFromPoints", 0)
    gmsh.option.setNumber("Mesh.CharacteristicLengthFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)  # Delaunay
    gmsh.option.setNumber("Mesh.RandomFactor", 1e-6)

    gmsh.model.mesh.generate(3)

    nodes = gmsh.model.mesh.getNodes()
    n_nodes = len(nodes[0])

    mesh_path = Path(domain_step_path).with_suffix(
        ".su2" if output_format == "su2" else ".msh")
    gmsh.write(str(mesh_path))
    gmsh.finalize()

    print(f"  Meshed (hypersonic size field): {n_nodes} nodes "
          f"[near={near_body_mm}mm, far={far_field_mm}mm, R_refine={refinement_radius_m}m] "
          f"-> {mesh_path.name}")
    return str(mesh_path)


# RAM-C II vehicle
RAM_C_GEOMETRY = {
    "name": "ram_c",
    "nose_radius_m": 0.1524,
    "half_angle_deg": 9.0,
    "body_length_m": 2.54,
}

# RAM-C trajectory reference points (Jones & Cross 1972, Grantham 1970)
RAM_C_TRAJECTORY = {
    81: {"mach": 23.9, "velocity_ms": 7620.0, "ref_ne_m3": 2.0e18},
    71: {"mach": 23.6, "velocity_ms": 7530.0, "ref_ne_m3": 1.0e19},
    61: {"mach": 22.5, "velocity_ms": 7100.0, "ref_ne_m3": 2.0e19},
    47: {"mach": 18.5, "velocity_ms": 5890.0, "ref_ne_m3": 2.0e19},
}

# Reflectometer stations along body (axial fraction of L)
RAM_C_STATIONS = [0.14, 0.32, 0.48, 0.67, 0.88]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--alt", type=int, default=61,
                    choices=list(RAM_C_TRAJECTORY.keys()),
                    help="altitude (km). Default 61 (primary validation target).")
    ap.add_argument("--all-alts", action="store_true",
                    help="generate all 4 altitudes instead of single")
    ap.add_argument("--output-dir", default=str(REPO / "data" / "cfd_cases_nemo" / "ram_c"),
                    help="output directory")
    ap.add_argument("--near-body-mm", type=float, default=4.0,
                    help="mesh size at body surface (mm). Mach 22 shock ~3 mm thick.")
    ap.add_argument("--far-field-mm", type=float, default=200.0,
                    help="mesh size at farfield (mm). Coarse since no physics there.")
    ap.add_argument("--refine-radius-m", type=float, default=5.0,
                    help="distance from body over which size transitions from near→far. "
                         "Must be LARGE (5+ m) so growth rate per layer stays below "
                         "~1.2× — NEMO 2-T solver rejects abrupt size jumps.")
    ap.add_argument("--domain-factor", type=float, default=6.0,
                    help="farfield radius / body length. Default 6.")
    ap.add_argument("--uniform", action="store_true",
                    help="Use uniform-size mesher (same as blunt_cone). "
                         "Drops the size-field transition that caused "
                         "convergence problems at Mach 22.")
    ap.add_argument("--uniform-size-mm", type=float, default=100.0,
                    help="Uniform mesh size when --uniform is set. "
                         "Default 100 mm = same ballpark as blunt_cone mesh "
                         "scaled up for larger body.")
    ap.add_argument("--gas-model", default="AIR-5",
                    help="AIR-5 (built-in) or air_11 (Mutation++, slower)")
    args = ap.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: geometry (one STEP per geometry, not per altitude)
    step_path = output_dir / f"{RAM_C_GEOMETRY['name']}.step"
    if step_path.exists():
        print(f"  Geometry already exists: {step_path.name}")
    else:
        print(f"Generating RAM-C II geometry: "
              f"R_n={RAM_C_GEOMETRY['nose_radius_m']:.4f} m, "
              f"half_angle={RAM_C_GEOMETRY['half_angle_deg']}°, "
              f"L={RAM_C_GEOMETRY['body_length_m']} m")
        generate_sphere_cone(
            nose_radius_m=RAM_C_GEOMETRY["nose_radius_m"],
            half_angle_deg=RAM_C_GEOMETRY["half_angle_deg"],
            body_length_m=RAM_C_GEOMETRY["body_length_m"],
            output_path=str(step_path),
        )

    # Step 2: flow domain (boolean cut)
    domain_step = output_dir / f"{RAM_C_GEOMETRY['name']}_domain.step"
    if domain_step.exists():
        print(f"  Flow domain already exists: {domain_step.name}")
    else:
        print(f"\nCreating flow domain (factor={args.domain_factor})")
        create_flow_domain(str(step_path), domain_factor=args.domain_factor)

    # Step 3: mesh (one per geometry — same mesh, different cfg per altitude)
    mesh_su2 = output_dir / f"{RAM_C_GEOMETRY['name']}_domain.su2"
    if mesh_su2.exists():
        print(f"  Mesh already exists: {mesh_su2.name}")
    elif args.uniform:
        # Use plasmanet.generate_geometries.mesh_domain — uniform sizing,
        # same approach that worked for blunt_cone.
        from plasmanet.generate_geometries import mesh_domain
        print(f"\nMeshing uniformly with char_length_mm={args.uniform_size_mm}")
        mesh_domain(str(domain_step),
                    char_length_mm=args.uniform_size_mm,
                    output_format="su2")
    else:
        print(f"\nMeshing with size field: near={args.near_body_mm}mm, "
              f"far={args.far_field_mm}mm, R_refine={args.refine_radius_m}m")
        mesh_domain_hypersonic(
            str(domain_step),
            body_length_m=RAM_C_GEOMETRY["body_length_m"],
            near_body_mm=args.near_body_mm,
            far_field_mm=args.far_field_mm,
            refinement_radius_m=args.refine_radius_m,
            output_format="su2",
        )

    # Step 4: generate per-altitude NEMO configs
    altitudes = list(RAM_C_TRAJECTORY.keys()) if args.all_alts else [args.alt]
    for alt in altitudes:
        traj = RAM_C_TRAJECTORY[alt]
        case_dir = output_dir / f"ram_c_M{traj['mach']:.1f}_A{alt}"
        case_dir.mkdir(exist_ok=True)
        cfg_path = case_dir / "run.cfg"

        # Tuned for Mach 22+ strong-shock stability:
        #   - LAX-FRIEDRICH for robustness (Roe can oscillate at strong shocks
        #     without entropy fix; AUSM better for smooth flow)
        #   - CFL = 0.5 initially, scheduled lower
        #   - No MUSCL initially; can re-enable once first-order converges
        write_nemo_config(
            path=str(cfg_path),
            mach=traj["mach"],
            altitude_km=alt,
            gas_model=args.gas_model,
            mesh_filename=mesh_su2.name,
            flux_scheme="LAX-FRIEDRICH",
            muscl=False,              # first-order for initial convergence
            iters=3000,
            cfl=0.5,
            convergence_min=-6.0,
            output_freq=200,
        )

        # Also copy the mesh into the case directory (so scp can send
        # a self-contained case)
        import shutil
        dst_mesh = case_dir / mesh_su2.name
        if not dst_mesh.exists():
            shutil.copy(mesh_su2, dst_mesh)

        # Metadata
        meta = {
            **RAM_C_GEOMETRY,
            "altitude_km": alt,
            "mach": traj["mach"],
            "velocity_ms": traj["velocity_ms"],
            "published_ne_peak_m3": traj["ref_ne_m3"],
            "reflectometer_stations_zL": RAM_C_STATIONS,
            "gas_model": args.gas_model,
        }
        (case_dir / "ram_c_metadata.json").write_text(json.dumps(meta, indent=2))
        print(f"  Case: {case_dir.name}")
        print(f"    mach={traj['mach']:.1f}, alt={alt} km, "
              f"ref ne_peak={traj['ref_ne_m3']:.2e} m^-3")

    print()
    print("Next: upload to GCP and run SU2-NEMO.")
    print(f"  gcloud compute scp --recurse {output_dir} \\")
    print(f"    openfoam-hgv:~/ram_c_runs --zone=us-central1-a")
    print()
    print("Then on the VM (env vars already in scripts/run_nemo_batch.sh):")
    print("  cd ~/ram_c_runs/ram_c_M22.5_A61")
    print("  export LD_LIBRARY_PATH=/opt/su2-nemo/lib:$LD_LIBRARY_PATH")
    print("  export MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data")
    print("  /opt/su2-nemo/bin/SU2_CFD run.cfg 2>&1 | tee su2.log")


if __name__ == "__main__":
    main()
