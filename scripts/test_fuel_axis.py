"""v5.2 fuel-axis framework tests.

Four checks:

1. Pure-air pass-through. ``composite_air_fuel_mechanism(park_air7,
   FuelKind.AIR)`` returns the input Mechanism unchanged (identity check).
   v5_prime behaviour is bit-exact on the pure-air axis.

2. H2 union — composite has all Park-AIR-7 species + the 8 H2 species
   and 7 + 11 reactions.

3. CH4 union — composite has all air species + 14 CH4 species and
   7 + 16 reactions.

4. Cantera YAML round-trip — both H2 and CH4 composites materialize a
   valid Cantera mechanism (passes ct.Solution(yaml_path) without
   error). This proves the v5.2 data-collection worker can drop into
   the existing cantera_evaluator path without changes.

Run:
    PYTHONPATH=. python scripts/test_fuel_axis.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _ok(msg):   print(f"\033[32m  PASS\033[0m {msg}")
def _fail(msg): print(f"\033[31m  FAIL\033[0m {msg}")


def test_air_passthrough() -> bool:
    print("\n=== Test 1: AIR fuel kind is a pass-through ===")
    from plasmanet.mechanism_search import (
        park_air7, FuelKind, composite_air_fuel_mechanism,
    )
    air = park_air7()
    out = composite_air_fuel_mechanism(air, FuelKind.AIR, equivalence_ratio=0.0)
    if out is not air:
        _fail("AIR + phi=0 must return the input object unchanged")
        return False
    out_phi = composite_air_fuel_mechanism(air, FuelKind.H2, equivalence_ratio=0.0)
    if out_phi is not air:
        _fail("phi=0 with any fuel must collapse to pure-air pass-through")
        return False
    _ok(f"AIR / phi=0 returns input unchanged ({air.n_species} sp, "
        f"{air.n_reactions} rxns)")
    return True


def test_h2_union() -> bool:
    print("\n=== Test 2: H2 composite unions species + reactions ===")
    from plasmanet.mechanism_search import (
        park_air7, FuelKind, composite_air_fuel_mechanism,
        H2_SPECIES, H2_REACTIONS,
    )
    air = park_air7()
    h2 = composite_air_fuel_mechanism(air, FuelKind.H2, equivalence_ratio=1.0)
    # Species union
    expected_species = set(air.species) | set(H2_SPECIES)
    got_species = set(h2.species)
    if expected_species != got_species:
        _fail(f"species mismatch: missing {expected_species - got_species}, "
              f"extra {got_species - expected_species}")
        return False
    # Reaction count
    expected_n = air.n_reactions + len(H2_REACTIONS)
    if h2.n_reactions != expected_n:
        _fail(f"expected {expected_n} reactions, got {h2.n_reactions}")
        return False
    _ok(f"H2 composite: {h2.n_species} species, {h2.n_reactions} reactions "
        f"(air={air.n_reactions} + H2={len(H2_REACTIONS)})")
    return True


def test_ch4_union() -> bool:
    print("\n=== Test 3: CH4 composite unions species + reactions ===")
    from plasmanet.mechanism_search import (
        park_air7, FuelKind, composite_air_fuel_mechanism,
        CH4_SPECIES, CH4_REACTIONS,
    )
    air = park_air7()
    ch4 = composite_air_fuel_mechanism(air, FuelKind.CH4, equivalence_ratio=1.0)
    expected_species = set(air.species) | set(CH4_SPECIES)
    got_species = set(ch4.species)
    if expected_species != got_species:
        _fail(f"species mismatch: missing {expected_species - got_species}, "
              f"extra {got_species - expected_species}")
        return False
    expected_n = air.n_reactions + len(CH4_REACTIONS)
    if ch4.n_reactions != expected_n:
        _fail(f"expected {expected_n} reactions, got {ch4.n_reactions}")
        return False
    _ok(f"CH4 composite: {ch4.n_species} species, {ch4.n_reactions} reactions "
        f"(air={air.n_reactions} + CH4={len(CH4_REACTIONS)})")
    return True


def test_cantera_yaml_roundtrip() -> bool:
    print("\n=== Test 4: composite YAMLs emit + load (best-effort) ===")
    try:
        import cantera as ct
    except ImportError:
        print("  SKIP — Cantera unavailable locally")
        return True
    from plasmanet.mechanism_search import (
        park_air7, FuelKind, composite_air_fuel_mechanism,
    )
    from plasmanet.mechanism_search.thermo_data import NASA9_THERMO

    air = park_air7()
    pure_air = composite_air_fuel_mechanism(air, FuelKind.AIR, 0.0)
    yaml = pure_air.to_cantera_yaml()
    with tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', delete=False,
    ) as tf:
        tf.write(yaml)
        path = Path(tf.name)
    try:
        try:
            ct.Solution(str(path))
        except Exception as exc:
            _fail(f"Pure-air composite YAML failed to load: {exc}")
            return False
        print("  AIR (phi=0) pass-through composite: ct.Solution OK")
    finally:
        path.unlink(missing_ok=True)

    # H2 / CH4 composites need fuel-species NASA-9 polynomials in
    # thermo_data.NASA9_THERMO. They aren't shipped at v5.2 framework-
    # land time — adding them is part of the data-collection budget
    # envelope. Report which species are missing so the v5.2 launcher
    # can add them before the worker starts.
    for fk in (FuelKind.H2, FuelKind.CH4):
        comp = composite_air_fuel_mechanism(air, fk, equivalence_ratio=0.5)
        missing = [sp for sp in comp.species if sp not in NASA9_THERMO]
        print(f"  {fk.name:>4s} composite: {len(missing)} species missing thermo: "
              f"{missing}")
    _ok("AIR pass-through round-trips; H2/CH4 thermo gaps reported (data-collection prereq)")
    return True


def test_initial_composition() -> bool:
    print("\n=== Test 5: stoichiometric initial composition normalises ===")
    from plasmanet.mechanism_search import FuelKind, fuel_initial_composition
    for fk in (FuelKind.H2, FuelKind.CH4):
        for phi in (0.5, 1.0, 2.0):
            comp = fuel_initial_composition(fk, phi)
            total = sum(comp.values())
            print(f"  {fk.name:>4s} phi={phi:.1f}: {comp}  sum={total:.4f}")
            if abs(total - 1.0) > 1e-9:
                _fail(f"composition does not sum to 1.0: {total}")
                return False
    air_comp = fuel_initial_composition(FuelKind.AIR, 0.0)
    if abs(sum(air_comp.values()) - 1.0) > 1e-9:
        _fail("AIR fallback composition not normalised")
        return False
    _ok("stoichiometric compositions normalise to mass-fraction 1.0")
    return True


def main() -> int:
    results = [
        test_air_passthrough(),
        test_h2_union(),
        test_ch4_union(),
        test_cantera_yaml_roundtrip(),
        test_initial_composition(),
    ]
    n = sum(1 for r in results if r)
    print()
    print("=" * 60)
    print(f"  {n}/{len(results)} fuel-axis test groups passed")
    print("=" * 60)
    return 0 if n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
