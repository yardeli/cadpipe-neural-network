"""Anchor test: prove the new scoring framework reproduces our measured
AIR-5 result (log10 err = −1.59 vs J&C 1972 RAM-C 61 km / M=22.5).

Why: before using score_candidate() to drive a search across thousands of
mechanism candidates, we must verify it returns the SAME number for our
known baseline that the original validate_ram_c_nemo.py script produced.
If they disagree, scoring is broken and search would be meaningless.

This script:
  1. Loads the AIR-5 CFD baseline VTU (data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu)
  2. Runs it through score_candidate() with the 'cfd_vtu' evaluator
  3. Asserts the log10 err matches the validate_ram_c_nemo.py headline of −1.59 ± 0.1
  4. Prints the full ScoringResult for inspection

Run:
    python scripts/validate_scoring_against_air5.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from plasmanet.mechanism_search.scoring import (
    score_candidate,
    BENCHMARKS,
)


AIR5_VTU = REPO / "data" / "nemo_test" / "ramC_refined_M22_5_A61_nemo.vtu"
EXPECTED_LOG10_ERR = -1.59
LOG10_TOLERANCE = 0.15


def main():
    if not AIR5_VTU.exists():
        print(f"ERROR: AIR-5 baseline VTU not found at {AIR5_VTU}",
              file=sys.stderr)
        print(f"       This script anchors against our existing CFD result;",
              file=sys.stderr)
        print(f"       it cannot run without it.", file=sys.stderr)
        sys.exit(1)

    print(f"=== Scoring framework anchor test ===")
    print(f"VTU: {AIR5_VTU}")
    print(f"Mechanism: AIR-5 (Park reduced, no ions, Saha post-process for ne)")
    print(f"Expected log10 err vs J&C 1972 (61 km / M=22.5): "
          f"{EXPECTED_LOG10_ERR:+.2f} (from earlier validate_ram_c_nemo.py run)")
    print()

    print("Running score_candidate via cfd_vtu evaluator...")
    result = score_candidate(
        mechanism_name="AIR-5_baseline",
        evaluator="cfd_vtu",
        evaluator_input={"vtu_path": str(AIR5_VTU)},
        benchmark="ram_c_61km_M22.5",
    )

    print()
    print(f"=== ScoringResult ===")
    print(f"  Mechanism:        {result.mechanism_name}")
    print(f"  Evaluator:        {result.evaluator}")
    print(f"  Composite score:  {result.composite_score:.3f}")
    print(f"  Verdict:          {result.verdict}")
    print()
    for r in result.per_benchmark:
        print(f"  Benchmark {r.benchmark_name}:")
        print(f"    ne_predicted = {r.ne_predicted_m3:.3e} m^-3")
        print(f"    log10 err    = {r.log10_err_ne:+.3f}")
        print(f"    score        = {r.score:.3f}")
        print(f"    dB margins:  {r.db_margins_by_freq_hz}")
        print(f"    dB verdicts: {r.db_verdicts_by_freq_hz}")

    # Anchor check
    actual = result.per_benchmark[0].log10_err_ne
    diff = abs(actual - EXPECTED_LOG10_ERR)
    print()
    print(f"=== Anchor check ===")
    print(f"  Actual:   {actual:+.3f}")
    print(f"  Expected: {EXPECTED_LOG10_ERR:+.3f}")
    print(f"  Diff:     {diff:.3f}")
    if diff <= LOG10_TOLERANCE:
        print(f"  PASS — within tolerance {LOG10_TOLERANCE:.2f}")
        print()
        print("Scoring framework correctly reproduces the AIR-5 baseline.")
        print("Safe to use for mechanism search.")
        return 0
    else:
        print(f"  FAIL — exceeds tolerance {LOG10_TOLERANCE:.2f}")
        print()
        print("Scoring framework gives a different answer than our prior")
        print("validate_ram_c_nemo.py run. DO NOT trust it for search until")
        print("the discrepancy is resolved.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
