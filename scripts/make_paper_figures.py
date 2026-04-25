"""Render publication-quality figures from a RAM-C NEMO validation result.

Generates four figures + a markdown results blurb, ready to drop into the
paper or the Notion doc once the M22.5 ramp completes.

Inputs:
    --vtu  data/nemo_test/<run>_nemo.vtu       (NEMO flow field)
    --validation-json  data/nemo_test/ram_c_validation.json (already produced
                                                  by validate_ram_c_nemo.py)
    --output-dir  docs/paper/figures           (default)

Figures:
    1. los_polar.png         Polar attenuation vs aspect angle, four bands
                             (VHF 225, VHF 450, X-band, Ku-band)
    2. ne_radial_stag.png    Electron density vs radial distance from wall
                             at the stagnation point. Log y-axis.
    3. ne_axial_stations.png Peak ne at each reflectometer station (z/L = 0.14,
                             0.32, 0.48, 0.67, 0.88) vs J&C published points.
    4. tt_tve_contour.png    T_tr and T_ve in the symmetry plane (xz),
                             with NEQ |T_tr - T_ve| isocontour overlaid.

Output:
    <output-dir>/results_blurb.md  — drop-in markdown with the four figures
                                     and a one-paragraph caption each.

Usage:
    python scripts/make_paper_figures.py \
        --vtu data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu \
        --output-dir docs/paper/figures
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import numpy as np

# Matplotlib import is gated so the script can fail fast with a clear msg.
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm
except ImportError as exc:
    print(f"ERROR: matplotlib required ({exc}). pip install matplotlib",
          file=sys.stderr)
    sys.exit(1)

from plasmanet.cfd_field import extract_nemo_field

# RAM-C II reference data (Jones & Cross 1972 + Grantham 1970)
RAM_C_REFERENCE = {
    81.0: {"mach": 23.9, "ne_peak_m3": 2.0e18,
           "ne_lower": 1.0e18, "ne_upper": 3.5e18},
    71.0: {"mach": 23.6, "ne_peak_m3": 1.0e19,
           "ne_lower": 5.0e18, "ne_upper": 2.0e19},
    61.0: {"mach": 22.5, "ne_peak_m3": 2.0e19,
           "ne_lower": 1.0e19, "ne_upper": 4.0e19},
    47.0: {"mach": 18.5, "ne_peak_m3": 2.0e19,
           "ne_lower": 1.5e19, "ne_upper": 3.0e19},
}

RAM_C_BODY_LENGTH_M = 2.54
RAM_C_NOSE_RADIUS_M = 0.1524
RAM_C_HALF_ANGLE_DEG = 9.0


def body_radius_at_x(x_m: float) -> float:
    """Sphere-cone body radius at axial position (nose at x=0, +x downstream)."""
    if x_m <= 0:
        return 0.0
    half = math.radians(RAM_C_HALF_ANGLE_DEG)
    R_n = RAM_C_NOSE_RADIUS_M
    x_tang = R_n * (1 - math.sin(half))
    if x_m <= x_tang:
        return math.sqrt(max(R_n * R_n - (R_n - x_m) ** 2, 0.0))
    r_tang = R_n * math.cos(half)
    return r_tang + (x_m - x_tang) * math.tan(half)


# ── Figure 1: polar attenuation ──────────────────────────────────────────────

def fig_los_polar(validation: dict, out_path: Path) -> None:
    """Polar plot of attenuation vs aspect angle, four frequency bands."""
    aspect_data = validation.get("aspect_scan_by_frequency", {})
    if not aspect_data:
        print(f"  skipped {out_path.name} (no aspect_scan data)")
        return

    fig, ax = plt.subplots(figsize=(8, 6),
                           subplot_kw={"projection": "polar"})

    band_styles = {
        "VHF_225":  {"color": "#fbbf24", "label": "VHF 225 MHz"},
        "VHF_450":  {"color": "#f59e0b", "label": "VHF 450 MHz"},
        "X_band":   {"color": "#10b981", "label": "X-band 9.2 GHz"},
        "Ku_band":  {"color": "#3b82f6", "label": "Ku-band 12 GHz"},
    }

    for label, style in band_styles.items():
        if label not in aspect_data:
            continue
        per_angle = aspect_data[label]["per_angle"]
        angles_rad = np.array([np.radians(p["angle_deg"]) for p in per_angle])
        atten = np.array([p["attenuation_db"] for p in per_angle])
        # Cap at 100 dB for visualization (anything above is fully blacked out)
        atten = np.clip(atten, 0, 100)
        ax.plot(angles_rad, atten, "o-", linewidth=2.0,
                color=style["color"], label=style["label"])

    # Detection threshold rings
    ax.axhline(20, color="gray", linestyle=":", linewidth=0.8, alpha=0.6)
    ax.axhline(40, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_thetamin(0); ax.set_thetamax(180)
    ax.set_rticks([20, 40, 60, 80, 100])
    ax.set_rlabel_position(45)
    ax.set_title("LOS attenuation vs aspect angle (capped at 100 dB)",
                 fontsize=11, pad=14)
    ax.legend(loc="upper right", bbox_to_anchor=(1.30, 1.0), fontsize=9)
    ax.text(np.radians(95), 22, "DETECTABLE→DEGRADED",
            fontsize=7, color="gray", ha="center")
    ax.text(np.radians(95), 42, "DEGRADED→BLACKOUT",
            fontsize=7, color="gray", ha="center")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_path.name}")


# ── Figure 2: ne radial profile at stagnation ────────────────────────────────

def fig_ne_radial_stag(cfd, validation: dict, out_path: Path) -> None:
    """Sample ne radially outward from the body wall at the stagnation point."""
    stag_xyz = np.array(validation["peak_sheath_ne"]["location_xyz"])

    # Sample a thin axial slab near the stagnation point.
    dx = 0.02
    mask = np.abs(cfd.coordinates[:, 0] - stag_xyz[0]) < dx
    if mask.sum() == 0:
        print(f"  skipped {out_path.name} (no cells near stagnation)")
        return
    pts = cfd.coordinates[mask]
    ne = cfd.ne_m3[mask]
    r = np.linalg.norm(pts[:, 1:3] - stag_xyz[1:3], axis=1)

    # Bin into radial shells of 5 mm.
    r_max = 0.30
    bin_edges = np.linspace(0, r_max, 31)
    bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    ne_max = np.zeros_like(bin_centers)
    for i in range(len(bin_centers)):
        in_bin = (r >= bin_edges[i]) & (r < bin_edges[i + 1])
        if in_bin.any():
            ne_max[i] = ne[in_bin].max()

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.semilogy(bin_centers * 1000, np.maximum(ne_max, 1e10),
                "o-", color="#3b82f6", linewidth=1.5, markersize=4,
                label="NEMO peak ne in radial shell")

    ref = RAM_C_REFERENCE.get(validation["flight_condition"]["altitude_km"])
    if ref:
        ax.axhline(ref["ne_peak_m3"], color="green", linestyle="--",
                   alpha=0.7, label=f"J&C 1972 peak ne = {ref['ne_peak_m3']:.1e}")
        ax.fill_between([0, r_max * 1000],
                        ref["ne_lower"], ref["ne_upper"],
                        color="green", alpha=0.1,
                        label=f"J&C uncertainty band")

    ax.set_xlim(0, r_max * 1000)
    ax.set_ylim(1e10, 1e22)
    ax.set_xlabel("Radial distance from stagnation point (mm)")
    ax.set_ylabel("Electron density n$_e$ (m$^{-3}$)")
    ax.set_title("ne radial profile at stagnation — RAM-C M22.5 @ 61 km")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=9, loc="upper right")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_path.name}")


# ── Figure 3: ne along reflectometer stations ────────────────────────────────

def fig_ne_axial_stations(validation: dict, out_path: Path) -> None:
    """Peak ne at each axial station vs J&C reference."""
    stations = validation.get("station_profile", [])
    if not stations:
        print(f"  skipped {out_path.name} (no station data)")
        return

    zL = np.array([s["zL"] for s in stations])
    p99 = np.array([s.get("p99_ne_m3", s.get("max_ne_m3", 0)) for s in stations])
    n_nonzero = np.array([s.get("n_nonzero_ne", 0) for s in stations])

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.semilogy(zL, np.maximum(p99, 1e10), "o-", color="#3b82f6",
                markersize=8, linewidth=1.5,
                label="NEMO p99 ne in sheath shell")

    # Annotate each marker with cell-count for transparency.
    for x, y, n in zip(zL, p99, n_nonzero):
        ax.annotate(f"n={n}", (x, max(y, 1e10)),
                    textcoords="offset points", xytext=(0, 8),
                    fontsize=7, ha="center", color="#1e3a8a")

    ref = RAM_C_REFERENCE.get(validation["flight_condition"]["altitude_km"])
    if ref:
        ax.axhline(ref["ne_peak_m3"], color="green", linestyle="--",
                   alpha=0.7, label=f"J&C 1972 peak = {ref['ne_peak_m3']:.1e}")

    ax.set_xlim(0, 1)
    ax.set_ylim(1e10, 1e22)
    ax.set_xlabel("Station axial position z/L")
    ax.set_ylabel("Peak n$_e$ in sheath shell (m$^{-3}$)")
    ax.set_title("Reflectometer-station ne profile — RAM-C M22.5 @ 61 km")
    ax.grid(True, alpha=0.3, which="both")
    ax.legend(fontsize=9)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_path.name}")


# ── Figure 4: T_tr / T_ve symmetry-plane contour ─────────────────────────────

def fig_tt_tve_contour(cfd, out_path: Path) -> None:
    """Side-by-side T_tr and T_ve in the xz plane (y ≈ 0 slab)."""
    # Take cells in a thin slab around y=0.
    dy = 0.02
    mask = np.abs(cfd.coordinates[:, 1]) < dy
    if mask.sum() < 100:
        print(f"  skipped {out_path.name} (too few cells in y≈0 slab)")
        return
    x = cfd.coordinates[mask, 0]
    z = cfd.coordinates[mask, 2]
    T_tr = cfd.T_K[mask]
    T_ve = getattr(cfd, "T_ve_K", None)
    if T_ve is None:
        T_ve_slab = T_tr  # fallback: no Tve field, plot T_tr twice
        ve_label = "T_tr (T_ve unavailable)"
    else:
        T_ve_slab = T_ve[mask]
        ve_label = "T_ve (vibrational-electronic)"

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    # Restrict to a window around the body for readability.
    xlim = (-0.1, 0.6)
    zlim = (-0.4, 0.4)
    in_win = (x >= xlim[0]) & (x <= xlim[1]) & (z >= zlim[0]) & (z <= zlim[1])

    sc1 = axes[0].scatter(x[in_win], z[in_win], c=T_tr[in_win], s=2,
                          cmap="inferno", vmin=300, vmax=8000)
    axes[0].set_title("T_tr (translational-rotational)")
    axes[0].set_xlim(xlim); axes[0].set_ylim(zlim)
    axes[0].set_xlabel("x (m)"); axes[0].set_ylabel("z (m)")
    axes[0].set_aspect("equal")
    plt.colorbar(sc1, ax=axes[0], label="T (K)")

    sc2 = axes[1].scatter(x[in_win], z[in_win], c=T_ve_slab[in_win], s=2,
                          cmap="inferno", vmin=300, vmax=8000)
    axes[1].set_title(ve_label)
    axes[1].set_xlim(xlim); axes[1].set_ylim(zlim)
    axes[1].set_xlabel("x (m)"); axes[1].set_ylabel("z (m)")
    axes[1].set_aspect("equal")
    plt.colorbar(sc2, ax=axes[1], label="T (K)")

    fig.suptitle("Two-temperature thermochemical NEQ — symmetry-plane slab")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  wrote {out_path.name}")


# ── Markdown results blurb ───────────────────────────────────────────────────

def write_results_blurb(validation: dict, out_path: Path,
                        fig_dir_relative: str) -> None:
    """Drop-in markdown summary referencing the four figures."""
    flight = validation["flight_condition"]
    peak = validation["peak_sheath_ne"]
    stag = validation["cfd_stagnation"]
    ref = RAM_C_REFERENCE.get(flight["altitude_km"], {})

    log10_err = validation.get("log10_error_vs_published")
    log10_str = f"{log10_err:+.2f}" if log10_err is not None else "n/a"

    T_tr = stag.get("T_tr_K", stag.get("T_K", 0))
    T_ve = stag.get("T_ve_K", T_tr)
    md = f"""# RAM-C M{flight['mach']} @ {flight['altitude_km']} km — NEMO results

## Stagnation thermodynamics
- **T_tr** = {T_tr:.0f} K
- **T_ve** = {T_ve:.0f} K (Δ = {abs(T_tr - T_ve):.0f} K nonequilibrium)
- **p_stag** = {stag['p_Pa']:.2e} Pa

## Peak sheath electron density
- **NEMO (top-{peak.get('n_top_cells', 50)} mean)** = {peak['ne_m3']:.2e} m⁻³
- **NEMO single-cell max** = {peak.get('ne_m3_max', peak['ne_m3']):.2e} m⁻³
- **Published (J&C 1972)** = {ref.get('ne_peak_m3', 0):.2e} m⁻³
- **log₁₀ error** = {log10_str}

## Figures

### LOS attenuation polar scan
Aspect-resolved attenuation across all four reflectometer bands. Detection
status thresholds shown as concentric rings.

![LOS polar]({fig_dir_relative}/los_polar.png)

### Sheath ne radial profile at stagnation
Electron density falls off with radial distance from the wall. The Jones &
Cross 1972 reference and uncertainty band are overlaid.

![ne radial]({fig_dir_relative}/ne_radial_stag.png)

### Reflectometer-station axial profile
Peak ne in the sheath shell at each station vs the published peak.
Annotation `n=N` reports the count of nonzero-ne cells in the search shell —
small N indicates undersheath resolution.

![ne axial]({fig_dir_relative}/ne_axial_stations.png)

### Two-temperature contour
T_tr and T_ve side-by-side in the symmetry plane. Visible Δ between them is
the thermochemical nonequilibrium signature that AIR-5 + NEMO captures and
the equilibrium analytical sheath does not.

![Tt Tve]({fig_dir_relative}/tt_tve_contour.png)
"""
    out_path.write_text(md, encoding="utf-8")
    print(f"  wrote {out_path.name}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtu", required=True, help="NEMO flow.vtu (renamed)")
    ap.add_argument("--validation-json", default=None,
                    help="ram_c_validation.json (defaults to <vtu>/../ram_c_validation.json)")
    ap.add_argument("--output-dir", default=str(REPO / "docs" / "paper" / "figures"))
    args = ap.parse_args()

    vtu = Path(args.vtu)
    if not vtu.exists():
        print(f"ERROR: VTU not found: {vtu}", file=sys.stderr)
        sys.exit(1)

    val_path = (Path(args.validation_json) if args.validation_json else
                vtu.parent / "ram_c_validation.json")
    if not val_path.exists():
        print(f"ERROR: validation JSON not found: {val_path}", file=sys.stderr)
        print("Run scripts/validate_ram_c_nemo.py first.", file=sys.stderr)
        sys.exit(1)
    validation = json.loads(val_path.read_text(encoding="utf-8"))

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing figures to {out_dir}")

    print("Loading NEMO field...")
    cfd = extract_nemo_field(
        str(vtu), geometry="ram_c",
        mach=validation["flight_condition"]["mach"],
        altitude_km=validation["flight_condition"]["altitude_km"],
        verbose=False,
    )

    fig_los_polar(validation, out_dir / "los_polar.png")
    fig_ne_radial_stag(cfd, validation, out_dir / "ne_radial_stag.png")
    fig_ne_axial_stations(validation, out_dir / "ne_axial_stations.png")
    fig_tt_tve_contour(cfd, out_dir / "tt_tve_contour.png")

    try:
        fig_dir_relative = str(out_dir.relative_to(REPO.resolve())).replace("\\", "/")
    except ValueError:
        fig_dir_relative = str(out_dir).replace("\\", "/")
    write_results_blurb(validation, out_dir / "results_blurb.md",
                        fig_dir_relative)

    print(f"\nDone. {len(list(out_dir.glob('*.png')))} PNGs + 1 markdown blurb.")


if __name__ == "__main__":
    main()
