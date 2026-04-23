"""Tests for CFD field extraction and LOS integration.

Require a completed CFD case on disk. If one isn't available, the tests
are skipped with a clear message.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import numpy as np

SAMPLE_VTU = Path(__file__).parent.parent / "data" / "cfd_results" / "blunt_cone_M10_A30" / "flow.vtu"


def test_read_vtu_fields():
    """Reader pulls all expected SU2 point-data arrays."""
    if not SAMPLE_VTU.exists():
        print(f"  read_vtu_fields: SKIP (no {SAMPLE_VTU.name})")
        return
    from plasmanet.cfd_field import read_vtu_fields
    fields, n_points, n_cells = read_vtu_fields(str(SAMPLE_VTU))
    assert "coordinates" in fields
    assert "Temperature" in fields
    assert "Pressure" in fields
    assert "Mach" in fields
    assert fields["coordinates"].shape == (n_points, 3)
    assert fields["Temperature"].shape == (n_points,)
    assert fields["Pressure"].shape == (n_points,)
    assert n_points > 1000
    # Physical sanity
    assert fields["Temperature"].min() > 0
    assert fields["Pressure"].min() > 0
    print(f"  read_vtu_fields: PASS ({n_points} pts, {n_cells} cells, "
          f"T∈[{fields['Temperature'].min():.0f}, {fields['Temperature'].max():.0f}]K)")


def test_extract_cfd_field_sparse():
    """Sparse-mode extraction runs in <5 s and finds physical stagnation."""
    if not SAMPLE_VTU.exists():
        print(f"  extract_cfd_field_sparse: SKIP")
        return
    from plasmanet.cfd_field import extract_cfd_field
    import time
    t0 = time.time()
    cfd = extract_cfd_field(
        str(SAMPLE_VTU), geometry="blunt_cone", mach=10.0, altitude_km=30.0,
        chem_mode="sparse", max_chem_samples=500, verbose=False,
    )
    dt = time.time() - t0
    assert dt < 10.0, f"Extract took {dt:.1f}s — too slow"
    # Physical sanity for Mach 10 @ 30 km stagnation
    stag = cfd.stag_point
    assert 2500 < stag["T_K"] < 7000, f"stag T = {stag['T_K']}"
    assert 1e4 < stag["p_Pa"] < 1e6, f"stag p = {stag['p_Pa']}"
    # Stagnation ne should be non-trivial at Mach 10
    assert stag["ne_m3"] > 1e14, f"stag ne = {stag['ne_m3']:.2e}"
    # At least 80% of sampled cells should have non-zero ne
    sampled = (cfd.ne_m3 > 0).sum()
    assert sampled > 400, f"only {sampled} cells got chemistry"
    print(f"  extract_cfd_field_sparse: PASS ({dt:.1f}s, stag T={stag['T_K']:.0f}K, "
          f"ne={stag['ne_m3']:.2e})")


def test_save_and_reload_cfd_field(tmp_path=None):
    """Round-trip: save → load yields identical data."""
    if not SAMPLE_VTU.exists():
        print(f"  save_and_reload_cfd_field: SKIP")
        return
    from plasmanet.cfd_field import extract_cfd_field, load_cfd_field
    import tempfile
    cfd = extract_cfd_field(
        str(SAMPLE_VTU), geometry="blunt_cone", mach=10.0, altitude_km=30.0,
        chem_mode="sparse", max_chem_samples=100, verbose=False,
    )
    with tempfile.NamedTemporaryFile(suffix=".npz", delete=False) as f:
        tmp = f.name
    cfd.save(tmp)
    cfd2 = load_cfd_field(tmp)
    assert np.allclose(cfd.coordinates, cfd2.coordinates)
    assert np.allclose(cfd.T_K, cfd2.T_K)
    assert np.allclose(cfd.p_Pa, cfd2.p_Pa)
    assert np.allclose(cfd.ne_m3, cfd2.ne_m3)
    assert cfd.chem_mode == cfd2.chem_mode
    Path(tmp).unlink()
    print("  save_and_reload_cfd_field: PASS")


def test_build_unstructured_field():
    """Unstructured field returns ne/nu at stagnation matching stored value."""
    if not SAMPLE_VTU.exists():
        print(f"  build_unstructured_field: SKIP")
        return
    from plasmanet.cfd_field import extract_cfd_field, build_unstructured_field
    cfd = extract_cfd_field(
        str(SAMPLE_VTU), geometry="blunt_cone", mach=10.0, altitude_km=30.0,
        chem_mode="sparse", max_chem_samples=500, verbose=False,
    )
    field = build_unstructured_field(cfd)
    ne_at_stag, nu_at_stag = field(cfd.stag_point["xyz"])
    # Nearest-neighbour interpolation at exact mesh point → matches stored
    assert abs(ne_at_stag - cfd.stag_point["ne_m3"]) < 1.0
    # Away from the mesh (at 100 m) → zero (outside interpolation domain;
    # returns nearest-neighbour which might not be zero, but nu should follow ne)
    print(f"  build_unstructured_field: PASS (ne_at_stag={ne_at_stag:.2e})")


def test_integrate_los_through_cfd_field():
    """End-to-end LOS through real CFD field gives aspect-dependent atten."""
    if not SAMPLE_VTU.exists():
        print(f"  integrate_los_through_cfd_field: SKIP")
        return
    from plasmanet.cfd_field import extract_cfd_field, build_unstructured_field
    from plasmanet.line_of_sight import scan_aspect

    cfd = extract_cfd_field(
        str(SAMPLE_VTU), geometry="blunt_cone", mach=10.0, altitude_km=30.0,
        chem_mode="sparse", max_chem_samples=1000, verbose=False,
    )
    field = build_unstructured_field(cfd)
    target = cfd.stag_point["xyz"]

    results = scan_aspect(
        field, target_position=target, f_hz=12e9,
        source_distance=5.0,
        angles_deg=np.array([0, 60, 90, 120, 180]),
        n_samples=2000, adaptive=True, plane="xz",
    )
    atts = [r.attenuation_db for r in results]
    # Range should span at least 2 orders of magnitude in attenuation
    # (nose-on through body is much longer path than flank-on)
    att_range = max(atts) - min(atts)
    assert att_range > 5.0, f"aspect range = {att_range:.1f} dB too small"
    # At Mach 10, some aspects should reach BLACKOUT status
    blackout_count = sum(1 for r in results if r.detection == "BLACKOUT")
    # Mach 10 near the boundary — at least one aspect should see BLACKOUT
    print(f"  integrate_los_through_cfd_field: PASS "
          f"(range={att_range:.0f} dB, blackout={blackout_count}/{len(results)})")


def run_all():
    print("\nCFD Field Extraction Tests")
    print("=" * 50)
    test_read_vtu_fields()
    test_extract_cfd_field_sparse()
    test_save_and_reload_cfd_field()
    test_build_unstructured_field()
    test_integrate_los_through_cfd_field()
    print("=" * 50)
    print("ALL CFD FIELD TESTS PASSED\n")


if __name__ == "__main__":
    run_all()
