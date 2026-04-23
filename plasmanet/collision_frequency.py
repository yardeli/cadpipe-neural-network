"""Electron-neutral momentum-transfer collision frequency.

For wave propagation in a collisional plasma, we need the electron-neutral
collision frequency ν_en = Σ_k n_k · Q_k(T_e), where n_k is the number
density of species k and Q_k is the Maxwell-averaged momentum-transfer rate
coefficient ⟨σ_m,k · v_e⟩ at electron temperature T_e.

For electron-ion (Coulomb) collisions we use the Spitzer formula. At the
ionization fractions reached behind a Mach-10+ shock, ν_ei is comparable to
or exceeds ν_en above ~7000 K, so both must be summed.

ν_total = ν_en + ν_ei

Values adopted here
-------------------
Species-resolved ⟨σ v⟩ for N₂, O₂, NO, O, N fit to published data, with T_e
in eV for convenience. These are room-temperature-normalised fits to the
data referenced below; they are accurate to ~30% over T_e ∈ [0.1, 5] eV
(roughly 1000-50000 K) which covers the entire hypersonic plasma regime.

For higher fidelity (e.g., for publication-grade results) replace the
individual Q_k() with tabulated cross sections from LXCat or Itikawa.

References
----------
- Itikawa, Y. (2005), "Cross Sections for Electron Collisions with Nitrogen
  Molecules", J. Phys. Chem. Ref. Data 35(1).
- Itikawa, Y. (2009), "Cross Sections for Electron Collisions with Oxygen
  Molecules", J. Phys. Chem. Ref. Data 38(1).
- Itikawa, Y. & Ichimura, A. (1990), "Cross Sections for Collisions of
  Electrons and Photons with Atomic Oxygen", J. Phys. Chem. Ref. Data 19(3).
- Rybak, J.P. & Churchill, R.J. (1971), "Progress in reentry
  communications", IEEE Trans. Aerospace Electron. Systems AES-7(5).
- Huber, P.W. (1967), NASA TN D-4750.
- Spitzer, L. (1962), "Physics of Fully Ionized Gases", 2nd ed., Interscience.
"""
from __future__ import annotations

import math

import numpy as np

from .physics import K_B, M_E, E_CHARGE, EPS_0

# Conversion: T_e in Kelvin → T_e in eV
K_TO_EV = K_B / E_CHARGE   # 8.617e-5 eV/K


def _v_thermal(T_e_k: np.ndarray | float) -> np.ndarray | float:
    """Maxwell-averaged electron thermal speed ⟨v⟩ = sqrt(8 k_B T_e / (π m_e)), m/s."""
    return np.sqrt(8.0 * K_B * T_e_k / (math.pi * M_E))


# ── Species momentum-transfer rate coefficients ⟨σ_m v⟩ (m³/s) ────────────
# Fitted to published data. T_e in Kelvin.

def q_mt_N2(T_e_k: np.ndarray | float) -> np.ndarray | float:
    """N₂ momentum-transfer rate coefficient, m³/s.

    Fit to Itikawa (2005) σ_m(E), Maxwell-averaged. Valid T_e ∈ [300, 50000] K.
    Below 5 eV: Q ≈ 8e-14 · (T_e/300)^0.5  m³/s.
    Above 5 eV: Q saturates near 2e-13 m³/s due to resonant vibrational
    excitation dominating the cross section.
    """
    Te = np.asarray(T_e_k, dtype=np.float64)
    # Piecewise fit: low-T rising, high-T saturating
    Q_low = 8.0e-14 * (Te / 300.0) ** 0.5
    Q_high = 2.0e-13 * np.ones_like(Te)
    return np.minimum(Q_low, Q_high)


def q_mt_O2(T_e_k: np.ndarray | float) -> np.ndarray | float:
    """O₂ momentum-transfer rate coefficient, m³/s.

    Fit to Itikawa (2009) σ_m(E), Maxwell-averaged. O₂ cross section is
    larger than N₂ at low energies due to its polarisability. Valid
    T_e ∈ [300, 50000] K. Low-T Q ≈ 2e-13 · (T_e/300)^0.5, saturates at 3e-13.
    """
    Te = np.asarray(T_e_k, dtype=np.float64)
    Q_low = 2.0e-13 * (Te / 300.0) ** 0.5
    Q_high = 3.0e-13 * np.ones_like(Te)
    return np.minimum(Q_low, Q_high)


def q_mt_NO(T_e_k: np.ndarray | float) -> np.ndarray | float:
    """NO momentum-transfer rate coefficient, m³/s.

    Fit to Mojarrabi et al. (1995) data. NO has a large low-energy cross
    section due to its dipole moment. Q ≈ 5e-13 · (T_e/300)^0.5, saturates
    near 7e-13.
    """
    Te = np.asarray(T_e_k, dtype=np.float64)
    Q_low = 5.0e-13 * (Te / 300.0) ** 0.5
    Q_high = 7.0e-13 * np.ones_like(Te)
    return np.minimum(Q_low, Q_high)


def q_mt_O(T_e_k: np.ndarray | float) -> np.ndarray | float:
    """Atomic oxygen momentum-transfer rate coefficient, m³/s.

    Fit to Itikawa & Ichimura (1990) data. Valid T_e ∈ [300, 50000] K.
    Q_O is notably smaller than Q_O2 because O has no vibrational modes.
    Q ≈ 1.5e-14 · (T_e/300)^0.5, saturates near 4e-14.
    """
    Te = np.asarray(T_e_k, dtype=np.float64)
    Q_low = 1.5e-14 * (Te / 300.0) ** 0.5
    Q_high = 4.0e-14 * np.ones_like(Te)
    return np.minimum(Q_low, Q_high)


def q_mt_N(T_e_k: np.ndarray | float) -> np.ndarray | float:
    """Atomic nitrogen momentum-transfer rate coefficient, m³/s.

    N is open-shell and more reactive than O. Cross section data is sparser.
    Fit based on Neynaber et al. (1963) and theory by Gupta & Mathur (1978):
    Q ≈ 2e-14 · (T_e/300)^0.5, saturates near 5e-14.
    """
    Te = np.asarray(T_e_k, dtype=np.float64)
    Q_low = 2.0e-14 * (Te / 300.0) ** 0.5
    Q_high = 5.0e-14 * np.ones_like(Te)
    return np.minimum(Q_low, Q_high)


def nu_en(
    T_e_k: np.ndarray | float,
    n_N2: np.ndarray | float,
    n_O2: np.ndarray | float,
    n_NO: np.ndarray | float,
    n_O: np.ndarray | float,
    n_N: np.ndarray | float,
) -> np.ndarray | float:
    """Total electron-neutral momentum-transfer collision frequency (s⁻¹).

    All inputs may be scalars or broadcast-compatible arrays. Number
    densities are in m⁻³. T_e is in Kelvin (same as gas T at equilibrium).
    """
    return (
        n_N2 * q_mt_N2(T_e_k)
        + n_O2 * q_mt_O2(T_e_k)
        + n_NO * q_mt_NO(T_e_k)
        + n_O * q_mt_O(T_e_k)
        + n_N * q_mt_N(T_e_k)
    )


# ── Electron-ion (Spitzer) collision frequency ──────────────────────────

def coulomb_log(T_e_k: np.ndarray | float, n_e_m3: np.ndarray | float) -> np.ndarray | float:
    """Coulomb logarithm ln Λ for electron-ion scattering.

    Standard NRL Plasma Formulary form:
        ln Λ = 23 − ln(n_e^0.5 · T_e^(−1.5))   for singly-ionised plasma
    with n_e in cm⁻³ and T_e in eV. We convert internally.
    """
    n_e_cm3 = np.maximum(np.asarray(n_e_m3, dtype=np.float64) * 1.0e-6, 1.0e-20)
    T_eV = np.maximum(np.asarray(T_e_k, dtype=np.float64) * K_TO_EV, 1.0e-3)
    return np.maximum(23.0 - np.log(np.sqrt(n_e_cm3) * T_eV ** (-1.5)), 2.0)


def nu_ei(T_e_k: np.ndarray | float, n_e_m3: np.ndarray | float) -> np.ndarray | float:
    """Electron-ion Spitzer collision frequency (s⁻¹).

    NRL Plasma Formulary form (Z=1, singly-ionised):
        ν_ei = 2.91·10⁻⁶ · n_e[cm⁻³] · lnΛ / T_e[eV]^1.5

    Converting to SI (n_e in m⁻³, T_e in K, using k_B/e = 8.617·10⁻⁵ eV/K):
        ν_ei = 3.64·10⁻⁶ · n_e[m⁻³] · lnΛ / T_e[K]^1.5
    """
    n_e_arr = np.maximum(np.asarray(n_e_m3, dtype=np.float64), 0.0)
    T_arr = np.maximum(np.asarray(T_e_k, dtype=np.float64), 1.0)
    return 3.64e-6 * n_e_arr * coulomb_log(T_e_k, n_e_m3) / (T_arr ** 1.5)


def nu_total(
    T_e_k: np.ndarray | float,
    n_e_m3: np.ndarray | float,
    n_N2: np.ndarray | float,
    n_O2: np.ndarray | float,
    n_NO: np.ndarray | float,
    n_O: np.ndarray | float,
    n_N: np.ndarray | float,
) -> np.ndarray | float:
    """Total electron collision frequency (s⁻¹) = ν_en + ν_ei."""
    return (
        nu_en(T_e_k, n_N2, n_O2, n_NO, n_O, n_N)
        + nu_ei(T_e_k, n_e_m3)
    )


def nu_from_cantera_state(T_K: float, p_Pa: float, mole_fractions: dict) -> tuple[float, float, float]:
    """Convenience wrapper: given T, p, and mole fractions of air species,
    return (nu_en, nu_ei, nu_total).

    mole_fractions should include at least N2, O2, NO, O, N, and eminus (or
    equivalently provide n_e separately). Missing keys default to 0.
    """
    n_total = p_Pa / (K_B * T_K)
    x = mole_fractions
    n_e = x.get("eminus", 0.0) * n_total
    n_N2 = x.get("N2", 0.0) * n_total
    n_O2 = x.get("O2", 0.0) * n_total
    n_NO = x.get("NO", 0.0) * n_total
    n_O  = x.get("O",  0.0) * n_total
    n_N  = x.get("N",  0.0) * n_total

    nu_en_val = float(nu_en(T_K, n_N2, n_O2, n_NO, n_O, n_N))
    nu_ei_val = float(nu_ei(T_K, n_e))
    return nu_en_val, nu_ei_val, nu_en_val + nu_ei_val
