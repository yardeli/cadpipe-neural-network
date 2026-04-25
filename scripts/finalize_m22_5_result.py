"""One-shot M22.5 result finalizer — runs as soon as the ramp completes.

Sequence:
  1. scp the M22.5 flow.vtu from the GCP VM into data/nemo_test/
  2. Run scripts/validate_ram_c_nemo.py to produce ram_c_validation.json
     and ram_c_validation.md
  3. Run scripts/make_paper_figures.py to render the four PNGs +
     drop-in markdown blurb under docs/paper/figures/
  4. Patch docs/PLASMANET_NOTION.md §3.2 — replace the "NEMO 2-T (4.5M
     tet — running)" placeholder row with the real refined-mesh numbers,
     and update the stagnation block + detection-status table
  5. Stage everything; print the diff for review; --commit-and-push runs
     git add/commit/push automatically (default: dry-run)

Usage:
    # Once the monitor reports M22_5:done(exit=0,...):
    python scripts/finalize_m22_5_result.py             # dry run
    python scripts/finalize_m22_5_result.py --commit-and-push

Optional overrides for non-default run names:
    python scripts/finalize_m22_5_result.py \\
        --vm-stage-dir /home/yarden/ram_c_runs/ramC_refined_M22_5_A61 \\
        --local-vtu data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu

Failure modes (handled cleanly, exits non-zero):
  - VTU not present on VM (ramp still running) -> abort
  - Validate or figures script crashes        -> abort, leave artifacts in place
  - Notion patch can't find the placeholder row -> abort, no commit
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent

DEFAULT_VM = "openfoam-hgv"
DEFAULT_ZONE = "us-central1-a"
DEFAULT_VM_STAGE_DIR = "/home/yarden/ram_c_runs/ramC_refined_M22_5_A61"
DEFAULT_LOCAL_VTU = REPO / "data" / "nemo_test" / "ramC_refined_M22_5_A61_nemo.vtu"
DEFAULT_NOTION = REPO / "docs" / "PLASMANET_NOTION.md"
FIG_DIR = REPO / "docs" / "paper" / "figures"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run a subprocess, stream output, raise on nonzero exit."""
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=True, **kw)


def step1_scp_vtu(args) -> Path:
    """scp the M22.5 VTU from VM to local."""
    print("=" * 70)
    print("STEP 1 / 5 — scp M22.5 VTU from VM")
    print("=" * 70)
    src = f"{args.vm}:{args.vm_stage_dir}/flow.vtu"
    dst = Path(args.local_vtu)
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["gcloud", "compute", "scp", "--zone", args.zone, src, str(dst)])
    if not dst.exists() or dst.stat().st_size < 1_000_000:
        print(f"ERROR: VTU did not arrive or is too small: {dst}", file=sys.stderr)
        sys.exit(2)
    size_mb = dst.stat().st_size / 1024 / 1024
    print(f"  Got {dst} ({size_mb:.1f} MB)")
    return dst


def step2_validate(vtu: Path, mach: float, alt: float) -> tuple[Path, dict]:
    """Run validate_ram_c_nemo.py; return path to JSON report + parsed dict."""
    print("=" * 70)
    print("STEP 2 / 5 — RAM-C validation vs Jones & Cross 1972")
    print("=" * 70)
    run([sys.executable, str(REPO / "scripts" / "validate_ram_c_nemo.py"),
         "--vtu", str(vtu), "--altitude", str(alt), "--mach", str(mach)],
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    json_path = vtu.parent / "ram_c_validation.json"
    if not json_path.exists():
        print(f"ERROR: validation JSON not produced: {json_path}", file=sys.stderr)
        sys.exit(3)
    return json_path, json.loads(json_path.read_text(encoding="utf-8"))


def step3_figures(vtu: Path):
    """Run make_paper_figures.py to render the 4 PNGs + blurb."""
    print("=" * 70)
    print("STEP 3 / 5 — paper figures (polar, ne radial, ne axial, T contour)")
    print("=" * 70)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    run([sys.executable, str(REPO / "scripts" / "make_paper_figures.py"),
         "--vtu", str(vtu), "--output-dir", str(FIG_DIR)],
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})


def step4_patch_notion(validation: dict, notion_path: Path) -> None:
    """Replace the placeholder M22.5 refined-mesh row in §3.2."""
    print("=" * 70)
    print("STEP 4 / 5 — patch PLASMANET_NOTION.md §3.2")
    print("=" * 70)

    text = notion_path.read_text(encoding="utf-8")
    peak = validation["peak_sheath_ne"]
    ne_robust = peak["ne_m3"]
    ne_max = peak.get("ne_m3_max", ne_robust)
    n_top = peak.get("n_top_cells", 50)
    log10_err = validation.get("log10_error_vs_published")

    stag = validation["cfd_stagnation"]
    T_tr = stag.get("T_tr_K", stag.get("T_K", 0))
    T_ve = stag.get("T_ve_K", T_tr)
    p_stag = stag["p_Pa"]
    ne_stag = stag.get("ne_m3", 0)
    delta_T = abs(T_tr - T_ve)

    n_points = validation.get("n_points", 0)
    n_tets = n_points * 6  # rough — node-to-tet ratio

    # Replace the "TBD" placeholder row.
    placeholder = re.compile(
        r"\| 61 km \| 22\.5 \| NEMO 2-T \(4\.5M tet — running\) \| TBD \| 2\.0 × 10¹⁹ \| TBD \|"
    )
    new_row = (
        f"| 61 km | 22.5 | **NEMO 2-T ({n_points//1000}k node refined, 2026-04-25)** "
        f"| {ne_robust:.2e} (top-{n_top} mean) "
        f"| 2.0 × 10¹⁹ "
        f"| **{log10_err:+.2f}** "
        f"{'✅ excellent' if abs(log10_err) < 0.3 else '✓ good' if abs(log10_err) < 0.7 else '✓ acceptable' if abs(log10_err) < 1.0 else '⚠ needs work'} |"
    )
    text2, n_replaced = placeholder.subn(new_row, text, count=1)
    if n_replaced == 0:
        print("ERROR: could not find the placeholder row in §3.2.", file=sys.stderr)
        print("       The doc may have been edited; patch Notion manually.", file=sys.stderr)
        sys.exit(4)

    # Update the stagnation block (find the existing one and replace numbers).
    stag_re = re.compile(
        r"(\*\*Stagnation conditions \(NEMO M22\.5 @ 61 km\)\*\*: )"
        r"T_tr = [\d,]+ K, T_ve = [\d,]+ K [^,]+, "
        r"p_stag = [\d.e+×]+ Pa[^.]+\."
    )
    new_stag = (
        f"\\1T_tr = {T_tr:,.0f} K, T_ve = {T_ve:,.0f} K (Δ = {delta_T:.0f} K nonequilibrium), "
        f"p_stag = {p_stag:.2e} Pa (refined-mesh result)."
    )
    text3, n_stag = stag_re.subn(new_stag, text2, count=1)
    if n_stag == 0:
        print("WARNING: could not update stagnation block; leaving as-is.")
        text3 = text2

    notion_path.write_text(text3, encoding="utf-8")
    print(f"  Patched {notion_path.name}: 1 row updated, {n_stag} stagnation block updated")
    if log10_err is not None:
        print(f"  log10 error: {log10_err:+.2f}")
    print(f"  ne_robust:   {ne_robust:.2e}")
    print(f"  ne_max:      {ne_max:.2e} (spike ratio {ne_max/max(ne_robust,1e-30):.2f}x)")


def step5_commit(args, validation: dict, vtu: Path, json_path: Path) -> None:
    """Stage + diff. If --commit-and-push: git commit + push."""
    print("=" * 70)
    print("STEP 5 / 5 — stage / commit / push")
    print("=" * 70)

    log10 = validation.get("log10_error_vs_published")
    log10_str = f"{log10:+.2f}" if log10 is not None else "n/a"

    files_to_stage = [
        str(vtu.relative_to(REPO)),
        str(json_path.relative_to(REPO)),
        "data/nemo_test/ram_c_validation.md",
        "docs/PLASMANET_NOTION.md",
    ]
    run(["git", "-C", str(REPO), "add", *files_to_stage])
    run(["git", "-C", str(REPO), "status", "--short"])
    run(["git", "-C", str(REPO), "diff", "--cached", "--stat"])

    if not args.commit_and_push:
        print("\nDry run — no commit. Re-run with --commit-and-push to ship.")
        return

    msg = (
        f"RAM-C M22.5 @ 61 km — refined-mesh NEMO validation result\n"
        f"\n"
        f"log10 error vs Jones & Cross 1972: {log10_str}\n"
        f"Refined 2.7M-tet body-clustered mesh, Mach ramp M10 -> M22.5.\n"
        f"\n"
        f"Files updated:\n"
        f"  - data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu (~100 MB)\n"
        f"  - data/nemo_test/ram_c_validation.{{json,md}}\n"
        f"  - docs/PLASMANET_NOTION.md §3.2 (refined-mesh row + stagnation block)\n"
        f"  - docs/paper/figures/{{los_polar,ne_radial_stag,ne_axial_stations,tt_tve_contour}}.png\n"
        f"    (gitignored, regenerate via scripts/make_paper_figures.py)\n"
        f"\n"
        f"Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>\n"
    )
    run(["git", "-C", str(REPO), "commit", "-m", msg])
    run(["git", "-C", str(REPO), "push", "origin", "master"])
    print("\nDONE — pushed to origin/master.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vm", default=DEFAULT_VM)
    ap.add_argument("--zone", default=DEFAULT_ZONE)
    ap.add_argument("--vm-stage-dir", default=DEFAULT_VM_STAGE_DIR)
    ap.add_argument("--local-vtu", default=str(DEFAULT_LOCAL_VTU))
    ap.add_argument("--notion", default=str(DEFAULT_NOTION))
    ap.add_argument("--mach", type=float, default=22.5)
    ap.add_argument("--altitude", type=float, default=61.0)
    ap.add_argument("--commit-and-push", action="store_true",
                    help="Auto git commit + push (default: dry run, just stage)")
    args = ap.parse_args()

    vtu = step1_scp_vtu(args)
    json_path, validation = step2_validate(vtu, args.mach, args.altitude)
    step3_figures(vtu)
    step4_patch_notion(validation, Path(args.notion))
    step5_commit(args, validation, vtu, json_path)

    print("\n" + "=" * 70)
    print("FINALIZER COMPLETE")
    print("=" * 70)
    log10 = validation.get("log10_error_vs_published")
    if log10 is not None:
        verdict = ("EXCELLENT" if abs(log10) < 0.3 else
                   "GOOD"      if abs(log10) < 0.7 else
                   "ACCEPTABLE" if abs(log10) < 1.0 else
                   "NEEDS WORK")
        print(f"\nlog10 error vs J&C 1972: {log10:+.2f}  →  {verdict}")
    print(f"Validation JSON: {json_path}")
    print(f"Paper figures:   {FIG_DIR}")


if __name__ == "__main__":
    main()
