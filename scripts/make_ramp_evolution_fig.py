"""Multi-stage Mach-ramp evolution figure for the paper.

Reads N stage VTUs (e.g., M10, M15, M18, M22.5) and produces two
publication-grade figures:

  1. ramp_evolution_stag.png — 4-panel summary plot:
       - T_tr (stagnation, log-y) vs Mach, with T_ve overlaid for NEQ delta
       - p_stag vs Mach, with Rayleigh perfect-gas analytical curve
       - Peak ne in domain vs Mach (top-50 robust + single-cell max)
       - Cell-count breakdown (cells with ne > 1e17/1e18/1e19)
       Annotates the M22.5 / 61 km point with the J&C 1972 reference
       value and the NEMO log10 error if --validation-json is supplied.

  2. ramp_evolution_contours.png — N-column contour figure:
       Top row:    T_tr scatter in symmetry-plane (xz, y≈0 slab)
       Bottom row: ne scatter (log color scale) in same slab
       Each column = one Mach number; colorbars per row.

Usage:
    python scripts/make_ramp_evolution_fig.py \\
        --vtu data/nemo_test/ramC_refined_M10_0_A61_nemo.vtu:10 \\
        --vtu data/nemo_test/ramC_refined_M15_0_A61_nemo.vtu:15 \\
        --vtu data/nemo_test/ramC_refined_M18_0_A61_nemo.vtu:18 \\
        --output-dir docs/paper/figures
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

from plasmanet.cfd_field import extract_nemo_field

# RAM-C 61 km reference (Jones & Cross 1972) — for annotating the M22.5 point
RAMC_61KM_NE_REF = 2.0e19
RAMC_61KM_NE_LO  = 1.0e19
RAMC_61KM_NE_HI  = 4.0e19


def rayleigh_pitot_pressure(mach: float, p_inf: float, gamma: float = 1.4) -> float:
    """Analytical perfect-gas Rayleigh pitot pressure ratio."""
    M2 = mach * mach
    ratio = ((gamma + 1) * M2 / 2) ** (gamma / (gamma - 1)) * \
            ((gamma + 1) / (2 * gamma * M2 - (gamma - 1))) ** (1 / (gamma - 1))
    return p_inf * ratio


def collect_stage_data(vtu_path: Path, mach: float, alt_km: float):
    """Extract NEMO fields + summary metrics for one stage."""
    cfd = extract_nemo_field(str(vtu_path), geometry="ram_c",
                             mach=mach, altitude_km=alt_km, verbose=False)
    sp = cfd.stag_point
    ne = cfd.ne_m3
    n_top = max(min(50, cfd.n_points // 1000), 1)
    top_idx = np.argpartition(ne, -n_top)[-n_top:]
    return {
        "mach": mach,
        "n_points": cfd.n_points,
        "T_tr_stag": sp["T_K"],
        "T_ve_stag": sp["T_ve_K"],
        "p_stag": sp["p_Pa"],
        "ne_stag": sp["ne_m3"],
        "ne_peak_top50": float(np.mean(ne[top_idx])),
        "ne_peak_max": float(ne.max()),
        "n_cells_ne_gt_1e17": int((ne > 1e17).sum()),
        "n_cells_ne_gt_1e18": int((ne > 1e18).sum()),
        "n_cells_ne_gt_1e19": int((ne > 1e19).sum()),
        "coords": cfd.coordinates,
        "T_tr_field": cfd.T_K,
        "ne_field": ne,
    }


def fig_stagnation_summary(stages, out_path: Path):
    """4-panel stagnation summary across the ramp."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    machs = np.array([s["mach"] for s in stages])

    # Panel 1: Stagnation temperatures
    ax = axes[0, 0]
    T_tr = [s["T_tr_stag"] for s in stages]
    T_ve = [s["T_ve_stag"] for s in stages]
    ax.plot(machs, T_tr, "o-", color="#dc2626", linewidth=2, markersize=8,
            label="T_tr (translational-rotational)")
    ax.plot(machs, T_ve, "s-", color="#2563eb", linewidth=2, markersize=8,
            label="T_ve (vibrational-electronic)")
    ax.fill_between(machs, T_ve, T_tr, alpha=0.15, color="purple",
                    label="NEQ delta")
    ax.set_xlabel("Mach number")
    ax.set_ylabel("Stagnation T (K)")
    ax.set_title("Stagnation temperatures — two-temperature NEQ")
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9, loc="upper left")

    # Panel 2: Stagnation pressure with Rayleigh analytical
    ax = axes[0, 1]
    p_stag = np.array([s["p_stag"] for s in stages])
    p_inf = 253.7116  # 61 km US std atmosphere
    rayleigh = np.array([rayleigh_pitot_pressure(m, p_inf) for m in machs])
    ax.semilogy(machs, p_stag, "o-", color="#16a34a", linewidth=2, markersize=8,
                label="NEMO stagnation pressure")
    ax.semilogy(machs, rayleigh, "--", color="gray", linewidth=1.5,
                label="Rayleigh perfect-gas (analytical)")
    ax.set_xlabel("Mach number")
    ax.set_ylabel("p_stag (Pa, log scale)")
    ax.set_title("Stagnation pressure vs analytical")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="lower right")

    # Panel 3: Peak ne in domain
    ax = axes[1, 0]
    ne_top50 = [s["ne_peak_top50"] for s in stages]
    ne_max = [s["ne_peak_max"] for s in stages]
    ax.semilogy(machs, ne_top50, "o-", color="#3b82f6", linewidth=2, markersize=8,
                label="Top-50 mean (robust peak)")
    ax.semilogy(machs, ne_max, "x--", color="#ef4444", linewidth=1.5, markersize=10,
                label="Single-cell max")
    # J&C 1972 reference at M22.5 only
    ax.axhline(RAMC_61KM_NE_REF, color="green", linestyle=":", linewidth=1.5,
               alpha=0.7, label=f"J&C 1972 M22.5/61km = {RAMC_61KM_NE_REF:.1e}")
    ax.fill_between([machs.min() - 1, machs.max() + 1],
                    RAMC_61KM_NE_LO, RAMC_61KM_NE_HI,
                    color="green", alpha=0.08)
    ax.set_xlim(machs.min() - 1, machs.max() + 1)
    ax.set_xlabel("Mach number")
    ax.set_ylabel("Electron density n_e (m^-3, log scale)")
    ax.set_title("Peak n_e in domain — stage-by-stage progression")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="lower right")

    # Panel 4: Sheath resolution (cell counts at thresholds)
    ax = axes[1, 1]
    width = 0.25
    x = np.arange(len(stages))
    n17 = [s["n_cells_ne_gt_1e17"] for s in stages]
    n18 = [s["n_cells_ne_gt_1e18"] for s in stages]
    n19 = [s["n_cells_ne_gt_1e19"] for s in stages]
    ax.bar(x - width, n17, width, label="n_e > 1e17", color="#fbbf24")
    ax.bar(x,         n18, width, label="n_e > 1e18", color="#f59e0b")
    ax.bar(x + width, n19, width, label="n_e > 1e19", color="#dc2626")
    ax.set_xticks(x)
    ax.set_xticklabels([f"M{m}" for m in machs])
    ax.set_xlabel("Ramp stage")
    ax.set_ylabel("Cell count in plasma threshold")
    ax.set_title("Sheath resolution per stage")
    ax.set_yscale("log")
    ax.grid(True, alpha=0.3, which="both", axis="y")
    ax.legend(fontsize=9)

    fig.suptitle("RAM-C refined-mesh Mach ramp — stagnation evolution",
                 fontsize=14, y=1.00)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_path.name}")


def fig_contour_panels(stages, out_path: Path):
    """N-column contour figure: T_tr top row, ne bottom row."""
    n_stages = len(stages)
    fig, axes = plt.subplots(2, n_stages, figsize=(4 * n_stages, 7))
    if n_stages == 1:
        axes = axes.reshape(2, 1)

    # Window around the body
    xlim = (-0.1, 0.7)
    zlim = (-0.4, 0.4)
    dy = 0.02

    # Pre-compute global vmin/vmax for consistent color scales across stages
    T_max = max(s["T_tr_field"].max() for s in stages)
    ne_max = max(s["ne_field"].max() for s in stages)
    T_max = max(T_max, 5000)
    ne_floor = 1e15

    for col, s in enumerate(stages):
        x = s["coords"][:, 0]; y = s["coords"][:, 1]; z = s["coords"][:, 2]
        T = s["T_tr_field"]; ne = s["ne_field"]
        slab = np.abs(y) < dy
        in_win = slab & (x >= xlim[0]) & (x <= xlim[1]) & (z >= zlim[0]) & (z <= zlim[1])

        # Top: T_tr
        ax = axes[0, col]
        sc = ax.scatter(x[in_win], z[in_win], c=T[in_win], s=2,
                        cmap="inferno", vmin=300, vmax=T_max)
        ax.set_xlim(xlim); ax.set_ylim(zlim)
        ax.set_aspect("equal")
        ax.set_title(f"M{s['mach']} — T_tr (K)", fontsize=10)
        if col == 0:
            ax.set_ylabel("z (m)")

        # Bottom: ne (log scale)
        ax = axes[1, col]
        ne_clipped = np.maximum(ne[in_win], ne_floor)
        sc2 = ax.scatter(x[in_win], z[in_win], c=ne_clipped, s=2,
                         cmap="viridis", norm=LogNorm(vmin=ne_floor, vmax=ne_max))
        ax.set_xlim(xlim); ax.set_ylim(zlim)
        ax.set_aspect("equal")
        ax.set_xlabel("x (m)")
        ax.set_title(f"M{s['mach']} — n_e (m^-3)", fontsize=10)
        if col == 0:
            ax.set_ylabel("z (m)")

    # Single colorbars on the right
    cbar_T = fig.colorbar(sc, ax=axes[0, :].ravel().tolist(),
                          fraction=0.04, pad=0.02)
    cbar_T.set_label("T_tr (K)", fontsize=9)
    cbar_ne = fig.colorbar(sc2, ax=axes[1, :].ravel().tolist(),
                           fraction=0.04, pad=0.02)
    cbar_ne.set_label("n_e (m^-3)", fontsize=9)

    fig.suptitle("RAM-C ramp evolution — symmetry-plane contours",
                 fontsize=14, y=1.00)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_path.name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtu", action="append", required=True,
                    help="path:mach (e.g. data/nemo_test/M10.vtu:10)")
    ap.add_argument("--altitude", type=float, default=61.0)
    ap.add_argument("--output-dir",
                    default=str(REPO / "docs" / "paper" / "figures"))
    args = ap.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stages = []
    for spec in args.vtu:
        path_str, mach_str = spec.rsplit(":", 1)
        path = Path(path_str)
        if not path.exists():
            print(f"ERROR: VTU not found: {path}", file=sys.stderr)
            sys.exit(1)
        mach = float(mach_str)
        print(f"Loading M{mach} from {path.name}...")
        stages.append(collect_stage_data(path, mach, args.altitude))

    stages.sort(key=lambda s: s["mach"])

    print(f"\nWriting figures to {out_dir}")
    fig_stagnation_summary(stages, out_dir / "ramp_evolution_stag.png")
    fig_contour_panels(stages, out_dir / "ramp_evolution_contours.png")

    # Print a one-line summary table
    print(f"\n{'Mach':>6} {'T_tr':>8} {'T_ve':>8} {'NEQ_dT':>8} {'p_stag':>10} "
          f"{'ne_top50':>10} {'cells>1e19':>12}")
    for s in stages:
        print(f"  M{s['mach']:>4} {s['T_tr_stag']:>8.0f} {s['T_ve_stag']:>8.0f} "
              f"{abs(s['T_tr_stag']-s['T_ve_stag']):>8.0f} {s['p_stag']:>10.2e} "
              f"{s['ne_peak_top50']:>10.2e} {s['n_cells_ne_gt_1e19']:>12d}")


if __name__ == "__main__":
    main()
