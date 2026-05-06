"""Stagnation-point conditions: Pitot pressure + real-gas temperature.

For a blunt body at M > 1 the bow shock is detached. On the stagnation
streamline the shock is normal; the post-shock flow then decelerates
isentropically to the stagnation point. The stagnation pressure at the
body is therefore p_t,2 (Rayleigh-Pitot), NOT the isentropic stagnation
pressure of the freestream.

Stagnation TEMPERATURE depends on freestream + chemistry only — for an
adiabatic stagnation point T_t,2 satisfies h(T_t, p_t) = h_∞ + 0.5·U_∞².
At hypersonic conditions chemistry absorbs ~30-70% of the kinetic energy,
so T_t,real << T_t,frozen.

NOSE RADIUS does not enter either expression in the inviscid limit, which
is why stagnation chemistry is geometry-independent under perfect-gas
Pitot. (Fay-Riddell heating gives the wall heat flux as q_w ~ R_n^(-1/2)
but heating drives the BL, not the stagnation-point chemistry.)
"""
import math
import warnings

from .constants import GAMMA_AIR


def pitot_pressure(P_inf_Pa: float, M_inf: float,
                    gamma: float = GAMMA_AIR) -> float:
    """Rayleigh-Pitot stagnation pressure behind a normal shock.

    Anderson 2006 Eq. 9.65:
        p_t,2 / p_1 = [((γ+1)² M²) / (4γ M² − 2(γ−1))]^(γ/(γ−1))
                    · (1 − γ + 2γ M²) / (γ+1)

    For M < 1, falls back to the isentropic stagnation pressure
    formula since there's no shock in subsonic flow.
    """
    if M_inf <= 1.0:
        return P_inf_Pa * (1.0 + 0.5 * (gamma - 1.0) * M_inf**2) ** (gamma / (gamma - 1.0))
    g = gamma
    M2 = M_inf * M_inf
    pre = ((g+1)**2 * M2 / (4*g*M2 - 2*(g-1))) ** (g/(g-1))
    post = (1 - g + 2*g*M2) / (g + 1)
    return P_inf_Pa * pre * post


def stagnation_T_perfect(T_inf_K: float, M_inf: float,
                          gamma: float = GAMMA_AIR) -> float:
    """Perfect-gas (frozen, no chemistry) stagnation T.
        T_t / T_∞ = 1 + 0.5·(γ−1)·M²
    """
    return T_inf_K * (1.0 + 0.5 * (gamma - 1.0) * M_inf**2)


def stagnation_T_real_gas(
    T_inf_K: float, P_inf_Pa: float, U_inf_ms: float, P_t_Pa: float,
    gas_yaml: str = "air.yaml", composition: str = "N2:0.79, O2:0.21",
    T_lo: float = 500.0, T_hi: float = 30000.0,
    n_bisect: int = 60,
) -> dict:
    """Real-gas stagnation T via h_t = h_∞ + 0.5·U² with Cantera.

    Cantera handles partial dissociation of N2/O2 and NO formation, so
    T_t,real << T_t,frozen at hypersonic. Returns the equilibrium
    composition at (T_t,real, p_t) for downstream Saha/Cantera ionization.

    Falls back to ImportError-tolerant dict when Cantera isn't available.
    """
    try:
        import cantera as ct
    except ImportError:
        return {"error": "cantera not installed",
                "T_t_real_K": stagnation_T_perfect(T_inf_K, U_inf_ms /
                                                    math.sqrt(GAMMA_AIR * 287.058 * T_inf_K))}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sol = ct.Solution(gas_yaml)
    sol.TPX = T_inf_K, P_inf_Pa, composition
    sol.equilibrate("TP")
    h_inf = float(sol.enthalpy_mass)
    h_t = h_inf + 0.5 * U_inf_ms * U_inf_ms

    lo, hi = T_lo, T_hi
    for _ in range(n_bisect):
        mid = 0.5 * (lo + hi)
        sol.TPX = mid, P_t_Pa, composition
        sol.equilibrate("TP")
        if float(sol.enthalpy_mass) < h_t:
            lo = mid
        else:
            hi = mid
    T_t = 0.5 * (lo + hi)

    sol.TPX = T_t, P_t_Pa, composition
    sol.equilibrate("TP")

    def _frac(name: str) -> float:
        if name in sol.species_names:
            return float(sol.X[sol.species_index(name)])
        return 0.0

    return {
        "T_t_real_K": T_t,
        "P_t_Pa": P_t_Pa,
        "h_t_J_per_kg": h_t,
        "x_N2": _frac("N2"), "x_O2": _frac("O2"),
        "x_NO": _frac("NO"), "x_N":  _frac("N"),  "x_O": _frac("O"),
    }
