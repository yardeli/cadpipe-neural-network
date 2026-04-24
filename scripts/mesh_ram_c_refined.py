"""Refined RAM-C mesh with body-clustered sizing for sheath resolution.

The first-pass 63k-node mesh put only ~63 cells in the plasma region
(ne > 1e19), giving a 1.5-orders-too-high peak ne. This mesh uses a
3-shell threshold field stack (combined via Min) so cells grow smoothly
from 4mm at the body wall to 200mm at far field, with most of the
budget spent in the first 50mm shell where the bow shock and sheath sit.

Targets:
  body wall:  4mm  (resolves 10mm bow shock with ~3 cells)
  50mm out:  15mm
  500mm out: 50mm
  5000mm out: 200mm

Expected total: ~600-800k tets. Output goes through add_markers_su2.py
to tag body/farfield by distance classification, same as the small mesh.

Usage:
    python scripts/mesh_ram_c_refined.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).parent.parent
STEP = REPO / "data" / "cfd_cases_nemo" / "ram_c_small" / "ram_c_domain.step"
OUT_DIR = REPO / "data" / "cfd_cases_nemo" / "ram_c_refined"
OUT_RAW = OUT_DIR / "ram_c_domain_raw.su2"


def main():
    if not STEP.exists():
        print(f"ERROR: {STEP} not found", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[mesh_refined] Loading gmsh", flush=True)
    import gmsh

    print(f"[mesh_refined] Initializing", flush=True)
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)

    print(f"[mesh_refined] Importing STEP: {STEP.name}", flush=True)
    gmsh.model.occ.importShapes(str(STEP))
    gmsh.model.occ.synchronize()

    surfaces = gmsh.model.getEntities(2)
    print(f"[mesh_refined] Found {len(surfaces)} surfaces", flush=True)

    areas = []
    for dim, tag in surfaces:
        a = gmsh.model.occ.getMass(dim, tag)
        areas.append((tag, a))
    areas.sort(key=lambda x: -x[1])
    farfield_tag = areas[0][0]
    body_tags = [t for t, _ in areas[1:]]
    print(f"[mesh_refined] farfield surface tag={farfield_tag} "
          f"area={areas[0][1]:.2f} m^2", flush=True)
    print(f"[mesh_refined] body surface tags={body_tags} "
          f"areas={[round(a, 4) for _, a in areas[1:]]} m^2", flush=True)

    gmsh.model.addPhysicalGroup(2, body_tags, name="body")
    gmsh.model.addPhysicalGroup(2, [farfield_tag], name="farfield")
    volumes = gmsh.model.getEntities(3)
    gmsh.model.addPhysicalGroup(3, [t for _, t in volumes], name="fluid")

    print(f"[mesh_refined] Setting up size field stack", flush=True)
    df = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(df, "FacesList", body_tags)

    inner = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(inner, "InField", df)
    gmsh.model.mesh.field.setNumber(inner, "SizeMin", 0.004)
    gmsh.model.mesh.field.setNumber(inner, "SizeMax", 0.015)
    gmsh.model.mesh.field.setNumber(inner, "DistMin", 0.0)
    gmsh.model.mesh.field.setNumber(inner, "DistMax", 0.05)
    gmsh.model.mesh.field.setNumber(inner, "StopAtDistMax", 1)

    mid = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(mid, "InField", df)
    gmsh.model.mesh.field.setNumber(mid, "SizeMin", 0.015)
    gmsh.model.mesh.field.setNumber(mid, "SizeMax", 0.05)
    gmsh.model.mesh.field.setNumber(mid, "DistMin", 0.05)
    gmsh.model.mesh.field.setNumber(mid, "DistMax", 0.5)
    gmsh.model.mesh.field.setNumber(mid, "StopAtDistMax", 1)

    outer = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(outer, "InField", df)
    gmsh.model.mesh.field.setNumber(outer, "SizeMin", 0.05)
    gmsh.model.mesh.field.setNumber(outer, "SizeMax", 0.2)
    gmsh.model.mesh.field.setNumber(outer, "DistMin", 0.5)
    gmsh.model.mesh.field.setNumber(outer, "DistMax", 5.0)

    bg = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(bg, "FieldsList", [inner, mid, outer])
    gmsh.model.mesh.field.setAsBackgroundMesh(bg)

    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)
    gmsh.option.setNumber("Mesh.RandomFactor", 1e-6)

    print(f"[mesh_refined] Generating 3D mesh (this may take 5-15 min)", flush=True)
    t0 = time.time()
    gmsh.model.mesh.generate(3)
    dt = time.time() - t0
    n_nodes = len(gmsh.model.mesh.getNodes()[0])
    elements = gmsh.model.mesh.getElementsByType(4)
    n_tets = len(elements[0])
    print(f"[mesh_refined] Meshed in {dt:.1f}s: "
          f"{n_nodes} nodes, {n_tets} tets", flush=True)

    print(f"[mesh_refined] Writing {OUT_RAW}", flush=True)
    gmsh.write(str(OUT_RAW))
    gmsh.finalize()

    size_mb = OUT_RAW.stat().st_size / 1024 / 1024
    print(f"[mesh_refined] DONE: {OUT_RAW} ({size_mb:.1f} MB)", flush=True)
    print(f"[mesh_refined] Next: python scripts/add_markers_su2.py "
          f"--input {OUT_RAW} "
          f"--output {OUT_DIR}/ram_c_tagged.su2", flush=True)


if __name__ == "__main__":
    main()
