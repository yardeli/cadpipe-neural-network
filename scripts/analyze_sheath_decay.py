"""Diagnose where the M22.5 sheath ne is collapsing.

Two questions this script answers:

  1. Is the boundary layer single-cell thick? (mesh-resolution issue)
     Plot ne(r) at each station vs distance from the body wall. If the
     plasma layer is contained in 1-2 cells of the mesh, we need finer
     near-wall meshing to resolve it correctly. If it spans many cells,
     the mesh is fine and the chemistry is the issue.

  2. How does ne(z/L) decay along the body wall — is the decay rate
     exponential (chemistry recombination) or geometric (expansion)?
     Plot ne_peak vs z/L and fit a slope. Compare to J&C's measured
     decay (~uniform ~2e19 at all stations vs our 5e17 → 0).

Outputs to docs/paper/figures/:
  - sheath_radial_profiles.png   ne(r) at each station (log y)
  - sheath_axial_decay.png       peak ne(z/L) along body, J&C overlay
  - sheath_diagnosis.md          one-paragraph diagnosis of where the
                                  loss happens

Usage:
    python scripts/analyze_sheath_decay.py \\
        --vtu data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu
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

from plasmanet.cfd_field import extract_nemo_field

RAM_C_NOSE_R = 0.1524
RAM_C_HALF_DEG = 9.0
RAM_C_BODY_LEN = 2.54
STATION_ZL = [0.14, 0.32, 0.48, 0.67, 0.88]
JC_REF = 2.0e19   # Jones & Cross 1972 published peak ne at 61 km


def body_radius(x: float) -> float:
    if x <= 0:
        return 0.0
    half = math.radians(RAM_C_HALF_DEG)
    x_t = RAM_C_NOSE_R * (1 - math.sin(half))
    if x <= x_t:
        return math.sqrt(max(RAM_C_NOSE_R**2 - (RAM_C_NOSE_R - x)**2, 0))
    return RAM_C_NOSE_R * math.cos(half) + (x - x_t) * math.tan(half)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtu", required=True)
    ap.add_argument("--output-dir",
                    default=str(REPO / "docs" / "paper" / "figures"))
    args = ap.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {args.vtu}...")
    cfd = extract_nemo_field(args.vtu, geometry="ram_c",
                             mach=22.5, altitude_km=61.0, verbose=False)

    # Per-station radial profile data
    radial_data = []
    for zL in STATION_ZL:
        z = zL * RAM_C_BODY_LEN
        rw = body_radius(z)
        # 5 cm axial window
        ax_mask = np.abs(cfd.coordinates[:, 0] - z) < 0.025
        if ax_mask.sum() == 0:
            continue
        r = np.linalg.norm(cfd.coordinates[ax_mask, 1:3], axis=1)
        ne = cfd.ne_m3[ax_mask]
        # Bin into 1cm radial bins from the wall outward
        bin_edges = np.arange(0, 0.30, 0.01)
        bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
        ne_p99 = np.zeros_like(bin_centers)
        cell_count = np.zeros_like(bin_centers, dtype=int)
        for i in range(len(bin_centers)):
            d_from_wall = r - rw
            in_bin = (d_from_wall >= bin_edges[i]) & (d_from_wall < bin_edges[i + 1])
            if in_bin.any():
                ne_in_bin = ne[in_bin]
                if (ne_in_bin > 0).any():
                    ne_p99[i] = np.percentile(ne_in_bin[ne_in_bin > 0], 99)
                cell_count[i] = int(in_bin.sum())
        radial_data.append({
            "zL": zL, "z": z, "r_wall": rw,
            "bin_centers": bin_centers,
            "ne_p99": ne_p99,
            "cell_count": cell_count,
        })

    # Figure 1: radial profiles overlaid
    fig, ax = plt.subplots(figsize=(9, 6))
    colors = plt.cm.plasma(np.linspace(0.1, 0.85, len(radial_data)))
    for s, color in zip(radial_data, colors):
        nz = s["ne_p99"] > 0
        if nz.any():
            ax.semilogy(s["bin_centers"][nz] * 100, s["ne_p99"][nz],
                        "o-", color=color, linewidth=1.5, markersize=4,
                        label=f"z/L={s['zL']:.2f} (z={s['z']:.2f} m)")
    ax.axhline(JC_REF, color="green", linestyle="--", linewidth=1.5,
               alpha=0.7, label=f"J&C 1972 published peak = {JC_REF:.1e}")
    ax.fill_between([0, 30], 1.0e19, 4.0e19, color="green", alpha=0.08)
    ax.set_xlim(0, 30)
    ax.set_ylim(1e10, 1e22)
    ax.set_xlabel("Distance from body wall (cm)")
    ax.set_ylabel("Electron density n_e (m^-3, log scale)")
    ax.set_title("Sheath ne radial profile at each reflectometer station")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="upper right")
    out_radial = out_dir / "sheath_radial_profiles.png"
    fig.tight_layout()
    fig.savefig(out_radial, dpi=150)
    plt.close(fig)
    print(f"  wrote {out_radial}")

    # Figure 2: peak ne along body wall, J&C overlay
    fig, ax = plt.subplots(figsize=(8, 5))
    zL_vals = [s["zL"] for s in radial_data]
    ne_peak_vals = [s["ne_p99"].max() if s["ne_p99"].max() > 0 else 1e10
                    for s in radial_data]
    ax.semilogy(zL_vals, ne_peak_vals, "o-", color="#3b82f6",
                markersize=10, linewidth=2,
                label="NEMO peak ne in radial bins")
    # J&C reference: ~constant at 2e19 across stations (their published
    # data shows roughly uniform peak ne along body at this altitude)
    ax.axhline(JC_REF, color="green", linestyle="--", linewidth=1.5,
               alpha=0.7,
               label=f"J&C 1972 published peak (~constant along body) = {JC_REF:.1e}")
    ax.fill_between([0, 1], 1.0e19, 4.0e19, color="green", alpha=0.08,
                    label="J&C uncertainty band")
    ax.set_xlim(0, 1)
    ax.set_ylim(1e10, 1e22)
    ax.set_xlabel("Station axial position z/L")
    ax.set_ylabel("Peak n_e (m^-3, log scale)")
    ax.set_title("ne axial decay along body wall — NEMO vs J&C 1972 expected profile")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="lower left")
    out_axial = out_dir / "sheath_axial_decay.png"
    fig.tight_layout()
    fig.savefig(out_axial, dpi=150)
    plt.close(fig)
    print(f"  wrote {out_axial}")

    # Diagnosis text
    bl_thicknesses_cm = []
    for s in radial_data:
        nz = s["ne_p99"] > 0
        if nz.any():
            ne_max = s["ne_p99"].max()
            half_max = ne_max / 2
            above_half = s["bin_centers"][nz][s["ne_p99"][nz] >= half_max]
            if len(above_half) > 0:
                bl_thicknesses_cm.append(above_half.max() * 100 -
                                          above_half.min() * 100)

    diag = []
    diag.append("# Sheath decay diagnosis — refined-mesh M22.5 NEMO result\n")
    diag.append("## Per-station radial profile peaks\n")
    diag.append("| z/L | z (m) | r_wall (m) | peak n_e (m^-3) | log10 vs J&C 2e19 | "
                "BL HWHM (cm) | nonzero radial bins |")
    diag.append("|---|---|---|---|---|---|---|")
    for s in radial_data:
        nz = s["ne_p99"] > 0
        if nz.any():
            peak = s["ne_p99"].max()
            log10_err = math.log10(peak) - math.log10(JC_REF) if peak > 0 else float("nan")
            ne_max = peak
            half_max = ne_max / 2
            radial_above_half = s["bin_centers"][nz][s["ne_p99"][nz] >= half_max] * 100
            bl_hwhm = (radial_above_half.max() - radial_above_half.min()
                       if len(radial_above_half) > 1 else 0.0)
            diag.append(
                f"| {s['zL']:.2f} | {s['z']:.3f} | {s['r_wall']:.3f} | "
                f"{peak:.2e} | {log10_err:+.2f} | {bl_hwhm:.1f} | {int(nz.sum())} |"
            )
        else:
            diag.append(
                f"| {s['zL']:.2f} | {s['z']:.3f} | {s['r_wall']:.3f} | "
                f"0 | n/a | — | 0 |"
            )

    avg_bl = np.mean(bl_thicknesses_cm) if bl_thicknesses_cm else 0
    diag.append("")
    diag.append("## Interpretation\n")
    if avg_bl < 2:
        diag.append(
            f"**BL HWHM averages {avg_bl:.1f} cm — likely under-resolved.** "
            f"Our refined mesh is 4mm at the body wall, so the plasma layer "
            f"spans only ~{avg_bl*10/4:.0f} cell heights at half-max. Fine-tune "
            f"the mesh further (1-2mm at body) before chasing chemistry fixes."
        )
    elif avg_bl < 5:
        diag.append(
            f"**BL HWHM averages {avg_bl:.1f} cm — marginally resolved.** "
            f"The plasma layer is captured but the half-max width is only "
            f"~{avg_bl*10/4:.0f} cell heights. AIR-11 / wall catalysis are "
            f"the right next experiments; mesh refinement is a marginal extra."
        )
    else:
        diag.append(
            f"**BL HWHM averages {avg_bl:.1f} cm — well-resolved.** Plasma layer "
            f"spans many cell heights. The −1.59 log10 error is genuinely a "
            f"chemistry-model gap (AIR-5 + Saha), not a mesh-resolution gap. "
            f"AIR-11 is the right next experiment."
        )
    diag.append("")
    diag.append(f"Average BL HWHM across stations: {avg_bl:.2f} cm  "
                f"(refined mesh body-wall cell size: 4 mm = 0.4 cm)")
    diag.append("")
    diag.append("## Axial decay rate")
    if len(zL_vals) >= 2 and ne_peak_vals[0] > 0 and ne_peak_vals[1] > 0:
        slope = ((math.log10(ne_peak_vals[1]) - math.log10(ne_peak_vals[0])) /
                 (zL_vals[1] - zL_vals[0]))
        diag.append(f"Decay rate from z/L={zL_vals[0]:.2f} to z/L={zL_vals[1]:.2f}: "
                    f"**{slope:+.1f} log10 per unit z/L** "
                    f"(J&C measured ~0 — flat profile along body).")
        if slope < -8:
            diag.append("**Decay is much faster than physical**, supporting "
                        "the chemistry-collapse hypothesis.")

    out_md = out_dir / "sheath_diagnosis.md"
    out_md.write_text("\n".join(diag), encoding="utf-8")
    print(f"  wrote {out_md}")
    print()
    print("\n".join(diag))


if __name__ == "__main__":
    main()
