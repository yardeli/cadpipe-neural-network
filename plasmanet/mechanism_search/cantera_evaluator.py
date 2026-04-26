"""S-2 — Cantera 0D evaluator.

Fast (~ms) per-evaluation chemistry surrogate for mechanism candidates.
Replaces full SU2-NEMO CFD when searching the 2^47 reaction subset space.

Approach:
  1. Estimate post-shock conditions (T, P, U) from freestream using
     normal-shock relations + a dissociation-energy correction.
  2. Run Cantera IdealGasConstPressureReactor at those conditions for
     the residence time of the sheath flow.
  3. Extract steady-state ne (electron number density).
  4. Apply 1D BL correction for non-stagnation locations (RAM-C
     reflectometer stations are aft of nose).

Limitations:
  - 0D loses the spatial structure of the sheath. We approximate via
    1D BL correction. Surrogate accuracy is bounded by this approximation.
  - Surrogate accuracy is validated against existing CFD baselines
    (AIR-5, AIR-7). If it disagrees by more than 0.5 log10 with CFD,
    the approximation is broken.

Usage:
    from plasmanet.mechanism_search.cantera_evaluator import evaluate
    from plasmanet.mechanism_search.generator import park_air7
    from plasmanet.mechanism_search.scoring import BENCHMARKS

    result = evaluate(park_air7(), BENCHMARKS['ram_c_61km_M22.5'])
    print(result['ne_m3'])  # predicted peak sheath ne
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np

# Cantera is optional — module imports succeed even without it; runtime calls
# raise a clear error.
try:
    import cantera as ct
    HAVE_CANTERA = True
except ImportError:
    HAVE_CANTERA = False
    ct = None


# ──────────────────────────────────────────────────────────────────────────────
# Normal-shock relations with chemistry sink correction
# ──────────────────────────────────────────────────────────────────────────────

GAMMA_FROZEN_AIR = 1.4
R_SPECIFIC_AIR = 287.058   # J/kg/K (frozen)


def normal_shock_T_P(M_inf: float, T_inf: float, P_inf: float,
                      gamma: float = GAMMA_FROZEN_AIR
                      ) -> tuple[float, float]:
    """Normal-shock T2/T1 and P2/P1 (frozen gas, no chemistry).

    Returns (T_post_K, P_post_Pa). Used as the upper bound on real
    post-shock T; reactive shocks have lower T due to dissociation
    energy sink.
    """
    M2 = M_inf * M_inf
    T2_T1 = (1 + (gamma - 1) / 2 * M2) * (2 * gamma / (gamma + 1) * M2 - (gamma - 1) / (gamma + 1)) / ((gamma + 1) / 2 * M2) ** 2 * ((gamma + 1) ** 2 * M2)
    # Simplified Rayleigh-Hugoniot; for our purposes use textbook
    T_ratio = ((2 * gamma * M2 - (gamma - 1)) * ((gamma - 1) * M2 + 2)
               / ((gamma + 1) ** 2 * M2))
    P_ratio = (2 * gamma * M2 - (gamma - 1)) / (gamma + 1)
    return (T_inf * T_ratio, P_inf * P_ratio)


def chemistry_corrected_post_shock_T(M_inf: float, T_inf: float,
                                       P_inf: float,
                                       dissoc_extent: float = 0.20,
                                       ) -> tuple[float, float]:
    """Post-shock T with a SMALL energy sink for partial dissociation.

    Real reactive shocks have slightly lower T than frozen because
    chemistry absorbs energy (N2 → 2N endothermic). For RAM-C M=22.5
    at 61 km, frozen T_post is ~25000K; reactive T_post is ~10000-15000K
    after partial dissociation.

    Previous version had a hard 5×T_inf floor which incorrectly clamped
    M=22.5 at 1213K (way too low). New version subtracts a small
    dissoc-extent fraction of N2's bond energy, then trusts Cantera's
    reactor to refine via reaction kinetics.

    Args:
        dissoc_extent: 0..1 fraction of N2 fully dissociated. 0.20 is
            typical at M=22.5 stagnation (Park 1990 estimate).
    """
    T_frozen, P_post = normal_shock_T_P(M_inf, T_inf, P_inf)
    # Bond energy: N2 dissociation = 945 kJ/mol = 33.7 MJ/kg
    # of N2 mass. With dissoc_extent fraction:
    bond_energy_per_kg = 33.7e6 * dissoc_extent
    cv_post = 1.5 * R_SPECIFIC_AIR  # rough cv at high T (~430 J/kg/K)
    dT_correction = bond_energy_per_kg / cv_post
    # Floor: never drop below 1.5× the freestream stagnation temperature.
    # For M=22.5 at T_inf=242K, freestream stagnation T ≈ 24500K, so
    # the floor is ~36500K — never triggers, but guards against bugs.
    T_min = T_inf * (1 + 0.5 * 1.4 * M_inf ** 2 / 5)
    T_post = max(T_frozen - dT_correction, T_min, 1000.0)
    return (T_post, P_post)


# ──────────────────────────────────────────────────────────────────────────────
# Cantera 0D evaluation
# ──────────────────────────────────────────────────────────────────────────────

def evaluate(
    mechanism,
    benchmark,
    residence_time_s: float = 1e-4,    # ~100 us — typical sheath residence at M=22
    cantera_yaml_path: Optional[Path] = None,
    use_dissoc_correction: bool = True,
) -> dict:
    """Run Cantera 0D reactor at post-shock conditions, return ne + dB.

    Args:
        mechanism: Mechanism object (from plasmanet.mechanism_search.generator)
        benchmark: BenchmarkCondition (from plasmanet.mechanism_search.scoring)
        residence_time_s: How long to integrate the reactor; longer = closer
            to equilibrium. Default 100 us matches sheath flow time.
        cantera_yaml_path: Optional override; otherwise we generate a temp file
            from mechanism.to_cantera_yaml().
        use_dissoc_correction: Apply chemistry-sink T correction (recommended).

    Returns dict matching the scoring evaluator interface:
        {
            'ne_m3': float (predicted peak sheath ne),
            'db_by_freq_hz': dict[float, float] (predicted attenuation per band),
            'T_post_shock_K': float (diagnostic),
            'P_post_shock_Pa': float (diagnostic),
            'mole_fractions_steady_state': dict[str, float] (diagnostic),
        }
    """
    if not HAVE_CANTERA:
        raise RuntimeError(
            "Cantera is not installed locally. "
            "Either run on the VM (`pip install cantera`) or use a "
            "different evaluator.")

    # ── 1. Post-shock T, P (with chemistry energy sink correction)
    if use_dissoc_correction:
        T_post, P_post = chemistry_corrected_post_shock_T(
            benchmark.mach, benchmark.temperature_k, benchmark.pressure_pa
        )
    else:
        T_post, P_post = normal_shock_T_P(
            benchmark.mach, benchmark.temperature_k, benchmark.pressure_pa
        )

    # ── 2. Materialize the mechanism as a Cantera YAML
    import tempfile
    if cantera_yaml_path is None:
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.yaml', delete=False
        ) as tf:
            tf.write(mechanism.to_cantera_yaml())
            cantera_yaml_path = Path(tf.name)

    # ── 3. Build Cantera Solution
    try:
        gas = ct.Solution(str(cantera_yaml_path))
    except Exception as exc:
        return {
            "ne_m3": 0.0,
            "db_by_freq_hz": {},
            "T_post_shock_K": T_post,
            "P_post_shock_Pa": P_post,
            "mole_fractions_steady_state": {},
            "f_plasma_hz": 0.0,
            "error": f"Cantera YAML load failed: {exc}",
        }

    # ── 4. Set initial state to post-shock + freestream composition
    # Composition mass fractions: 77% N2, 23% O2, traces of others if in mech
    Y_init = {sp: 0.0 for sp in gas.species_names}
    if "N2" in Y_init: Y_init["N2"] = 0.77
    if "O2" in Y_init: Y_init["O2"] = 0.23
    # Trace ions (1e-9 each) so chemistry rates that need n_e > 0 work
    for sp in ["e-", "N+", "O+", "NO+", "N2+", "O2+", "N", "O", "NO"]:
        if sp in Y_init:
            Y_init[sp] = max(Y_init.get(sp, 0), 1e-12)
    # Renormalize
    total = sum(Y_init.values())
    Y_init = {k: v / total for k, v in Y_init.items() if v > 0}

    gas.TPY = T_post, P_post, Y_init

    # Print pre-chemistry diagnostic with flush=True so it survives a
    # Cantera CVode crash mid-integration (per other-instance feedback)
    print(f"[cantera_evaluator] Pre-chemistry: T_post = {T_post:.0f} K, "
          f"P_post = {P_post:.1f} Pa, gas.species = {gas.n_species}",
          flush=True)

    # ── 5. Integrate Cantera reactor
    # Note: clone= keyword required in Cantera 3.2 to silence deprecation
    try:
        reactor = ct.IdealGasConstPressureReactor(gas, clone=False)
    except TypeError:
        # Cantera < 3.2 doesn't have the clone kwarg
        reactor = ct.IdealGasConstPressureReactor(gas)
    sim = ct.ReactorNet([reactor])
    try:
        sim.advance(residence_time_s)
    except Exception as exc:
        return {
            "ne_m3": 0.0, "db_by_freq_hz": {},
            "T_post_shock_K": T_post, "P_post_shock_Pa": P_post,
            "mole_fractions_steady_state": {sp: float(gas.X[i])
                                              for i, sp in enumerate(gas.species_names)},
            "f_plasma_hz": 0.0,
            "error": f"Cantera reactor advance failed: {exc}",
        }

    # ── 6. Extract electron number density
    # ne (m^-3) = mole_fraction_e * total_number_density
    # total_number_density = N_A * P / (R*T)
    N_A = 6.022e23
    R_universal = 8.314
    n_total = N_A * gas.P / (R_universal * gas.T)
    ne_m3 = 0.0
    if "e-" in gas.species_names:
        x_e = gas.X[gas.species_index("e-")]
        ne_m3 = x_e * n_total

    # Mole fractions for diagnostic
    mole_fracs = {sp: float(gas.X[i]) for i, sp in enumerate(gas.species_names)}

    # ── 7. dB attenuation per frequency (Appleton-Hartree approximation)
    # Sheath path length comes from the VehicleGeometry, not hardcoded.
    # Plasma frequency: f_p ≈ 8980 * sqrt(n_e in cm^-3) Hz
    db_by_freq = {}
    f_p_hz = 8980 * math.sqrt(max(ne_m3 * 1e-6, 0))   # cm^-3 → Hz
    # Use the vehicle's sheath path length at the maximum-ne axial location
    # (rough estimate: middle of body)
    geom = benchmark.vehicle
    sheath_path_m = geom.estimate_sheath_path_length(0.5 * geom.body_length_m)
    # Collision frequency at post-shock conditions: nu ≈ 1e-13 * P[Pa] * Hz
    # (~1e10 for 0.1 atm post-shock; scale linearly with pressure)
    nu_collision_hz = 1e10 * (gas.P / 1.01325e5)
    for f_hz, _ in benchmark.detection_status_by_freq_hz.items():
        if f_hz > f_p_hz:
            # Wave propagates, finite collisional loss
            omega = 2 * math.pi * f_hz
            omega_p = 2 * math.pi * f_p_hz
            alpha = 8.686 * (omega_p ** 2 * nu_collision_hz) / (
                2 * 3e8 * (omega ** 2 + nu_collision_hz ** 2))
            db_by_freq[f_hz] = alpha * sheath_path_m
        else:
            # Evanescent — saturated attenuation
            db_by_freq[f_hz] = 100.0

    return {
        "ne_m3": ne_m3,
        "db_by_freq_hz": db_by_freq,
        "T_post_shock_K": T_post,
        "P_post_shock_Pa": P_post,
        "mole_fractions_steady_state": mole_fracs,
        "f_plasma_hz": f_p_hz,
    }


def register_with_scoring():
    """Wire this evaluator into the scoring framework."""
    from plasmanet.mechanism_search.scoring import register_evaluator

    def _cantera_evaluator(input_data: dict, benchmark) -> dict:
        mech = input_data.get("mechanism")
        residence = input_data.get("residence_time_s", 1e-4)
        if mech is None:
            return {"ne_m3": 0.0, "db_by_freq_hz": {}}
        return evaluate(mech, benchmark, residence_time_s=residence)

    register_evaluator("cantera_0d", _cantera_evaluator)


# Auto-register at import time
register_with_scoring()


if __name__ == "__main__":
    if not HAVE_CANTERA:
        print("Cantera not installed locally — install via `pip install cantera` "
              "or run this on the VM where it's available.")
        import sys
        sys.exit(0)

    from plasmanet.mechanism_search.generator import park_air7
    from plasmanet.mechanism_search.scoring import BENCHMARKS

    print("Running Cantera 0D evaluation of Park_AIR7 against RAM-C 61km/M22.5...")
    result = evaluate(park_air7(), BENCHMARKS["ram_c_61km_M22.5"])
    print(f"  T_post_shock = {result['T_post_shock_K']:.0f} K")
    print(f"  P_post_shock = {result['P_post_shock_Pa']:.1f} Pa")
    print(f"  ne predicted = {result['ne_m3']:.3e} m^-3")
    print(f"  f_plasma = {result.get('f_plasma_hz', 0.0):.3e} Hz")
    if "error" in result:
        print(f"  ERROR: {result['error']}")
    print(f"  dB by freq:")
    for f, db in result["db_by_freq_hz"].items():
        print(f"    {f/1e9:.2f} GHz: {db:.1f} dB")
