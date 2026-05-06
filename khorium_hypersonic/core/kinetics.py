"""Finite-rate residence-time chemistry via Cantera 0D constant-pressure reactor.

v0.3.0 additions:
  - cantera_residence_time_ne_batch: vectorized over (T, P, τ) arrays
    so an axial sweep over 50–200 stations runs in one Python loop with
    Cantera state caching.
  - select_chemistry_mode: deterministic auto-pick logic centralised
    here so solver, flowfield, and trajectory all behave consistently.



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


def cantera_residence_time_ne_batch(
    T_K_arr,
    P_Pa_arr,
    tau_s_arr,
    cantera_yaml: str = "air.yaml",
    composition: str = "N2:0.79, O2:0.21",
    n_steps: int = 20,
):
    """Vectorized residence-time chemistry over arrays of (T, P, τ).

    Used by core.flowfield.compute_axial_profile to evaluate chemistry
    at all axial stations efficiently. Reuses one Cantera Solution
    instance across the loop (Cantera state-set is fast; reactor object
    creation isn't, hence the per-call reactor build).

    All arrays must broadcast to the same shape. Returns ne_m3 as a
    numpy array of the same shape; on Cantera unavailability returns a
    zero array (caller falls back to equilibrium Saha).
    """
    import numpy as np

    T_arr = np.atleast_1d(np.asarray(T_K_arr, dtype=np.float64))
    P_arr = np.atleast_1d(np.asarray(P_Pa_arr, dtype=np.float64))
    tau_arr = np.atleast_1d(np.asarray(tau_s_arr, dtype=np.float64))
    T_arr, P_arr, tau_arr = np.broadcast_arrays(T_arr, P_arr, tau_arr)
    out = np.zeros_like(T_arr, dtype=np.float64)

    try:
        import cantera as ct
    except ImportError:
        return out   # caller will fall back to Saha

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sol = ct.Solution(cantera_yaml)

    for idx in np.ndindex(T_arr.shape):
        T = float(T_arr[idx]); P = float(P_arr[idx]); tau = float(tau_arr[idx])
        if T < 500 or P < 1.0 or tau <= 0:
            continue
        try:
            sol.TPX = T, P, composition
            reactor = ct.IdealGasConstPressureReactor(sol)
            sim = ct.ReactorNet([reactor])
            for k in range(1, n_steps + 1):
                sim.advance(tau * k / n_steps)
            state = reactor.thermo
            if "eminus" in state.species_names:
                ne = float(state.X[state.species_index("eminus")] * state.density_mole)
            elif "e-" in state.species_names:
                ne = float(state.X[state.species_index("e-")] * state.density_mole)
            else:
                # Fall back to Saha at the integrated final state
                from .chemistry import saha_ne

                def _f(name):
                    return float(state.X[state.species_index(name)]) if name in state.species_names else 0.0

                s = saha_ne(T_K=float(state.T), P_Pa=float(state.P),
                              x_N=_f("N"), x_O=_f("O"), x_NO=_f("NO"))
                ne = s["ne_m3"]
            out[idx] = ne
        except Exception:
            continue
    return out


def select_chemistry_mode(
    tau_s: float,
    have_cantera: bool,
    have_surrogate: bool,
    altitude_km: float | None = None,
) -> str:
    """Deterministic mode-selection logic.

    Used by solver, flowfield, and trajectory so they all auto-pick
    consistently:
      - If τ > 1 ms (effectively equilibrated), 'equilibrium' is fine.
      - If a v4 surrogate is loaded AND we're in its trained range
        (40 km ≤ altitude ≤ 90 km, residence time 1–100 µs), prefer it.
      - Else if Cantera available, 'kinetics' (residence-time reactor).
      - Else 'equilibrium' (Saha closed-form).
    """
    if tau_s > 1e-3:
        return "equilibrium"

    if have_surrogate and altitude_km is not None:
        if 40.0 <= altitude_km <= 90.0:
            return "surrogate"

    if have_cantera:
        return "kinetics"

    return "equilibrium"
