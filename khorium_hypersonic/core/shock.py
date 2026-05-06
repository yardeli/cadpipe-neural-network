"""Frozen normal-shock Rankine-Hugoniot (perfect gas, γ=1.4).

Anderson 2006, "Modern Compressible Flow" Ch. 3, Eqs. 3.57–3.59.

Frozen because we ignore chemistry across the shock. For real-gas
(equilibrium-chemistry) post-shock conditions, downstream Cantera handles
the equilibration. The frozen result is a fast first-order anchor and a
sanity reference.
"""
import math

from .constants import GAMMA_AIR


def normal_shock_frozen(M1: float, T1_K: float, P1_Pa: float,
                         rho1_kgm3: float, gamma: float = GAMMA_AIR) -> dict:
    """Closed-form Rankine-Hugoniot post-shock state.

    Parameters
    ----------
    M1 : pre-shock Mach number
    T1_K, P1_Pa, rho1_kgm3 : pre-shock state
    gamma : ratio of specific heats (default 1.4 for air)

    Returns
    -------
    dict with T2_K, P2_Pa, rho2_kgm3, M2, rho_ratio, p_ratio.
    """
    g = gamma
    M1sq = M1 * M1
    T2 = T1_K * (2*g*M1sq - (g-1)) * ((g-1)*M1sq + 2) / ((g+1)**2 * M1sq)
    p_ratio = (2*g*M1sq - (g-1)) / (g + 1)
    P2 = P1_Pa * p_ratio
    rho_ratio = (g+1) * M1sq / ((g-1)*M1sq + 2)
    rho2 = rho1_kgm3 * rho_ratio
    M2 = math.sqrt(((g-1)*M1sq + 2) / (2*g*M1sq - (g-1)))
    return {
        "T2_K": T2, "P2_Pa": P2, "rho2_kgm3": rho2, "M2": M2,
        "rho_ratio": rho_ratio, "p_ratio": p_ratio,
    }
