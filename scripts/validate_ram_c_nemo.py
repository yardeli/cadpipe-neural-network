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
RAM_C_STATION_ZL = [0.14, 0.32, 0.48, 0.67, 0.88]


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

    # Step 2: Analyse peak sheath ne
    peak_idx = int(np.argmax(cfd.ne_m3))
    peak_ne = float(cfd.ne_m3[peak_idx])
    peak_xyz = cfd.coordinates[peak_idx]
    peak_T_tr = float(cfd.T_K[peak_idx])

    print(f"\nPeak sheath ne:")
    print(f"  ne_peak  = {peak_ne:.2e} m^-3")
    print(f"  location = ({peak_xyz[0]:.3f}, {peak_xyz[1]:.3f}, {peak_xyz[2]:.3f}) m")
    print(f"  T_tr     = {peak_T_tr:.0f} K")

    # log10 error vs reference
    log10_error = None
    if ref and ref["ne_peak_m3"] > 0 and peak_ne > 0:
        log10_error = math.log10(peak_ne) - math.log10(ref["ne_peak_m3"])
        print(f"  log10-error vs published: {log10_error:+.2f}")
        if abs(log10_error) < 0.3:
            verdict = "EXCELLENT — within measurement uncertainty"
        elif abs(log10_error) < 0.7:
            verdict = "GOOD — within factor of 5"
        elif abs(log10_error) < 1.0:
            verdict = "ACCEPTABLE — within one order of magnitude"
        else:
            verdict = f"NEEDS WORK — {abs(log10_error):.1f} orders off"
        print(f"  Verdict: {verdict}")

    # Step 3: ne profile along axial stations
    print(f"\nne profile along body axis (reflectometer stations):")
    print(f"  {'z/L':>6} {'z (m)':>8} {'max ne':>12} {'max T_tr':>10}")
    station_data = []
    body_axis_span = 0.1  # radial +/- 0.1m sample window
    for zL in RAM_C_STATION_ZL:
        z_target = zL * RAM_C_BODY_LENGTH_M
        # Sample cells near this axial position
        dz = 0.05
        mask = (np.abs(cfd.coordinates[:, 0] - z_target) < dz)
        if mask.sum() == 0:
            print(f"  {zL:>6.2f} {z_target:>8.3f} (no cells)")
            continue
        r = np.linalg.norm(cfd.coordinates[mask, 1:3], axis=1)
        ne_slice = cfd.ne_m3[mask]
        T_slice = cfd.T_K[mask]
        max_ne = float(ne_slice.max())
        max_T  = float(T_slice.max())
        print(f"  {zL:>6.2f} {z_target:>8.3f} {max_ne:>12.2e} {max_T:>10.0f}")
        station_data.append({
            "zL": zL, "z_m": z_target,
            "max_ne_m3": max_ne, "max_T_tr_K": max_T,
        })

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
        "peak_sheath_ne": {
            "ne_m3": peak_ne,
            "T_tr_K": peak_T_tr,
            "location_xyz": peak_xyz.tolist(),
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
        md.extend([
            f"| | Value | Source |",
            f"|---|---|---|",
            f"| NEMO prediction | {peak_ne:.2e} m^-3 | this run |",
            f"| Published reference | {ref['ne_peak_m3']:.2e} m^-3 (range {ref['ne_lower']:.1e}-{ref['ne_upper']:.1e}) | {ref['source']} |",
            f"| log10 error | {log10_error:+.2f} | |",
        ])
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
