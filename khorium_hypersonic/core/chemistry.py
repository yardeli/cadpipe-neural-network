"""Equilibrium chemistry helpers: Saha + JANAF for air at high T.

These are the closed-form fallbacks that don't need Cantera. For a
proper hypersonic chemistry calculation use stagnation_T_real_gas
(Cantera) and then route through Saha for the ionization step.
"""
import math

from .constants import (
    K_B, M_E, H_PLANCK, E_CHARGE,
    EI_NO_eV, EI_O_eV, EI_N_eV,
)


def saha_ne(T_K: float, P_Pa: float,
             x_N: float, x_O: float, x_NO: float) -> dict:
    """Closed-form Saha electron density.

    Sums NO+ + O+ + N+ contributions with their respective ionization
    energies. NO+ dominates at re-entry temperatures (4-8 kK) because
    its ionization energy is lowest (9.26 eV vs 13.6 / 14.5 eV for O / N).

    Saha equation:
        n_e² / n_X = (2π m_e k T / h²)^(3/2) · 2 · exp(-E_i / kT)

    Sums over X ∈ {NO, O, N}:
        n_e² ≈ Σ K_X · n_X
    """
    n_total = P_Pa / (K_B * T_K)

    def _saha_K(EI_eV: float) -> float:
        return ((2 * math.pi * M_E * K_B * T_K / H_PLANCK**2) ** 1.5
                * 2.0 * math.exp(-EI_eV * E_CHARGE / (K_B * T_K)))

    K_NO = _saha_K(EI_NO_eV)
    K_O  = _saha_K(EI_O_eV)
    K_N  = _saha_K(EI_N_eV)
    ne_sq = K_NO * x_NO * n_total + K_O * x_O * n_total + K_N * x_N * n_total
    ne = math.sqrt(max(ne_sq, 0.0))
    return {"ne_m3": ne, "n_total_m3": n_total,
             "saha_K_NO": K_NO, "saha_K_O": K_O, "saha_K_N": K_N}


def janaf_air_equilibrium(T_K: float, P_Pa: float) -> dict:
    """JANAF-based equilibrium mole fractions for 5-species air.

    Approximate fallback when Cantera isn't available. Solves the
    coupled equilibria
        O2  ↔ 2 O      (Kp1)
        N2  ↔ 2 N      (Kp2)
        N2 + O2 ↔ 2 NO (Kp3)
    with tabulated log10(Kp) from Chase 1998 JANAF 4th ed. (chunked at
    500 K spacing). Adequate for first-order checks; not a substitute
    for Cantera Gibbs minimization.
    """
    # log10(Kp) tabulated at 500-K intervals from 2000 K to 12000 K
    # Source: Chase 1998 (NIST JANAF Thermochemical Tables 4th ed.)
    T_table = [2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000,
                7000, 8000, 9000, 10000, 12000]
    log_Kp1 = [-9.6, -6.2, -3.5, -1.5, +0.0, +1.1, +2.0, +2.7, +3.3, +4.2, +4.9, +5.5, +5.9, +6.6]
    log_Kp2 = [-26, -19, -14.5, -11.0, -8.4, -6.3, -4.6, -3.2, -2.0, +0.0, +1.5, +2.7, +3.7, +5.2]
    log_Kp3 = [-3.5, -2.6, -2.0, -1.6, -1.3, -1.0, -0.8, -0.7, -0.6, -0.4, -0.2, 0.0, +0.1, +0.3]

    def _interp(table_y, T):
        if T <= T_table[0]: return table_y[0]
        if T >= T_table[-1]: return table_y[-1]
        for i in range(len(T_table) - 1):
            if T_table[i] <= T <= T_table[i+1]:
                frac = (T - T_table[i]) / (T_table[i+1] - T_table[i])
                return table_y[i] + frac * (table_y[i+1] - table_y[i])
        return table_y[-1]

    Kp1 = 10 ** _interp(log_Kp1, T_K)
    Kp2 = 10 ** _interp(log_Kp2, T_K)
    Kp3 = 10 ** _interp(log_Kp3, T_K)

    p_atm = P_Pa / 101325.0
    # Approximate decoupled solver: O2 + N2 + (NO traces)
    # x_O = sqrt(Kp1·x_O2 / p_atm); x_N = sqrt(Kp2·x_N2 / p_atm)
    # iterate twice
    x_N2, x_O2 = 0.79, 0.21
    for _ in range(8):
        x_O = math.sqrt(max(Kp1 * x_O2 / p_atm, 0.0))
        x_N = math.sqrt(max(Kp2 * x_N2 / p_atm, 0.0))
        x_NO = math.sqrt(max(Kp3 * x_N2 * x_O2, 0.0))
        # Re-normalize keeping element balance approximately
        total = x_N2 + x_O2 + x_NO + x_O + x_N
        x_N2 /= total; x_O2 /= total
        x_NO /= total; x_O /= total; x_N /= total
        # Reduce parents proportionally
        x_N2 = max(0.79 - 0.5 * x_N - 0.5 * x_NO, 0.0)
        x_O2 = max(0.21 - 0.5 * x_O - 0.5 * x_NO, 0.0)

    return {"x_N2": x_N2, "x_O2": x_O2, "x_NO": x_NO,
             "x_O": x_O, "x_N": x_N,
             "Kp1": Kp1, "Kp2": Kp2, "Kp3": Kp3}
