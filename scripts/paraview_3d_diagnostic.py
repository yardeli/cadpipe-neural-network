"""3D diagnostic renderings of a SU2-NEMO RAM-C result for the report.

Loads a SU2-NEMO flow.vtu (AIR-5 or AIR-7), reconstructs ne via the existing
extract_nemo_field (Saha for AIR-5, direct rho_e for AIR-7+), and renders
publication-grade 3D figures showing where the plasma sits relative to
the body.

Output figures (saved to data/checkpoints/<case_name>/):
  1. ne_isosurface.png — semi-transparent ne > 1e16 m^-3 isovolume
     showing the sheath/wake plasma envelope
  2. ne_slice_y0.png — ne contour on the y=0 symmetry plane
  3. mach_slice.png — Mach number contour showing bow shock
  4. T_tr_slice.png — translational temperature on the y=0 plane
  5. ne_axial_profile.png — line plot of peak ne along the body axis at
     each reflectometer station

Usage:
    python scripts/paraview_3d_diagnostic.py \\
        --vtu data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu \\
        --case-name air5_M22_5_A61 \\
        --mach 22.5 --altitude 61
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtu", required=True, type=Path)
    ap.add_argument("--case-name", required=True)
    ap.add_argument("--mach", type=float, required=True)
    ap.add_argument("--altitude", type=float, required=True)
    ap.add_argument("--ne-iso", type=float, default=1e16,
                    help="Electron density (m^-3) for isosurface")
    ap.add_argument("--out-dir", type=Path,
                    default=REPO / "data" / "checkpoints")
    args = ap.parse_args()

    if not args.vtu.exists():
        print(f"ERROR: VTU not found: {args.vtu}", file=sys.stderr)
        sys.exit(1)

    out_dir = args.out_dir / args.case_name
    out_dir.mkdir(parents=True, exist_ok=True)

    import numpy as np
    import pyvista as pv
    pv.OFF_SCREEN = True

    from plasmanet.cfd_field import extract_nemo_field

    print(f"[3d] reading {args.vtu.name}...")
    cfd = extract_nemo_field(
        str(args.vtu), geometry="ram_c",
        mach=args.mach, altitude_km=args.altitude,
        verbose=False,
    )
    n = cfd.n_points
    print(f"[3d] field has {n} points; ne range [{cfd.ne_m3.min():.1e}, "
          f"{cfd.ne_m3.max():.1e}] m^-3")

    # Build pyvista UnstructuredGrid by re-reading the VTU and adding our ne field
    grid = pv.read(str(args.vtu))
    # Make sure our fields are attached as point data
    grid.point_data["ne_m3"] = cfd.ne_m3
    grid.point_data["T_tr_K"] = cfd.T_K
    if hasattr(cfd, "ve_m3"):
        pass  # placeholder

    # Identify Mach if it exists
    if "Mach" in grid.point_data:
        has_mach = True
    else:
        has_mach = False

    bbox = grid.bounds
    print(f"[3d] bbox x[{bbox[0]:.2f},{bbox[1]:.2f}] "
          f"y[{bbox[2]:.2f},{bbox[3]:.2f}] z[{bbox[4]:.2f},{bbox[5]:.2f}]")

    # ─── 1. ne isosurface (3D plasma envelope) ────────────────────────
    print(f"[3d] computing ne isosurface @ {args.ne_iso:.1e} m^-3...")
    iso = grid.contour(isosurfaces=[args.ne_iso], scalars="ne_m3")
    if iso.n_points > 0:
        pl = pv.Plotter(window_size=(1200, 800), off_screen=True)
        pl.add_mesh(iso, color="dodgerblue", opacity=0.6,
                    label=f"ne = {args.ne_iso:.0e} m^-3")
        # Body silhouette: show outline of the bbox for orientation
        pl.add_mesh(grid.outline(), color="gray", line_width=1)
        pl.add_axes()
        pl.add_text(f"AIR-5 RAM-C ne isosurface\nMach {args.mach}, "
                    f"{args.altitude} km, ne={args.ne_iso:.0e} m^-3",
                    font_size=10)
        pl.camera_position = "xy"
        out_iso = out_dir / "ne_isosurface.png"
        pl.screenshot(str(out_iso))
        pl.close()
        print(f"[3d] wrote {out_iso}")
    else:
        print(f"[3d] no isosurface at ne={args.ne_iso:.1e} (range too low)")

    # ─── 2. ne slice on y=0 ──────────────────────────────────────────
    print("[3d] ne slice y=0...")
    slc_y = grid.slice(normal="y", origin=(0, 0, 0))
    pl = pv.Plotter(window_size=(1400, 600), off_screen=True)
    pl.add_mesh(slc_y, scalars="ne_m3", cmap="plasma",
                log_scale=True, clim=[1e14, max(1e15, float(cfd.ne_m3.max()))],
                show_scalar_bar=True,
                scalar_bar_args={"title": "ne (m^-3)", "vertical": True})
    pl.add_mesh(grid.outline(), color="gray", line_width=1)
    pl.camera_position = "xz"
    pl.add_text(f"ne on y=0 plane — Mach {args.mach}, {args.altitude} km",
                font_size=10)
    out_slc = out_dir / "ne_slice_y0.png"
    pl.screenshot(str(out_slc))
    pl.close()
    print(f"[3d] wrote {out_slc}")

    # ─── 3. Mach number slice (bow shock) ─────────────────────────────
    if has_mach:
        print("[3d] Mach slice y=0...")
        pl = pv.Plotter(window_size=(1400, 600), off_screen=True)
        pl.add_mesh(slc_y, scalars="Mach", cmap="coolwarm",
                    show_scalar_bar=True,
                    scalar_bar_args={"title": "Mach", "vertical": True})
        pl.add_mesh(grid.outline(), color="gray", line_width=1)
        pl.camera_position = "xz"
        pl.add_text(f"Mach number — Mach {args.mach}, {args.altitude} km",
                    font_size=10)
        out_mach = out_dir / "mach_slice_y0.png"
        pl.screenshot(str(out_mach))
        pl.close()
        print(f"[3d] wrote {out_mach}")
    else:
        print("[3d] no Mach field — skipping Mach slice")

    # ─── 4. T_tr slice ────────────────────────────────────────────────
    print("[3d] T_tr slice y=0...")
    pl = pv.Plotter(window_size=(1400, 600), off_screen=True)
    pl.add_mesh(slc_y, scalars="T_tr_K", cmap="hot",
                show_scalar_bar=True,
                scalar_bar_args={"title": "T_tr (K)", "vertical": True})
    pl.add_mesh(grid.outline(), color="gray", line_width=1)
    pl.camera_position = "xz"
    pl.add_text(f"Translational T — Mach {args.mach}, {args.altitude} km",
                font_size=10)
    out_T = out_dir / "T_tr_slice_y0.png"
    pl.screenshot(str(out_T))
    pl.close()
    print(f"[3d] wrote {out_T}")

    # ─── 5. Axial ne profile at body wall ─────────────────────────────
    # RAM-C II body: 2.54 m sphere-cone, nose at x=0, back at x=2.54.
    # Sample in the SHEATH SHELL (between body wall and 0.3m beyond) since
    # ne is concentrated near the body surface, and inside the body there
    # are no fluid cells.
    import math
    RAM_C_BODY_LENGTH_M = 2.54
    RAM_C_NOSE_RADIUS_M = 0.1524
    RAM_C_HALF_ANGLE_DEG = 9.0

    def body_radius(x):
        if x <= 0:
            return 0.0
        half = math.radians(RAM_C_HALF_ANGLE_DEG)
        R_n = RAM_C_NOSE_RADIUS_M
        x_tang = R_n * (1 - math.sin(half))
        if x <= x_tang:
            return math.sqrt(max(R_n * R_n - (R_n - x) ** 2, 0.0))
        r_tang = R_n * math.cos(half)
        return r_tang + (x - x_tang) * math.tan(half)

    print("[3d] axial ne profile (body-relative z/L, sheath shell)...")
    import matplotlib.pyplot as plt
    coords = cfd.coordinates
    x_axis = np.linspace(0.01, RAM_C_BODY_LENGTH_M - 0.01, 200)
    dx_window = 0.01 * RAM_C_BODY_LENGTH_M
    ne_axial = []
    T_axial = []
    for x in x_axis:
        mask = np.abs(coords[:, 0] - x) < dx_window
        rad = np.sqrt(coords[mask, 1] ** 2 + coords[mask, 2] ** 2)
        r_w = body_radius(x)
        # Sheath: r_wall < r < r_wall + 0.3 m
        sheath_mask = mask.copy()
        sheath_mask[mask] &= (rad >= r_w) & (rad < r_w + 0.3)
        if np.any(sheath_mask):
            ne_axial.append(float(np.percentile(cfd.ne_m3[sheath_mask], 99)))
            T_axial.append(float(np.percentile(cfd.T_K[sheath_mask], 99)))
        else:
            ne_axial.append(0.0)
            T_axial.append(0.0)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    z_L = x_axis / RAM_C_BODY_LENGTH_M
    ax1.semilogy(z_L, np.maximum(ne_axial, 1e10), lw=1.8)
    ax1.set_ylabel("Sheath p99 ne (m⁻³)")
    ax1.set_title(f"AIR-5 RAM-C axial profile — Mach {args.mach}, "
                  f"{args.altitude} km")
    ax1.grid(True, alpha=0.3)
    # J&C reflectometer stations
    for zl in [0.14, 0.32, 0.48, 0.67, 0.88]:
        ax1.axvline(zl, ls="--", c="red", alpha=0.4)
        ax1.text(zl, ax1.get_ylim()[1] * 0.5,
                 f"z/L={zl:.2f}", rotation=90, fontsize=8,
                 color="red", alpha=0.7, va="top")

    ax2.plot(z_L, T_axial, lw=1.8, color="orange")
    ax2.set_xlabel("z / L (axial fraction)")
    ax2.set_ylabel("Sheath p99 T_tr (K)")
    ax2.grid(True, alpha=0.3)
    out_prof = out_dir / "ne_axial_profile.png"
    fig.tight_layout()
    fig.savefig(out_prof, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[3d] wrote {out_prof}")

    print(f"\n[3d] DONE — figures in {out_dir}/")


if __name__ == "__main__":
    main()
