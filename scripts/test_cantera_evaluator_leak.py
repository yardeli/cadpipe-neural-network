"""Regression test: cantera_evaluator.evaluate() no longer leaks tmp YAMLs.

Two checks:

1. Repeated calls with no explicit ``cantera_yaml_path`` leave the temp
   directory at its pre-call file count. Before the fix this leaked
   one tmp*.yaml per call; on the GCP VM that filled /dev/root after
   ~380K calls (see reference_cantera_evaluator_yaml_leak.md).

2. When the caller passes ``cantera_yaml_path`` explicitly the file is
   left in place (caller-managed lifetime — v5 worker pattern).

Skips silently when Cantera is unavailable.

Run:
    PYTHONPATH=. python scripts/test_cantera_evaluator_leak.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _ok(msg):   print(f"\033[32m  PASS\033[0m {msg}")
def _fail(msg): print(f"\033[31m  FAIL\033[0m {msg}")


def _count_tmp_yamls() -> int:
    return sum(1 for _ in Path(tempfile.gettempdir()).glob("tmp*.yaml"))


def test_no_leak_default_path() -> bool:
    print("\n=== Test 1: 5 evaluate() calls with no explicit yaml path ===")
    try:
        from plasmanet.mechanism_search.cantera_evaluator import evaluate, HAVE_CANTERA
    except ImportError as e:
        _fail(f"cantera_evaluator import failed: {e}")
        return False
    if not HAVE_CANTERA:
        print("  SKIP — Cantera unavailable locally")
        return True
    from plasmanet.mechanism_search.generator import park_air7
    from plasmanet.mechanism_search.scoring import BENCHMARKS

    bench = BENCHMARKS["ram_c_61km_M22.5"]
    mech = park_air7()

    before = _count_tmp_yamls()
    print(f"  tmp YAMLs before: {before}")
    for i in range(5):
        evaluate(mech, bench, residence_time_s=1e-6)
    after = _count_tmp_yamls()
    print(f"  tmp YAMLs after 5 evaluate() calls: {after}")
    if after != before:
        _fail(f"leaked {after - before} tmp YAML(s) — fix did not hold")
        return False
    _ok("no tmp YAML accumulation over 5 calls")
    return True


def test_caller_managed_path_preserved() -> bool:
    print("\n=== Test 2: caller-managed yaml path is preserved across calls ===")
    try:
        from plasmanet.mechanism_search.cantera_evaluator import evaluate, HAVE_CANTERA
    except ImportError as e:
        _fail(f"cantera_evaluator import failed: {e}")
        return False
    if not HAVE_CANTERA:
        print("  SKIP — Cantera unavailable locally")
        return True
    from plasmanet.mechanism_search.generator import park_air7
    from plasmanet.mechanism_search.scoring import BENCHMARKS

    bench = BENCHMARKS["ram_c_61km_M22.5"]
    mech = park_air7()

    # Caller writes the YAML once and reuses across N calls (v5-worker pattern)
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', delete=False, prefix='reused_',
    ) as tf:
        tf.write(mech.to_cantera_yaml())
        reused = Path(tf.name)

    try:
        if not reused.exists():
            _fail("reused yaml file vanished before first call")
            return False
        for i in range(3):
            evaluate(mech, bench, residence_time_s=1e-6, cantera_yaml_path=reused)
            if not reused.exists():
                _fail(f"caller-managed yaml was deleted on iteration {i}")
                return False
        _ok(f"caller-managed yaml {reused.name} preserved across 3 calls")
        return True
    finally:
        reused.unlink(missing_ok=True)


def main() -> int:
    results = [
        test_no_leak_default_path(),
        test_caller_managed_path_preserved(),
    ]
    n = sum(1 for r in results if r)
    print()
    print("=" * 60)
    print(f"  {n}/{len(results)} cantera-leak test groups passed")
    print("=" * 60)
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
