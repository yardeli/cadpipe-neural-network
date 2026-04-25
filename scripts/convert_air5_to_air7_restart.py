"""Convert AIR-5 SU2-NEMO ASCII restart to AIR-7-compatible format.

Why this exists: AIR-11 + Mutation++ cold-start (and warm-start from
AIR-5 converted restart) keeps NaN'ing because Mutation++'s EOS conventions
differ from SU2-NEMO's built-in CSU2TCLib (different formation enthalpies,
different mode partitioning of internal energy). Five separate attempts
hit the same "non-physical cells + NaN chemistry" pathology.

AIR-7 sidesteps this by using the SAME built-in CSU2TCLib EOS as AIR-5.
Restart values (Density, Energy, Energy_ve) are interpreted identically
between the two — only the species count and reactions change.

Mapping (AIR-5 -> AIR-7):
  AIR-5 species (5):  [N2, O2, NO, N, O]
  AIR-7 species (7):  [e-, N2, O2, NO, N, O, NO+]
                       (verified from CSU2TCLib.cpp lines 686-684)

  AIR-5 Density_0 (N2) -> AIR-7 Density_1 (N2)   (preserved, slight reduction)
  AIR-5 Density_1 (O2) -> AIR-7 Density_2 (O2)   (preserved, slight reduction)
  AIR-5 Density_2 (NO) -> AIR-7 Density_3 (NO)   (preserved)
  AIR-5 Density_3 (N)  -> AIR-7 Density_4 (N)    (preserved)
  AIR-5 Density_4 (O)  -> AIR-7 Density_5 (O)    (preserved)
  AIR-7 Density_0 (e-) = SEED * rho * (M_e/M_NO+) (NEW, charge-balanced)
  AIR-7 Density_6 (NO+) = SEED * rho             (NEW)

  Charge balance: rho_e * N_A / M_e = rho_NO+ * N_A / M_NO+
  i.e. rho_e = SEED * rho * (M_e / M_NO+) ≈ SEED * rho * 1.83e-5

  Total density rho preserved per cell:
    rho = sum(AIR-5 species) = sum(AIR-7 species)
  Achieved by subtracting (rho_e + rho_NO+) from N2+O2 in the converted output.

Energy and Energy_ve preserved verbatim — flow state unchanged. Trace ions
contribute negligibly to internal energy (1e-9 mass × 1e6 J/kg ~ 1e-3 J/kg
vs. e_internal ~ 1e6 J/kg = 1e-9 ratio).

Usage:
    python scripts/convert_air5_to_air7_restart.py \\
        --input /path/to/air5_restart.csv (ASCII) \\
        --output /path/to/air7_restart.csv (ASCII) \\
        --seed 1.0e-9
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_air5_ascii(input_path: Path) -> tuple[list[str], list[list[str]]]:
    """Read ASCII SU2 restart, return (header tokens, list of per-row tokens)."""
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
    print(f"  header: {header[:15]}...")

    try:
        idx_d0 = header.index("Density_0")    # AIR-5 N2
        idx_d1 = header.index("Density_1")    # AIR-5 O2
        idx_d2 = header.index("Density_2")    # AIR-5 NO
        idx_d3 = header.index("Density_3")    # AIR-5 N
        idx_d4 = header.index("Density_4")    # AIR-5 O
        idx_mx = header.index("Momentum_x")
        idx_my = header.index("Momentum_y")
        idx_mz = header.index("Momentum_z")
        idx_E  = header.index("Energy")
        idx_Eve = header.index("Energy_ve")
    except ValueError as exc:
        print(f"ERROR: required column missing: {exc}", file=sys.stderr)
        print(f"       Available columns: {header}", file=sys.stderr)
        sys.exit(2)

    has_pointid = header[0].lower() == "pointid"
    coord_idx = (1, 2, 3) if has_pointid else (0, 1, 2)

    # AIR-7 header (7 species: e-, N2, O2, NO, N, O, NO+)
    new_header = []
    if has_pointid:
        new_header.append("PointID")
    new_header += ["x", "y", "z"]
    for i in range(7):
        new_header.append(f"Density_{i}")
    new_header += ["Momentum_x", "Momentum_y", "Momentum_z", "Energy", "Energy_ve"]

    # Charge-balance ratio: M_e / M_NO+ (in kg/mol)
    M_e = 5.486e-7
    M_NO_p = 0.030
    e_per_ion = M_e / M_NO_p  # ~1.83e-5

    print(f"Writing AIR-7 ASCII restart to {output_path} ...")
    print(f"  seed = {seed:.1e} mass fraction NO+; e- = {seed*e_per_ion:.2e} (charge-balanced)")
    n_dropped = 0
    with open(output_path, "w") as f:
        f.write(",".join(f'"{h}"' for h in new_header) + "\n")

        for r_idx, tokens in enumerate(rows):
            try:
                rho_n2  = float(tokens[idx_d0])
                rho_o2  = float(tokens[idx_d1])
                rho_no  = float(tokens[idx_d2])
                rho_n   = float(tokens[idx_d3])
                rho_o   = float(tokens[idx_d4])
                mx      = float(tokens[idx_mx])
                my      = float(tokens[idx_my])
                mz      = float(tokens[idx_mz])
                E       = float(tokens[idx_E])
                Eve     = float(tokens[idx_Eve])
            except (IndexError, ValueError):
                n_dropped += 1
                continue

            rho = rho_n2 + rho_o2 + rho_no + rho_n + rho_o
            rho_NO_p = seed * rho
            rho_e = rho_NO_p * e_per_ion
            ion_total_mass = rho_NO_p + rho_e

            # Subtract from N2+O2 proportionally to preserve total rho
            if rho_n2 + rho_o2 > 0:
                f_n2 = rho_n2 / (rho_n2 + rho_o2)
                f_o2 = rho_o2 / (rho_n2 + rho_o2)
            else:
                f_n2, f_o2 = 0.5, 0.5
            new_rho_n2 = max(rho_n2 - ion_total_mass * f_n2, 0.0)
            new_rho_o2 = max(rho_o2 - ion_total_mass * f_o2, 0.0)

            # AIR-7 species order: e-, N2, O2, NO, N, O, NO+
            new_densities = [
                rho_e,        # 0: e-
                new_rho_n2,   # 1: N2
                new_rho_o2,   # 2: O2
                rho_no,       # 3: NO
                rho_n,        # 4: N
                rho_o,        # 5: O
                rho_NO_p,     # 6: NO+
            ]

            row_out = []
            if has_pointid:
                row_out.append(tokens[0])
            row_out.append(tokens[coord_idx[0]])
            row_out.append(tokens[coord_idx[1]])
            row_out.append(tokens[coord_idx[2]])
            for d in new_densities:
                row_out.append(f"{d:.16e}")
            row_out.append(f"{mx:.16e}")
            row_out.append(f"{my:.16e}")
            row_out.append(f"{mz:.16e}")
            row_out.append(f"{E:.16e}")
            row_out.append(f"{Eve:.16e}")

            f.write(",".join(row_out) + "\n")

    if n_dropped:
        print(f"  WARNING: dropped {n_dropped} malformed rows", file=sys.stderr)
    print(f"  wrote {output_path}, {len(rows) - n_dropped} cells")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--seed", type=float, default=1.0e-9,
                    help="NO+ trace mass fraction (default 1e-9). "
                         "Electron mass derived from charge balance "
                         "(rho_e = seed * rho * M_e/M_NO+ ~ seed * 1.83e-5).")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    convert(args.input, args.output, args.seed)


if __name__ == "__main__":
    main()
