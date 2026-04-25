"""Post-process a SU2-NEMO RAM-C run and validate against Jones & Cross (1972).

Reads the converged flow.vtu, extracts:
  1. Peak electron density in the sheath → compare to published ne_peak
  2. ne profile along the five reflectometer station axial locations
  3. Full detectability report at VHF (225 MHz, 450 MHz), X-band (9.2 GHz),
     Ku-band (12 GHz, the StarLink target)

Writes a markdown report for the Notion doc + a JSON for programmatic use.

Usage:
    python scripts/validate_ram_c_nemo.py \\
        --vtu data/cfd_cases_nemo/ram_c/ram_c_M22.5_A61/flow.vtu \\
        --altitude 61 --mach 22.5
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

from plasmanet.cfd_field import extract_nemo_field, build_unstructured_field
from plasmanet.line_of_sight import Ray, integrate_los, scan_aspect
from plasmanet.physics import plasma_frequency_ghz
from plasmanet.plasma_wave import detection_status


# Jones & Cross 1972 + Grantham 1970: published peak ne at each altitude
RAM_C_REFERENCE = {
    81.0: {"mach": 23.9, "ne_peak_m3": 2.0e18,
           "ne_lower": 1.0e18, "ne_upper": 3.5e18,
           "source": "Jones & Cross 1972 — Fig. 8, peak sheath ne"},
    71.0: {"mach": 23.6, "ne_peak_m3": 1.0e19,
           "ne_lower": 5.0e18, "ne_upper": 2.0e19,
           "source": "Jones & Cross 1972"},
    61.0: {"mach": 22.5, "ne_peak_m3": 2.0e19,
           "ne_lower": 1.0e19, "ne_upper": 4.0e19,
           "source": "Jones & Cross 1972"},
    47.0: {"mach": 18.5, "ne_peak_m3": 2.0e19,
           "ne_lower": 1.5e19, "ne_upper": 3.0e19,
           "source": "Grantham 1970"},
}

RAM_C_BODY_LENGTH_M = 2.54
RAM_C_NOSE_RADIUS_M = 0.1524
RAM_C_HALF_ANGLE_DEG = 9.0
RAM_C_STATION_ZL = [0.14, 0.32, 0.48, 0.67, 0.88]


def ram_c_body_radius_at_x(x_m: float) -> float:
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


def status_for_alt(alt_km: float, freq_hz: float) -> str:
    """Published Jones & Cross observed status at the four altitudes."""
    tbl = {
        (81.0, 225e6): "BLACKOUT",  (81.0, 450e6): "BLACKOUT",  (81.0, 9.2e9): "DETECTABLE",
        (71.0, 225e6): "BLACKOUT",  (71.0, 450e6): "BLACKOUT",  (71.0, 9.2e9): "DEGRADED",
        (61.0, 225e6): "BLACKOUT",  (61.0, 450e6): "BLACKOUT",  (61.0, 9.2e9): "BLACKOUT",
        (47.0, 225e6): "BLACKOUT",  (47.0, 450e6): "BLACKOUT",  (47.0, 9.2e9): "DEGRADED",
    }
    return tbl.get((alt_km, freq_hz), "UNKNOWN")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtu", required=True, help="Path to SU2-NEMO flow.vtu")
    ap.add_argument("--altitude", type=float, required=True, help="km")
    ap.add_argument("--mach", type=float, required=True)
    ap.add_argument("--output-json", default=None)
    ap.add_argument("--output-md", default=None)
    args = ap.parse_args()

    vtu = Path(args.vtu)
    if not vtu.exists():
        print(f"ERROR: VTU not found at {vtu}", file=sys.stderr)
        sys.exit(1)

    ref = RAM_C_REFERENCE.get(args.altitude)
    if ref is None:
        print(f"WARNING: no reference data for {args.altitude} km "
              f"— validation against published is disabled", file=sys.stderr)
        ref = None

    print(f"=== RAM-C II NEMO validation ===")
    print(f"Conditions: Mach {args.mach} @ {args.altitude} km altitude")
    if ref:
        print(f"Reference: {ref['source']}")
        print(f"  Published ne_peak: {ref['ne_peak_m3']:.2e} m^-3 "
              f"(range {ref['ne_lower']:.1e}-{ref['ne_upper']:.1e})")

    # Step 1: Extract CFD field
    print(f"\nLoading NEMO flow field from {vtu.name}…")
    cfd = extract_nemo_field(
        str(vtu), geometry="ram_c",
        mach=args.mach, altitude_km=args.altitude,
        verbose=True,
    )

    # Body-axis sanity check (fail loudly if mesh orientation is off)
    bbox = np.array([cfd.coordinates.min(axis=0), cfd.coordinates.max(axis=0)])
    x_extent = bbox[1, 0] - bbox[0, 0]
    print(f"\nMesh bbox: x[{bbox[0,0]:.2f},{bbox[1,0]:.2f}] "
          f"y[{bbox[0,1]:.2f},{bbox[1,1]:.2f}] "
          f"z[{bbox[0,2]:.2f},{bbox[1,2]:.2f}]")
    if x_extent < RAM_C_BODY_LENGTH_M:
        print(f"WARNING: x-extent {x_extent:.2f}m < body length "
              f"{RAM_C_BODY_LENGTH_M}m -- body may not be along +x.",
              file=sys.stderr)

    # Step 2: Analyse peak sheath ne
    # Single-cell argmax is sensitive to coarse-mesh spike artifacts;
    # take top-K mean as a robust peak (still picks the strong peak,
    # but averages over the few cells defining it).
    n_top = max(min(50, cfd.n_points // 1000), 1)
    top_idx = np.argpartition(cfd.ne_m3, -n_top)[-n_top:]
    peak_idx = int(top_idx[np.argmax(cfd.ne_m3[top_idx])])
    peak_ne_max = float(cfd.ne_m3[peak_idx])
    peak_ne = float(np.mean(cfd.ne_m3[top_idx]))   # robust peak
    peak_xyz = cfd.coordinates[peak_idx]
    peak_T_tr = float(cfd.T_K[peak_idx])

    print(f"\nDomain-wide peak ne (diagnostic — at stagnation point, NOT what J&C measured):")
    print(f"  ne_peak (robust) = {peak_ne:.2e} m^-3")
    print(f"  ne_peak (max)    = {peak_ne_max:.2e} m^-3 "
          f"(spike ratio {peak_ne_max/max(peak_ne,1e-30):.2f}x)")
    print(f"  location         = ({peak_xyz[0]:.3f}, {peak_xyz[1]:.3f}, {peak_xyz[2]:.3f}) m")
    print(f"  T_tr             = {peak_T_tr:.0f} K")
    print(f"  NOTE: J&C 1972 measured ne via probes AT THE BODY at "
          f"reflectometer stations,")
    print(f"        not at stagnation. The headline log10 error is computed "
          f"below from the")
    print(f"        per-station sheath ne — apples-to-apples with the "
          f"published measurement.")

    # Step 3: ne profile along axial stations.
    # At each reflectometer station, restrict to the sheath shell
    # (radial range from body wall to body wall + 0.3 m) so far-field
    # zeros don't contaminate the slice. Report nonzero-cell count
    # so undersheath cases are visible at a glance.
    print(f"\nne profile along body axis (reflectometer stations,"
          f" filtered to sheath shell r in [r_wall, r_wall+0.3m]):")
    print(f"  {'z/L':>6} {'z (m)':>8} {'r_wall':>8} {'cells':>8} "
          f"{'ne>0 cells':>11} {'max ne':>12} {'p99 ne':>12} {'max T_tr':>10}")
    station_data = []
    dz = 0.05  # axial half-window
    sheath_thickness = 0.3  # radial sheath search depth (m)
    for zL in RAM_C_STATION_ZL:
        z_target = zL * RAM_C_BODY_LENGTH_M
        r_wall = ram_c_body_radius_at_x(z_target)
        ax_mask = np.abs(cfd.coordinates[:, 0] - z_target) < dz
        if ax_mask.sum() == 0:
            print(f"  {zL:>6.2f} {z_target:>8.3f} {r_wall:>8.3f} "
                  f"{'(no cells in axial window)':>40}")
            continue
        r = np.linalg.norm(cfd.coordinates[ax_mask, 1:3], axis=1)
        sheath_mask = (r >= r_wall) & (r <= r_wall + sheath_thickness)
        ne_slice = cfd.ne_m3[ax_mask][sheath_mask]
        T_slice = cfd.T_K[ax_mask][sheath_mask]
        n_cells = int(sheath_mask.sum())
        n_nonzero = int((ne_slice > 0).sum())
        if n_cells == 0:
            print(f"  {zL:>6.2f} {z_target:>8.3f} {r_wall:>8.3f} "
                  f"{0:>8d} {'(no sheath cells)':>40}")
            continue
        max_ne = float(ne_slice.max())
        p99_ne = float(np.percentile(ne_slice, 99))
        max_T  = float(T_slice.max())
        print(f"  {zL:>6.2f} {z_target:>8.3f} {r_wall:>8.3f} "
              f"{n_cells:>8d} {n_nonzero:>11d} {max_ne:>12.2e} "
              f"{p99_ne:>12.2e} {max_T:>10.0f}")
        station_data.append({
            "zL": zL, "z_m": z_target, "r_wall_m": r_wall,
            "n_cells": n_cells, "n_nonzero_ne": n_nonzero,
            "max_ne_m3": max_ne, "p99_ne_m3": p99_ne,
            "max_T_tr_K": max_T,
        })

    # Step 3b: Headline ne comparison vs J&C 1972 — apples-to-apples.
    # J&C measured peak ne via electrostatic probes AT THE BODY at the five
    # reflectometer stations (z/L = 0.14, 0.32, 0.48, 0.67, 0.88), not at
    # the stagnation point. Compare the peak ne across those stations to
    # their published peak. Use p99 (not max) so single-cell artifacts
    # don't drive the comparison.
    sheath_peak_ne = max(
        (s["p99_ne_m3"] for s in station_data if s["p99_ne_m3"] > 0),
        default=0.0,
    )
    sheath_peak_station = next(
        (s for s in station_data if s["p99_ne_m3"] == sheath_peak_ne),
        None,
    )

    log10_error = None
    if ref and ref["ne_peak_m3"] > 0 and sheath_peak_ne > 0:
        log10_error = math.log10(sheath_peak_ne) - math.log10(ref["ne_peak_m3"])
        if abs(log10_error) < 0.3:
            verdict = "EXCELLENT — within measurement uncertainty"
        elif abs(log10_error) < 0.7:
            verdict = "GOOD — within factor of 5"
        elif abs(log10_error) < 1.0:
            verdict = "ACCEPTABLE — within one order of magnitude"
        else:
            sign = "OVER" if log10_error > 0 else "UNDER"
            verdict = f"NEEDS WORK — {abs(log10_error):.1f} orders {sign}-prediction"
        zL_str = f"z/L={sheath_peak_station['zL']:.2f}" if sheath_peak_station else "?"
        print(f"\nHeadline comparison vs J&C 1972 (apples-to-apples, "
              f"sheath p99 ne at body):")
        print(f"  NEMO sheath peak (best station, {zL_str}): "
              f"{sheath_peak_ne:.2e} m^-3")
        print(f"  Published peak (J&C 1972 reflectometer):  "
              f"{ref['ne_peak_m3']:.2e} m^-3")
        print(f"  log10 error:  {log10_error:+.2f}  →  {verdict}")
    elif ref:
        # Sheath totally undersheath at every station — solution has no
        # downstream plasma. Report this clearly instead of skipping.
        print(f"\nHeadline comparison vs J&C 1972: ne is ZERO at every "
              f"reflectometer station — sheath unresolved, can't compare.")

    # Step 4: Line-of-sight attenuation at the three RAM-C reflectometer
    # frequencies (VHF 225, VHF 450, X-band 9.2 GHz) plus Ku-band
    print(f"\nLOS aspect scan attenuation at RAM-C reflectometer frequencies:")
    field = build_unstructured_field(cfd)
    target = cfd.stag_point["xyz"]
    frequencies = {
        "VHF_225":  225e6,
        "VHF_450":  450e6,
        "X_band":   9.2e9,
        "Ku_band":  12e9,
    }
    aspect_results = {}
    for label, f_hz in frequencies.items():
        results = scan_aspect(
            field, target_position=target,
            f_hz=f_hz, source_distance=10.0,
            angles_deg=np.array([0, 30, 60, 90, 120, 150, 180]),
            plane="xz", n_samples=2000, adaptive=True,
        )
        max_att = max(r.attenuation_db for r in results)
        min_att = min(r.attenuation_db for r in results)
        worst = detection_status(max_att)
        pub_status = status_for_alt(args.altitude, f_hz) if f_hz in (225e6, 450e6, 9.2e9) else "-"
        match = "OK" if worst == pub_status else ("-" if pub_status == "-" else "MISS")
        print(f"  {label:>10s} ({f_hz/1e9:>5.2f} GHz): "
              f"min={min_att:>6.1f} dB, max={max_att:>8.1f} dB, "
              f"worst_status={worst}, published={pub_status} {match}")
        aspect_results[label] = {
            "frequency_hz": f_hz,
            "min_attenuation_db": min_att,
            "max_attenuation_db": max_att,
            "worst_status": worst,
            "published_status": pub_status,
            "matches": worst == pub_status,
            "per_angle": [
                {"angle_deg": float(ang), "attenuation_db": r.attenuation_db,
                 "status": r.detection}
                for ang, r in zip(
                    [0, 30, 60, 90, 120, 150, 180], results)
            ],
        }

    # Step 5: Compile report
    report = {
        "flight_condition": {
            "mach": args.mach, "altitude_km": args.altitude,
            "velocity_ms": args.mach * math.sqrt(1.4 * 287.058 * 216.65),  # rough
        },
        "cfd_stagnation": {
            "T_tr_K": cfd.stag_point["T_K"],
            "T_ve_K": cfd.stag_point["T_ve_K"],
            "p_Pa": cfd.stag_point["p_Pa"],
            "ne_m3": cfd.stag_point["ne_m3"],
        },
        "domain_peak_ne": {
            # Diagnostic — at stagnation point, NOT what J&C measured.
            # Kept here for visibility but not used for the headline error.
            "ne_m3": peak_ne,            # robust (top-K mean)
            "ne_m3_max": peak_ne_max,    # raw single-cell max
            "n_top_cells": n_top,
            "T_tr_K": peak_T_tr,
            "location_xyz": peak_xyz.tolist(),
        },
        # Backward-compat alias — older Notion entries reference peak_sheath_ne.
        "peak_sheath_ne": {
            "ne_m3": sheath_peak_ne,     # NEW: sheath peak (apples-to-apples)
            "ne_m3_max": peak_ne_max,    # legacy: domain single-cell max
            "n_top_cells": n_top,
            "T_tr_K": peak_T_tr,
            "location_xyz": peak_xyz.tolist(),
        },
        "sheath_peak_ne": {
            # Apples-to-apples with J&C 1972 reflectometer measurements.
            "ne_m3": sheath_peak_ne,
            "matched_station_zL": (sheath_peak_station["zL"]
                                    if sheath_peak_station else None),
            "matched_station_z_m": (sheath_peak_station["z_m"]
                                    if sheath_peak_station else None),
        },
        "reference": ref,
        "log10_error_vs_published": log10_error,
        "station_profile": station_data,
        "aspect_scan_by_frequency": aspect_results,
        "n_points": cfd.n_points,
    }

    out_json = Path(args.output_json) if args.output_json else vtu.parent / "ram_c_validation.json"
    out_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nJSON report: {out_json}")

    # Markdown table for Notion
    out_md = Path(args.output_md) if args.output_md else vtu.parent / "ram_c_validation.md"
    md = [
        f"# RAM-C II NEMO validation — {args.mach} Mach @ {args.altitude} km",
        "",
        "## Stagnation",
        "",
        f"| Quantity | Value |",
        f"|---|---|",
        f"| T_tr (K) | {cfd.stag_point['T_K']:.0f} |",
        f"| T_ve (K) | {cfd.stag_point['T_ve_K']:.0f} |",
        f"| p_stag (Pa) | {cfd.stag_point['p_Pa']:.2e} |",
        f"| ne_stag (m^-3) | {cfd.stag_point['ne_m3']:.2e} |",
        "",
        "## Peak sheath ne vs published",
        "",
    ]
    if ref:
        zL_str = (f"z/L={sheath_peak_station['zL']:.2f}"
                  if sheath_peak_station else "n/a")
        log10_str = f"{log10_error:+.2f}" if log10_error is not None else "n/a"
        md.extend([
            f"| | Value | Source |",
            f"|---|---|---|",
            f"| **NEMO sheath peak (best station, {zL_str})** | **{sheath_peak_ne:.2e} m^-3** | **apples-to-apples vs J&C** |",
            f"| Published reference (J&C 1972 reflectometer) | {ref['ne_peak_m3']:.2e} m^-3 (range {ref['ne_lower']:.1e}-{ref['ne_upper']:.1e}) | {ref['source']} |",
            f"| **log10 error (sheath peak vs J&C)** | **{log10_str}** | |",
            f"| (diagnostic) NEMO domain peak — at stagnation, not what J&C measured | {peak_ne:.2e} m^-3 (top-{n_top} mean) | informational only |",
            f"| (diagnostic) NEMO domain single-cell max | {peak_ne_max:.2e} m^-3 | informational only |",
        ])
    md.extend([
        "",
        "## ne profile along reflectometer stations",
        "",
        f"| z/L | z (m) | r_wall (m) | sheath cells | nonzero ne | max ne | p99 ne | max T_tr |",
        f"|---|---|---|---|---|---|---|---|",
    ])
    for s in station_data:
        md.append(
            f"| {s['zL']:.2f} | {s['z_m']:.3f} | {s['r_wall_m']:.3f} | "
            f"{s['n_cells']} | {s['n_nonzero_ne']} | "
            f"{s['max_ne_m3']:.2e} | {s['p99_ne_m3']:.2e} | "
            f"{s['max_T_tr_K']:.0f} |"
        )
    md.extend([
        "",
        "## Reflectometer-frequency LOS attenuation",
        "",
        f"| Band | Freq (GHz) | Min-Max atten (dB) | NEMO worst | Published | Match |",
        f"|---|---|---|---|---|---|",
    ])
    for label, data in aspect_results.items():
        md.append(
            f"| {label} | {data['frequency_hz']/1e9:.2f} | "
            f"{data['min_attenuation_db']:.1f}-{data['max_attenuation_db']:.1f} | "
            f"{data['worst_status']} | {data['published_status']} | "
            f"{'OK' if data['matches'] else 'MISS'} |"
        )
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"Markdown report: {out_md}")


if __name__ == "__main__":
    main()
