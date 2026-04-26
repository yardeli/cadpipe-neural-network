"""Example: how a designer adds a custom vehicle to the search framework.

Demonstrates the modular flow:
  1. Define a VehicleGeometry from CAD-derived parameters
  2. Define a BenchmarkCondition with experimental ne measurements (if any)
  3. Run the search framework on this vehicle without changing framework code

Future (S-8): step 1 will be replaced by VehicleGeometry.from_step_file('design.step').

Run:
    python examples/custom_vehicle_example.py
"""
from __future__ import annotations

from plasmanet.mechanism_search import (
    VehicleGeometry,
    BenchmarkCondition,
    BENCHMARKS,
    PREDEFINED_GEOMETRIES,
    park_air5,
    park_air7,
    score_against_benchmark,
)


# ──────────────────────────────────────────────────────────────────────────────
# Step 1: Define your vehicle's geometry
# ──────────────────────────────────────────────────────────────────────────────
# This is what S-8 will auto-extract from a STEP file. For now, the designer
# measures their CAD by hand and fills these in.

my_hgv = VehicleGeometry(
    name="my_hgv_design_v3",
    body_length_m=4.5,           # nose-to-base axial length
    nose_radius_m=0.030,          # 3 cm nose radius (sharp for low drag)
    body_type="sphere_cone",
    half_angle_deg=6.0,           # 6-degree slender cone
    # Where the comms antennas / probes are on the body, as fractions of length
    reflectometer_stations_zL=[0.25, 0.50, 0.75, 0.95],
    sheath_thickness_m=0.04,      # thin attached shock for slender HGV
)

print(f"Vehicle: {my_hgv.name}")
print(f"  Body length: {my_hgv.body_length_m} m")
print(f"  Nose radius: {my_hgv.nose_radius_m} m")
print(f"  Body type: {my_hgv.body_type} ({my_hgv.half_angle_deg}° half-angle)")
print(f"  Sensor stations: z/L = {my_hgv.reflectometer_stations_zL}")
print(f"  Wall radius at z/L=0.5: {my_hgv.body_radius_at_x(0.5*my_hgv.body_length_m):.3f} m")
print()


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: Add benchmark conditions (if you have measured / simulated data)
# ──────────────────────────────────────────────────────────────────────────────
# Designer typically doesn't have flight data — they want PREDICTION, not
# validation. But for ground-truth re-anchoring (e.g., from a wind-tunnel
# test), benchmarks tie experiments to specific (vehicle, flight) pairs.

# Hypothetical wind-tunnel measurement at LENS-II:
my_benchmark = BenchmarkCondition(
    name="my_hgv_LENS_M15_30km",
    vehicle=my_hgv,
    altitude_km=30.0,
    mach=15.0,
    velocity_ms=4500.0,
    pressure_pa=1197.0,
    temperature_k=226.5,
    ne_published_m3=5.0e18,   # measured peak ne at sensor station 2
    ne_lower_m3=2.5e18,
    ne_upper_m3=1.0e19,
    detection_status_by_freq_hz={
        2.25e8: "BLACKOUT",
        9.20e9: "DEGRADED",
    },
    source="Hypothetical LENS-II tunnel test 2026",
    weight=1.0,
)

print(f"Benchmark: {my_benchmark.name}")
print(f"  Conditions: M={my_benchmark.mach}, alt={my_benchmark.altitude_km} km")
print(f"  Measured ne: {my_benchmark.ne_published_m3:.1e} m^-3")
print()


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: Score a candidate mechanism against the benchmark
# ──────────────────────────────────────────────────────────────────────────────
# Designer can ask: "If I use Park-AIR-5, what does it predict for my vehicle?"
# (Without actually running CFD — using a stub prediction here. In real use,
# this would be the result from the Cantera 0D evaluator or full CFD.)

stub_prediction_ne = 1.2e18    # what some hypothetical mechanism would predict
result = score_against_benchmark(
    mechanism_name="Park_AIR5_test",
    benchmark=my_benchmark,
    ne_predicted_m3=stub_prediction_ne,
    db_predicted_by_freq_hz={2.25e8: 35.0, 9.20e9: 8.0},
)

print(f"Score for Park_AIR5 prediction:")
print(f"  ne predicted: {result.ne_predicted_m3:.1e} m^-3")
print(f"  log10 err:    {result.log10_err_ne:+.3f}")
print(f"  composite:    {result.score:.3f}")
print(f"  dB verdicts:  {result.db_verdicts_by_freq_hz}")
print()


# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Run a full mechanism search over your vehicle (when fast evaluator
# is available — Cantera 0D requires NASA-9 thermo to be filled in)
# ──────────────────────────────────────────────────────────────────────────────
# Pseudo-code (commented out — requires Cantera + valid mechanisms):
#
# from plasmanet.mechanism_search import genetic_search, save_results
# results = genetic_search(
#     base_mechanism=PARK_47,
#     evaluator='cantera_0d',
#     evaluator_input_fn=lambda mech: {'mechanism': mech},
#     budget=500,
#     benchmarks=['my_hgv_LENS_M15_30km'],   # YOUR benchmark, not RAM-C
# )
# save_results(results, Path('outputs/my_hgv_search/'))
#
# This searches across reaction subsets to find the mechanism that best
# fits YOUR vehicle's measurements. The framework is fully decoupled from
# RAM-C — just supply the geometry + benchmarks for your vehicle.


# ──────────────────────────────────────────────────────────────────────────────
# Predefined geometries (for reference)
# ──────────────────────────────────────────────────────────────────────────────
print(f"Predefined geometries available:")
for name, geom in PREDEFINED_GEOMETRIES.items():
    print(f"  {name}: L={geom.body_length_m}m, "
          f"R_n={geom.nose_radius_m}m, type={geom.body_type}")
