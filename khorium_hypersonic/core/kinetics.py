"""Finite-rate residence-time chemistry via Cantera 0D constant-pressure reactor.

The equilibrium chemistry assumption (Cantera Gibbs minimization at
T_stag, p_stag) gives n_e ~ 5–50× too high at high altitude (60–80 km)
compared to RAM-C published flight data. The reason: real flight
residence time (~10 µs at the stagnation point) is too short for full
equilibration of the slow ionization reactions (NO + O ⇌ NO⁺ + e⁻ has
time constants approaching 100 µs at low collision frequencies).

This module solves a constant-pressure 0D Cantera reactor for time τ
starting from freestream-equivalent post-shock initial conditions, and
returns the n_e at time τ rather than at full equilibrium. τ is supplied
by the caller — typically τ = τ_residence from
core.heat_transfer.boundary_layer_residence_time_s, which makes
chemistry geometry-aware.

Together with Fay-Riddell heating, this closes the geometry-chemistry
coupling that the equilibrium path is missing.
"""
from __future__ import annotations

import math
import warnings


def cantera_residence_time_ne(
    T_initial_K: float,
    P_initial_Pa: float,
    residence_time_s: float = 1e-5,
    cantera_yaml: str = "air.yaml",
    plasma_yaml: str | None = None,
    composition: str = "N2:0.79, O2:0.21",
    n_steps: int = 50,
) -> dict:
    """Integrate a constant-(T, P) Cantera 0D reactor for τ seconds.

    Parameters
    ----------
    T_initial_K : initial reactor temperature (e.g. real-gas T_stag)
    P_initial_Pa : initial reactor pressure (Pitot stagnation pressure)
    residence_time_s : how long to integrate (1 µs default = kinetics
        regime; 100 µs = approaches equilibrium for re-entry chemistry)
    cantera_yaml : neutral-air mechanism (default Cantera built-in)
    plasma_yaml : optional ionized-air YAML for a separate ionization
        sub-mechanism. If provided, reactor is run on this; otherwise
        the neutral mechanism is used and ne is computed by Saha at the
        final state.
    composition : initial mole-fraction string

    Returns
    -------
    dict with ne_m3 (kinetics-evolved electron density), T_final_K,
    composition_x_final (mole fractions at τ), and trajectory (list of
    (t, T, ne) snapshots if requested).

    Falls back to {'error': '...'} if Cantera unavailable.
    """
    try:
        import cantera as ct
    except ImportError:
        return {"error": "cantera not installed",
                 "ne_m3": 0.0, "T_final_K": T_initial_K}

    yaml_path = plasma_yaml or cantera_yaml
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sol = ct.Solution(yaml_path)
    sol.TPX = T_initial_K, P_initial_Pa, composition

    reactor = ct.IdealGasConstPressureReactor(sol)
    sim = ct.ReactorNet([reactor])

    dt = residence_time_s / n_steps
    trajectory = []
    t = 0.0
    for _ in range(n_steps):
        t += dt
        try:
            sim.advance(t)
        except Exception as exc:
            return {"error": f"reactor advance failed: {exc}",
                     "ne_m3": 0.0, "T_final_K": float(reactor.thermo.T)}
        if "eminus" in reactor.thermo.species_names:
            ne_now = float(reactor.thermo.X[reactor.thermo.species_index("eminus")]
                            * reactor.thermo.density_mole)
        elif "e-" in reactor.thermo.species_names:
            ne_now = float(reactor.thermo.X[reactor.thermo.species_index("e-")]
                            * reactor.thermo.density_mole)
        else:
            ne_now = 0.0
        trajectory.append((t, float(reactor.thermo.T), ne_now))

    state = reactor.thermo
    if "eminus" in state.species_names:
        ne_final = float(state.X[state.species_index("eminus")] * state.density_mole)
    elif "e-" in state.species_names:
        ne_final = float(state.X[state.species_index("e-")] * state.density_mole)
    else:
        # No electrons in this YAML — fall back to Saha
        from .chemistry import saha_ne

        def _frac(name):
            return float(state.X[state.species_index(name)]) if name in state.species_names else 0.0

        s = saha_ne(
            T_K=float(state.T), P_Pa=float(state.P),
            x_N=_frac("N"), x_O=_frac("O"), x_NO=_frac("NO"),
        )
        ne_final = s["ne_m3"]

    composition_final = {
        sp: float(state.X[i])
        for i, sp in enumerate(state.species_names)
        if state.X[i] > 1e-8
    }
    return {
        "ne_m3": ne_final,
        "T_final_K": float(state.T),
        "P_final_Pa": float(state.P),
        "composition_x_final": composition_final,
        "trajectory": trajectory,
        "residence_time_s": residence_time_s,
    }
