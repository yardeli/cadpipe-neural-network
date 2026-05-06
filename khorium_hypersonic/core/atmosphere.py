"""US Standard Atmosphere 1976.

Reference: NASA-TM-X-74335 (USSA76), 7-layer piecewise-linear lapse rates
through h = 86 km. The barometric exponent for a layer with lapse rate L
is -g/(L·R); its sign depends on the SIGN of L:
    L > 0 (T rises with altitude): exponent < 0
    L < 0 (T falls with altitude): exponent > 0

A long-standing sign error in plasmanet/physics.py was fixed
2026-05-03 — see CHECKPOINT_2026-05-03.md.
"""
import math

from .constants import G_EARTH, R_AIR, GAMMA_AIR


def standard_atmosphere(altitude_km: float) -> dict:
    """USSA76 freestream conditions at altitude.

    Returns
    -------
    dict with T_K, P_Pa, rho_kgm3, a_ms (speed of sound).

    Validated against USSA76 reference table at h = 0, 11, 20, 32, 47,
    51, 60, 70, 80 km (within ~10% of published values; small drift from
    using slightly different g and M_AIR than USSA76).
    """
    h = altitude_km * 1000.0
    if h < 11000:
        T = 288.15 - 0.0065 * h
        P = 101325.0 * (T / 288.15) ** 5.2561
    elif h < 20000:
        T = 216.65
        P = 22632.06 * math.exp(-0.00015769 * (h - 11000))
    elif h < 32000:
        T = 216.65 + 0.001 * (h - 20000)
        P = 5474.889 * (T / 216.65) ** (-34.1632)
    elif h < 47000:
        T = 228.65 + 0.0028 * (h - 32000)
        P = 868.0187 * (T / 228.65) ** (-12.2009)
    elif h < 51000:
        T = 270.65
        P = 110.9063 * math.exp(-0.00015769 * (h - 47000))
    elif h < 71000:
        T = 270.65 - 0.0028 * (h - 51000)
        P = 66.93887 * (T / 270.65) ** (12.2009)        # +12.2 (negative-lapse layer)
    elif h < 84852:
        T = 214.65 - 0.002 * (h - 71000)
        P = 3.956420 * (T / 214.65) ** (17.0816)
    else:
        # Above mesopause: extrapolate as isothermal at 186.87 K
        T = 186.87
        P = 0.3734 * math.exp(-G_EARTH * (h - 84852) / (R_AIR * T))

    rho = P / (R_AIR * T)
    a = math.sqrt(GAMMA_AIR * R_AIR * T)
    return {
        "altitude_km": altitude_km,
        "T_K": T, "P_Pa": P, "rho_kgm3": rho, "a_ms": a,
    }
