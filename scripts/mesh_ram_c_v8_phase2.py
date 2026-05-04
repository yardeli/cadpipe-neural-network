"""Phase 2 RAM-C mesh: 5-10 cells across the 3 mm bow-shock standoff.

Track B target from CHECKPOINT_2026-04-26 §2.8 (revised after first
attempt overshot — 0.5 mm body wall produced 12.18M tets vs 4-6M target):
  body wall    = 1.0 mm   (was 0.5 mm — saves a 2x linear -> 8x volumetric)
  3 mm out     ~ 1 mm    (3-4 cells across the equilibrium shock standoff)
  10 mm out    ~ 2 mm    (post-shock chemistry zone)
  100 mm out   ~ 8 mm
  1000 mm out  ~ 50 mm
  5 m out      ~ 200 mm
  total budget: 3-5M tets

Designed to drive RhoU < -2 from a M=22.5 cold start with AUSMPLUSM +
MUSCL + VAN_ALBADA_EDGE + accurate flux Jacobians + CFL=0.5. The
existing v8 phase1A 2.74M-tet mesh held drag Cauchy-converged at
1e-3 by iter 100 but RMS residual floored at -0.21 because of sub-cell
shock breathing. This mesh aims to give the shock front enough cells
to settle on a unique cell-aligned position.

Usage (gmsh required):
    python scripts/mesh_ram_c_v8_phase2.py
    # then
    python scripts/add_markers_su2.py \\
        --input data/cfd_cases_nemo/ram_c_v8_phase2/ram_c_domain_raw.su2 \\
        --output data/cfd_cases_nemo/ram_c_v8_phase2/ram_c_tagged.su2
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Fall back across the filenames the project has used historically
# (ram_c_domain.step on local, ram_c.step on the VM).
_STEP_CANDIDATES = [
    REPO / "data" / "cfd_cases_nemo" / "ram_c_small" / "ram_c_domain.step",
    REPO / "data" / "cfd_cases_nemo" / "ram_c_small" / "ram_c.step",
    REPO / "data" / "cfd_cases_nemo" / "ram_c" / "ram_c_domain.step",
    REPO / "data" / "cfd_cases_nemo" / "ram_c" / "ram_c.step",
]
STEP = next((p for p in _STEP_CANDIDATES if p.exists()), _STEP_CANDIDATES[0])

OUT_DIR = REPO / "data" / "cfd_cases_nemo" / "ram_c_v8_phase2"
OUT_RAW = OUT_DIR / "ram_c_domain_raw.su2"


def main():
    if not STEP.exists():
        print(f"ERROR: STEP geometry not found at {STEP}", file=sys.stderr)
        print("       Re-run mesh_ram_c_refined.py first to generate the "
              "STEP file.", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[v8_phase2] Loading gmsh", flush=True)
    import gmsh

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)

    print(f"[v8_phase2] Importing STEP: {STEP.name}", flush=True)
    gmsh.model.occ.importShapes(str(STEP))
    gmsh.model.occ.synchronize()

    surfaces = gmsh.model.getEntities(2)
    areas = sorted(
        ((tag, gmsh.model.occ.getMass(2, tag)) for _, tag in surfaces),
        key=lambda x: -x[1],
    )
    farfield_tag = areas[0][0]
    body_tags = [t for t, _ in areas[1:]]
    print(f"[v8_phase2] farfield surface tag={farfield_tag} "
          f"area={areas[0][1]:.2f} m^2", flush=True)
    print(f"[v8_phase2] body surface tags={body_tags} "
          f"areas={[round(a, 4) for _, a in areas[1:]]} m^2", flush=True)

    gmsh.model.addPhysicalGroup(2, body_tags, name="body")
    gmsh.model.addPhysicalGroup(2, [farfield_tag], name="farfield")
    volumes = gmsh.model.getEntities(3)
    gmsh.model.addPhysicalGroup(3, [t for _, t in volumes], name="fluid")

    print(f"[v8_phase2] Setting up size field stack (5 shells)", flush=True)
    df = gmsh.model.mesh.field.add("Distance")
    gmsh.model.mesh.field.setNumbers(df, "FacesList", body_tags)

    # Shell 1: 0 - 3 mm out from body (covers the bow-shock standoff).
    # 1 mm at wall, fine band so shock crossing has 3+ cells.
    s1 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s1, "InField", df)
    gmsh.model.mesh.field.setNumber(s1, "SizeMin", 0.001)    # 1 mm
    gmsh.model.mesh.field.setNumber(s1, "SizeMax", 0.001)
    gmsh.model.mesh.field.setNumber(s1, "DistMin", 0.0)
    gmsh.model.mesh.field.setNumber(s1, "DistMax", 0.003)
    gmsh.model.mesh.field.setNumber(s1, "StopAtDistMax", 1)

    # Shell 2: 3 - 10 mm (post-shock chemistry-equilibration zone)
    s2 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s2, "InField", df)
    gmsh.model.mesh.field.setNumber(s2, "SizeMin", 0.001)
    gmsh.model.mesh.field.setNumber(s2, "SizeMax", 0.002)    # 2 mm
    gmsh.model.mesh.field.setNumber(s2, "DistMin", 0.003)
    gmsh.model.mesh.field.setNumber(s2, "DistMax", 0.010)
    gmsh.model.mesh.field.setNumber(s2, "StopAtDistMax", 1)

    # Shell 3: 10 - 100 mm (afterbody plume region)
    s3 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s3, "InField", df)
    gmsh.model.mesh.field.setNumber(s3, "SizeMin", 0.002)
    gmsh.model.mesh.field.setNumber(s3, "SizeMax", 0.008)    # 8 mm
    gmsh.model.mesh.field.setNumber(s3, "DistMin", 0.010)
    gmsh.model.mesh.field.setNumber(s3, "DistMax", 0.100)
    gmsh.model.mesh.field.setNumber(s3, "StopAtDistMax", 1)

    # Shell 4: 100 mm - 1 m
    s4 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s4, "InField", df)
    gmsh.model.mesh.field.setNumber(s4, "SizeMin", 0.008)
    gmsh.model.mesh.field.setNumber(s4, "SizeMax", 0.050)    # 50 mm
    gmsh.model.mesh.field.setNumber(s4, "DistMin", 0.100)
    gmsh.model.mesh.field.setNumber(s4, "DistMax", 1.000)
    gmsh.model.mesh.field.setNumber(s4, "StopAtDistMax", 1)

    # Shell 5: 1 m - 5 m (far field)
    s5 = gmsh.model.mesh.field.add("Threshold")
    gmsh.model.mesh.field.setNumber(s5, "InField", df)
    gmsh.model.mesh.field.setNumber(s5, "SizeMin", 0.050)
    gmsh.model.mesh.field.setNumber(s5, "SizeMax", 0.200)
    gmsh.model.mesh.field.setNumber(s5, "DistMin", 1.000)
    gmsh.model.mesh.field.setNumber(s5, "DistMax", 5.000)

    bg = gmsh.model.mesh.field.add("Min")
    gmsh.model.mesh.field.setNumbers(bg, "FieldsList", [s1, s2, s3, s4, s5])
    gmsh.model.mesh.field.setAsBackgroundMesh(bg)

    # Disable curvature + boundary size influences so the field stack is
    # the sole driver. (Same convention as mesh_ram_c_refined.py.)
    gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 1)        # Delaunay
    gmsh.option.setNumber("Mesh.RandomFactor", 1e-6)
    # Optimization for tet quality at the wall — penalty for high
    # aspect-ratio cells in the inner shell where AUSMPLUSM is sensitive
    # to non-orthogonal connectivity.
    gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)

    print(f"[v8_phase2] Generating 3D mesh (this may take 10-30 min "
          f"at this resolution)", flush=True)
    t0 = time.time()
    gmsh.model.mesh.generate(3)
    dt = time.time() - t0

    n_nodes = len(gmsh.model.mesh.getNodes()[0])
    elements = gmsh.model.mesh.getElementsByType(4)
    n_tets = len(elements[0])
    print(f"[v8_phase2] Meshed in {dt:.1f}s: {n_nodes} nodes, {n_tets} tets",
          flush=True)

    if n_tets < 2_500_000:
        print(f"[v8_phase2] WARNING: tet count {n_tets} below 2.5M target — "
              f"shock may still be under-resolved", flush=True)
    elif n_tets > 6_000_000:
        print(f"[v8_phase2] WARNING: tet count {n_tets} above 6M — "
              f"SU2-NEMO preprocessing will be slow + disk pressure",
              flush=True)

    print(f"[v8_phase2] Writing {OUT_RAW}", flush=True)
    gmsh.write(str(OUT_RAW))
    gmsh.finalize()

    size_mb = OUT_RAW.stat().st_size / 1024 / 1024
    print(f"[v8_phase2] DONE: {OUT_RAW} ({size_mb:.1f} MB)", flush=True)
    print(f"[v8_phase2] Next steps:", flush=True)
    print(f"  1. python scripts/add_markers_su2.py "
          f"--input {OUT_RAW} --output {OUT_DIR}/ram_c_tagged.su2", flush=True)
    print(f"  2. cp scripts/configs/v8_phase2_cold.cfg "
          f"{OUT_DIR}/run.cfg", flush=True)
    print(f"  3. cd {OUT_DIR} && bash launch_su2_v8.sh", flush=True)


if __name__ == "__main__":
    main()
