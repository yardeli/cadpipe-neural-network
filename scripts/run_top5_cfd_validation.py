"""S-5 Phase 4 — emit SU2-NEMO MPI cfg files for top-5 search candidates.

This script DOES NOT EXECUTE SU2 — it only generates cfg files and prints
the launch commands. The CFD runs are deferred until the v7 AIR-7 ramp
finishes (don't compete for VM CPU + memory).

Pipeline:
  search_v4_top50.jsonl  →  top 5 by Cantera-verified score
                         ↓
  base_cfg_template.cfg  →  per-mechanism cfg with GAS_MODEL/FLUID_MODEL/
                            GAS_COMPOSITION overridden, mesh + flight
                            conditions inherited
                         ↓
  /home/yarden/ram_c_runs/search_v4_top5/cand_{i}_{nrxn}rxn/run.cfg
                         ↓
  Launch (MANUALLY, after v7 done):
      cd cand_0_8rxn && mpirun -np 16 /opt/su2-nemo-mpi/bin/SU2_CFD run.cfg

Run:
    cd /home/yarden/plasmanet && PYTHONPATH=. python3 -u \\
        scripts/run_top5_cfd_validation.py
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shortlist", type=Path,
                    default=Path("/home/yarden/mechanism_search_results/"
                                 "search_v4_top50.jsonl"),
                    help="Cantera-verified top-50 from BO search (Phase 3 output)")
    ap.add_argument("--out-dir", type=Path,
                    default=Path("/home/yarden/ram_c_runs/search_v4_top5"),
                    help="Where to drop the per-candidate cfg directories")
    ap.add_argument("--base-cfg", type=Path,
                    default=Path("/home/yarden/ram_c_runs/"
                                 "ramC_refined_air7v7b_ramp_A61/run.cfg"),
                    help="Base SU2 cfg to copy + override (uses v7 AIR-7 ramp "
                         "settings as the proven-good baseline)")
    ap.add_argument("--mesh", type=Path,
                    default=Path("/home/yarden/ram_c_runs/"
                                 "ramC_refined_air7v7b_ramp_A61/mesh.su2"),
                    help="Mesh file (will be symlinked into each candidate dir)")
    ap.add_argument("--top-k", type=int, default=5,
                    help="How many candidates to emit (default 5)")
    ap.add_argument("--rank-by", default="score_cantera",
                    choices=["score_cantera", "score_surrogate"],
                    help="Which score column to rank by; Cantera-verified is "
                         "the trustworthy one")
    args = ap.parse_args()

    if not args.shortlist.exists():
        print(f"ERROR: shortlist {args.shortlist} does not exist.")
        print("  Run Phase 3 first (other instance — see "
              "docs/PROMPT_NEXT_INSTANCE_2026-04-26.md).")
        return 1

    # ── Load + rank
    candidates = []
    with open(args.shortlist) as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))
    print(f"Loaded {len(candidates)} candidates from {args.shortlist}")

    candidates.sort(key=lambda c: c.get(args.rank_by, float("inf")))
    top = candidates[:args.top_k]
    print(f"Top {len(top)} by {args.rank_by}:")
    for i, c in enumerate(top):
        rxn_ids = c.get("reaction_ids", [])
        print(f"  #{i}: nrxn={len(rxn_ids)} "
              f"score_cantera={c.get('score_cantera', '?')} "
              f"ne_cantera={c.get('ne_cantera_m3', '?'):.2e} "
              f"ne_surrogate={c.get('ne_surrogate_m3', '?'):.2e}")

    # ── Sanity: base files exist
    if not args.base_cfg.exists():
        print(f"ERROR: base cfg {args.base_cfg} missing. "
              f"Run after v7 ramp script writes the canonical cfg.")
        return 1
    if not args.mesh.exists():
        print(f"WARN: mesh {args.mesh} missing — will need to copy in manually.")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Late-import so PYTHONPATH must include repo root
    from plasmanet.mechanism_search import PARK_47

    base_cfg_text = args.base_cfg.read_text()

    launch_cmds = []
    for i, c in enumerate(top):
        rxn_ids = c.get("reaction_ids", [])
        if not rxn_ids:
            print(f"  skip #{i}: empty reaction_ids")
            continue
        mech = PARK_47.subset(reaction_ids=rxn_ids)
        mech.name = f"cand_{i}_{len(rxn_ids)}rxn"

        cand_dir = args.out_dir / mech.name
        cand_dir.mkdir(exist_ok=True)

        try:
            su2_keys = mech.to_su2_cfg_snippet()
        except ValueError as e:
            # Mechanism doesn't map to a v7.5.1-supported gas model
            # (e.g. partial AIR-7 species). Save a note + skip.
            (cand_dir / "SKIPPED.txt").write_text(
                f"Cannot map to SU2 v7.5.1 built-in gas model: {e}\n"
                f"Reaction IDs: {rxn_ids}\n"
                f"Species: {mech.species}\n"
            )
            print(f"  skip #{i}: {e}")
            continue

        # Override the gas-model lines in the base cfg
        cfg_text = _override_gas_model_lines(base_cfg_text, su2_keys)
        cfg_text = _annotate_header(cfg_text, c, mech, rxn_ids)
        (cand_dir / "run.cfg").write_text(cfg_text)

        # Symlink mesh in (avoid copying GB-sized files 5×)
        mesh_link = cand_dir / args.mesh.name
        if not mesh_link.exists():
            try:
                mesh_link.symlink_to(args.mesh.resolve())
            except OSError:
                shutil.copy(args.mesh, mesh_link)

        # Mechanism YAML for downstream Cantera comparison
        (cand_dir / "mechanism.yaml").write_text(mech.to_cantera_yaml())
        (cand_dir / "candidate_meta.json").write_text(json.dumps({
            "rank": i,
            "reaction_ids": rxn_ids,
            "n_reactions": len(rxn_ids),
            "species": mech.species,
            "ne_cantera_m3": c.get("ne_cantera_m3"),
            "ne_surrogate_m3": c.get("ne_surrogate_m3"),
            "score_cantera": c.get("score_cantera"),
            "score_surrogate": c.get("score_surrogate"),
        }, indent=2))

        launch_cmds.append(
            f"cd {cand_dir} && mpirun -np 16 /opt/su2-nemo-mpi/bin/SU2_CFD "
            f"run.cfg 2>&1 | tee su2.log"
        )
        print(f"  emitted #{i} → {cand_dir}/run.cfg")

    # ── Launch script
    launch_sh = args.out_dir / "LAUNCH_AFTER_V7_DONE.sh"
    launch_sh.write_text(
        "#!/bin/bash\n"
        "# DO NOT RUN until v7 ramp finishes (PID may differ).\n"
        "# Each candidate is ~12-24h on 16 cores. Run sequentially OR in tmux.\n"
        "set -euo pipefail\n\n"
        + "\n\n".join(launch_cmds) + "\n"
    )
    launch_sh.chmod(0o755)

    print(f"\nWrote {len(launch_cmds)} launch commands to {launch_sh}")
    print("DO NOT RUN until v7 finishes (PID 215175 on VM, M=22.5 stage pending).")
    return 0


def _override_gas_model_lines(cfg_text: str, su2_keys: dict) -> str:
    """Replace GAS_MODEL / FLUID_MODEL / GAS_COMPOSITION in a SU2 cfg.

    SU2 cfg format: KEY= VALUE, one per line. We do a line-wise scan
    rather than regex-replace to preserve whitespace and comments.
    """
    targets = {
        "GAS_MODEL": su2_keys["GAS_MODEL"],
        "FLUID_MODEL": su2_keys["FLUID_MODEL"],
        "GAS_COMPOSITION": su2_keys["GAS_COMPOSITION"],
    }
    out_lines = []
    seen = set()
    for line in cfg_text.splitlines():
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("%"):
            key = stripped.split("=", 1)[0].strip()
            if key in targets:
                out_lines.append(f"{key}= {targets[key]}")
                seen.add(key)
                continue
        out_lines.append(line)
    # If any target wasn't in the base cfg, append it (with a marker comment)
    for key, val in targets.items():
        if key not in seen:
            out_lines.append(f"% added by run_top5_cfd_validation.py:")
            out_lines.append(f"{key}= {val}")
    return "\n".join(out_lines) + "\n"


def _annotate_header(cfg_text: str, candidate: dict, mech, rxn_ids: list) -> str:
    """Prepend a comment block describing this candidate's provenance."""
    header = (
        f"% ─────────────────────────────────────────────────────────────────\n"
        f"% Auto-generated by scripts/run_top5_cfd_validation.py\n"
        f"% Mechanism: {mech.name}\n"
        f"% Reactions ({len(rxn_ids)}): {rxn_ids}\n"
        f"% Species: {mech.species}\n"
        f"% ne_cantera_m3:    {candidate.get('ne_cantera_m3', '?')}\n"
        f"% ne_surrogate_m3:  {candidate.get('ne_surrogate_m3', '?')}\n"
        f"% score_cantera:    {candidate.get('score_cantera', '?')}\n"
        f"% Source: search_v4_top50 ranked by Cantera-verified score.\n"
        f"% ─────────────────────────────────────────────────────────────────\n"
    )
    return header + cfg_text


if __name__ == "__main__":
    import sys
    sys.exit(main())
