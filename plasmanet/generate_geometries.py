"""Generate parametric vehicle geometries for CFD training data.

Creates sphere-cone vehicles with varying nose radius and cone half-angle,
meshes them with gmsh, and prepares SU2 config files for each flight condition.

This is the bridge from "one-shape demo" to "geometry-aware production model."
"""
import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


def generate_sphere_cone(nose_radius_m, half_angle_deg, body_length_m, output_path):
    """Generate a sphere-cone vehicle body using CadQuery.

    Geometry: spherical nose cap blended into a conical body.
    This is the standard hypersonic vehicle shape (blunt body, cone afterbody).

    Returns the path to the saved STEP file.
    """
    import cadquery as cq

    half_angle_rad = math.radians(half_angle_deg)
    R = nose_radius_m

    # Sphere-cone junction point
    # The sphere and cone are tangent where the cone surface meets the sphere
    x_tang = R * (1 - math.sin(half_angle_rad))
    r_tang = R * math.cos(half_angle_rad)

    # Cone extends from tangent point to body_length
    x_end = body_length_m
    r_end = r_tang + (x_end - x_tang) * math.tan(half_angle_rad)

    # Build as revolution of a 2D profile
    # Profile: arc (nose) + line (cone)
    # Use workplane approach with revolve

    # Create the profile points for the cross-section (in XZ plane, revolve around X)
    n_arc = 20
    profile_points = []

    # Spherical nose arc: from tip (0,0) to tangent point
    for i in range(n_arc + 1):
        # Angle from 0 (tip) to pi/2 - half_angle (tangent)
        theta = i * (math.pi / 2 - half_angle_rad) / n_arc
        x = R * (1 - math.cos(theta))
        r = R * math.sin(theta)
        profile_points.append((x, r))

    # Cone: from tangent to end
    profile_points.append((x_end, r_end))

    # Close the profile (back along axis)
    profile_points.append((x_end, 0))
    profile_points.append((0, 0))

    # Build with CadQuery using a revolve
    # Create 2D wire from points
    wp = cq.Workplane("XZ")

    # Start at origin, draw through all points
    wire = wp.moveTo(0, 0)
    for x, r in profile_points[1:-1]:  # skip first (0,0) and last (0,0)
        wire = wire.lineTo(x, r)
    wire = wire.close()

    # Revolve around X axis (the axis of symmetry)
    body = wire.revolve(360, (0, 0, 0), (1, 0, 0))

    # Export
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(body, str(output_path))

    # Compute metadata
    bbox = body.val().BoundingBox()
    metadata = {
        "nose_radius_m": nose_radius_m,
        "half_angle_deg": half_angle_deg,
        "body_length_m": body_length_m,
        "r_base_m": round(r_end, 4),
        "bbox": {
            "xmin": round(bbox.xmin, 4), "xmax": round(bbox.xmax, 4),
            "ymin": round(bbox.ymin, 4), "ymax": round(bbox.ymax, 4),
            "zmin": round(bbox.zmin, 4), "zmax": round(bbox.zmax, 4),
        },
        "step_file": str(output_path),
    }
    meta_path = output_path.with_suffix(".json")
    meta_path.write_text(json.dumps(metadata, indent=2))
    print(f"  Generated: R={nose_radius_m}m, angle={half_angle_deg}deg, "
          f"L={body_length_m}m -> {output_path.name}")
    return str(output_path), metadata


def create_flow_domain(body_step_path, domain_factor=8.0):
    """Create a spherical flow domain around the body and boolean subtract.

    Returns path to the flow domain STEP file.
    """
    import cadquery as cq

    body = cq.importers.importStep(body_step_path)
    bbox = body.val().BoundingBox()
    L = max(bbox.xmax - bbox.xmin, bbox.ymax - bbox.ymin, bbox.zmax - bbox.zmin)
    center_x = (bbox.xmin + bbox.xmax) / 2
    center_y = (bbox.ymin + bbox.ymax) / 2
    center_z = (bbox.zmin + bbox.zmax) / 2
    R_domain = L * domain_factor

    # Create sphere
    sphere = cq.Workplane("XY").sphere(R_domain).translate((center_x, center_y, center_z))

    # Boolean subtract body from sphere
    domain = sphere.cut(body)

    domain_path = Path(body_step_path).with_name(
        Path(body_step_path).stem + "_domain.step")
    cq.exporters.export(domain, str(domain_path))

    meta = {
        "body_step": body_step_path,
        "domain_step": str(domain_path),
        "domain_radius_m": round(R_domain, 4),
        "center": [round(center_x, 4), round(center_y, 4), round(center_z, 4)],
    }
    print(f"  Flow domain: R={R_domain:.3f}m -> {domain_path.name}")
    return str(domain_path), meta


def mesh_domain(domain_step_path, char_length_mm=5.0, output_format="su2"):
    """Mesh the flow domain with gmsh.

    Returns path to the mesh file.
    """
    try:
        import gmsh
    except ImportError:
        print("  gmsh not available, skipping mesh generation")
        return None

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.occ.importShapes(domain_step_path)
    gmsh.model.occ.synchronize()

    # Set mesh size
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", char_length_mm / 1000)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", char_length_mm / 1000 / 5)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)  # Delaunay

    # Generate 3D mesh
    gmsh.model.mesh.generate(3)

    # Get stats
    nodes = gmsh.model.mesh.getNodes()
    n_nodes = len(nodes[0])

    # Save
    mesh_path = Path(domain_step_path).with_suffix(".su2" if output_format == "su2" else ".msh")
    gmsh.write(str(mesh_path))
    gmsh.finalize()

    print(f"  Meshed: {n_nodes} nodes -> {mesh_path.name}")
    return str(mesh_path)


def generate_su2_config(mach, altitude_km, mesh_filename, output_dir):
    """Generate SU2 Euler config for a specific flight condition."""
    from plasmanet.physics import standard_atmosphere

    T_inf, p_inf, rho_inf, a_inf = standard_atmosphere(altitude_km)

    config = f"""% SU2 Configuration - Hypersonic Euler
% Auto-generated for Mach {mach}, Alt {altitude_km}km
SOLVER= EULER
MATH_PROBLEM= DIRECT
RESTART_SOL= NO

% Freestream
MACH_NUMBER= {mach}
AOA= 0.0
FREESTREAM_TEMPERATURE= {T_inf:.2f}
FREESTREAM_PRESSURE= {p_inf:.4f}

% Fluid model
FLUID_MODEL= IDEAL_GAS
GAMMA_VALUE= 1.4
GAS_CONSTANT= 287.058

% Numerics
NUM_METHOD_GRAD= GREEN_GAUSS
CONV_NUM_METHOD_FLOW= ROE
MUSCL_FLOW= YES
SLOPE_LIMITER_FLOW= VENKATAKRISHNAN
VENKAT_LIMITER_COEFF= 0.5
TIME_DISCRE_FLOW= EULER_IMPLICIT
CFL_NUMBER= 1.0
CFL_ADAPT= YES
CFL_ADAPT_PARAM= ( 0.3, 1.5, 0.5, 50.0 )

% Convergence
ITER= 5000
CONV_RESIDUAL_MINVAL= -8

% Mesh
MESH_FILENAME= {mesh_filename}
MESH_FORMAT= SU2

% Boundaries
MARKER_EULER= ( body )
MARKER_FAR= ( farfield )

% Output
CONV_FILENAME= history
VOLUME_FILENAME= flow
SURFACE_FILENAME= surface_flow
OUTPUT_WRT_FREQ= 5000
OUTPUT_FILES= (RESTART, PARAVIEW)
MARKER_PLOTTING= ( body )
MARKER_MONITORING= ( body )
"""
    config_path = Path(output_dir) / f"M{mach}_A{altitude_km}.cfg"
    config_path.write_text(config)
    return str(config_path)


def generate_training_cases(output_dir="data/cfd_cases", n_geometries=5):
    """Generate all geometries, meshes, and SU2 configs for CFD training.

    Creates a matrix of geometries x flight conditions.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Geometry parameters: (nose_radius_m, half_angle_deg, body_length_m)
    geometries = [
        (0.02, 7,  0.5,  "sharp_narrow"),    # sharp nose, narrow cone (HGV-like)
        (0.05, 12, 0.8,  "medium_cone"),      # moderate
        (0.08, 15, 1.0,  "blunt_cone"),        # baseline blunt cone
        (0.15, 20, 1.0,  "blunt_wide"),        # blunter, wider
        (0.30, 30, 0.8,  "capsule"),           # capsule-like (Apollo shape)
    ]

    # Flight conditions: (Mach, altitude_km)
    conditions = [
        (8, 30),  (8, 40),
        (10, 30), (10, 40),
        (12, 30), (12, 40),
        (15, 35), (15, 45),
    ]

    manifest = {
        "geometries": [],
        "conditions": [{"mach": m, "altitude_km": a} for m, a in conditions],
        "cases": [],
    }

    t0 = time.monotonic()

    for nose_r, angle, length, name in geometries:
        print(f"\n--- Geometry: {name} (R={nose_r}m, angle={angle}deg) ---")
        geom_dir = output_dir / name
        geom_dir.mkdir(exist_ok=True)

        # Generate STEP
        step_path, geom_meta = generate_sphere_cone(
            nose_r, angle, length,
            str(geom_dir / f"{name}.step"))

        manifest["geometries"].append({
            "name": name,
            "nose_radius_m": nose_r,
            "half_angle_deg": angle,
            "body_length_m": length,
            "step_file": step_path,
        })

        # Create flow domain
        try:
            domain_path, domain_meta = create_flow_domain(step_path, domain_factor=8.0)
        except Exception as e:
            print(f"  Domain creation failed: {e}")
            continue

        # Mesh (this can be slow for fine meshes)
        try:
            # Use coarser mesh for initial training (faster SU2)
            char_len = max(5.0, nose_r * 1000 * 0.5)  # scale mesh size with nose radius
            mesh_path = mesh_domain(domain_path, char_length_mm=char_len)
        except Exception as e:
            print(f"  Meshing failed: {e}")
            mesh_path = None

        # Generate SU2 configs for each flight condition
        for mach, alt in conditions:
            case_dir = geom_dir / f"M{mach}_A{alt}"
            case_dir.mkdir(exist_ok=True)

            mesh_file = f"{name}_domain.su2"
            config_path = generate_su2_config(mach, alt, mesh_file, str(case_dir))

            manifest["cases"].append({
                "geometry": name,
                "mach": mach,
                "altitude_km": alt,
                "config": config_path,
                "mesh": mesh_path,
                "domain_step": domain_path,
                "status": "pending",
            })

    elapsed = time.monotonic() - t0

    # Save manifest
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    n_geom = len(manifest["geometries"])
    n_cases = len(manifest["cases"])
    print(f"\n{'='*50}")
    print(f"Generated {n_geom} geometries x {len(conditions)} conditions = {n_cases} cases")
    print(f"Time: {elapsed:.0f}s")
    print(f"Manifest: {manifest_path}")
    print(f"\nNext: Upload meshes + configs to GCP and run SU2")
    print(f"  python -m plasmanet.run_cfd_batch --manifest {manifest_path}")

    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate parametric vehicle geometries")
    parser.add_argument("--output", default="data/cfd_cases")
    parser.add_argument("--n-geometries", type=int, default=5)
    args = parser.parse_args()

    generate_training_cases(args.output, args.n_geometries)
