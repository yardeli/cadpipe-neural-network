"""Convert a meshgen-generated gmsh .msh file to SU2 format for NEMO.

meshgen produces a mesh with the body surface split into multiple patches
(body_wall_000, body_wall_001, ...) to let users refine individual
surfaces. For SU2-NEMO we want one 'body' marker for Euler wall BC.
This script:
  1. Reads the gmsh .msh
  2. Merges all body_wall_* physical groups into a single 'body' group
  3. Merges inlet + outlet + farfield into a single 'farfield' group
     (SU2_NEMO uses one MARKER_FAR for all incoming/outgoing boundaries)
  4. Writes as .su2 format
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, help="Input gmsh .msh file")
    ap.add_argument("--output", required=True, help="Output SU2 .su2 file")
    ap.add_argument("--body-prefix", default="body_wall_",
                    help="Prefix identifying body-surface patches to merge")
    ap.add_argument("--farfield-names", nargs="+",
                    default=["inlet", "outlet", "farfield"],
                    help="Physical-group names to merge into 'farfield'")
    args = ap.parse_args()

    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.open(args.input)

    # Inspect physical groups
    groups = gmsh.model.getPhysicalGroups()
    print("Physical groups in input:")
    group_info = []  # list of (dim, tag, name, entities)
    for dim, tag in groups:
        name = gmsh.model.getPhysicalName(dim, tag)
        entities = gmsh.model.getEntitiesForPhysicalGroup(dim, tag)
        group_info.append((dim, tag, name, list(entities)))
        print(f"  dim={dim} tag={tag} name='{name}' entities={len(entities)}")

    # Identify which entities belong to body vs farfield
    body_entities = set()
    farfield_entities = set()
    fluid_entities = set()
    for dim, tag, name, entities in group_info:
        if dim == 2 and name.startswith(args.body_prefix):
            body_entities.update(entities)
        elif dim == 2 and name in args.farfield_names:
            farfield_entities.update(entities)
        elif dim == 3:
            fluid_entities.update(entities)

    print(f"\nMerged groups:")
    print(f"  body:     {len(body_entities)} surface entities")
    print(f"  farfield: {len(farfield_entities)} surface entities")
    print(f"  fluid:    {len(fluid_entities)} volume entities")

    if not body_entities:
        print("ERROR: no body surfaces found (looked for prefix "
              f"'{args.body_prefix}')", file=sys.stderr)
        sys.exit(1)

    # Remove all existing physical groups, add merged ones
    for dim, tag in groups:
        gmsh.model.removePhysicalGroups([(dim, tag)])

    gmsh.model.addPhysicalGroup(2, list(body_entities), name="body")
    gmsh.model.addPhysicalGroup(2, list(farfield_entities), name="farfield")
    gmsh.model.addPhysicalGroup(3, list(fluid_entities), name="fluid")

    gmsh.model.geo.synchronize()

    # Write SU2 format
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    gmsh.write(str(out))

    # Stats
    nodes = gmsh.model.mesh.getNodes()
    elements = gmsh.model.mesh.getElements(3)
    n_tets = sum(len(tags) for tags in elements[1])
    print(f"\nWrote {out} — {len(nodes[0])} nodes, {n_tets} volumetric elements")
    gmsh.finalize()


if __name__ == "__main__":
    main()
