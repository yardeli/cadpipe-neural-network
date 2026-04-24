"""Post-process a raw SU2 mesh (produced by gmsh CLI with no physical groups)
to add body/farfield markers by classifying boundary faces by distance.

gmsh CLI produces clean meshes fast but doesn't preserve physical-group
info from a STEP import. This script inspects boundary faces (faces belonging
to only one volume cell) and tags them:

  body     = boundary face whose centroid is within 1 m of origin (vehicle)
  farfield = boundary face whose centroid is farther than 1 m (outer sphere)

Writes a new SU2 file with NMARK=2 and MARKER_TAG= body / farfield.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np


SU2_ELEM_NODE_COUNT = {
    3: 2,   # line
    5: 3,   # triangle
    9: 4,   # quad
    10: 4,  # tet
    12: 8,  # hex
    13: 6,  # wedge/prism
    14: 5,  # pyramid
}

# Tet faces (local node indices into the tet's 4 nodes)
TET_FACES = [(0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--body-radius-m", type=float, default=2.0,
                    help="Face centroids closer than this to origin → body")
    args = ap.parse_args()

    # Parse the SU2 file
    print(f"Reading {args.input}")
    with open(args.input) as f:
        lines = f.read().splitlines()

    # Find NELEM, NPOIN
    i = 0
    ndim = None
    nelem = None
    npoin = None
    while i < len(lines):
        L = lines[i].strip()
        if L.startswith("NDIME="):
            ndim = int(L.split("=")[1])
        elif L.startswith("NELEM="):
            nelem = int(L.split("=")[1])
            elem_start = i + 1
            break
        i += 1

    print(f"  NDIM={ndim}, NELEM={nelem}")

    # Read volume elements
    tets = []
    i = elem_start
    for _ in range(nelem):
        parts = lines[i].split()
        etype = int(parts[0])
        if etype == 10:   # tet
            tets.append([int(x) for x in parts[1:5]])
        i += 1

    # Find NPOIN
    while i < len(lines) and not lines[i].strip().startswith("NPOIN="):
        i += 1
    npoin = int(lines[i].split("=")[1])
    point_start = i + 1
    print(f"  NPOIN={npoin}, tets={len(tets)}")

    # Read points
    points = np.zeros((npoin, 3))
    for k in range(npoin):
        parts = lines[point_start + k].split()
        points[k, 0] = float(parts[0])
        points[k, 1] = float(parts[1])
        points[k, 2] = float(parts[2])
    print(f"  Read {npoin} points, bbox: "
          f"x[{points[:,0].min():.2f}, {points[:,0].max():.2f}] "
          f"y[{points[:,1].min():.2f}, {points[:,1].max():.2f}] "
          f"z[{points[:,2].min():.2f}, {points[:,2].max():.2f}]")

    # Find boundary faces: for each tet, each face is shared between
    # at most 2 tets. Faces appearing only once are boundary faces.
    face_count = defaultdict(int)  # sorted node tuple → count
    face_owner = {}                # sorted tuple → (tet_idx, local_face_idx, face_in_order)

    for ti, tet in enumerate(tets):
        for f, face_nodes in enumerate(TET_FACES):
            face = tuple(sorted([tet[n] for n in face_nodes]))
            face_count[face] += 1
            if face not in face_owner:
                # Store the ORIGINAL (unsorted) face node order so normals are right
                face_owner[face] = [tet[n] for n in face_nodes]

    boundary_faces = [face_owner[f] for f, c in face_count.items() if c == 1]
    print(f"  Found {len(boundary_faces)} boundary faces out of "
          f"{sum(face_count.values())} total face sides")

    # Classify each boundary face
    body_faces = []
    farfield_faces = []
    R = args.body_radius_m
    for face in boundary_faces:
        centroid = (points[face[0]] + points[face[1]] + points[face[2]]) / 3
        r = np.linalg.norm(centroid)
        if r < R:
            body_faces.append(face)
        else:
            farfield_faces.append(face)

    print(f"  Classification (R_body = {R} m):")
    print(f"    body faces:     {len(body_faces)}")
    print(f"    farfield faces: {len(farfield_faces)}")

    if len(body_faces) == 0 or len(farfield_faces) == 0:
        print(f"ERROR: one marker got 0 faces. Adjust --body-radius-m.",
              file=sys.stderr)
        sys.exit(1)

    # Write new SU2 file
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write(f"NDIME= {ndim}\n")
        f.write(f"NELEM= {len(tets)}\n")
        for ti, tet in enumerate(tets):
            f.write(f"10 {tet[0]} {tet[1]} {tet[2]} {tet[3]} {ti}\n")
        f.write(f"NPOIN= {npoin}\n")
        for k in range(npoin):
            f.write(f"{points[k,0]:.10e} {points[k,1]:.10e} {points[k,2]:.10e} {k}\n")
        f.write(f"NMARK= 2\n")
        f.write(f"MARKER_TAG= body\n")
        f.write(f"MARKER_ELEMS= {len(body_faces)}\n")
        for face in body_faces:
            f.write(f"5 {face[0]} {face[1]} {face[2]}\n")
        f.write(f"MARKER_TAG= farfield\n")
        f.write(f"MARKER_ELEMS= {len(farfield_faces)}\n")
        for face in farfield_faces:
            f.write(f"5 {face[0]} {face[1]} {face[2]}\n")

    size_mb = out.stat().st_size / 1024 / 1024
    print(f"  Wrote {out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
