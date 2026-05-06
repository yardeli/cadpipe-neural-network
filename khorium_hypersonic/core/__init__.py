"""Core hypersonic physics primitives (geometry-agnostic).

Each module is a pure-physics layer:

    atmosphere   — US Standard Atmosphere 1976 (0-86 km)
    shock        — frozen Rankine-Hugoniot normal shock
    stagnation   — Rayleigh-Pitot + real-gas T_stag via Cantera enthalpy
    chemistry    — Saha + JANAF + equilibrium ne
    plasma       — plasma frequency, Appleton-Hartree attenuation
    standoff     — Billig 1967 bow-shock standoff

These match scripts/unified_hypersonic_solver.py's textbook references
and the audited plasmanet/physics.py functions (atmosphere sign-fix
applied 2026-05-03). Importing core does NOT pull in Cantera or torch —
those are optional and only loaded by the modules that need them.
"""
from .atmosphere import standard_atmosphere
from .shock import normal_shock_frozen
from .stagnation import (
    pitot_pressure, stagnation_T_perfect, stagnation_T_real_gas,
)
from .chemistry import saha_ne, janaf_air_equilibrium
from .plasma import (
    plasma_frequency_Hz, plasma_frequency_GHz,
    appleton_hartree_attenuation_dB, cutoff_ne_for_freq,
)
from .standoff import billig_sphere_standoff
from .heat_transfer import fay_riddell_qw, boundary_layer_residence_time_s
from .kinetics import cantera_residence_time_ne

__all__ = [
    "standard_atmosphere",
    "normal_shock_frozen",
    "pitot_pressure", "stagnation_T_perfect", "stagnation_T_real_gas",
    "saha_ne", "janaf_air_equilibrium",
    "plasma_frequency_Hz", "plasma_frequency_GHz",
    "appleton_hartree_attenuation_dB", "cutoff_ne_for_freq",
    "billig_sphere_standoff",
    "fay_riddell_qw", "boundary_layer_residence_time_s",
    "cantera_residence_time_ne",
]
