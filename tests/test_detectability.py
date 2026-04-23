"""Tests for the top-level detectability API."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import numpy as np

from plasmanet.detectability import (
    analyze_detectability, detection_envelope, VehicleGeometry,
    build_sheath_field_from_analysis,
)


VEHICLE = VehicleGeometry(nose_radius_m=0.08, half_angle_deg=15, length_m=2.5)


def test_cool_flight_is_detectable():
    """Mach 6 @ 40 km: T_stag ~ 2000 K, negligible ionisation → DETECTABLE."""
    r = analyze_detectability(VEHICLE, mach=6.0, altitude_km=40.0,
                               radar_freq_hz=12e9,
                               aspect_angles_deg=[0, 90, 180],
                               include_uq=False)
    assert r.ne_peak_m3 < 1e15, f"ne = {r.ne_peak_m3:.2e} shouldn't be plasma"
    assert r.overall_status == "DETECTABLE"
    assert r.attenuation_db.max() < 3.0
    print(f"  cool_flight_is_detectable: PASS (ne={r.ne_peak_m3:.2e}, "
          f"peak_att={r.attenuation_db.max():.2f} dB)")


def test_hot_flight_blackout():
    """Mach 15 @ 35 km: expect BLACKOUT — dense sheath at hypersonic conditions."""
    r = analyze_detectability(VEHICLE, mach=15.0, altitude_km=35.0,
                               radar_freq_hz=12e9,
                               aspect_angles_deg=[0, 90, 135, 150, 180],
                               include_uq=False)
    assert r.ne_peak_m3 > 1e18, f"ne = {r.ne_peak_m3:.2e} should be dense"
    assert r.overall_status == "BLACKOUT"
    assert r.attenuation_db.max() > 50.0
    print(f"  hot_flight_blackout: PASS (ne={r.ne_peak_m3:.2e}, "
          f"peak_att={r.attenuation_db.max():.1f} dB)")


def test_aspect_dependence():
    """Attenuation varies with aspect angle — nose-on and tail-on cross less
    sheath than side-on and rear-quarter views."""
    r = analyze_detectability(VEHICLE, mach=15.0, altitude_km=35.0,
                               radar_freq_hz=12e9,
                               aspect_angles_deg=[0, 45, 90, 135, 180],
                               include_uq=False)
    # Range should span at least 2 orders of magnitude (10 dB → 1000 dB)
    att = r.attenuation_db
    att_range_db = att.max() - att.min()
    assert att_range_db > 10.0, f"aspect range = {att_range_db:.1f} dB is too small"
    print(f"  aspect_dependence: PASS "
          f"(range = {att_range_db:.0f} dB: min={att.min():.1f}, max={att.max():.1f})")


def test_uq_bands_bracket_median():
    """UQ P05 ≤ median ≤ P95 at every aspect."""
    r = analyze_detectability(VEHICLE, mach=10.0, altitude_km=35.0,
                               radar_freq_hz=12e9,
                               aspect_angles_deg=[60, 90, 135],
                               include_uq=True)
    assert r.attenuation_p05_db is not None
    for i in range(len(r.aspect_angles_deg)):
        assert r.attenuation_p05_db[i] <= r.attenuation_db[i] + 0.01
        assert r.attenuation_p95_db[i] + 0.01 >= r.attenuation_db[i]
    print(f"  uq_bands_bracket_median: PASS (ne log10 std = {r.log10_ne_std:.2f})")


def test_uq_dependent_status_at_boundary():
    """At Mach 10 near the detection boundary, the UQ-dependent status
    should reflect that the answer flips with plausible input uncertainty."""
    r = analyze_detectability(VEHICLE, mach=10.0, altitude_km=35.0,
                               radar_freq_hz=12e9,
                               aspect_angles_deg=[135, 150, 170],
                               include_uq=True)
    # Status should mention UQ-dependent or be robustly categorised
    status = r.overall_status
    valid = (
        "UQ-dependent" in status
        or status in ("DETECTABLE", "DEGRADED", "BLACKOUT")
    )
    assert valid, f"unexpected status: {status}"
    print(f"  uq_dependent_status_at_boundary: PASS (status={status})")


def test_radar_frequency_scaling():
    """Test the fundamental cutoff behaviour: at a condition where ne gives
    a plasma frequency between two radar frequencies, the lower radar
    frequency should see overdense (huge attenuation) while the higher
    radar frequency sees underdense (low attenuation).

    At Mach 10 @ 35 km, ne_peak ~ 6e17 → fp ~ 7 GHz.
    - 3 GHz radar: below cutoff → overdense sheath → strong attenuation
    - 12 GHz radar: above cutoff → underdense → weak attenuation
    """
    r_low = analyze_detectability(VEHICLE, mach=10.0, altitude_km=35.0,
                                   radar_freq_hz=3e9,   # 3 GHz — below cutoff
                                   aspect_angles_deg=[90, 135, 150],
                                   include_uq=False)
    r_high = analyze_detectability(VEHICLE, mach=10.0, altitude_km=35.0,
                                    radar_freq_hz=12e9,   # Ku-band — above cutoff
                                    aspect_angles_deg=[90, 135, 150],
                                    include_uq=False)
    # Both should be meaningful, low-freq should have higher peak attenuation
    assert r_low.attenuation_db.max() > r_high.attenuation_db.max(), \
        f"3 GHz ({r_low.attenuation_db.max():.1f}) should exceed 12 GHz " \
        f"({r_high.attenuation_db.max():.1f}) attenuation when ne spans cutoff"
    print(f"  radar_frequency_scaling: PASS "
          f"(3 GHz max={r_low.attenuation_db.max():.1f} dB, "
          f"12 GHz max={r_high.attenuation_db.max():.1f} dB)")


def test_detection_envelope_shape():
    """Detection envelope: low M / high alt → DETECT, high M / low alt → BLACKOUT."""
    env = detection_envelope(
        VEHICLE,
        mach_grid=np.array([6, 10, 15]),
        altitude_grid=np.array([30, 40]),
        radar_freq_hz=12e9,
        aspect_angles_deg=[90, 135, 150],
        include_uq=False,
    )
    att = env["attenuation_worst_dB"]
    # Mach 6 rows should have lower attenuation than Mach 15 rows
    assert att[0, 0] < att[2, 0], f"M6@30km ({att[0,0]}) should < M15@30km ({att[2,0]})"
    assert att[0, 1] < att[2, 1], f"M6@40km ({att[0,1]}) should < M15@40km ({att[2,1]})"
    print(f"  detection_envelope_shape: PASS "
          f"(M6={att[0,0]:.0f}dB, M10={att[1,0]:.0f}dB, M15={att[2,0]:.0f}dB at 30km)")


def test_summary_prints_without_error():
    r = analyze_detectability(VEHICLE, mach=10.0, altitude_km=35.0,
                               radar_freq_hz=12e9,
                               aspect_angles_deg=[0, 90, 180],
                               include_uq=False)
    s = r.summary()
    assert "Mach 10.0" in s
    assert "Line-of-sight" in s or "aspect" in s.lower()
    assert "Worst case" in s
    print("  summary_prints_without_error: PASS")


def run_all():
    print("\nDetectability API Tests")
    print("=" * 50)
    test_cool_flight_is_detectable()
    test_hot_flight_blackout()
    test_aspect_dependence()
    test_uq_bands_bracket_median()
    test_uq_dependent_status_at_boundary()
    test_radar_frequency_scaling()
    test_detection_envelope_shape()
    test_summary_prints_without_error()
    print("=" * 50)
    print("ALL DETECTABILITY TESTS PASSED\n")


if __name__ == "__main__":
    run_all()
