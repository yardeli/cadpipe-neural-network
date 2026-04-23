"""Standalone physics functions for PlasmaNet.

These are the exact same physics used in cadpipe's hypersonic_cfd_agent.py,
extracted here so PlasmaNet can generate training data and validate results
without depending on the cadpipe codebase.

All constants from NIST. All formulas from standard references.
"""
import math
import numpy as np

# ── Physical Constants (NIST 2019 SI exact where applicable) ──
K_B = 1.380649e-23      # Boltzmann constant (J/K) — exact 2019 SI
M_E = 9.1093837015e-31  # electron mass (kg)
H_PLANCK = 6.62607015e-34  # Planck constant (J·s) — exact
E_CHARGE = 1.602176634e-19  # elementary charge (C) — exact
EPS_0 = 8.8541878128e-12    # vacuum permittivity (F/m)
C_LIGHT = 2.99792458e8      # speed of light (m/s) — exact
R_UNIVERSAL = 8.314462618   # universal gas constant (J/(mol·K))
R_AIR = 287.058             # specific gas constant for air (J/(kg·K))

# Ionization energies (NIST Atomic Spectra Database)
EI_NO = 9.2642 * E_CHARGE   # NO ionization energy (J)
EI_O = 13.61806 * E_CHARGE   # O ionization energy (J)
EI_N = 14.53414 * E_CHARGE   # N ionization energy (J)

# Radar
STARLINK_FREQ_HZ = 12.0e9   # Ku-band (Hz)


def standard_atmosphere(altitude_km):
    """US Standard Atmosphere 1976.

    Returns (T_K, p_Pa, rho_kgm3, speed_of_sound_ms).
    Valid 0-60 km.
    """
    h = altitude_km * 1000.0
    if h < 11000:
        T = 288.15 - 0.0065 * h
        p = 101325.0 * (T / 288.15) ** 5.2561
    elif h < 20000:
        T = 216.65
        p = 22632.0 * math.exp(-0.00015769 * (h - 11000))
    elif h < 32000:
        T = 216.65 + 0.001 * (h - 20000)
        p = 5474.9 * (T / 216.65) ** (-34.1632)
    elif h < 47000:
        T = 228.65 + 0.0028 * (h - 32000)
        p = 868.02 * (T / 228.65) ** (-12.2009)
    elif h < 51000:
        T = 270.65
        p = 110.91 * math.exp(-0.00015769 * (h - 47000))
    elif h < 71000:
        T = 270.65 - 0.0028 * (h - 51000)
        p = 66.939 * (T / 270.65) ** (-12.2009)
    else:
        T = 214.65 - 0.002 * (h - 71000)
        p = 3.9564 * (T / 214.65) ** (17.0816)
    rho = p / (R_AIR * T)
    a = math.sqrt(1.4 * R_AIR * T)
    return T, p, rho, a


def cp_air(T):
    """Temperature-dependent Cp for air (J/kg/K).

    NASA 7-coefficient polynomial fit for 79% N2 + 21% O2 mixture.
    Source: NASA Glenn (McBride & Gordon 1996).
    """
    T = max(200.0, min(T, 6000.0))
    if T >= 1000:
        cp_N2 = (2.95258 + 1.3969e-3 * T - 4.9263e-7 * T**2
                 + 7.8601e-11 * T**3 - 4.6075e-15 * T**4)
        cp_O2 = (3.28254 + 1.4831e-3 * T - 7.5797e-7 * T**2
                 + 2.0950e-10 * T**3 - 2.1672e-14 * T**4)
    else:
        cp_N2 = (3.53101 - 1.2366e-4 * T - 5.0300e-7 * T**2
                 + 2.4353e-9 * T**3 - 1.4088e-12 * T**4)
        cp_O2 = (3.78246 - 2.9967e-3 * T + 9.8473e-6 * T**2
                 - 9.6813e-9 * T**3 + 3.2437e-12 * T**4)
    cp_R = 0.79 * cp_N2 + 0.21 * cp_O2
    return cp_R * R_AIR


def stagnation_temperature_perfect(T_inf, mach, gamma=1.4):
    """Perfect-gas stagnation temperature."""
    return T_inf * (1.0 + (gamma - 1.0) / 2.0 * mach ** 2)


def stagnation_temperature_real(T_inf, mach, p_inf):
    """Real-gas stagnation temperature via enthalpy inversion.

    Uses Cantera if available, otherwise falls back to iterative
    Cp-integration method.
    """
    a_inf = math.sqrt(1.4 * R_AIR * T_inf)
    U_inf = mach * a_inf
    h0 = cp_air(T_inf) * T_inf + 0.5 * U_inf ** 2

    try:
        import cantera as ct
        sol = ct.Solution("air.yaml")
        # Use pitot pressure (post-normal-shock stagnation) for hypersonic
        # blunt-body flow. Isentropic p_stag is only valid for subsonic flow.
        p_stag = pitot_pressure(p_inf, mach)
        T_lo, T_hi = 300.0, stagnation_temperature_perfect(T_inf, mach) * 1.5
        T_hi = min(T_hi, 30000.0)
        for _ in range(50):
            T_mid = (T_lo + T_hi) / 2.0
            sol.TP = T_mid, max(p_stag, 100.0)
            sol.equilibrate("TP")
            if sol.enthalpy_mass < h0:
                T_lo = T_mid
            else:
                T_hi = T_mid
        return (T_lo + T_hi) / 2.0
    except (ImportError, Exception):
        # Fallback: iterative Cp integration
        T_pg = stagnation_temperature_perfect(T_inf, mach)
        # Real-gas correction factor (empirical fit to Cantera results)
        # At high T, dissociation absorbs energy, lowering T_stag
        if T_pg < 2500:
            return T_pg
        # Approximate: integrate dh = Cp(T) dT from T_inf to T_stag
        T = T_inf
        dT = 10.0
        h_accum = 0.0
        while h_accum < 0.5 * U_inf ** 2 and T < 30000:
            h_accum += cp_air(T) * dT
            T += dT
        return T


def stagnation_pressure(p_inf, mach, gamma=1.4):
    """Isentropic stagnation pressure (perfect gas, subsonic flow).

    VALID ONLY for flow without a shock (M < 1, or subsonic inlet). For
    hypersonic bow-shock flow (what a blunt body at M > 2 sees), the
    correct stagnation pressure at the body stagnation point is obtained
    by passing through the normal portion of the bow shock and then
    decelerating isentropically — use pitot_pressure() for that.

    Kept for backward compatibility and low-Mach regimes.
    """
    return p_inf * (1.0 + (gamma - 1.0) / 2.0 * mach ** 2) ** (gamma / (gamma - 1.0))


def pitot_pressure(p_inf, mach, gamma=1.4):
    """Rayleigh pitot pressure — stagnation pressure behind a normal shock.

    For a blunt body at M > 1, the flow passes through a detached bow
    shock. On the stagnation streamline the shock is effectively normal.
    The stagnation pressure at the body is *not* the isentropic stagnation
    pressure of the freestream — there is an entropy jump across the shock.

    Rayleigh pitot formula:
        p_02/p_1 = [((γ+1)² M1²) / (4γ M1² − 2(γ−1))]^(γ/(γ−1))
                 · (1 − γ + 2γ M1²) / (γ+1)

    At M=10, γ=1.4 this gives p_02/p_1 ≈ 129 versus isentropic
    (1+0.2·100)^3.5 ≈ 48,168 — a factor of ~370 difference.

    For M < 1, falls back to the isentropic formula.

    Reference: Anderson, "Modern Compressible Flow" 3rd ed. §9.6.
    """
    if mach <= 1.0:
        return stagnation_pressure(p_inf, mach, gamma)
    gp = gamma + 1.0
    gm = gamma - 1.0
    M2 = mach * mach
    numer = (gp * gp * M2) / (4.0 * gamma * M2 - 2.0 * gm)
    term1 = numer ** (gamma / gm)
    term2 = (1.0 - gamma + 2.0 * gamma * M2) / gp
    return p_inf * term1 * term2


def post_shock_conditions(T_inf, p_inf, mach, gamma=1.4):
    """Perfect-gas post-normal-shock state (before isentropic deceleration).

    Returns (T2, p2, M2) immediately behind a normal shock at freestream
    Mach M1. Useful for initial-guess bracketing before real-gas
    Cantera equilibration.
    """
    if mach <= 1.0:
        return T_inf, p_inf, mach
    M1sq = mach * mach
    gp = gamma + 1.0
    gm = gamma - 1.0
    p_ratio = (2.0 * gamma * M1sq - gm) / gp
    T_ratio = (2.0 * gamma * M1sq - gm) * (gm * M1sq + 2.0) / (gp * gp * M1sq)
    M2sq = (gm * M1sq + 2.0) / (2.0 * gamma * M1sq - gm)
    return T_inf * T_ratio, p_inf * p_ratio, math.sqrt(M2sq)


# ── JANAF Dissociation Equilibrium ──

_JANAF_O2 = [
    (1000, -28.2), (1500, -16.1), (2000, -10.4), (2500, -7.1),
    (3000, -4.9), (3200, -4.1), (3500, -3.2), (3800, -2.5),
    (4000, -1.9), (4200, -1.5), (4500, -0.8), (4800, -0.2),
    (5000, 0.1), (5200, 0.4), (5500, 0.8), (6000, 1.4),
    (6500, 1.9), (7000, 2.4), (8000, 3.2), (9000, 3.8),
    (10000, 4.3), (12000, 5.0), (15000, 5.8),
]

_JANAF_N2 = [
    (2000, -24.0), (3000, -13.6), (3500, -10.8), (4000, -8.4),
    (4500, -6.6), (5000, -5.0), (5500, -3.8), (6000, -2.7),
    (6500, -1.8), (7000, -0.9), (7500, -0.3), (8000, 0.3),
    (8500, 0.9), (9000, 1.4), (10000, 2.2), (11000, 2.9),
    (12000, 3.6), (13000, 4.1), (15000, 5.1), (20000, 7.0),
]

_KP_NO_OVERALL = [
    (1000, -8.0), (1500, -5.5), (2000, -3.66), (2500, -2.75),
    (3000, -2.03), (3500, -1.83), (4000, -1.69), (4500, -1.40),
    (5000, -1.16), (6000, -0.80), (7000, -0.50), (8000, -0.30),
]


def _interp_table(T, table):
    """Linear interpolation on a (T, value) table."""
    if T <= table[0][0]:
        return table[0][1]
    if T >= table[-1][0]:
        return table[-1][1]
    for i in range(len(table) - 1):
        if table[i][0] <= T <= table[i + 1][0]:
            frac = (T - table[i][0]) / (table[i + 1][0] - table[i][0])
            return table[i][1] + frac * (table[i + 1][1] - table[i][1])
    return table[-1][1]


def janaf_equilibrium(T, p):
    """Analytical JANAF equilibrium composition (fallback, no Cantera needed)."""
    p_atm = p / 101325.0

    # O2 dissociation
    log10Kp_O2 = _interp_table(T, _JANAF_O2)
    Kp_O2 = 10.0 ** log10Kp_O2
    ratio_O2 = Kp_O2 / max(p_atm, 1e-10)
    alpha_O2 = min(1.0, math.sqrt(ratio_O2 / (1.0 + ratio_O2)))

    # N2 dissociation
    log10Kp_N2 = _interp_table(T, _JANAF_N2)
    Kp_N2 = 10.0 ** log10Kp_N2
    ratio_N2 = Kp_N2 / max(p_atm, 1e-10)
    alpha_N2 = min(1.0, math.sqrt(ratio_N2 / (1.0 + ratio_N2)))

    x_O2 = 0.21 * (1.0 - alpha_O2)
    x_O = 0.21 * 2.0 * alpha_O2
    x_N2 = 0.79 * (1.0 - alpha_N2)
    x_N = 0.79 * 2.0 * alpha_N2

    # NO formation (Zeldovich equilibrium)
    x_NO = 0.0
    if T > 1500:
        log10Kp_NO = _interp_table(T, _KP_NO_OVERALL)
        Kp_NO = 10.0 ** log10Kp_NO
        x_NO_sq = Kp_NO * x_N2 * x_O2
        x_NO = min(math.sqrt(max(0.0, x_NO_sq)), 0.15)

    # Normalize
    total = x_O2 + x_O + x_N2 + x_N + x_NO
    if total > 0:
        inv = 1.0 / total
        x_O2 *= inv
        x_O *= inv
        x_N2 *= inv
        x_N *= inv
        x_NO *= inv

    return x_N2, x_O2, x_O, x_N, x_NO


def saha_ionization(T, p, x_NO, x_O, x_N):
    """Compute electron density from Saha ionization.

    Partition functions from NIST Atomic Spectra Database.
    """
    if T < 800 or p <= 0:
        return 0.0

    saha_pre = (2.0 * math.pi * M_E * K_B * T / H_PLANCK ** 2) ** 1.5
    n_total = p / (K_B * T)

    # NO: spin-orbit + vibrational
    Q_NO = 2.0 + 2.0 * math.exp(-174.0 / T)
    if T > 100:
        Q_NO *= 1.0 / (1.0 - math.exp(-2740.0 / T))
    Q_NOp = 1.0
    if T > 100:
        Q_NOp *= 1.0 / (1.0 - math.exp(-3418.0 / T))
    S_NO = 2.0 * (Q_NOp / Q_NO) * saha_pre * math.exp(-EI_NO / (K_B * T))

    # O: fine structure + excited states
    Q_O = (5.0 + 3.0 * math.exp(-228.0 / T) + 1.0 * math.exp(-326.0 / T)
           + 5.0 * math.exp(-22830.0 / T) + 1.0 * math.exp(-48620.0 / T))
    # O+: 4S_3/2: g=4, 2D(J=3/2+5/2): g=4+6=10 at 38600K, 2P(J=1/2+3/2): g=2+4=6 at 58250K
    Q_Op = (4.0 + 10.0 * math.exp(-38600.0 / T) + 6.0 * math.exp(-58250.0 / T))
    S_O = 2.0 * (Q_Op / Q_O) * saha_pre * math.exp(-EI_O / (K_B * T))

    # N: ground + excited (NIST ASD, summing J-level degeneracies per term)
    # 4S_3/2: g=4, 2D(J=3/2+5/2): g=4+6=10 at 27670K, 2P(J=1/2+3/2): g=2+4=6 at 41500K
    Q_N = (4.0 + 10.0 * math.exp(-27670.0 / T) + 6.0 * math.exp(-41500.0 / T))
    # N+: 3P(J=0,1,2): g=1+3+5=9 split, 1D_2: g=5, 1S_0: g=1
    Q_Np = (1.0 + 3.0 * math.exp(-70.0 / T) + 5.0 * math.exp(-188.0 / T)
            + 5.0 * math.exp(-22040.0 / T) + 1.0 * math.exp(-47000.0 / T))
    S_N = 2.0 * (Q_Np / Q_N) * saha_pre * math.exp(-EI_N / (K_B * T))

    # Charge neutrality iteration
    n_NO = x_NO * n_total
    n_O = x_O * n_total
    n_N = x_N * n_total

    ne_sq = S_NO * n_NO + S_O * n_O + S_N * n_N
    ne = math.sqrt(max(0.0, ne_sq))

    for _ in range(20):  # extended from 8 for high-T convergence
        if ne < 1.0:
            break
        n_NO_n = n_NO / (1.0 + S_NO / ne) if ne > 0 else n_NO
        n_O_n = n_O / (1.0 + S_O / ne) if ne > 0 else n_O
        n_N_n = n_N / (1.0 + S_N / ne) if ne > 0 else n_N
        ne_new_sq = S_NO * n_NO_n + S_O * n_O_n + S_N * n_N_n
        ne_new = math.sqrt(max(0.0, ne_new_sq))
        if abs(ne_new - ne) < 1e-8 * max(ne, 1.0):
            ne = ne_new
            break
        ne = ne_new

    return ne


def nonequilibrium_correction(T_stag, ne_equil, nose_radius_m=0.08):
    """Non-equilibrium correction with geometry awareness.

    The correction factor depends on the Damkohler number, which scales
    with (rho_inf * nose_radius). Larger nose radius = more time to
    equilibrate = weaker correction (factor closer to 1.0).

    Base calibration is for nose_radius = 0.08 m (blunt cone test case).
    """
    if T_stag < 3500 or ne_equil <= 0:
        return ne_equil

    # Base correction table (calibrated for R_nose = 0.08 m)
    _NEQ_BASE = [
        (3500, 1.0), (3900, 0.26), (5300, 0.021),
        (7000, 0.010), (8100, 0.0085), (12000, 0.005),
    ]

    T = max(T_stag, 3500.0)
    if T >= _NEQ_BASE[-1][0]:
        factor_base = _NEQ_BASE[-1][1]
    else:
        factor_base = _NEQ_BASE[-1][1]
        for i in range(len(_NEQ_BASE) - 1):
            if _NEQ_BASE[i][0] <= T <= _NEQ_BASE[i + 1][0]:
                frac = (T - _NEQ_BASE[i][0]) / (_NEQ_BASE[i + 1][0] - _NEQ_BASE[i][0])
                lf = (math.log(_NEQ_BASE[i][1])
                      + frac * (math.log(_NEQ_BASE[i + 1][1]) - math.log(_NEQ_BASE[i][1])))
                factor_base = math.exp(lf)
                break

    # Geometry scaling: larger nose = closer to equilibrium
    # Damkohler number scales as R_nose / R_ref
    R_ref = 0.08  # reference nose radius (m)
    Da_ratio = nose_radius_m / R_ref
    # Correction weakens (factor increases toward 1.0) for larger noses
    # factor = 1 - (1 - factor_base) * exp(-k * (Da_ratio - 1))
    # For Da_ratio = 1 (reference), factor = factor_base
    # For Da_ratio >> 1 (large nose), factor -> 1.0 (equilibrium)
    # For Da_ratio << 1 (sharp nose), factor -> factor_base^(1/Da_ratio) (more frozen)
    if Da_ratio >= 1.0:
        factor = 1.0 - (1.0 - factor_base) * math.exp(-0.5 * (Da_ratio - 1.0))
    else:
        # Sharper nose: even further from equilibrium
        factor = factor_base ** (1.0 / max(Da_ratio, 0.01))

    factor = max(0.001, min(1.0, factor))
    return ne_equil * factor


def plasma_frequency_hz(ne):
    """Plasma frequency (Hz) from electron density (m^-3)."""
    if ne <= 0:
        return 0.0
    return (1.0 / (2.0 * math.pi)) * math.sqrt(ne * E_CHARGE ** 2 / (M_E * EPS_0))


def plasma_frequency_ghz(ne):
    """Plasma frequency (GHz) from electron density (m^-3)."""
    return plasma_frequency_hz(ne) / 1e9


def radar_status(fp_ghz, radar_freq_ghz=12.0):
    """Determine radar detection status."""
    if fp_ghz > radar_freq_ghz:
        return "BLACKOUT"
    elif fp_ghz > radar_freq_ghz * 0.25:
        return "ATTENUATED"
    else:
        return "DETECTABLE"


def full_analysis(mach, altitude_km, nose_radius_m=0.08, use_cantera=True,
                  use_neq=True, stagnation_pressure_model="pitot"):
    """Complete plasma analysis for one flight condition.

    Parameters
    ----------
    mach, altitude_km : freestream conditions
    nose_radius_m : vehicle nose radius (for optional NEQ scaling)
    use_cantera : use Cantera Gibbs minimisation; fall back to JANAF if False
    use_neq : apply the non-equilibrium correction (off by default for
        clean equilibrium training data)
    stagnation_pressure_model : 'pitot' (Rayleigh formula behind a normal
        shock — the PHYSICALLY CORRECT choice for hypersonic blunt bodies)
        or 'isentropic' (legacy — gives p_stag ~10000× too high at M=22,
        retained only for backward-compatibility with pre-2026-04-23 training
        checkpoints).

    Returns a dict with all predicted quantities.
    """
    T_inf, p_inf, rho_inf, a_inf = standard_atmosphere(altitude_km)
    if stagnation_pressure_model == "pitot":
        p_stag = pitot_pressure(p_inf, mach)
    elif stagnation_pressure_model == "isentropic":
        p_stag = stagnation_pressure(p_inf, mach)
    else:
        raise ValueError(
            f"stagnation_pressure_model must be 'pitot' or 'isentropic', "
            f"got {stagnation_pressure_model!r}")

    # Real-gas stagnation temperature
    if use_cantera:
        T_stag = stagnation_temperature_real(T_inf, mach, p_inf)
    else:
        T_stag = stagnation_temperature_perfect(T_inf, mach)

    # Species equilibrium
    cantera_worked = False
    if use_cantera:
        try:
            import cantera as ct
            sol = ct.Solution("air.yaml")
            sol.TPX = T_stag, max(p_stag, 100.0), "N2:0.79, O2:0.21"
            sol.equilibrate("TP")
            x_N2 = float(sol.X[sol.species_index("N2")])
            x_O2 = float(sol.X[sol.species_index("O2")])
            x_O = float(sol.X[sol.species_index("O")])
            x_N = float(sol.X[sol.species_index("N")])
            x_NO = float(sol.X[sol.species_index("NO")])
            cantera_worked = True
        except Exception:
            pass

    if not cantera_worked:
        x_N2, x_O2, x_O, x_N, x_NO = janaf_equilibrium(T_stag, p_stag)

    # Ionization
    cantera_plasma_worked = False
    if use_cantera:
        try:
            import cantera as ct
            mech_path = None
            import importlib.resources
            # Try to find the 11-species mechanism
            from pathlib import Path
            candidates = [
                Path(__file__).parent.parent.parent.parent / "cadpipe" / "mechanisms" / "air_plasma_11s.yaml",
                Path(__file__).parent.parent / "mechanisms" / "air_plasma_11s.yaml",
                Path("C:/Users/yarden/Desktop/cadpipe/mechanisms/air_plasma_11s.yaml"),
            ]
            for c in candidates:
                if c.exists():
                    mech_path = c
                    break

            if mech_path:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sol_plasma = ct.Solution(str(mech_path), "air_plasma")
                    sol_plasma.TPX = T_stag, max(p_stag, 100.0), "N2:0.79, O2:0.21"
                    sol_plasma.equilibrate("TP")
                    x_e = float(sol_plasma.X[sol_plasma.species_index("eminus")])
                    n_total = p_stag / (K_B * T_stag)
                    ne_equil = x_e * n_total
                    cantera_plasma_worked = True
        except Exception:
            pass

    if not cantera_plasma_worked:
        ne_equil = saha_ionization(T_stag, p_stag, x_NO, x_O, x_N)

    # Non-equilibrium correction (optional — disabled for clean training data)
    if use_neq:
        ne = nonequilibrium_correction(T_stag, ne_equil, nose_radius_m)
    else:
        ne = ne_equil

    # Plasma frequency
    fp = plasma_frequency_ghz(ne)
    status = radar_status(fp)

    return {
        "mach": mach,
        "altitude_km": altitude_km,
        "nose_radius_m": nose_radius_m,
        "T_inf_K": T_inf,
        "p_inf_Pa": p_inf,
        "p_stag_Pa": p_stag,
        "T_stag_K": T_stag,
        "x_N2": x_N2,
        "x_O2": x_O2,
        "x_O": x_O,
        "x_N": x_N,
        "x_NO": x_NO,
        "ne_m3": ne,
        "ne_equil_m3": ne_equil,
        "fp_GHz": fp,
        "status": status,
        "source": "cantera_plasma" if cantera_plasma_worked else ("cantera" if cantera_worked else "janaf"),
    }
