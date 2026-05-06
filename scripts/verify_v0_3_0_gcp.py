"""End-to-end verification of khorium_hypersonic v0.3.0 on GCP.

Runs the full v0.3.0 capability surface (axial profile, boundary layer,
trajectory simulator, Monte Carlo UQ) at multiple geometries and flight
conditions, with Cantera-backed kinetics (NOT the equilibrium fallback
or the surrogate — we want real cantera runs to verify the pipeline
stands up to actual hypersonic chemistry).

Output: data/verify_v0_3_0_gcp_results.json + Markdown summary.

Run on the VM:
    cd /home/yarden/plasmanet
    PYTHONPATH=. python3 -u scripts/verify_v0_3_0_gcp.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np

import khorium_hypersonic as kh
from khorium_hypersonic import (
    GEOMETRY_PRESETS, compute_axial_profile,
    TrajectoryPoint, solve_trajectory,
    UncertaintyConfig, run_monte_carlo,
    bl_summary,
)
from khorium_hypersonic.solver import (
    SolverInput, GeometryInput, FlightCondition,
)


GEOMETRIES = ["sharp_narrow", "medium_cone", "blunt_cone", "ram_c", "blunt_wide", "capsule"]

# Three flight conditions chosen to span the regime
FLIGHTS = [
    (12.0, 35.0),    # mid-Mach, mid-altitude (NEMO test conditions)
    (18.5, 47.0),    # RAM-C low-altitude anchor
    (22.5, 61.0),    # RAM-C peak-heating anchor (J&C 1972)
    (23.6, 71.0),    # RAM-C mid-altitude
    (23.9, 81.0),    # RAM-C high-altitude
]


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def stagewise_axial_sweep(n_stations: int = 30) -> dict:
    """Per-(geometry, flight) axial profiles, kinetics mode."""
    section(f"Axial profiles ({n_stations} stations) at {len(FLIGHTS)} flight conditions")
    rows = []
    for mach, alt in FLIGHTS:
        for name in GEOMETRIES:
            geom = GEOMETRY_PRESETS[name]
            t0 = time.monotonic()
            try:
                profile = compute_axial_profile(
                    geom, mach=mach, altitude_km=alt,
                    n_stations=n_stations, chemistry_mode="kinetics",
                )
            except Exception as exc:
                print(f"  {name:>14s} M{mach}/{alt}km: FAILED — {exc}")
                rows.append({"geometry": name, "mach": mach, "alt_km": alt,
                              "error": str(exc)})
                continue
            dt = time.monotonic() - t0
            x_peak, ne_peak = profile.peak_ne()
            tau_arr = profile.tau_residence_s
            T_e_arr = profile.T_e_K
            row = {
                "geometry": name, "mach": mach, "alt_km": alt,
                "n_stations": n_stations,
                "wall_seconds": dt,
                "peak_ne_m3": float(ne_peak),
                "x_at_peak_mm": float(x_peak * 1000),
                "ne_at_x_0p14L_m3": float(profile.ne_m3[
                    int(0.14 * (n_stations - 1))
                ]),
                "ne_at_x_0p5L_m3": float(profile.ne_m3[
                    n_stations // 2
                ]),
                "tau_max_us": float(tau_arr.max() * 1e6),
                "tau_min_us": float(tau_arr.min() * 1e6),
                "T_e_max_K": float(T_e_arr.max()),
                "T_e_min_K": float(T_e_arr.min()),
                "n_normal_shock_stations": sum(1 for s in profile.stations
                                                 if s.shock_kind == "normal"),
                "n_oblique_shock_stations": sum(1 for s in profile.stations
                                                  if s.shock_kind == "oblique"),
            }
            rows.append(row)
            print(f"  {name:>14s} M{mach}/{alt}km: "
                  f"peak_ne={ne_peak:.2e} @ x={x_peak*1000:>5.1f}mm  "
                  f"τmax={tau_arr.max()*1e6:>5.1f}µs  "
                  f"({dt:.1f}s)")
    return {"axial_sweep": rows}


def boundary_layer_sweep() -> dict:
    """Fay-Riddell q_w + δ_BL across geometries at one canonical condition."""
    section("Boundary layer sweep at M=22.5/61km")
    mach, alt = 22.5, 61.0
    fs = kh.core.standard_atmosphere(alt)
    U_inf = mach * fs["a_ms"]
    rows = []
    for name in GEOMETRIES:
        geom = GEOMETRY_PRESETS[name]
        try:
            T_w = 1500.0
            rho_t = 14 * fs["rho_kgm3"]    # equilibrium ratio
            T_t_real = 6196 if alt > 50 else 3800
            bl = bl_summary(
                R_n_m=geom.nose_radius_m, U_inf_ms=U_inf,
                rho_e_kgm3=rho_t, T_e_K=T_t_real,
                rho_w_kgm3=fs["P_Pa"] / (287.058 * T_w), T_w_K=T_w,
                h_e_J_per_kg=0.5 * U_inf ** 2 + 1004.5 * fs["T_K"],
                h_w_J_per_kg=1004.5 * T_w,
                p_t_Pa=14 * fs["P_Pa"], p_inf_Pa=fs["P_Pa"],
                rho_t_kgm3=rho_t,
            )
        except Exception as exc:
            print(f"  {name:>14s}: FAILED — {exc}")
            rows.append({"geometry": name, "error": str(exc)})
            continue
        row = {
            "geometry": name,
            "R_n_m": geom.nose_radius_m,
            "q_w_MW_per_m2": bl["q_w_W_per_m2"] / 1e6,
            "delta_stag_um": bl["delta_stag_m"] * 1e6,
            "mu_e_Pa_s": bl["mu_e_Pa_s"],
            "lewis_correction": bl["lewis_correction"],
        }
        rows.append(row)
        print(f"  {name:>14s} R_n={geom.nose_radius_m*1000:>5.1f}mm: "
              f"q_w={bl['q_w_W_per_m2']/1e6:>5.2f} MW/m²  "
              f"δ_stag={bl['delta_stag_m']*1e6:>5.0f} µm")

    # Verify R_n^(-0.5) scaling
    if all("q_w_MW_per_m2" in r for r in rows):
        sharp = next((r for r in rows if r["geometry"] == "sharp_narrow"), None)
        cap = next((r for r in rows if r["geometry"] == "capsule"), None)
        if sharp and cap:
            actual = sharp["q_w_MW_per_m2"] / cap["q_w_MW_per_m2"]
            expected = (cap["R_n_m"] / sharp["R_n_m"]) ** 0.5
            print(f"\n  Fay-Riddell R_n^(-0.5) check: actual={actual:.3f}  "
                  f"expected={expected:.3f}  "
                  f"{'PASS' if abs(actual - expected) / expected < 0.05 else 'FAIL'}")
            return {"boundary_layer": rows,
                     "fay_riddell_scaling_test": {
                         "actual_ratio": actual, "expected_ratio": expected,
                         "passes": abs(actual - expected) / expected < 0.05
                     }}
    return {"boundary_layer": rows}


def trajectory_test() -> dict:
    """10-point reentry trajectory simulation."""
    section("Trajectory: 10-point RAM-C-class reentry")
    trajectory = [
        TrajectoryPoint(t=0.0,   mach=24.0, altitude_km=85.0),
        TrajectoryPoint(t=10.0,  mach=23.9, altitude_km=81.0),
        TrajectoryPoint(t=25.0,  mach=23.6, altitude_km=71.0),
        TrajectoryPoint(t=40.0,  mach=22.5, altitude_km=61.0),
        TrajectoryPoint(t=55.0,  mach=20.0, altitude_km=55.0),
        TrajectoryPoint(t=70.0,  mach=18.5, altitude_km=47.0),
        TrajectoryPoint(t=90.0,  mach=15.0, altitude_km=40.0),
        TrajectoryPoint(t=110.0, mach=12.0, altitude_km=35.0),
        TrajectoryPoint(t=130.0, mach=8.0,  altitude_km=30.0),
        TrajectoryPoint(t=150.0, mach=5.0,  altitude_km=25.0),
    ]
    # Test on RAM-C and capsule
    out = {}
    for geom_name in ["ram_c", "capsule", "sharp_narrow"]:
        t0 = time.monotonic()
        try:
            result = solve_trajectory(
                trajectory, geometry=geom_name, chemistry_mode="auto",
            )
            dt = time.monotonic() - t0
        except Exception as exc:
            print(f"  {geom_name}: FAILED — {exc}")
            out[geom_name] = {"error": str(exc)}
            continue

        ku_blackouts = [iv for iv in result.blackout_intervals
                        if iv.band_label == "Ku_12"]
        x_blackouts = [iv for iv in result.blackout_intervals
                       if iv.band_label == "X_9.2"]
        print(f"\n  {geom_name}: ({dt:.1f}s)")
        print(f"    Ku-band blackout intervals: {len(ku_blackouts)}")
        for iv in ku_blackouts:
            print(f"      t [{iv.t_start:>5.1f}, {iv.t_end:>5.1f}]s "
                  f"({iv.duration_s:>5.1f}s)  peak {iv.peak_atten_dB:.0f} dB")

        out[geom_name] = {
            "n_waypoints": len(result.waypoints),
            "wall_seconds": dt,
            "blackout_intervals": [
                {"band": iv.band_label,
                 "t_start": iv.t_start, "t_end": iv.t_end,
                 "duration_s": iv.duration_s,
                 "peak_atten_dB": iv.peak_atten_dB}
                for iv in result.blackout_intervals
            ],
            "ne_time_series": [
                {"t": w.t, "ne_m3": w.ne_peak_m3,
                 "Ku_atten_dB": w.band_atten_dB.get("Ku_12", 0),
                 "Ku_status": w.band_status.get("Ku_12", "?")}
                for w in result.waypoints
            ],
        }
    return {"trajectory": out}


def monte_carlo_test() -> dict:
    """N=15 Monte Carlo at one canonical condition + geometry."""
    section("Monte Carlo UQ: RAM-C M=22.5/61km, N=15")
    base = SolverInput(
        geometry=GeometryInput(preset_name="ram_c"),
        flight=FlightCondition(mach=22.5, altitude_km=61.0),
        chemistry_mode="kinetics",
    )
    cfg = UncertaintyConfig(n_samples=15)
    t0 = time.monotonic()
    try:
        mc = run_monte_carlo(base, cfg)
    except Exception as exc:
        print(f"  FAILED — {exc}")
        return {"monte_carlo": {"error": str(exc)}}
    dt = time.monotonic() - t0

    print(f"  Completed {mc.n_samples} samples in {dt:.1f}s")
    print(f"  ne   mean: {mc.ne_mean_m3:.2e}")
    print(f"  ne   std : {mc.ne_std_m3:.2e}")
    print(f"  ne   P95 : {mc.ne_p95_m3:.2e}")
    print(f"  ne worst : {mc.ne_worst_m3:.2e}")
    print(f"  Ku blackout probability: {mc.blackout_probability.get('Ku_12', 0)*100:.0f}%")

    return {"monte_carlo": {
        "n_samples": mc.n_samples,
        "wall_seconds": dt,
        "ne_mean_m3": mc.ne_mean_m3,
        "ne_std_m3": mc.ne_std_m3,
        "ne_p05_m3": mc.ne_p05_m3,
        "ne_p95_m3": mc.ne_p95_m3,
        "ne_worst_m3": mc.ne_worst_m3,
        "band_atten_mean_dB": mc.band_atten_mean_dB,
        "blackout_probability": mc.blackout_probability,
    }}


def main():
    print(f"khorium_hypersonic v{kh.__version__} — GCP verification suite")
    print(f"Cantera available: {kh.chemistry.HAVE_CANTERA}")
    print(f"PyTorch available: {kh.chemistry.HAVE_TORCH}")

    overall_t0 = time.monotonic()
    results = {
        "version": kh.__version__,
        "cantera_available": kh.chemistry.HAVE_CANTERA,
        "torch_available": kh.chemistry.HAVE_TORCH,
        "geometries_tested": GEOMETRIES,
        "flight_conditions": [{"mach": m, "altitude_km": a} for m, a in FLIGHTS],
    }

    results.update(stagewise_axial_sweep(n_stations=20))
    results.update(boundary_layer_sweep())
    results.update(trajectory_test())
    results.update(monte_carlo_test())
    results["total_wall_seconds"] = time.monotonic() - overall_t0

    out_json = REPO / "data" / "verify_v0_3_0_gcp_results.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print(f"\n=== TOTAL WALL: {results['total_wall_seconds']:.1f}s ===")
    print(f"Results written to {out_json}")


if __name__ == "__main__":
    main()
