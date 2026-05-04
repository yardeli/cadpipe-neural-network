"""First-principles sanity checks for a SU2-NEMO RAM-C run.

Five textbook-physics comparisons against CFD output. Each one has an
analytical reference that does NOT depend on the J&C 1972 measurement,
so passing/failing tells you whether the CFD's chemistry, T field, and
shock position are internally consistent before any flight-data
comparison.

Checks:
  1. Frozen-shock T2 (Rankine-Hugoniot, perfect gas gamma=1.4) vs CFD's
     T_tr at the high-T region downstream of the shock.
  2. Real-gas stagnation T from enthalpy conservation (h_stag =
     h_inf + 0.5*U_inf^2) vs CFD's T_tr at the max-pressure cell.
  3. Saha-equilibrium ne at the CFD's stagnation (T, p) vs CFD's ne at
     the same cell. If chemistry is right, these should be close.
  4. Billig 1967 bow-shock standoff (frozen and equilibrium estimates)
     vs CFD's measured shock position along the stagnation line.
  5. Plasma frequency / X-band attenuation from CFD's stagnation ne vs
     the J&C published peak. Closes the loop on the detection story.

Usage:
    python scripts/sanity_check.py \
        --vtu data/cfd_runs/v8_phase1A_iter251/flow_iter251.vtu \
        --mach 22.5 --altitude 61

Output: prints each check with TEXTBOOK / CFD / AGREEMENT and writes a
JSON next to the input vtu.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np

from plasmanet.cfd_field import extract_nemo_field
from plasmanet.physics import (
    standard_atmosphere, saha_ionization, janaf_equilibrium,
    plasma_frequency_ghz, K_B,
)


GAMMA = 1.4
R_AIR = 287.058


def rh_normal_shock(mach_inf: float, T_inf: float, p_inf: float):
    """Perfect-gas (gamma=1.4) Rankine-Hugoniot across a normal shock.

    Returns (T2, p2, rho2_over_rho1, M2). Strictly frozen — no chemistry.
    """
    M = mach_inf
    g = GAMMA
    T_ratio = (2*g*M*M - (g-1)) * ((g-1)*M*M + 2) / ((g+1)**2 * M*M)
    p_ratio = (2*g*M*M - (g-1)) / (g + 1)
    rho_ratio = (g + 1) * M*M / ((g-1) * M*M + 2)
    M2_sq = ((g-1)*M*M + 2) / (2*g*M*M - (g-1))
    return T_ratio * T_inf, p_ratio * p_inf, rho_ratio, math.sqrt(M2_sq)


def real_gas_T_stag(T_inf: float, p_inf: float, U_inf: float):
    """Real-gas stagnation T via enthalpy conservation.

    Solves h(T_stag, p_stag) = h(T_inf, p_inf) + 0.5*U_inf^2 with Cantera
    equilibrium air at p_stag = p_inf * (frozen pitot rise).

    Returns (T_stag_real, T_stag_frozen, p_stag).
    """
    g = GAMMA
    M_inf = U_inf / math.sqrt(g * R_AIR * T_inf)
    # Frozen pitot pressure (Rayleigh): p_stag/p_inf = ((g+1)^2 M^2 / (4gM^2-2(g-1)))^(g/(g-1)) * ((1-g+2gM^2)/(g+1))
    pre = ((g+1)**2 * M_inf**2 / (4*g*M_inf**2 - 2*(g-1)))**(g/(g-1))
    post = (1 - g + 2*g*M_inf**2) / (g + 1)
    p_stag = p_inf * pre * post

    # Frozen stagnation T (perfect gas)
    T_stag_frozen = T_inf * (1 + 0.5*(g-1)*M_inf**2)

    # Real-gas iteration with Cantera
    try:
        import cantera as ct
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sol = ct.Solution("air.yaml")
        sol.TPX = T_inf, p_inf, "N2:0.79, O2:0.21"
        sol.equilibrate("TP")
        h_inf = sol.enthalpy_mass
        h_stag = h_inf + 0.5 * U_inf**2

        T_lo, T_hi = 500.0, 30000.0
        for _ in range(60):
            T_mid = 0.5 * (T_lo + T_hi)
            sol.TPX = T_mid, p_stag, "N2:0.79, O2:0.21"
            sol.equilibrate("TP")
            if sol.enthalpy_mass < h_stag:
                T_lo = T_mid
            else:
                T_hi = T_mid
        T_stag_real = 0.5 * (T_lo + T_hi)
    except Exception as exc:
        T_stag_real = float("nan")

    return T_stag_real, T_stag_frozen, p_stag


def billig_standoff(mach_inf: float, R_nose_m: float, rho_ratio_eq: float = 14.0):
    """Billig 1967 empirical bow-shock standoff for a sphere.

    delta_frozen / R_n = 0.143 * exp(3.24 / M^2)
    Equilibrium correction: delta_eq ~ delta_frozen * (rho_ratio_frozen / rho_ratio_eq)
    Frozen rho_ratio at high M: (g+1)/(g-1) = 6.0 in the strong-shock limit.

    Returns (delta_frozen_m, delta_eq_m). The equilibrium estimate is rough
    (depends on assumed rho_ratio_eq); use as ballpark.
    """
    delta_frozen = 0.143 * math.exp(3.24 / mach_inf**2) * R_nose_m
    rho_ratio_frozen = (GAMMA + 1) / (GAMMA - 1)   # 6.0 for gamma=1.4
    delta_eq = delta_frozen * rho_ratio_frozen / rho_ratio_eq
    return delta_frozen, delta_eq


def measure_shock_standoff(cfd, n_axial_samples: int = 200):
    """Find the bow-shock standoff distance from the vtu.

    Walks a line along the stagnation streamline (negative x from the
    nose, since the body sits on +x), looks for the upstream pressure
    jump where p crosses 2x the freestream value.

    Returns delta_m (negative if no shock found).
    """
    coords = cfd.coordinates
    p = cfd.p_Pa

    # Find the most-forward body cell (stagnation point ~ argmax(p))
    stag_idx = int(np.argmax(p))
    x_stag = coords[stag_idx, 0]

    # Sample along x at fixed y=0, z=0 (axisymmetric assumption); find
    # nearest cell to each sample.
    xs = np.linspace(coords[:, 0].min(), x_stag, n_axial_samples)
    p_inf_estimate = float(np.median(p[p > 0]))   # rough freestream proxy
    # Better: use the minimum p in the bbox far-field
    p_inf_estimate = float(np.percentile(p, 5))

    # For each sample x, find nearest cell within radial cylinder of ~0.05m
    x_shock = None
    last_p = p_inf_estimate
    for x_target in xs:
        ax_mask = np.abs(coords[:, 0] - x_target) < (xs[1] - xs[0])
        if not ax_mask.any():
            continue
        r = np.linalg.norm(coords[ax_mask, 1:3], axis=1)
        near_axis = r < 0.05
        if not near_axis.any():
            continue
        p_local = p[ax_mask][near_axis].mean()
        if p_local > 2.0 * p_inf_estimate and last_p < 2.0 * p_inf_estimate:
            x_shock = x_target
            break
        last_p = p_local

    if x_shock is None:
        return -1.0
    return float(x_stag - x_shock)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtu", required=True, help="Path to SU2-NEMO flow.vtu")
    ap.add_argument("--mach", type=float, required=True)
    ap.add_argument("--altitude", type=float, required=True, help="km")
    ap.add_argument("--nose-radius", type=float, default=0.1524,
                     help="Nose radius (m), default RAM-C 6 inches")
    ap.add_argument("--output-json", default=None,
                     help="Default: <vtu_dir>/sanity_check.json")
    args = ap.parse_args()

    vtu = Path(args.vtu)
    if not vtu.exists():
        print(f"ERROR: VTU not found at {vtu}", file=sys.stderr)
        sys.exit(1)

    out_json = Path(args.output_json) if args.output_json else (
        vtu.parent / "sanity_check.json")

    # Atmosphere + freestream
    T_inf, p_inf, rho_inf, a_inf = standard_atmosphere(args.altitude)
    U_inf = args.mach * a_inf

    print(f"=== Sanity check: M={args.mach} @ {args.altitude} km ===")
    print(f"Freestream: T_inf={T_inf:.1f} K  p_inf={p_inf:.1f} Pa  "
          f"a_inf={a_inf:.1f} m/s  U_inf={U_inf:.0f} m/s")
    print(f"Vehicle: nose radius {args.nose_radius*1000:.1f} mm")
    print()

    # Load CFD field
    print(f"Loading {vtu.name}...")
    cfd = extract_nemo_field(
        str(vtu), geometry="ram_c", mach=args.mach,
        altitude_km=args.altitude, verbose=False,
    )
    coords = cfd.coordinates
    T_tr = cfd.T_K
    p = cfd.p_Pa
    ne = cfd.ne_m3

    stag_idx = int(np.argmax(p))
    T_stag_cfd = float(T_tr[stag_idx])
    p_stag_cfd = float(p[stag_idx])
    ne_stag_cfd = float(ne[stag_idx])
    T_max_cfd = float(T_tr.max())
    print(f"CFD stag: T_tr={T_stag_cfd:.0f} K  p={p_stag_cfd:.2e} Pa  "
          f"ne={ne_stag_cfd:.2e} m^-3")
    print(f"CFD T_max (anywhere): {T_max_cfd:.0f} K")
    print()

    results = {
        "freestream": {"T_inf_K": T_inf, "p_inf_Pa": p_inf,
                        "rho_inf": rho_inf, "U_inf_ms": U_inf,
                        "mach": args.mach, "altitude_km": args.altitude},
        "cfd_stag": {"T_tr_K": T_stag_cfd, "p_Pa": p_stag_cfd,
                      "ne_m3": ne_stag_cfd},
        "cfd_T_max_K": T_max_cfd,
        "checks": {},
    }

    # ---- Check 1: Frozen Rankine-Hugoniot post-shock T ----
    T2_frozen, p2_frozen, rho_ratio, M2 = rh_normal_shock(
        args.mach, T_inf, p_inf)
    print(f"[1] Frozen Rankine-Hugoniot (perfect gas, gamma=1.4):")
    print(f"    Textbook T2     = {T2_frozen:.0f} K  (post-shock, no chemistry)")
    print(f"    CFD T_max       = {T_max_cfd:.0f} K")
    rh_ratio = T_max_cfd / T2_frozen
    rh_ok = 0.15 < rh_ratio < 1.05   # real chemistry pulls T2 way down
    print(f"    Ratio CFD/frozen = {rh_ratio:.2f}  "
          f"(<1 expected because chemistry absorbs energy; "
          f"<<1 means heavy chemistry sink)")
    print(f"    Verdict: {'PLAUSIBLE' if rh_ok else 'SUSPICIOUS'}")
    results["checks"]["1_frozen_rh"] = {
        "T2_textbook_K": T2_frozen, "p2_textbook_Pa": p2_frozen,
        "rho_ratio_frozen": rho_ratio, "T_cfd_max_K": T_max_cfd,
        "ratio_cfd_to_frozen": rh_ratio, "verdict": "PLAUSIBLE" if rh_ok else "SUSPICIOUS",
    }
    print()

    # ---- Check 2: Real-gas stagnation T from enthalpy ----
    T_stag_real, T_stag_frozen, p_stag_book = real_gas_T_stag(
        T_inf, p_inf, U_inf)
    print(f"[2] Stagnation T from enthalpy conservation:")
    print(f"    Frozen (perfect gas)   T_stag = {T_stag_frozen:.0f} K")
    if math.isnan(T_stag_real):
        print(f"    Real-gas (Cantera)     T_stag = N/A (Cantera not available)")
        check2 = {"verdict": "CANTERA_UNAVAILABLE"}
    else:
        print(f"    Real-gas (Cantera eq.) T_stag = {T_stag_real:.0f} K")
        print(f"    Pitot p_stag (frozen)        = {p_stag_book:.2e} Pa")
        print(f"    CFD T_tr at stag             = {T_stag_cfd:.0f} K")
        print(f"    CFD p     at stag            = {p_stag_cfd:.2e} Pa")
        T_err = abs(T_stag_cfd - T_stag_real) / T_stag_real
        p_err = abs(p_stag_cfd - p_stag_book) / p_stag_book
        verdict_T = "GOOD" if T_err < 0.10 else (
            "FAIR" if T_err < 0.25 else "POOR")
        verdict_p = "GOOD" if p_err < 0.15 else (
            "FAIR" if p_err < 0.40 else "POOR")
        print(f"    T agreement: {verdict_T} (rel err {T_err*100:.1f}%)")
        print(f"    p agreement: {verdict_p} (rel err {p_err*100:.1f}%)")
        check2 = {
            "T_stag_real_K": T_stag_real, "T_stag_frozen_K": T_stag_frozen,
            "p_stag_textbook_Pa": p_stag_book,
            "T_rel_err": T_err, "p_rel_err": p_err,
            "verdict_T": verdict_T, "verdict_p": verdict_p,
        }
    results["checks"]["2_real_gas_stag"] = check2
    print()

    # ---- Check 3: Saha-equilibrium ne at CFD (T, p) ----
    # Use JANAF-derived neutral fractions at the CFD stag T,p, then Saha
    xN2, xO2, xNO, xO, xN = janaf_equilibrium(T_stag_cfd, p_stag_cfd)
    ne_saha = saha_ionization(T_stag_cfd, p_stag_cfd, xNO, xO, xN)
    print(f"[3] Saha-equilibrium ne at CFD stagnation (T={T_stag_cfd:.0f} K, "
          f"p={p_stag_cfd:.2e} Pa):")
    print(f"    JANAF mole fractions: x_N2={xN2:.3f} x_O2={xO2:.3f} "
          f"x_NO={xNO:.3f} x_O={xO:.3f} x_N={xN:.3f}")
    print(f"    Saha equilibrium ne   = {ne_saha:.2e} m^-3")
    print(f"    CFD ne at stag        = {ne_stag_cfd:.2e} m^-3")
    if ne_saha > 0 and ne_stag_cfd > 0:
        log_diff = math.log10(ne_stag_cfd) - math.log10(ne_saha)
        verdict = ("EXCELLENT" if abs(log_diff) < 0.3 else
                    "GOOD" if abs(log_diff) < 0.7 else
                    "FAIR" if abs(log_diff) < 1.0 else "POOR")
        sign = "OVER" if log_diff > 0 else "UNDER"
        print(f"    log10 diff: {log_diff:+.2f}  ({verdict} — CFD "
              f"{abs(log_diff):.1f} orders {sign}-predicting Saha-equilibrium)")
        check3 = {
            "T_stag_K": T_stag_cfd, "p_stag_Pa": p_stag_cfd,
            "x_N2": xN2, "x_O2": xO2, "x_NO": xNO, "x_O": xO, "x_N": xN,
            "ne_saha_m3": ne_saha, "ne_cfd_m3": ne_stag_cfd,
            "log10_diff": log_diff, "verdict": verdict,
        }
    else:
        print(f"    Cannot compare: ne is zero somewhere")
        check3 = {"verdict": "MISSING_DATA",
                   "ne_saha_m3": ne_saha, "ne_cfd_m3": ne_stag_cfd}
    results["checks"]["3_saha_at_cfd_stag"] = check3
    print()

    # ---- Check 4: Billig bow-shock standoff ----
    delta_frozen, delta_eq = billig_standoff(args.mach, args.nose_radius)
    delta_cfd = measure_shock_standoff(cfd)
    print(f"[4] Bow-shock standoff (Billig 1967):")
    print(f"    Frozen estimate     = {delta_frozen*1000:.2f} mm")
    print(f"    Equilibrium est.    = {delta_eq*1000:.2f} mm "
          f"(rho_ratio_eq=14)")
    if delta_cfd > 0:
        print(f"    CFD measured        = {delta_cfd*1000:.2f} mm "
              f"(p > 2*p_inf at stagnation streamline)")
        ratio = delta_cfd / delta_eq
        # CFD between equilibrium and frozen is healthy
        verdict_b = "PLAUSIBLE" if (0.5 * delta_eq < delta_cfd < 1.5 * delta_frozen) else "SUSPICIOUS"
        print(f"    CFD/Billig_eq ratio = {ratio:.2f}  Verdict: {verdict_b}")
        check4 = {
            "delta_frozen_m": delta_frozen, "delta_eq_m": delta_eq,
            "delta_cfd_m": delta_cfd, "ratio_cfd_to_eq": ratio,
            "verdict": verdict_b,
        }
    else:
        print(f"    CFD shock-position search FAILED "
              f"(no p>2*p_inf transition found near axis)")
        check4 = {"delta_frozen_m": delta_frozen, "delta_eq_m": delta_eq,
                   "delta_cfd_m": -1.0, "verdict": "SHOCK_NOT_FOUND"}
    results["checks"]["4_billig_standoff"] = check4
    print()

    # ---- Check 5: Plasma frequency / X-band attenuation closure ----
    f_p_stag = plasma_frequency_ghz(ne_stag_cfd)
    # Also compute f_p for the published J&C peak at 61 km for comparison
    ne_published = 2.0e19   # J&C 1972 peak at 61 km/M22.5
    f_p_published = plasma_frequency_ghz(ne_published)
    print(f"[5] Plasma frequency closure:")
    print(f"    CFD ne_stag = {ne_stag_cfd:.2e} m^-3 -> f_p = {f_p_stag:.2f} GHz")
    print(f"    J&C published peak = {ne_published:.1e} m^-3 -> f_p = {f_p_published:.2f} GHz")
    blackout_threshold_ne = 1.787e18   # 12 GHz Ku-band
    f_p_eq = plasma_frequency_ghz(blackout_threshold_ne)
    print(f"    12 GHz (Ku) blackout threshold = {blackout_threshold_ne:.2e} "
          f"m^-3 -> f_p = {f_p_eq:.2f} GHz (consistency check)")
    print(f"    X-band (9.2 GHz) blackout threshold = "
          f"{(2*math.pi*9.2e9)**2 * 9.10938e-31 * 8.854e-12 / (1.6e-19**2):.2e} m^-3")
    if f_p_stag >= 12.0:
        print(f"    -> CFD predicts X-band AND Ku-band blackout at stagnation")
    elif f_p_stag >= 9.2:
        print(f"    -> CFD predicts X-band blackout but NOT Ku-band")
    else:
        print(f"    -> CFD predicts NO X-band blackout at stagnation "
              f"(suspicious for M22.5 at 61 km)")
    check5 = {
        "f_p_cfd_GHz": f_p_stag,
        "f_p_published_peak_GHz": f_p_published,
        "ne_published_peak_m3": ne_published,
        "x_band_blackout_predicted": f_p_stag >= 9.2,
        "ku_band_blackout_predicted": f_p_stag >= 12.0,
    }
    results["checks"]["5_plasma_freq_closure"] = check5
    print()

    # ---- Summary ----
    print(f"=== Summary ===")
    for name, c in results["checks"].items():
        v = c.get("verdict", c.get("verdict_T", "n/a"))
        print(f"  {name}: {v}")

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=2))
    print(f"\nWritten: {out_json}")


if __name__ == "__main__":
    main()
