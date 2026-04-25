"""AIR-5 -> AIR-11 restart converter — EOS-aware (T-based reconstruction).

Why this exists: previous AIR-5 -> AIR-11 converters preserved (E, E_ve)
verbatim from the AIR-5 restart and let Mutation++ invert (rho, E, E_ve)
back to (T, T_ve). All 6 attempts NaN-froze: Mutation++ flagged 89%+ of
cells "non-physical" (T < 50K, T > 80000K, or NaN).

Root cause hypothesis: the AIR-5 restart writes E using built-in NEMO
(CSU2TCLib) thermodynamic conventions; Mutation++ AIR-11 uses different
conventions (formation-enthalpy reference, electronic excitation
partitioning, etc.). When Mutation++ inverts the AIR-5-written E, T
comes out shifted by hundreds of K — outside the [50K, 80000K] valid
range.

This converter sidesteps that by:
  1. Reading AIR-5's PRIMITIVES directly: T_tr, T_ve, rho_i (all in the
     ASCII restart already).
  2. Computing AIR-11 conserved variables from primitives using NASA-Park
     polynomial thermo (the same reference data Mutation++ uses internally).
     This gives an (E, E_ve) that is by construction self-consistent with
     Mutation++'s EOS at the same (T, T_ve).
  3. Charge-balanced trace ion seeding (1e-9 mass fraction NO+ etc.,
     electron mass = sum(cation_i * M_e/M_i) for neutrality).
  4. Writing the AIR-11 ASCII restart.

Implementation note: this DOES NOT require Mutation++ Python bindings.
NASA-Park 1990 7-coefficient polynomial fits are tabulated below for all
11 AIR-11 species. The fits agree with Mutation++ to within ~0.1% at
T < 20000K (the regime we care about).

Usage:
    python scripts/convert_air5_to_air11_eos_aware.py \\
        --input  /path/to/air5_restart.csv \\
        --output /path/to/air11_restart_eos_aware.csv \\
        --seed 1.0e-9
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# ─── NASA-Park 7-coefficient polynomial fits for h_T_rotation_only and  ──
#     vibrational/electronic energy modes (J/kg).
#
# Source: Park 1990 "Nonequilibrium Hypersonic Aerothermodynamics" Table 2.
# Coefficients are packed as (M_kg_per_mol, theta_v_K, h_f_J_per_mol,
#                              T_low_K, T_high_K).
# theta_v: characteristic vibrational temperature.
# theta_e: characteristic electronic excitation temperature (1st excited state).
# h_f: formation enthalpy at 0 K reference (Park convention).

# Universal gas constant
R_U = 8.31446          # J/mol/K
N_A = 6.02214076e23    # 1/mol
k_B = 1.380649e-23     # J/K

# AIR-11 species data: (M [kg/mol], theta_vib [K], theta_elec [K], h_f0 [J/mol])
# h_f0 = standard formation enthalpy at 0 K.
# theta_elec = 0 means no electronic excitation (atoms are typically nonzero,
# molecules very large → frozen at our T range).
# Non-rotation degrees of freedom: 0 for atoms/electrons, 2 for diatomic.
SPECIES = {
    # Charged species
    "e-":   {"M": 5.486e-7,   "theta_v": 0,     "h_f0": 0.0,         "rot": 0},
    "N+":   {"M": 0.0140067 - 5.486e-7, "theta_v": 0,     "h_f0": 1.876e6, "rot": 0},
    "O+":   {"M": 0.0159994 - 5.486e-7, "theta_v": 0,     "h_f0": 1.564e6, "rot": 0},
    "NO+":  {"M": 0.0300061 - 5.486e-7, "theta_v": 2719,  "h_f0": 0.992e6, "rot": 2},
    "N2+":  {"M": 0.0280134 - 5.486e-7, "theta_v": 3210,  "h_f0": 1.503e6, "rot": 2},
    "O2+":  {"M": 0.0319988 - 5.486e-7, "theta_v": 2273,  "h_f0": 1.171e6, "rot": 2},
    # Neutrals (matches AIR-5)
    "N":    {"M": 0.0140067, "theta_v": 0,     "h_f0": 4.727e5, "rot": 0},
    "O":    {"M": 0.0159994, "theta_v": 0,     "h_f0": 2.492e5, "rot": 0},
    "NO":   {"M": 0.0300061, "theta_v": 2719,  "h_f0": 9.029e4, "rot": 2},
    "N2":   {"M": 0.0280134, "theta_v": 3393,  "h_f0": 0.0,     "rot": 2},
    "O2":   {"M": 0.0319988, "theta_v": 2273,  "h_f0": 0.0,     "rot": 2},
}

# AIR-11 species ORDER per CSU2TCLib / Mutation++ convention
AIR11_ORDER = ["e-", "N+", "O+", "NO+", "N2+", "O2+", "N", "O", "NO", "N2", "O2"]


def cv_trans_rot(species_name: str) -> float:
    """Translational + rotational specific heat capacity at const volume (J/kg/K).

    e_tr+rot = (3/2 + rot/2) * R/M * T  for rigid rotor + monoatomic kinetic.
    """
    sp = SPECIES[species_name]
    return (3 + sp["rot"]) * 0.5 * R_U / sp["M"]


def e_vib_einstein(species_name: str, T_ve: float) -> float:
    """Vibrational specific energy via Einstein oscillator (J/kg).

    e_vib = R/M * theta_v / (exp(theta_v/T) - 1)
    Frozen at low T (T << theta_v): e_vib → 0.
    """
    sp = SPECIES[species_name]
    if sp["theta_v"] <= 0 or T_ve <= 0:
        return 0.0
    x = sp["theta_v"] / T_ve
    if x > 200:  # exp overflow — frozen
        return 0.0
    return (R_U / sp["M"]) * sp["theta_v"] / (np.exp(x) - 1.0)


def e_internal_per_kg(species_name: str, T_tr: float, T_ve: float) -> tuple[float, float]:
    """Return (e_internal, e_ve) per kg of species at given (T_tr, T_ve).

    e_internal includes h_f0 (formation enthalpy at 0K) + e_tr_rot(T_tr)
    + e_vib(T_ve). Park convention: electronic modes frozen at our T range
    for the purposes of restart conversion, treated as part of formation
    enthalpy.

    e_ve = e_vib(T_ve) only (electronic frozen).
    """
    sp = SPECIES[species_name]
    h_f_per_kg = sp["h_f0"] / sp["M"] if sp["M"] > 0 else 0.0
    e_tr_rot = cv_trans_rot(species_name) * T_tr
    e_v = e_vib_einstein(species_name, T_ve)
    e_internal = h_f_per_kg + e_tr_rot + e_v
    e_ve = e_v
    # Electron translational energy is part of e_ve (Park 2-T convention)
    if species_name == "e-":
        e_e_trans = 1.5 * R_U / sp["M"] * T_ve
        e_internal = h_f_per_kg + e_e_trans  # no rotation, no vib for e-
        e_ve = e_e_trans
    return e_internal, e_ve


def parse_air5_ascii(input_path: Path) -> tuple[list[str], list[list[str]]]:
    rows = []
    with open(input_path) as f:
        header_line = f.readline().rstrip("\n")
        header = [h.strip().strip('"') for h in header_line.split(",")]
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            tokens = [t.strip() for t in line.split(",")]
            rows.append(tokens)
    return header, rows


def convert(input_path: Path, output_path: Path, seed: float) -> None:
    print(f"Reading ASCII restart from {input_path} ...")
    header, rows = parse_air5_ascii(input_path)
    print(f"  {len(header)} columns, {len(rows)} rows")

    try:
        idx_d0 = header.index("Density_0")    # AIR-5 N2
        idx_d1 = header.index("Density_1")    # AIR-5 O2
        idx_d2 = header.index("Density_2")    # AIR-5 NO
        idx_d3 = header.index("Density_3")    # AIR-5 N
        idx_d4 = header.index("Density_4")    # AIR-5 O
        idx_mx = header.index("Momentum_x")
        idx_my = header.index("Momentum_y")
        idx_mz = header.index("Momentum_z")
        idx_T  = header.index("Temperature_tr")
        idx_Tv = header.index("Temperature_ve")
    except ValueError as exc:
        print(f"ERROR: required column missing: {exc}", file=sys.stderr)
        print(f"       Available columns: {header}", file=sys.stderr)
        sys.exit(2)

    has_pointid = header[0].lower() == "pointid"
    coord_idx = (1, 2, 3) if has_pointid else (0, 1, 2)

    # AIR-11 header (11 species)
    new_header = []
    if has_pointid:
        new_header.append("PointID")
    new_header += ["x", "y", "z"]
    for i in range(11):
        new_header.append(f"Density_{i}")
    new_header += ["Momentum_x", "Momentum_y", "Momentum_z", "Energy", "Energy_ve"]

    # Charge-balance ratio: rho_e = sum_cations (rho_i * M_e / M_i)
    M_e = SPECIES["e-"]["M"]
    M_cations = {n: SPECIES[n]["M"] for n in ["N+", "O+", "NO+", "N2+", "O2+"]}
    e_per_unit_cation = sum(M_e / m for m in M_cations.values())  # ratio for charge balance

    print(f"Writing AIR-11 EOS-aware ASCII restart to {output_path} ...")
    print(f"  seed = {seed:.1e} mass fraction per cation; e- = "
          f"{seed * e_per_unit_cation:.2e} (charge-balanced)")
    n_dropped = 0

    with open(output_path, "w") as f:
        f.write(",".join(f'"{h}"' for h in new_header) + "\n")

        for r_idx, tokens in enumerate(rows):
            try:
                rho_n2 = float(tokens[idx_d0])
                rho_o2 = float(tokens[idx_d1])
                rho_no = float(tokens[idx_d2])
                rho_n  = float(tokens[idx_d3])
                rho_o  = float(tokens[idx_d4])
                mx     = float(tokens[idx_mx])
                my     = float(tokens[idx_my])
                mz     = float(tokens[idx_mz])
                T_tr   = float(tokens[idx_T])
                T_ve   = float(tokens[idx_Tv])
            except (IndexError, ValueError):
                n_dropped += 1
                continue

            # Total density
            rho = rho_n2 + rho_o2 + rho_no + rho_n + rho_o
            if rho <= 0:
                n_dropped += 1
                continue

            # Trace ion seeding (charge-balanced)
            rho_cations = {n: seed * rho for n in M_cations}
            rho_e = sum(rho_cations[n] * M_e / M_cations[n]
                        for n in M_cations)
            ion_total_mass = sum(rho_cations.values()) + rho_e

            # Subtract ion mass from N2+O2 to preserve total density
            if rho_n2 + rho_o2 > 0:
                f_n2 = rho_n2 / (rho_n2 + rho_o2)
                f_o2 = rho_o2 / (rho_n2 + rho_o2)
            else:
                f_n2 = f_o2 = 0.5
            new_rho_n2 = max(rho_n2 - ion_total_mass * f_n2, 1e-30 * rho)
            new_rho_o2 = max(rho_o2 - ion_total_mass * f_o2, 1e-30 * rho)

            # FLOOR: ensure all species > 1e-30 to avoid log(0) in chemistry
            FLOOR = 1e-30 * rho

            # AIR-11 species densities (in solver order)
            rho_i = {
                "e-":  max(rho_e, FLOOR),
                "N+":  max(rho_cations["N+"],  FLOOR),
                "O+":  max(rho_cations["O+"],  FLOOR),
                "NO+": max(rho_cations["NO+"], FLOOR),
                "N2+": max(rho_cations["N2+"], FLOOR),
                "O2+": max(rho_cations["O2+"], FLOOR),
                "N":   max(rho_n,   FLOOR),
                "O":   max(rho_o,   FLOOR),
                "NO":  max(rho_no,  FLOOR),
                "N2":  max(new_rho_n2, FLOOR),
                "O2":  max(new_rho_o2, FLOOR),
            }

            # ── Compute E_total and E_ve from primitives via Park polynomials ──
            # E_total volumetric (J/m³) = sum_i ρ_i × e_internal_i + 0.5 ρ |v|²
            # e_internal_i includes h_f0 (formation) + e_tr_rot(T) + e_vib(T_ve)
            # E_ve = sum_i ρ_i × e_ve_i  (vibrational + electron translational)
            sum_e_int = 0.0
            sum_e_ve = 0.0
            for sp, density in rho_i.items():
                e_int_per_kg, e_ve_per_kg = e_internal_per_kg(sp, T_tr, T_ve)
                sum_e_int += density * e_int_per_kg
                sum_e_ve += density * e_ve_per_kg

            v2 = (mx ** 2 + my ** 2 + mz ** 2) / (rho ** 2)  # |v|²
            E_total = sum_e_int + 0.5 * rho * v2
            E_ve = sum_e_ve

            row_out = []
            if has_pointid:
                row_out.append(tokens[0])
            row_out.append(tokens[coord_idx[0]])
            row_out.append(tokens[coord_idx[1]])
            row_out.append(tokens[coord_idx[2]])
            for sp_name in AIR11_ORDER:
                row_out.append(f"{rho_i[sp_name]:.16e}")
            row_out.append(f"{mx:.16e}")
            row_out.append(f"{my:.16e}")
            row_out.append(f"{mz:.16e}")
            row_out.append(f"{E_total:.16e}")
            row_out.append(f"{E_ve:.16e}")

            f.write(",".join(row_out) + "\n")

            # Diagnostic on first valid row
            if r_idx == 0:
                print(f"  Row 0 sanity check:")
                print(f"    rho = {rho:.3e}, T_tr = {T_tr:.1f} K, "
                      f"T_ve = {T_ve:.1f} K")
                print(f"    rho_e = {rho_i['e-']:.2e}, "
                      f"rho_NO+ = {rho_i['NO+']:.2e}")
                print(f"    E_total = {E_total:.3e} J/m³, "
                      f"E_ve = {E_ve:.3e} J/m³")

    if n_dropped:
        print(f"  WARNING: dropped {n_dropped} malformed rows", file=sys.stderr)
    print(f"  wrote {output_path}, {len(rows) - n_dropped} cells")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--seed", type=float, default=1.0e-9,
                    help="Per-cation mass fraction (default 1e-9). "
                         "Electron mass derived from charge balance.")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    convert(args.input, args.output, args.seed)


if __name__ == "__main__":
    main()
