"""Plot AIR-7 v7 chemistry development from the live history.csv.

Pulls the SU2-NEMO history.csv from the GCP VM (or reads a local copy) and
plots:
  1. Species residual evolution (Rho_e, Rho_NO+, Rho_N, Rho_O, Rho_NO,
     Rho_N2, Rho_O2) — shows when each species 'turned on'
  2. Bulk-flow residuals (RhoU, RhoV, RhoW, RhoE, RhoEve) — shows the
     limit-cycle behavior in RhoU
  3. Annotations marking 'chemistry developed' (Rho_NOp residual stops
     decreasing, ~iter 30) and 'limit cycle entered' (RhoU plateau)

Outputs:
  data/checkpoints/air7v7_chemistry_dev.png

Usage:
    python scripts/plot_air7_chemistry_dev.py
        # auto-pulls from VM via gcloud scp
    python scripts/plot_air7_chemistry_dev.py --local /path/to/history.csv
        # reads a local copy
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
VM_HISTORY = "/home/yarden/ram_c_runs/ramC_refined_air7v7_M10_0_A61/history.csv"


def pull_history_from_vm(local_path: Path) -> bool:
    cmd_str = (
        f'gcloud compute scp "openfoam-hgv:{VM_HISTORY}" "{local_path}" '
        f'--zone=us-central1-a'
    )
    try:
        result = subprocess.run(cmd_str, shell=True, capture_output=True,
                                text=True, timeout=120)
        return result.returncode == 0 and local_path.exists()
    except subprocess.TimeoutExpired:
        return False


def parse_history(path: Path) -> tuple[list[str], list[list[float]]]:
    rows = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = [h.strip().strip('"') for h in next(reader)]
        for row in reader:
            try:
                rows.append([float(x) for x in row])
            except ValueError:
                continue
    return header, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--local", type=Path, default=None,
                    help="Local history.csv (skip VM pull)")
    ap.add_argument("--output", type=Path,
                    default=REPO / "data" / "checkpoints" / "air7v7_chemistry_dev.png")
    ap.add_argument("--vm-stage", default="M10_0",
                    help="VM stage subdirectory M-tag (default M10_0). "
                         "Use M15_0, M18_0, M22_5 for later stages.")
    args = ap.parse_args()

    if args.local:
        history_path = args.local
    else:
        history_path = REPO / "data" / "tmp" / f"air7v7_{args.vm_stage}_history.csv"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        # Adjust VM path for the requested stage
        global VM_HISTORY
        VM_HISTORY = (f"/home/yarden/ram_c_runs/ramC_refined_air7v7_"
                      f"{args.vm_stage}_A61/history.csv")
        print(f"[plot] pulling {VM_HISTORY} from VM...")
        if not pull_history_from_vm(history_path):
            print(f"[plot] gcloud scp failed; using last cached copy if present",
                  file=sys.stderr)
            if not history_path.exists():
                sys.exit(1)

    header, rows = parse_history(history_path)
    if len(rows) < 2:
        print(f"[plot] history has only {len(rows)} data rows — too few "
              f"to plot. Check stage {args.vm_stage} is actually running.",
              file=sys.stderr)
        sys.exit(1)
    print(f"[plot] {len(rows)} iters, {len(header)} columns")

    import numpy as np
    import matplotlib.pyplot as plt

    data = np.array(rows)
    # Find columns by name (handle whitespace + quote inconsistency)
    def col(name: str) -> int:
        for i, h in enumerate(header):
            if h.strip() == name:
                return i
        raise ValueError(f"column '{name}' not in {header}")

    iter_idx = col("Inner_Iter")
    iters = data[:, iter_idx].astype(int)

    # AIR-7 species column names
    species_cols = {
        "Rho_e (electrons)": "rms[Rho_0]",
        "Rho_N2": "rms[Rho_1]",
        "Rho_O2": "rms[Rho_2]",
        "Rho_NO": "rms[Rho_3]",
        "Rho_N": "rms[Rho_4]",
        "Rho_O": "rms[Rho_5]",
        "Rho_NO+ (cation)": "rms[Rho_6]",
    }
    bulk_cols = {
        "RhoU (momentum-x)": "rms[RhoU]",
        "RhoV (momentum-y)": "rms[RhoV]",
        "RhoW (momentum-z)": "rms[RhoW]",
        "RhoE (total energy)": "rms[RhoE]",
        "RhoEve (V-E energy)": "rms[RhoEve]",
    }

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

    # Plot species
    for label, name in species_cols.items():
        try:
            ax1.plot(iters, data[:, col(name)], label=label, lw=1.5)
        except ValueError as e:
            print(f"[plot] skip {label}: {e}")

    ax1.set_ylabel("log10(species residual)")
    ax1.set_title(
        f"AIR-7 v7 chemistry development — stage {args.vm_stage} "
        f"({len(rows)} iters)"
    )
    ax1.legend(loc="lower right", fontsize=8, ncol=2)
    ax1.grid(True, alpha=0.3)
    ax1.axhline(-32, ls=":", c="gray", lw=0.8, label="machine zero")

    # Annotate when ions "turn on"
    rho_e = data[:, col("rms[Rho_0]")]
    rho_NOp = data[:, col("rms[Rho_6]")]
    # Find first iter where Rho_e > -25 (escaped machine zero)
    on_idx = np.where(rho_e > -25)[0]
    if len(on_idx) > 0:
        ax1.axvline(iters[on_idx[0]], ls="--", c="red", lw=0.8, alpha=0.5)
        ax1.text(iters[on_idx[0]] + 1, -28,
                 f"chemistry on\n(iter {iters[on_idx[0]]})",
                 fontsize=8, color="red")

    # Plot bulk
    for label, name in bulk_cols.items():
        try:
            ax2.plot(iters, data[:, col(name)], label=label, lw=1.5)
        except ValueError as e:
            print(f"[plot] skip {label}: {e}")
    ax2.set_xlabel("Iter")
    ax2.set_ylabel("log10(bulk residual)")
    ax2.legend(loc="upper right", fontsize=8, ncol=2)
    ax2.grid(True, alpha=0.3)

    # Annotate limit cycle floor for RhoU
    rhoU = data[:, col("rms[RhoU]")]
    if len(rhoU) > 50:
        # Limit cycle floor = mean of last 30% of iters
        tail = rhoU[int(0.7 * len(rhoU)):]
        floor = float(np.mean(tail))
        ax2.axhline(floor, ls=":", c="purple", lw=1.0, alpha=0.7)
        ax2.text(iters[-1] * 0.5, floor + 0.05,
                 f"RhoU limit cycle: {floor:.2f}", fontsize=8, color="purple")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(args.output, dpi=120, bbox_inches="tight")
    print(f"[plot] wrote {args.output}")


if __name__ == "__main__":
    main()
