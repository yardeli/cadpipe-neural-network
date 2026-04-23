"""End-to-end detectability analysis using real CFD field data.

Workflow:
  1. Read SU2 flow.vtu for a completed case
  2. Extract T, p fields, run Cantera chemistry on a sparse sample
  3. Save the chemistry-augmented field to NPZ
  4. Run aspect-resolved line-of-sight attenuation through the real field
  5. Compare against the analytical SheathProfile path (same stagnation ne)

This is the operational pipeline: CFD simulation → detectability report.
Everything that ships to AFRL should run through this path for validation.

Usage:
    python examples/detectability_from_cfd.py \\
        --case data/cfd_results/blunt_cone_M15_A35 \\
        --mach 15 --altitude 35 --geometry blunt_cone \\
        --nose-radius 0.08 --half-angle 15 --length 2.5 \\
        --freq 12e9
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import numpy as np


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", required=True,
                    help="Case directory containing flow.vtu")
    ap.add_argument("--mach", type=float, required=True)
    ap.add_argument("--altitude", type=float, required=True)
    ap.add_argument("--geometry", default="unknown")
    ap.add_argument("--nose-radius", type=float, default=0.08)
    ap.add_argument("--half-angle", type=float, default=15.0)
    ap.add_argument("--length", type=float, default=2.5)
    ap.add_argument("--freq", type=float, default=12e9,
                    help="Radar frequency (Hz)")
    ap.add_argument("--chem-samples", type=int, default=3000)
    ap.add_argument("--no-uq", action="store_true")
    ap.add_argument("--field-npz", default=None,
                    help="Path to save extracted field (default: case_dir/field.npz)")
    return ap.parse_args()


def main():
    args = parse_args()
    case_dir = Path(args.case)
    vtu = case_dir / "flow.vtu"
    if not vtu.exists():
        print(f"ERROR: {vtu} does not exist", file=sys.stderr)
        sys.exit(1)

    print(f"=== Detectability analysis: {case_dir.name} ===")
    print(f"    Mach {args.mach}, altitude {args.altitude} km, "
          f"radar {args.freq/1e9:.2f} GHz")
    print()

    # Step 1-3: Extract CFD field
    from plasmanet.cfd_field import (
        extract_cfd_field, load_cfd_field, build_unstructured_field,
    )
    field_npz = Path(args.field_npz) if args.field_npz else case_dir / "field.npz"
    t0 = time.time()
    cfd = extract_cfd_field(
        str(vtu), geometry=args.geometry,
        mach=args.mach, altitude_km=args.altitude,
        chem_mode="sparse", max_chem_samples=args.chem_samples,
        verbose=True,
    )
    cfd.save(str(field_npz))
    t_extract = time.time() - t0
    print(f"    Extracted + saved field in {t_extract:.1f}s → {field_npz}")
    print()

    print(f"    CFD Stagnation (from SU2 Euler + Cantera post-processing):")
    print(f"      Mesh:      {cfd.n_points:>12d} points")
    print(f"      T_stag:    {cfd.stag_point['T_K']:>12.0f}  K")
    print(f"      p_stag:    {cfd.stag_point['p_Pa']:>12.2e} Pa "
          f"({cfd.stag_point['p_Pa']/101325:.2f} atm)")
    print(f"      ne_stag:   {cfd.stag_point['ne_m3']:>12.2e} m⁻³")
    print()

    # Step 4: LOS analysis through REAL CFD field
    from plasmanet.detectability import (
        VehicleGeometry, analyze_detectability,
    )
    vehicle = VehicleGeometry(
        nose_radius_m=args.nose_radius,
        half_angle_deg=args.half_angle,
        length_m=args.length,
        name=args.geometry,
    )

    print(f"    Running aspect-resolved LOS through REAL CFD field…")
    t1 = time.time()
    report_cfd = analyze_detectability(
        vehicle=vehicle, mach=args.mach, altitude_km=args.altitude,
        radar_freq_hz=args.freq,
        aspect_angles_deg=list(range(0, 181, 15)),
        include_uq=not args.no_uq,
        cfd_field_npz=str(field_npz),
    )
    t_cfd = time.time() - t1
    print(f"    CFD-based detectability analysis: {t_cfd:.1f}s")
    print()

    # Step 5: Compare with analytical SheathProfile (stagnation-only fallback)
    print(f"    Running same analysis with analytical SheathProfile (no CFD)…")
    t2 = time.time()
    report_analytic = analyze_detectability(
        vehicle=vehicle, mach=args.mach, altitude_km=args.altitude,
        radar_freq_hz=args.freq,
        aspect_angles_deg=list(range(0, 181, 15)),
        include_uq=not args.no_uq,
        cfd_field_npz=None,
    )
    t_analytic = time.time() - t2
    print(f"    Analytical detectability analysis: {t_analytic:.1f}s")
    print()

    # Print both reports
    print("=" * 78)
    print(f"CFD-based aspect scan (using real SU2 + Cantera field)")
    print("=" * 78)
    print(report_cfd.summary())
    print()

    print("=" * 78)
    print(f"Analytical SheathProfile scan (for comparison)")
    print("=" * 78)
    print(report_analytic.summary())
    print()

    # Differences
    print("=" * 78)
    print(f"CFD vs Analytical Differences")
    print("=" * 78)
    print(f"  {'Angle':>6} {'CFD attn':>14} {'Analytical':>14} {'Δ (dB)':>12}")
    for i, ang in enumerate(report_cfd.aspect_angles_deg):
        c = report_cfd.attenuation_db[i]
        a = report_analytic.attenuation_db[i]
        d = c - a
        print(f"  {ang:>5.0f}°  {c:>12.1f}  {a:>12.1f}  {d:>+10.1f}")
    print()
    print(f"  CFD peak ne:        {report_cfd.ne_peak_m3:.3e} m⁻³")
    print(f"  Analytical peak ne: {report_analytic.ne_peak_m3:.3e} m⁻³")
    print(f"  Ratio:              {report_cfd.ne_peak_m3/max(report_analytic.ne_peak_m3,1.0):.2f}")
    print()
    print(f"Done. Total runtime: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
