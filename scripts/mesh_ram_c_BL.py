"""Refined RAM-C mesh with TRUE anisotropic boundary-layer (BL) extrusion.

Why this exists: the sheath-decay diagnostic (commit 74226ef) found the
plasma layer is only ~4 cells across at half-max on the current refined
mesh (4mm body cells, BL HWHM 17mm). Going to 1mm isotropic at the wall
would be ~30M cells and unfeasible. True anisotropic refinement keeps
tangential cells at ~3-4mm but compresses normal-to-wall to 0.5mm via
gmsh's BoundaryLayer field — extruded prism layers near the body, tets
in the interior.

Expected output: ~1.5-2M cells total. ~9 prism layers from 0.5mm at
wall growing geometrically (ratio 1.3) to 5mm at the BL edge (~16mm
total BL thickness, well past the 17mm HWHM).

Caveat: gmsh's 3D BoundaryLayer extrusion is fragile. Sometimes fails
to mesh complex geometries cleanly. If it does fail, the script falls
back to a tighter isotropic Distance+Threshold field with body-wall
size 2mm, accepting ~5-6M cells instead.

Caveat 2: SU2-NEMO on the current GCP VM is OpenMP-only (no MPI).
Even 2M cells of any kind takes ~30+ min in single-threaded
preprocessing. This script produces the mesh; the actual run requires
either patience or an MPI-rebuilt SU2-NEMO. See
docs/KHORIUM_ALIGNMENT.md §5.1 for the production path.

Usage:
    python scripts/mesh_ram_c_BL.py
    python scripts/mesh_ram_c_BL.py --body-mm 0.5 --bl-thickness-m 0.030
    python scripts/mesh_ram_c_BL.py --fallback-isotropic   # skip BL, use 2mm iso
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).parent.parent
STEP = REPO / "data" / "cfd_cases_nemo" / "ram_c_small" / "ram_c_domain.step"
OUT_DIR = REPO / "data" / "cfd_cases_nemo" / "ram_c_BL"
OUT_RAW = OUT_DIR / "ram_c_domain_raw.su2"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--body-mm", type=float, default=0.5,
                    help="First-layer cell thickness at body wall (mm). "
                         "Default 0.5mm — gives ~30 cells across the BL HWHM.")
    ap.add_argument("--bl-thickness-m", type=float, default=0.030,
                    help="Total BL extrusion thickness (m). Default 30mm "
                         "covers the full 17mm sheath HWHM with margin.")
    ap.add_argument("--bl-ratio", type=float, default=1.3,
                    help="Geometric growth ratio between layers. Default 1.3.")
    ap.add_argument("--bl-size-far-mm", type=float, default=5.0,
                    help="Cell size at the BL outer edge (mm). Default 5mm.")
    ap.add_argument("--mid-mm", type=float, default=20.0,
                    help="Cell size in the mid-field beyond BL (mm).")
    ap.add_argument("--far-mm", type=float, default=200.0,
                    help="Cell size in the far field (mm).")
    ap.add_argument("--fallback-isotropic", action="store_true",
                    help="Skip BL extrusion, use a tight isotropic Distance "
                         "field with --body-mm at the wall. Less efficient "
                         "but more robust. Cell count ~5-6M.")
    args = ap.parse_args()

    if not STEP.exists():
        print(f"ERROR: {STEP} not found", file=sys.stderr)
        sys.exit(1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[mesh_BL] importing gmsh", flush=True)
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)

    print(f"[mesh_BL] loading {STEP.name}", flush=True)
    gmsh.model.occ.importShapes(str(STEP))
    gmsh.model.occ.synchronize()

    surfaces = gmsh.model.getEntities(2)
    areas = []
    for dim, tag in surfaces:
        a = gmsh.model.occ.getMass(dim, tag)
        areas.append((tag, a))
    areas.sort(key=lambda x: -x[1])
    farfield_tag = areas[0][0]
    body_tags = [t for t, _ in areas[1:]]
    print(f"[mesh_BL] farfield tag={farfield_tag} body tags={body_tags}",
          flush=True)
    gmsh.model.addPhysicalGroup(2, body_tags, name="body")
    gmsh.model.addPhysicalGroup(2, [farfield_tag], name="farfield")
    volumes = gmsh.model.getEntities(3)
    gmsh.model.addPhysicalGroup(3, [t for _, t in volumes], name="fluid")

    body_size = args.body_mm / 1000.0
    bl_size_far = args.bl_size_far_mm / 1000.0
    mid_size = args.mid_mm / 1000.0
    far_size = args.far_mm / 1000.0

    if not args.fallback_isotropic:
        # ── True anisotropic BL extrusion ─────────────────────────────────
        print(f"[mesh_BL] setting up BoundaryLayer field: "
              f"size={args.body_mm}mm -> {args.bl_size_far_mm}mm over "
              f"{args.bl_thickness_m*1000:.0f}mm at ratio {args.bl_ratio}",
              flush=True)
        try:
            bl = gmsh.model.mesh.field.add("BoundaryLayer")
            gmsh.model.mesh.field.setNumbers(bl, "FacesList", body_tags)
            gmsh.model.mesh.field.setNumber(bl, "Thickness",
                                             args.bl_thickness_m)
            gmsh.model.mesh.field.setNumber(bl, "Size", body_size)
            gmsh.model.mesh.field.setNumber(bl, "SizeFar", bl_size_far)
            gmsh.model.mesh.field.setNumber(bl, "Ratio", args.bl_ratio)
            gmsh.model.mesh.field.setNumber(bl, "Quads", 0)  # prisms, not hexes
            gmsh.model.mesh.field.setAsBoundaryLayer(bl)
            print(f"[mesh_BL] BL field {bl} configured", flush=True)
        except Exception as exc:
            print(f"[mesh_BL] BoundaryLayer setup failed: {exc} — falling "
                  f"back to isotropic", flush=True)
            args.fallback_isotropic = True

    # Background size field for the rest of the volume (whether BL is
    # active or we're in fallback mode)
    df = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(df, "FacesList", body_tags)

    if args.fallback_isotropic:
        # Tight isotropic Distance+Threshold to give small cells in the
        # near-wall region without the BL extrusion machinery.
        size_min = body_size
        print(f"[mesh_BL] FALLBACK: isotropic Distance field, "
              f"SizeMin={args.body_mm}mm DistMax=20mm", flush=True)
        inner = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(inner, "InField", df)
        gmsh.model.mesh.field.setNumber(inner, "SizeMin", size_min)
        gmsh.model.mesh.field.setNumber(inner, "SizeMax", mid_size)
        gmsh.model.mesh.field.setNumber(inner, "DistMin", 0.0)
        gmsh.model.mesh.field.setNumber(inner, "DistMax", 0.020)
        gmsh.model.mesh.field.setNumber(inner, "StopAtDistMax", 1)
    else:
        # BL handles 0-30mm. Beyond that, ramp from 5mm to 20mm over 50mm.
        inner = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(inner, "InField", df)
        gmsh.model.mesh.field.setNumber(inner, "SizeMin", bl_size_far)
        gmsh.model.mesh.field.setNumber(inner, "SizeMax", mid_size)
        gmsh.model.mesh.field.setNumber(inner, "DistMin",
                                         args.bl_thickness_m)
        gmsh.model.mesh.field.setNumber(inner, "DistMax",
                                         args.bl_thickness_m + 0.050)
        gmsh.model.mesh.field.setNumber(inner, "StopAtDistMax", 1)

    mid = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(mid, "InField", df)
    gmsh.model.mesh.field.setNumber(mid, "SizeMin", mid_size)
    gmsh.model.mesh.field.setNumber(mid, "SizeMax", far_size)
    gmsh.model.mesh.field.setNumber(mid, "DistMin", 0.5)
    gmsh.model.mesh.field.setNumber(mid, "DistMax", 5.0)

    bg = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(bg, "FieldsList", [inner, mid])
    gmsh.model.mesh.field.setAsBackgroundMesh(bg)

    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)   # Delaunay
    gmsh.option.setNumber("Mesh.RandomFactor", 1e-6)

    print(f"[mesh_BL] generating 3D mesh (this is the slow step)", flush=True)
    t0 = time.time()
    try:
        gmsh.model.mesh.generate(3)
    except Exception as exc:
        print(f"[mesh_BL] 3D meshing failed: {exc}", file=sys.stderr)
        if not args.fallback_isotropic:
            print("[mesh_BL] If BL extrusion was the cause, retry with "
                  "--fallback-isotropic. The isotropic path is more "
                  "robust at the cost of higher cell count.",
                  file=sys.stderr)
        gmsh.finalize()
        sys.exit(2)

    dt = time.time() - t0
    n_nodes = len(gmsh.model.mesh.getNodes()[0])
    elements_4 = gmsh.model.mesh.getElementsByType(4)
    n_tets = len(elements_4[0])
    elements_6 = gmsh.model.mesh.getElementsByType(6) if not args.fallback_isotropic else (None,)
    n_prisms = len(elements_6[0]) if elements_6[0] is not None else 0
    print(f"[mesh_BL] meshed in {dt:.1f}s: {n_nodes} nodes, "
          f"{n_tets} tets, {n_prisms} prisms",
          flush=True)
    print(f"[mesh_BL] writing {OUT_RAW}", flush=True)
    gmsh.write(str(OUT_RAW))
    gmsh.finalize()

    size_mb = OUT_RAW.stat().st_size / 1024 / 1024
    print(f"[mesh_BL] DONE: {OUT_RAW} ({size_mb:.1f} MB)", flush=True)
    print(f"[mesh_BL] Next: python scripts/add_markers_su2.py "
          f"--input {OUT_RAW} "
          f"--output {OUT_DIR}/ram_c_tagged.su2", flush=True)
    if n_prisms > 0:
        print(f"[mesh_BL] WARNING: {n_prisms} prism elements present. "
              f"SU2-NEMO supports prisms (element type 13) but verify the "
              f"add_markers_su2.py post-processor handles mixed-element "
              f"meshes — original was tet-only.", flush=True)


if __name__ == "__main__":
    main()
