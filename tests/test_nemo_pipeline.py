"""Tests for the NEMO branch: config generation and field extraction.

The field-extraction tests require a NEMO-produced VTU under
data/nemo_test/. This is provided in-repo (committed in 52a0f41), so
these tests should pass on a fresh clone.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import numpy as np

SAMPLE_NEMO_VTU = Path(__file__).parent.parent / "data" / "nemo_test" / "blunt_cone_M10_A30_nemo.vtu"


def test_nemo_config_generation_AIR5():
    """AIR-5 config should use FLUID_MODEL= SU2_NONEQ and implicit time scheme."""
    from plasmanet.nemo_config import write_nemo_config
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
        tmp = f.name
    write_nemo_config(tmp, mach=10.0, altitude_km=30.0, gas_model="AIR-5")
    text = Path(tmp).read_text()
    assert "FLUID_MODEL= SU2_NONEQ" in text, "AIR-5 must use SU2_NONEQ"
    assert "EULER_IMPLICIT" in text
    assert "GAS_MODEL= AIR-5" in text
    assert "FREESTREAM_TEMPERATURE= 226.65" in text
    assert "(0.77, 0.23, 0.0, 0.0, 0.0)" in text
    Path(tmp).unlink()
    print("  nemo_config_generation_AIR5: PASS")


def test_nemo_config_generation_AIR11_MUTATIONPP():
    """air_11 config uses FLUID_MODEL= MUTATIONPP and explicit time scheme."""
    from plasmanet.nemo_config import write_nemo_config
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cfg", delete=False) as f:
        tmp = f.name
    write_nemo_config(tmp, mach=12.0, altitude_km=35.0, gas_model="air_11")
    text = Path(tmp).read_text()
    assert "FLUID_MODEL= MUTATIONPP" in text
    assert "EULER_EXPLICIT" in text, "MUTATIONPP requires EULER_EXPLICIT in v7.5.1"
    assert "GAS_MODEL= air_11" in text
    # 11-species composition: 10 commas in the tuple alone
    composition_lines = [ln for ln in text.splitlines() if ln.startswith("GAS_COMPOSITION")]
    assert composition_lines and composition_lines[0].count(",") == 10
    Path(tmp).unlink()
    print("  nemo_config_generation_AIR11_MUTATIONPP: PASS")


def test_nemo_env_vars():
    from plasmanet.nemo_config import nemo_env
    env = nemo_env("/opt/su2-nemo")
    assert "/opt/su2-nemo/lib" in env["LD_LIBRARY_PATH"]
    assert env["MPP_DATA_DIRECTORY"] == "/opt/su2-nemo/mpp-data"
    print("  nemo_env_vars: PASS")


def test_extract_nemo_field_runs():
    if not SAMPLE_NEMO_VTU.exists():
        print(f"  extract_nemo_field_runs: SKIP (no {SAMPLE_NEMO_VTU.name})")
        return
    from plasmanet.cfd_field import extract_nemo_field
    cfd = extract_nemo_field(
        str(SAMPLE_NEMO_VTU), geometry="blunt_cone",
        mach=10.0, altitude_km=30.0, verbose=False,
    )
    assert cfd.n_points > 1000
    stag = cfd.stag_point
    assert 3000 < stag["T_K"] < 7000, f"T_tr stag = {stag['T_K']}"
    assert "T_ve_K" in stag
    # NEMO gives lower T_ve than T_tr in the shock layer
    assert stag["T_ve_K"] <= stag["T_K"] + 100, "T_ve should be ≤ T_tr"
    # ne at stagnation for NEQ M10 is typically 1e17-5e18 (below equilibrium)
    assert 1e16 < stag["ne_m3"] < 1e20, f"NEMO stag ne = {stag['ne_m3']:.2e}"
    print(f"  extract_nemo_field_runs: PASS (T_tr={stag['T_K']:.0f}K, "
          f"T_ve={stag['T_ve_K']:.0f}K, ne={stag['ne_m3']:.2e})")


def test_nemo_field_has_two_temperatures():
    if not SAMPLE_NEMO_VTU.exists():
        print(f"  nemo_field_has_two_temperatures: SKIP")
        return
    from plasmanet.cfd_field import read_vtu_fields
    fields, n_pts, _ = read_vtu_fields(str(SAMPLE_NEMO_VTU))
    assert "Temperature_tr" in fields, "NEMO VTU must have Temperature_tr"
    assert "Temperature_ve" in fields, "NEMO VTU must have Temperature_ve"
    # And species
    assert "Density_0" in fields
    assert "Density_4" in fields  # 5 species
    print("  nemo_field_has_two_temperatures: PASS")


def test_nemo_field_to_los_end_to_end():
    if not SAMPLE_NEMO_VTU.exists():
        print(f"  nemo_field_to_los_end_to_end: SKIP")
        return
    from plasmanet.cfd_field import extract_nemo_field, build_unstructured_field
    from plasmanet.line_of_sight import scan_aspect
    cfd = extract_nemo_field(
        str(SAMPLE_NEMO_VTU), geometry="blunt_cone",
        mach=10.0, altitude_km=30.0, verbose=False,
    )
    field = build_unstructured_field(cfd)
    results = scan_aspect(
        field, target_position=cfd.stag_point["xyz"],
        f_hz=12e9, source_distance=10.0,
        angles_deg=np.array([0, 60, 90, 120, 180]),
        n_samples=2000, adaptive=True, plane="xz",
    )
    atts = [r.attenuation_db for r in results]
    # Expect aspect variation — not all zero, not all infinite
    assert max(atts) > 0.1, f"no attenuation at any aspect"
    assert max(atts) < 1e5, f"unphysically huge attenuation"
    print(f"  nemo_field_to_los_end_to_end: PASS "
          f"(max={max(atts):.1f} dB, min={min(atts):.1f} dB)")


def run_all():
    print("\nSU2-NEMO Pipeline Tests")
    print("=" * 50)
    test_nemo_config_generation_AIR5()
    test_nemo_config_generation_AIR11_MUTATIONPP()
    test_nemo_env_vars()
    test_extract_nemo_field_runs()
    test_nemo_field_has_two_temperatures()
    test_nemo_field_to_los_end_to_end()
    print("=" * 50)
    print("ALL NEMO TESTS PASSED\n")


if __name__ == "__main__":
    run_all()
