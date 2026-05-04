"""Phase 3 RAM-C mesh — wall-y+ resolved for viscous AIR-7 v8.

Difference vs the v8_phase2 mesh: this one adds prismatic boundary-layer
cells from the body surface so the first cell sits at y+ ~ 1-5 in the
wall-bound chemistry zone. Required because:
  - Phase 1A inviscid + Phase 2 inviscid both miss the J&C 1972 sheath
    ne by 250x. Track A diagnosed the gap as inviscid Euler having no BL.
  - Smoke test confirmed SU2 v8.4.0 fixes the AIR-7 viscous heap-corruption
    bug — viscous AIR-7 IS the path forward, not finer inviscid meshes.
  - First-cell y+ ~ 1 at M=22.5/61km/wall=1500K conditions ~= 2 um normal
    spacing. Anisotropic prism layers grow geometrically to ~1 mm at
    BL edge, then isotropic tets fill the rest of the domain.

Targets:
  body wall (normal)   = 5 um   (y+ ~ 2-3 at peak heating)
  layer count          = 18 prisms (geometric growth, ratio 1.3 -> 1 mm at top)
  BL thickness         = 1.5 mm
  body wall tangential = 2 mm (vs 1 mm in phase2 — relaxed since BL has the
                                anisotropic resolution)
  3-20 mm out          = 2-3 mm tets
  100 mm out           = 8 mm
  1 m out              = 50 mm
  5 m out              = 200 mm

Total budget aim: 4-8M cells (mostly hex prisms in BL + tets in volume).

Note: gmsh's BoundaryLayer field in 3D has known restrictions; if it
fails the script falls back to a fine isotropic threshold (body=100 um,
y+~50 — coarser BL but still functional for AUSMPLUSM viscous).

Usage:
    python scripts/mesh_ram_c_v8_phase3_viscous.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_STEP_CANDIDATES = [
    # Full-domain STEPs (BREP_WITH_VOIDS = body inside outer enclosure)
    # MUST be first; the *_small variants are body-only and produce a
    # bbox-of-the-body mesh with no farfield.
    REPO / "data" / "cfd_cases_nemo" / "ram_c" / "ram_c_domain.step",
    REPO / "data" / "cfd_cases_nemo" / "ram_c_small" / "ram_c_domain.step",
    # Body-only fallback (last resort — will produce a thin-shell mesh)
    REPO / "data" / "cfd_cases_nemo" / "ram_c" / "ram_c.step",
    REPO / "data" / "cfd_cases_nemo" / "ram_c_small" / "ram_c.step",
]
STEP = next((p for p in _STEP_CANDIDATES if p.exists()), _STEP_CANDIDATES[0])

OUT_DIR = REPO / "data" / "cfd_cases_nemo" / "ram_c_v8_phase3_viscous"
OUT_RAW = OUT_DIR / "ram_c_domain_raw.su2"


def main():
    if not STEP.exists():
        print(f"ERROR: STEP geometry not found at {STEP}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[v8_phase3v] Loading gmsh", flush=True)
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)

    print(f"[v8_phase3v] Importing STEP: {STEP.name}", flush=True)
    gmsh.model.occ.importShapes(str(STEP))
    gmsh.model.occ.synchronize()

    surfaces = gmsh.model.getEntities(2)
    areas = sorted(
        ((tag, gmsh.model.occ.getMass(2, tag)) for _, tag in surfaces),
        key=lambda x: -x[1],
    )
    farfield_tag = areas[0][0]
    body_tags = [t for t, _ in areas[1:]]
    print(f"[v8_phase3v] farfield={farfield_tag} body={body_tags}", flush=True)

    gmsh.model.addPhysicalGroup(2, body_tags, name="body")
    gmsh.model.addPhysicalGroup(2, [farfield_tag], name="farfield")
    volumes = gmsh.model.getEntities(3)
    gmsh.model.addPhysicalGroup(3, [t for _, t in volumes], name="fluid")

    # Volume sizing field (covers the volume away from the BL)
    print(f"[v8_phase3v] Setting up volume size fields", flush=True)
    df = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(df, "FacesList", body_tags)

    # Shell sizing (outside the BL — BL itself is governed by BoundaryLayer field)
    s1 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s1, "InField", df)
    gmsh.model.mesh.field.setNumber(s1, "SizeMin", 0.002)    # 2 mm post-BL
    gmsh.model.mesh.field.setNumber(s1, "SizeMax", 0.003)
    gmsh.model.mesh.field.setNumber(s1, "DistMin", 0.0015)   # past BL edge
    gmsh.model.mesh.field.setNumber(s1, "DistMax", 0.020)
    gmsh.model.mesh.field.setNumber(s1, "StopAtDistMax", 1)

    s2 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s2, "InField", df)
    gmsh.model.mesh.field.setNumber(s2, "SizeMin", 0.003)
    gmsh.model.mesh.field.setNumber(s2, "SizeMax", 0.008)
    gmsh.model.mesh.field.setNumber(s2, "DistMin", 0.020)
    gmsh.model.mesh.field.setNumber(s2, "DistMax", 0.100)
    gmsh.model.mesh.field.setNumber(s2, "StopAtDistMax", 1)

    s3 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s3, "InField", df)
    gmsh.model.mesh.field.setNumber(s3, "SizeMin", 0.008)
    gmsh.model.mesh.field.setNumber(s3, "SizeMax", 0.050)
    gmsh.model.mesh.field.setNumber(s3, "DistMin", 0.100)
    gmsh.model.mesh.field.setNumber(s3, "DistMax", 1.000)
    gmsh.model.mesh.field.setNumber(s3, "StopAtDistMax", 1)

    s4 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s4, "InField", df)
    gmsh.model.mesh.field.setNumber(s4, "SizeMin", 0.050)
    gmsh.model.mesh.field.setNumber(s4, "SizeMax", 0.200)
    gmsh.model.mesh.field.setNumber(s4, "DistMin", 1.000)
    gmsh.model.mesh.field.setNumber(s4, "DistMax", 5.000)

    bg = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(bg, "FieldsList", [s1, s2, s3, s4])
    gmsh.model.mesh.field.setAsBackgroundMesh(bg)

    # Try to set up a BoundaryLayer field. Known to be flaky in 3D
    # for embedded geometries — wrap in try/except and fall back to
    # a fine threshold inside-shell if it errors.
    bl_ok = False
    try:
        print(f"[v8_phase3v] Setting up BoundaryLayer field "
              f"(hwall=5um, ratio=1.3, thickness=1.5mm)", flush=True)
        bl = gmsh.model.mesh.field.add("BoundaryLayer")
        gmsh.model.mesh.field.setNumbers(bl, "FacesList", body_tags)
        gmsh.model.mesh.field.setNumber(bl, "hwall_n", 5e-6)     # 5 um
        gmsh.model.mesh.field.setNumber(bl, "ratio", 1.3)
        gmsh.model.mesh.field.setNumber(bl, "thickness", 1.5e-3)
        gmsh.model.mesh.field.setNumber(bl, "Quads", 1)
        gmsh.model.mesh.field.setAsBoundaryLayer(bl)
        bl_ok = True
        print(f"[v8_phase3v] BL field registered. Will produce prism layers.",
              flush=True)
    except Exception as e:
        print(f"[v8_phase3v] BL field setup FAILED: {e}", flush=True)
        print(f"[v8_phase3v] Falling back to fine isotropic threshold "
              f"(body=100um -> y+~50)", flush=True)
        bl_fallback = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(bl_fallback, "InField", df)
        gmsh.model.mesh.field.setNumber(bl_fallback, "SizeMin", 1e-4)  # 100um
        gmsh.model.mesh.field.setNumber(bl_fallback, "SizeMax", 0.002)
        gmsh.model.mesh.field.setNumber(bl_fallback, "DistMin", 0.0)
        gmsh.model.mesh.field.setNumber(bl_fallback, "DistMax", 0.0015)
        gmsh.model.mesh.field.setNumber(bl_fallback, "StopAtDistMax", 1)
        gmsh.model.mesh.field.setNumbers(bg, "FieldsList",
                                          [bl_fallback, s1, s2, s3, s4])

    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)
    gmsh.option.setNumber("Mesh.RandomFactor", 1e-6)
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)

    print(f"[v8_phase3v] Generating 3D mesh "
          f"(BL={'on' if bl_ok else 'off, fallback=fine threshold'})",
          flush=True)
    t0 = time.time()
    gmsh.model.mesh.generate(3)
    dt = time.time() - t0

    n_nodes = len(gmsh.model.mesh.getNodes()[0])
    elements_tets = gmsh.model.mesh.getElementsByType(4)
    n_tets = len(elements_tets[0])
    elements_prisms = gmsh.model.mesh.getElementsByType(6)
    n_prisms = len(elements_prisms[0]) if len(elements_prisms[0]) else 0
    print(f"[v8_phase3v] Meshed in {dt:.1f}s: {n_nodes} nodes, "
          f"{n_tets} tets, {n_prisms} prisms",
          flush=True)
    if bl_ok and n_prisms == 0:
        print(f"[v8_phase3v] WARNING: BL field was set but no prisms "
              f"produced — likely silently disabled by gmsh. Result is "
              f"isotropic-only.", flush=True)

    print(f"[v8_phase3v] Writing {OUT_RAW}", flush=True)
    gmsh.write(str(OUT_RAW))
    gmsh.finalize()

    size_mb = OUT_RAW.stat().st_size / 1024 / 1024
    print(f"[v8_phase3v] DONE: {OUT_RAW} ({size_mb:.1f} MB)", flush=True)


if __name__ == "__main__":
    main()
