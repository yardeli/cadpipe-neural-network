"""Animated GIF / MP4 of the Mach-ramp evolution — M10 → M22.5.

Cycles through stage VTUs, renders T_tr (top panel) and ne (bottom panel,
log-scale) in the symmetry plane. Writes both an animated GIF (for
Slack / Notion / docs) and an MP4 (for presentations).

Usage:
    python scripts/make_ramp_animation.py \\
        --vtu data/nemo_test/ramC_refined_M10_0_A61_nemo.vtu:10:AIR-5 \\
        --vtu data/nemo_test/ramC_refined_M15_0_A61_nemo.vtu:15:AIR-5 \\
        --vtu data/nemo_test/ramC_refined_M18_0_A61_nemo.vtu:18:AIR-5 \\
        --vtu data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu:22.5:AIR-5 \\
        --output-dir docs/paper/figures \\
        --fps 1.5

Each --vtu spec is `path:mach:label` (label is shown in the frame caption).

Frame rate: 1.5 fps default — slow enough to read each Mach number's
stagnation conditions, fast enough to feel like animation. The MP4 is
better for slide decks; the GIF embeds in Notion / Slack natively.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter, FFMpegWriter
from matplotlib.colors import LogNorm

from plasmanet.cfd_field import extract_nemo_field


def load_stage(vtu_path: Path, mach: float, label: str, alt_km: float = 61.0):
    """Read a stage VTU and pre-compute the slab + summary stats."""
    print(f"  loading M{mach} ({label}) from {vtu_path.name}...", flush=True)
    cfd = extract_nemo_field(
        str(vtu_path), geometry="ram_c",
        mach=mach, altitude_km=alt_km, verbose=False,
    )
    # Symmetry-plane slab around y=0
    dy = 0.02
    x = cfd.coordinates[:, 0]
    y = cfd.coordinates[:, 1]
    z = cfd.coordinates[:, 2]
    in_slab = np.abs(y) < dy

    # Window around the body for readability
    xlim = (-0.1, 0.7)
    zlim = (-0.4, 0.4)
    mask = in_slab & (x >= xlim[0]) & (x <= xlim[1]) & (z >= zlim[0]) & (z <= zlim[1])

    return {
        "mach": mach,
        "label": label,
        "x": x[mask],
        "z": z[mask],
        "T_tr": cfd.T_K[mask],
        "ne": cfd.ne_m3[mask],
        "stag": cfd.stag_point,
        "ne_top50": float(np.mean(np.partition(cfd.ne_m3, -50)[-50:])),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtu", action="append", required=True,
                    help="path:mach:label  (label is the chemistry/method tag)")
    ap.add_argument("--altitude", type=float, default=61.0)
    ap.add_argument("--output-dir",
                    default=str(REPO / "docs" / "paper" / "figures"))
    ap.add_argument("--fps", type=float, default=1.5,
                    help="Frames per second (default 1.5 — slow enough to read)")
    ap.add_argument("--gif", action="store_true", default=True,
                    help="Write an animated GIF (default on)")
    ap.add_argument("--mp4", action="store_true", default=False,
                    help="Also write an MP4 (requires ffmpeg)")
    args = ap.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {len(args.vtu)} stages...")
    stages = []
    for spec in args.vtu:
        path_str, mach_str, label = spec.rsplit(":", 2)
        path = Path(path_str)
        if not path.exists():
            print(f"WARNING: VTU not found, skipping: {path}", file=sys.stderr)
            continue
        stages.append(load_stage(path, float(mach_str), label, args.altitude))
    if not stages:
        print("ERROR: no stages loaded", file=sys.stderr)
        sys.exit(1)

    # Global colormap ranges so all frames are comparable
    T_min = 300
    T_max = max(float(s["T_tr"].max()) for s in stages)
    T_max = max(T_max, 8000)
    ne_floor = 1e15
    ne_max = max(float(s["ne"].max()) for s in stages)

    # Set up figure — leave headroom for the static suptitle (top) AND a
    # dynamic caption strip (just below it) that updates per frame.
    fig, axes = plt.subplots(2, 1, figsize=(10, 8.5))
    fig.subplots_adjust(left=0.08, right=0.88, top=0.86, bottom=0.06, hspace=0.30)
    ax_T, ax_ne = axes

    # Empty initial scatter — we update the data each frame
    sc_T = ax_T.scatter([], [], c=[], s=2, cmap="inferno", vmin=T_min, vmax=T_max)
    sc_ne = ax_ne.scatter([], [], c=[], s=2, cmap="viridis",
                          norm=LogNorm(vmin=ne_floor, vmax=ne_max))

    # Static elements
    for ax in (ax_T, ax_ne):
        ax.set_xlim(-0.1, 0.7)
        ax.set_ylim(-0.4, 0.4)
        ax.set_aspect("equal")
        ax.set_xlabel("x (m)")
        ax.set_ylabel("z (m)")
    ax_T.set_title("T_tr (translational-rotational)", fontsize=11)
    ax_ne.set_title("Electron density n_e (log scale)", fontsize=11)

    cbar_T = fig.colorbar(sc_T, ax=ax_T, fraction=0.04, pad=0.02)
    cbar_T.set_label("T (K)", fontsize=9)
    cbar_ne = fig.colorbar(sc_ne, ax=ax_ne, fraction=0.04, pad=0.02)
    cbar_ne.set_label("n_e (m^-3)", fontsize=9)

    fig.suptitle("RAM-C ramp evolution", fontsize=14, fontweight="bold", y=0.96)
    caption = fig.text(0.5, 0.91, "", ha="center", fontsize=10, style="italic",
                       color="#305496")

    def update(frame_idx: int):
        s = stages[frame_idx]
        # Data
        sc_T.set_offsets(np.column_stack([s["x"], s["z"]]))
        sc_T.set_array(s["T_tr"])
        sc_ne.set_offsets(np.column_stack([s["x"], s["z"]]))
        ne_clipped = np.maximum(s["ne"], ne_floor)
        sc_ne.set_array(ne_clipped)
        # Caption
        stag = s["stag"]
        cap = (
            f"Mach {s['mach']} @ 61 km · {s['label']} · "
            f"T_tr stag {stag['T_K']:.0f} K · "
            f"T_ve stag {stag['T_ve_K']:.0f} K · "
            f"n_e top-50 {s['ne_top50']:.1e} m⁻³"
        )
        caption.set_text(cap)
        return sc_T, sc_ne, caption

    anim = FuncAnimation(
        fig, update, frames=len(stages),
        interval=int(1000 / args.fps), blit=False,
    )

    if args.gif:
        gif_path = out_dir / "ramp_animation.gif"
        print(f"Writing {gif_path} ({len(stages)} frames @ {args.fps} fps)...")
        anim.save(str(gif_path), writer=PillowWriter(fps=args.fps))
        print(f"  wrote {gif_path}")

    if args.mp4:
        mp4_path = out_dir / "ramp_animation.mp4"
        print(f"Writing {mp4_path} (ffmpeg)...")
        try:
            anim.save(str(mp4_path), writer=FFMpegWriter(fps=args.fps, bitrate=2400))
            print(f"  wrote {mp4_path}")
        except Exception as exc:
            print(f"  MP4 write failed (likely missing ffmpeg): {exc}",
                  file=sys.stderr)

    plt.close(fig)


if __name__ == "__main__":
    main()
