"""Verify the LOS detectability solver handles arbitrary geometries.

The frontend hardcodes RAM-C, so we've effectively only validated the
solver on a sphere-cone with R_n=0.15m, half-angle=9 deg. The codebase
has 5 other geometries in data/cfd_cases/ ranging from sharp_narrow
(R_n=0.02m, 7 deg) through capsule (R_n=0.30m, 30 deg). This script
runs the solver on all 5 + RAM-C at a single flight condition and
reports the output, so a human can eyeball whether the answers differ
the way physics says they should:

  - Smaller nose radius -> thinner sheath, lower peak ne (less compression)
  - Larger half-angle -> more body area in the plasma, more aspect-angle
    coverage with attenuation
  - Longer body -> longer afterbody plume, attenuation persists farther
    downstream

If the solver returns identical results for very different geometries,
the geometry inputs are being silently ignored downstream.

Usage:
    python -u scripts/geometry_sweep.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from plasmanet.detectability import analyze_detectability, VehicleGeometry


# Geometries to sweep. RAM-C is added explicitly because it's the
# canonical baseline + the frontend's only option.
GEOMETRIES = [
    ("ram_c",        {"nose_radius_m": 0.1524, "half_angle_deg": 9.0,  "length_m": 1.295}),
    ("sharp_narrow", {"nose_radius_m": 0.02,   "half_angle_deg": 7.0,  "length_m": 0.50}),
    ("medium_cone",  {"nose_radius_m": 0.05,   "half_angle_deg": 15.0, "length_m": 0.50}),
    ("blunt_cone",   {"nose_radius_m": 0.08,   "half_angle_deg": 15.0, "length_m": 0.50}),
    ("blunt_wide",   {"nose_radius_m": 0.15,   "half_angle_deg": 25.0, "length_m": 0.60}),
    ("capsule",      {"nose_radius_m": 0.30,   "half_angle_deg": 30.0, "length_m": 0.80}),
]

# Flight condition — chosen at Mach 12, 35 km because it sits squarely
# in the BLACKOUT band for RAM-C-class vehicles (so any geometry
# differences should show up as "still in blackout" but with quantitatively
# different stagnation T, ne, attenuation per aspect angle).
MACH = 12.0
ALTITUDE_KM = 35.0
RADAR_FREQ_HZ = 9.2e9   # X-band — most sensitive to ne in the BLACKOUT regime
ASPECT_ANGLES = [0, 30, 60, 90, 120, 150, 180]


def main():
    print(f"Geometry sweep — Mach {MACH}, {ALTITUDE_KM} km, {RADAR_FREQ_HZ/1e9:.1f} GHz")
    print(f"{'name':<15} {'R_n':>6} {'half':>5} {'len':>5} | "
          f"{'T_stag':>7} {'p_stag':>9} {'ne_peak':>10} {'fp_GHz':>7} | "
          f"{'min_dB':>7} {'max_dB':>7} {'status':>10} {'wall':>5}")
    print("-" * 130)

    rows = []
    for name, dims in GEOMETRIES:
        geom = VehicleGeometry(**dims)
        t0 = time.monotonic()
        try:
            report = analyze_detectability(
                vehicle=geom,
                mach=MACH,
                altitude_km=ALTITUDE_KM,
                radar_freq_hz=RADAR_FREQ_HZ,
                aspect_angles_deg=ASPECT_ANGLES,
                include_uq=False,   # speed; not testing UQ here
                use_cantera=True,
                use_neq=False,
            )
            dt = time.monotonic() - t0
            min_db = float(min(report.attenuation_db))
            max_db = float(max(report.attenuation_db))
            print(f"{name:<15} {dims['nose_radius_m']:>6.3f} "
                  f"{dims['half_angle_deg']:>5.1f} {dims['length_m']:>5.2f} | "
                  f"{report.T_stag_K:>7.0f} {report.p_stag_Pa:>9.1f} "
                  f"{report.ne_peak_m3:>10.2e} {report.fp_GHz:>7.1f} | "
                  f"{min_db:>7.1f} {max_db:>7.1f} {report.overall_status:>10} "
                  f"{dt:>4.1f}s")
            rows.append({
                "name": name, "dims": dims,
                "T_stag_K": report.T_stag_K, "p_stag_Pa": report.p_stag_Pa,
                "ne_peak_m3": report.ne_peak_m3, "fp_GHz": report.fp_GHz,
                "att_per_angle_dB": list(map(float, report.attenuation_db)),
                "aspect_angles_deg": list(map(float, report.aspect_angles_deg)),
                "overall_status": report.overall_status,
                "wall_seconds": dt,
            })
        except Exception as exc:
            print(f"{name:<15} ERROR: {exc}")
            rows.append({"name": name, "dims": dims, "error": str(exc)})

    # Diagnostics: did the geometry actually change the answer?
    print()
    print("Sanity checks across the sweep:")
    valid = [r for r in rows if "error" not in r]
    if len(valid) < 2:
        print("  Not enough valid runs to compare.")
        return

    # 1. ne_peak should differ between geometries with different nose_r.
    ne_unique = len({round(r["ne_peak_m3"], -10) for r in valid})
    print(f"  ne_peak distinct values across {len(valid)} geometries: {ne_unique}")
    if ne_unique == 1:
        print("  -> WARNING: solver returns identical ne for every geometry. "
              "Geometry input is being silently ignored at the chemistry layer.")
    elif ne_unique < len(valid) // 2:
        print("  -> WARNING: many geometries collapse to same ne value. "
              "Geometry sensitivity is weak.")

    # 2. min/max attenuation should differ.
    att_unique = len({(round(r["att_per_angle_dB"][0], 1),
                       round(r["att_per_angle_dB"][3], 1))
                      for r in valid})
    print(f"  attenuation tuple (0deg, 90deg) distinct: {att_unique} of {len(valid)}")

    # 3. Print attenuation tables side-by-side
    print()
    print("Attenuation [dB] per aspect angle, by geometry:")
    print(f"{'angle':>6}  " + "  ".join(f"{r['name']:>12}" for r in valid))
    n_angles = len(valid[0]["aspect_angles_deg"])
    for i in range(n_angles):
        ang = valid[0]["aspect_angles_deg"][i]
        cells = "  ".join(f"{r['att_per_angle_dB'][i]:>12.1f}" for r in valid)
        print(f"{ang:>5.0f}   {cells}")

    # Persist the JSON for later analysis
    out = REPO / "data" / "geometry_sweep_result.json"
    out.write_text(json.dumps({
        "config": {"mach": MACH, "altitude_km": ALTITUDE_KM,
                   "radar_freq_hz": RADAR_FREQ_HZ,
                   "aspect_angles_deg": ASPECT_ANGLES},
        "rows": rows,
    }, indent=2, default=float))
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()
