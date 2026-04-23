"""Generate a NEMO batch directory from the existing Euler batch manifest.

Takes the manifest.json used for the SU2 Euler runs and produces a parallel
directory tree of NEMO configs. Each case gets run.cfg written via
plasmanet.nemo_config.write_nemo_config() and the mesh copied in.

Usage (local):
    python scripts/generate_nemo_batch.py \\
        --manifest data/cfd_cases/manifest.json \\
        --output-root data/cfd_cases_nemo \\
        --mesh-root data/cfd_cases \\
        --gas-model AIR-5

Then scp the resulting tree to the VM and run scripts/run_nemo_batch.sh.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from plasmanet.nemo_config import write_nemo_config


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, help="manifest.json from Euler batch")
    ap.add_argument("--output-root", required=True, help="Directory for NEMO case tree")
    ap.add_argument("--mesh-root", required=True, help="Directory containing geometry meshes")
    ap.add_argument("--gas-model", default="AIR-5",
                    help="AIR-5 | AIR-7 | air_5 | air_11 (default AIR-5, built-in)")
    ap.add_argument("--iters", type=int, default=2000)
    ap.add_argument("--cfl", type=float, default=1.0)
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text())
    out_root = Path(args.output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    # Build geometry → mesh filename map
    geom_to_mesh = {}
    for g in manifest.get("geometries", []):
        geom_to_mesh[g["name"]] = Path(args.mesh_root, g["mesh"])

    # Count geometries for reporting
    print(f"Generating NEMO batch under {out_root}")
    print(f"  Gas model: {args.gas_model}")
    print(f"  Iters: {args.iters}, CFL: {args.cfl}")
    print()

    n_written = 0
    for case in manifest.get("cases", []):
        geom = case["geometry"]
        mach = case["mach"]
        alt = case["alt"]
        case_name = f"{geom}_M{mach}_A{alt}"
        case_dir = out_root / case_name
        case_dir.mkdir(exist_ok=True)

        # Write config
        cfg_path = case_dir / "run.cfg"
        mesh_fn = Path(geom_to_mesh.get(geom, f"{geom}_domain.su2")).name
        write_nemo_config(
            path=str(cfg_path),
            mach=mach, altitude_km=alt,
            gas_model=args.gas_model,
            mesh_filename=mesh_fn,
            iters=args.iters,
            cfl=args.cfl,
        )

        # Copy mesh
        src_mesh = Path(args.mesh_root) / geom / f"{geom}_domain.su2"
        if src_mesh.exists():
            dst_mesh = case_dir / mesh_fn
            if not dst_mesh.exists():
                shutil.copy(src_mesh, dst_mesh)
        else:
            print(f"  WARN: mesh not found for {geom}: {src_mesh}")

        n_written += 1

    print(f"Wrote {n_written} NEMO cases to {out_root}")
    print()
    print(f"To run on VM:")
    print(f"  gcloud compute scp --recurse {out_root} openfoam-hgv:~/plasmanet_cfd_nemo --zone=us-central1-a")
    print(f"  gcloud compute ssh openfoam-hgv --zone=us-central1-a --command 'chmod +x scripts/run_nemo_batch.sh && scripts/run_nemo_batch.sh'")


if __name__ == "__main__":
    main()
