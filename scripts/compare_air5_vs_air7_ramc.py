"""Side-by-side comparison: AIR-5 (Saha post) vs AIR-7 (direct CFD ne) vs Jones & Cross 1972.

Runs validate_ram_c_nemo.py on two SU2-NEMO outputs, captures both JSON
reports, and produces a diff/comparison markdown.

Why this exists: AIR-5 has 5 species (no electrons), so ne is post-processed
via Saha ionization (electron temp = T_ve, Park 2-T model). This is a hack —
real plasma chemistry has nonequilibrium ions transported by the flow. AIR-7
adds e- and NO+ as transported species, giving direct CFD ne. The improvement
should be visible in:
  1. Per-station peak ne (J&C measured at 5 reflectometer stations)
  2. Headline log10 error vs published Jones & Cross sheath peak ne
  3. dB margin against published BLACKOUT/DEGRADED/DETECTABLE labels at
     VHF (225/450 MHz) and X-band (9.2 GHz)

Usage:
    python scripts/compare_air5_vs_air7_ramc.py \\
        --air5 data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu \\
        --air7 /path/to/air7_M22_5_flow.vtu \\
        --altitude 61 --mach 22.5
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent


def run_validator(vtu_path: Path, altitude: float, mach: float,
                  out_json: Path) -> dict:
    cmd = [
        sys.executable,
        str(REPO / "scripts" / "validate_ram_c_nemo.py"),
        "--vtu", str(vtu_path),
        "--altitude", str(altitude),
        "--mach", str(mach),
        "--output-json", str(out_json),
    ]
    print(f"\n{'=' * 70}")
    print(f"Running validator on: {vtu_path.name}")
    print(f"{'=' * 70}")
    try:
        subprocess.run(cmd, check=True, capture_output=False)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: validator failed for {vtu_path}: {e}", file=sys.stderr)
        sys.exit(2)
    if not out_json.exists():
        print(f"ERROR: validator didn't write {out_json}", file=sys.stderr)
        sys.exit(2)
    return json.loads(out_json.read_text())


def safe_log10_ratio(num: float, den: float) -> float | None:
    if num is None or den is None or num <= 0 or den <= 0:
        return None
    return math.log10(num / den)


def fmt_log10(value: float | None) -> str:
    if value is None or value != value:
        return "  -  "
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}"


def fmt_ne(ne: float) -> str:
    if not ne or ne <= 0:
        return "  -  "
    return f"{ne:.2e}"


def fmt_db(db: float) -> str:
    if db is None or db != db:
        return "  -  "
    return f"{db:+6.1f}"


def compare_reports(air5: dict, air7: dict) -> str:
    fc5 = air5.get("flight_condition", {})
    lines = []
    lines.append("# AIR-5 (Saha post-process) vs AIR-7 (direct CFD ne)")
    lines.append("")
    lines.append(f"**Conditions**: Mach {fc5.get('mach', '?')} @ "
                 f"{fc5.get('altitude_km', '?')} km altitude")
    lines.append("")
    ref = air5.get("reference") or air7.get("reference") or {}
    if ref:
        lines.append(f"**Reference**: {ref.get('source', 'Jones & Cross 1972')}")
        pub = ref.get("ne_peak_m3")
        lo, hi = ref.get("ne_lower"), ref.get("ne_upper")
        if pub:
            lines.append(f"  Published peak ne: {pub:.2e} m⁻³ "
                         f"(range {lo:.1e}–{hi:.1e})")
    lines.append("")

    # Headline log10 error
    h5 = air5.get("log10_error_vs_published")
    h7 = air7.get("log10_error_vs_published")
    lines.append("## Headline log10 error vs J&C peak ne")
    lines.append("")
    lines.append(f"- **AIR-5 (Saha post)**: {fmt_log10(h5)}")
    lines.append(f"- **AIR-7 (direct CFD)**: {fmt_log10(h7)}")
    if h5 is not None and h7 is not None:
        improvement = abs(h5) - abs(h7)
        verdict = "improvement" if improvement > 0 else "worsening"
        lines.append(f"- **Δ |log10 err|**: {abs(improvement):.2f} ({verdict})")
    lines.append("")

    # Sheath peak (apples-to-apples vs J&C)
    sh5 = air5.get("sheath_peak_ne", {})
    sh7 = air7.get("sheath_peak_ne", {})
    lines.append("## Sheath peak ne (best reflectometer station)")
    lines.append("")
    lines.append("| Run | sheath ne_p99 | Matched z/L | Δ vs published |")
    lines.append("|-----|---------------|-------------|----------------|")
    pub_ne = ref.get("ne_peak_m3") if ref else None
    for tag, sh in [("AIR-5", sh5), ("AIR-7", sh7)]:
        ne = sh.get("ne_m3", 0)
        zL = sh.get("matched_station_zL")
        zL_str = f"{zL:.2f}" if zL is not None else " - "
        d = safe_log10_ratio(ne, pub_ne) if pub_ne else None
        lines.append(f"| {tag} | {fmt_ne(ne)} | {zL_str} | {fmt_log10(d)} |")
    lines.append("")

    # Per-station table
    lines.append("## Per-station sheath ne (J&C reflectometer locations)")
    lines.append("")
    lines.append("| z/L | AIR-5 ne_p99 | AIR-7 ne_p99 | Δ log10 (7−5) |")
    lines.append("|-----|--------------|--------------|----------------|")
    sp5 = {s["zL"]: s for s in air5.get("station_profile", [])}
    sp7 = {s["zL"]: s for s in air7.get("station_profile", [])}
    for zL in sorted(set(sp5) | set(sp7)):
        s5 = sp5.get(zL, {})
        s7 = sp7.get(zL, {})
        ne5 = s5.get("p99_ne_m3", 0) or 0
        ne7 = s7.get("p99_ne_m3", 0) or 0
        d = safe_log10_ratio(ne7, ne5)
        lines.append(f"| {zL:.2f} | {fmt_ne(ne5)} | {fmt_ne(ne7)} | {fmt_log10(d)} |")
    lines.append("")

    # Domain peak (diagnostic)
    dp5 = air5.get("domain_peak_ne", {})
    dp7 = air7.get("domain_peak_ne", {})
    lines.append("## Domain peak ne (stagnation — diagnostic only)")
    lines.append("")
    lines.append("| Run | ne_robust | T_tr | Location |")
    lines.append("|-----|-----------|------|----------|")
    for tag, dp in [("AIR-5", dp5), ("AIR-7", dp7)]:
        ne = dp.get("ne_m3", 0)
        T = dp.get("T_tr_K", 0)
        loc = dp.get("location_xyz", [0, 0, 0])
        loc_str = f"({loc[0]:.2f}, {loc[1]:.2f}, {loc[2]:.2f}) m"
        lines.append(f"| {tag} | {fmt_ne(ne)} | {T:.0f} K | {loc_str} |")
    lines.append("")

    # dB margins per band
    asp5 = air5.get("aspect_scan_by_frequency", {})
    asp7 = air7.get("aspect_scan_by_frequency", {})
    if asp5 or asp7:
        lines.append("## LOS attenuation (worst aspect across angle scan)")
        lines.append("")
        lines.append("| Band | Freq | AIR-5 dB | AIR-7 dB | J&C status | AIR-5 verdict | AIR-7 verdict |")
        lines.append("|------|------|----------|----------|------------|---------------|---------------|")
        for band in sorted(set(asp5) | set(asp7)):
            b5 = asp5.get(band, {})
            b7 = asp7.get(band, {})
            f_hz = b5.get("frequency_hz") or b7.get("frequency_hz") or 0
            db5 = b5.get("max_attenuation_db", float("nan"))
            db7 = b7.get("max_attenuation_db", float("nan"))
            pub = b5.get("published_status") or b7.get("published_status") or "?"
            v5 = b5.get("db_margin_verdict", "?")
            v7 = b7.get("db_margin_verdict", "?")
            margin5 = b5.get("db_margin_to_published_band")
            margin7 = b7.get("db_margin_to_published_band")
            db5s = (f"{db5:.1f} ({fmt_db(margin5)})" if margin5 is not None
                    else f"{db5:.1f}")
            db7s = (f"{db7:.1f} ({fmt_db(margin7)})" if margin7 is not None
                    else f"{db7:.1f}")
            lines.append(
                f"| {band} | {f_hz/1e9:.2f} GHz | {db5s} | {db7s} | "
                f"{pub} | {v5} | {v7} |"
            )
        lines.append("")

    # Notes
    lines.append("## Notes")
    lines.append("")
    lines.append("- AIR-5 ne uses Park 2-T Saha post-process (T_e = T_ve).")
    lines.append("  Saha assumes equilibrium — real plasma is nonequilibrium.")
    lines.append("- AIR-7 ne is the transported electron mass density "
                 "(Density_0 / m_e).")
    lines.append("  Captures recombination, dissociative attachment, charge transfer kinetics.")
    lines.append("- Negative log10 err = under-prediction; positive = over-prediction.")
    lines.append("- dB margin: distance from the J&C published band edge. "
                 "Negative = inside band (consistent with status), "
                 "positive = outside (inconsistent).")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--air5", required=True, type=Path,
                    help="Path to AIR-5 SU2-NEMO flow.vtu")
    ap.add_argument("--air7", required=True, type=Path,
                    help="Path to AIR-7 SU2-NEMO flow.vtu")
    ap.add_argument("--altitude", type=float, required=True, help="km")
    ap.add_argument("--mach", type=float, required=True)
    ap.add_argument("--output-md", default=None, type=Path)
    args = ap.parse_args()

    if not args.air5.exists():
        print(f"ERROR: AIR-5 VTU not found: {args.air5}", file=sys.stderr)
        sys.exit(1)
    if not args.air7.exists():
        print(f"ERROR: AIR-7 VTU not found: {args.air7}", file=sys.stderr)
        sys.exit(1)

    out_md = args.output_md or (
        REPO / "docs" / f"air5_vs_air7_M{args.mach:g}_A{args.altitude:g}.md")
    tmp_dir = Path("/tmp" if Path("/tmp").exists() else REPO / "data" / "tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    air5 = run_validator(args.air5, args.altitude, args.mach,
                         tmp_dir / "ram_c_air5_validation.json")
    air7 = run_validator(args.air7, args.altitude, args.mach,
                         tmp_dir / "ram_c_air7_validation.json")

    md = compare_reports(air5, air7)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(md, encoding="utf-8")
    print(f"\n{'=' * 70}")
    print(f"Comparison written to {out_md}")
    print(f"{'=' * 70}")
    print(md)


if __name__ == "__main__":
    main()
