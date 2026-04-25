"""Convert an AIR-5 SU2-NEMO ASCII restart to AIR-11-compatible format.

Why this exists: cold-starting AIR-11 (Mutation++) from a pure-neutral
freestream NaN's the chemistry source terms in all cells, no matter how
the cfg is tweaked. Three attempts (commits 6b72f33, 65b105d, prior)
all hit the same pathology. The canonical CFD workaround is to start
AIR-11 from a CONVERGED neutral solution (AIR-5) where the bow shock
is fully formed and chemistry has equilibrated to a steady state —
then "promote" the species count by adding trace ions on top of the
already-stable flow.

Mapping (AIR-5 -> AIR-11):
  AIR-5 species (5):  [N2, O2, NO, N, O]
  AIR-11 species (11): [e-, N+, O+, NO+, N2+, O2+, N, O, NO, N2, O2]

  AIR-5 Density_0 (N2)  ->  AIR-11 Density_9 (N2)   (slightly reduced)
  AIR-5 Density_1 (O2)  ->  AIR-11 Density_10 (O2)  (slightly reduced)
  AIR-5 Density_2 (NO)  ->  AIR-11 Density_8 (NO)   (preserved)
  AIR-5 Density_3 (N)   ->  AIR-11 Density_6 (N)    (preserved)
  AIR-5 Density_4 (O)   ->  AIR-11 Density_7 (O)    (preserved)
  AIR-11 Density_0 (e-) = SEED * rho_total          (NEW)
  AIR-11 Density_1 (N+) = SEED * rho_total          (NEW)
  AIR-11 Density_2 (O+) = SEED * rho_total          (NEW)
  AIR-11 Density_3 (NO+) = SEED * rho_total         (NEW)
  AIR-11 Density_4 (N2+) = SEED * rho_total         (NEW)
  AIR-11 Density_5 (O2+) = SEED * rho_total         (NEW)

  Total density rho preserved per cell:
    rho = sum(AIR-5 species) = sum(AIR-11 species)
  Achieved by subtracting (6*SEED*rho) from N2+O2 in the converted output.

Momentum, Energy, Energy_ve preserved verbatim — flow state unchanged.

Usage:
    python scripts/convert_air5_to_air11_restart.py \\
        --input /path/to/air5_restart.dat (ASCII) \\
        --output /path/to/air11_restart.dat (ASCII) \\
        --seed 1.0e-9
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def detect_format(input_path: Path) -> str:
    """Sniff whether the file is SU2 ASCII restart (CSV-with-quoted-headers)."""
    with open(input_path, "rb") as f:
        head = f.read(64)
    # ASCII: starts with `"PointID"` or similar quoted column name
    if head.startswith(b'"PointID"') or head.startswith(b'"x"'):
        return "ascii"
    return "binary"


def parse_air5_ascii(input_path: Path) -> tuple[list[str], list[list[str]]]:
    """Read ASCII SU2 restart, return (header tokens, list of per-row tokens)."""
    rows = []
    with open(input_path) as f:
        header_line = f.readline().rstrip("\n")
        # SU2 ASCII restart uses quoted, comma-separated column names
        # plus optional trailing whitespace.
        header = [h.strip().strip('"') for h in header_line.split(",")]
        for line in f:
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            tokens = [t.strip() for t in line.split(",")]
            rows.append(tokens)
    return header, rows


def convert(input_path: Path, output_path: Path, seed: float) -> None:
    fmt = detect_format(input_path)
    if fmt != "ascii":
        print(f"ERROR: input is not ASCII SU2 restart: {input_path}", file=sys.stderr)
        print("       Re-run AIR-5 stage briefly with RESTART_FILE_FORMAT= ASCII",
              file=sys.stderr)
        sys.exit(1)

    print(f"Reading ASCII restart from {input_path} ...")
    header, rows = parse_air5_ascii(input_path)
    print(f"  {len(header)} columns, {len(rows)} rows")
    print(f"  header: {header[:15]}...")

    # Locate the AIR-5 species columns by name.
    try:
        idx_d0 = header.index("Density_0")    # N2
        idx_d1 = header.index("Density_1")    # O2
        idx_d2 = header.index("Density_2")    # NO
        idx_d3 = header.index("Density_3")    # N
        idx_d4 = header.index("Density_4")    # O
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

    # Build new header for AIR-11 (11 species: e-, N+, O+, NO+, N2+, O2+, N, O, NO, N2, O2).
    new_header = []
    if has_pointid:
        new_header.append("PointID")
    new_header += ["x", "y", "z"]
    for i in range(11):
        new_header.append(f"Density_{i}")
    new_header += ["Momentum_x", "Momentum_y", "Momentum_z", "Energy", "Energy_ve"]

    print(f"Writing AIR-11 ASCII restart to {output_path} ...")
    n_dropped = 0
    with open(output_path, "w") as f:
        # Write quoted header
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

            # Total density per cell — preserved.
            rho = rho_n2 + rho_o2 + rho_no + rho_n + rho_o
            # 6 ions seeded at trace * rho_total each
            ion_each = seed * rho
            ion_total = 6 * ion_each
            # Subtract from N2+O2 proportionally to preserve total
            if rho_n2 + rho_o2 > 0:
                f_n2 = rho_n2 / (rho_n2 + rho_o2)
                f_o2 = rho_o2 / (rho_n2 + rho_o2)
            else:
                f_n2, f_o2 = 0.5, 0.5
            new_rho_n2 = max(rho_n2 - ion_total * f_n2, 0.0)
            new_rho_o2 = max(rho_o2 - ion_total * f_o2, 0.0)

            # AIR-11 species order: e-, N+, O+, NO+, N2+, O2+, N, O, NO, N2, O2
            new_densities = [
                ion_each,    # 0: e-
                ion_each,    # 1: N+
                ion_each,    # 2: O+
                ion_each,    # 3: NO+
                ion_each,    # 4: N2+
                ion_each,    # 5: O2+
                rho_n,       # 6: N
                rho_o,       # 7: O
                rho_no,      # 8: NO
                new_rho_n2,  # 9: N2
                new_rho_o2,  # 10: O2
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
    print(f"  seed = {seed:.1e} mass fraction per ion (6 ions = {6*seed:.1e} total)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--seed", type=float, default=1.0e-9,
                    help="Trace mass fraction per ion species (default 1e-9). "
                         "Larger seed = more chemistry to converge from but more "
                         "robust to NaN at iter 0; smaller seed = closer to AIR-5 "
                         "result but riskier for chemistry init.")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    convert(args.input, args.output, args.seed)


if __name__ == "__main__":
    main()
