"""Convert a meshgen gmsh .msh to SU2 format via meshio.

meshio's SU2 writer is more conservative about face/volume topology than
gmsh's (which is what caused the "surface element doesn't have an
associated volume element" errors on the first attempt). This is a
last-resort for SU2 to consume hex-dominant OpenFOAM-derived meshes.

Merges all body_wall_* physical groups into a single 'body' marker.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--body-prefix", default="body_wall_")
    ap.add_argument("--farfield-names", nargs="+",
                    default=["inlet", "outlet", "farfield"])
    args = ap.parse_args()

    import meshio
    import numpy as np

    m = meshio.read(args.input)

    # Build group: physical-id → new-marker-name
    id_to_marker = {}
    for pg_name, (pg_id, pg_dim) in m.field_data.items():
        if pg_name.startswith(args.body_prefix):
            id_to_marker[pg_id] = "body"
        elif pg_name in args.farfield_names:
            id_to_marker[pg_id] = "farfield"
        elif pg_dim == 3:
            id_to_marker[pg_id] = "fluid"
        else:
            id_to_marker[pg_id] = pg_name  # keep others

    # Collect volume cells (tets + hexes + prisms)
    vol_types = {"tetra", "hexahedron", "wedge", "pyramid"}
    bdry_types = {"triangle", "quad"}

    vol_blocks = []
    # For each unique marker, collect surface cells with their type
    bdry_groups = {}  # marker_name → list[(type, cells_array)]

    # meshio cell_data_dict has gmsh:physical → per-block lists
    phys_data = m.cell_data_dict.get("gmsh:physical", {})

    for i, block in enumerate(m.cells):
        if block.type in vol_types:
            vol_blocks.append(block)
        elif block.type in bdry_types:
            # Look up physical group for this block
            if block.type not in phys_data:
                continue
            # phys_data[block.type] is an array over blocks; we need per-cell
            pdata = phys_data[block.type]
            # But meshio stores it per-cell within the block already
            # It's a single integer per cell in this block (if all same physical)
            # For simplicity, assume all cells in a block share same physical
            if len(pdata) == 0:
                continue
            # phys_data[block.type] is list of arrays, one per block of that type
            # Find the position of this block among blocks of its type
            block_of_type_idx = sum(
                1 for b in m.cells[:i] if b.type == block.type
            )
            cell_phys_ids = pdata[block_of_type_idx]
            # Assume all cells in the block share the same physical group
            phys_id = int(cell_phys_ids[0])
            marker_name = id_to_marker.get(phys_id, f"marker_{phys_id}")
            bdry_groups.setdefault(marker_name, []).append(
                (block.type, block.data))

    # Counts
    print("Volume blocks:")
    for b in vol_blocks:
        print(f"  {b.type}: {len(b.data)}")
    print("Boundary groups:")
    for name, items in bdry_groups.items():
        counts = {t: c.shape[0] for t, c in items}
        print(f"  {name}: {counts}")

    # Write SU2 format manually (meshio's SU2 writer is fragile)
    _write_su2(args.output, m.points, vol_blocks, bdry_groups)
    print(f"\nWrote {args.output}")


# SU2 element type IDs (VTK convention per SU2 docs)
SU2_TYPE_IDS = {
    "line": 3,
    "triangle": 5,
    "quad": 9,
    "tetra": 10,
    "hexahedron": 12,
    "wedge": 13,       # prism
    "pyramid": 14,
}


def _write_su2(path, points, vol_blocks, bdry_groups):
    """Write a SU2 ASCII mesh with the given cells and markers."""
    n_points = len(points)
    n_vol = sum(len(b.data) for b in vol_blocks)
    n_markers = len(bdry_groups)

    with open(path, "w") as f:
        f.write(f"NDIME= 3\n")
        f.write(f"NELEM= {n_vol}\n")
        # Volume elements
        idx = 0
        for b in vol_blocks:
            t = SU2_TYPE_IDS[b.type]
            for cell in b.data:
                nodes = " ".join(str(int(n)) for n in cell)
                f.write(f"{t} {nodes} {idx}\n")
                idx += 1
        # Points
        f.write(f"NPOIN= {n_points}\n")
        for i, p in enumerate(points):
            f.write(f"{p[0]:.10e} {p[1]:.10e} {p[2]:.10e} {i}\n")
        # Markers
        f.write(f"NMARK= {n_markers}\n")
        for name, items in bdry_groups.items():
            n_bdry = sum(c.shape[0] for _, c in items)
            f.write(f"MARKER_TAG= {name}\n")
            f.write(f"MARKER_ELEMS= {n_bdry}\n")
            for etype, cells in items:
                t = SU2_TYPE_IDS[etype]
                for cell in cells:
                    nodes = " ".join(str(int(n)) for n in cell)
                    f.write(f"{t} {nodes}\n")


if __name__ == "__main__":
    main()
