"""Analytical sheath profile — geometry-aware, Billig-anchored.

This is a thin wrapper over plasmanet.ram_c_validation.SheathProfile,
exposed in a way that takes ANY Geometry object (not just RAM-C). The
inner profile uses Billig 1967 for standoff thickness as of
2026-05-03 and so scales correctly for any sphere-cone (sharp_narrow
through capsule).
"""
from __future__ import annotations

from plasmanet.line_of_sight import AxisymmetricField
from plasmanet.ram_c_validation import SheathProfile

from ..geometry.base import Geometry


def build_analytical_sheath_field(
    geometry: Geometry,
    ne_peak_stag: float,
    T_e_peak_K: float,
    n_neutral_peak_m3: float,
    mach_freestream: float,
    shock_density_ratio_eq: float = 14.0,
) -> AxisymmetricField:
    """Build an axisymmetric (ne, ν_c) field for the given geometry.

    Parameters
    ----------
    geometry : any Geometry — uses effective_nose_radius_m,
        characteristic_length_m, half_angle_deg
    ne_peak_stag : peak electron density at the stagnation point (m^-3)
    T_e_peak_K   : electron temperature at peak (K)
    n_neutral_peak_m3 : total neutral number density at peak (m^-3)
    mach_freestream : freestream Mach (drives Billig standoff)
    shock_density_ratio_eq : ρ₂/ρ_∞ in equilibrium (default 14 at hypersonic)

    Returns
    -------
    AxisymmetricField — callable returning (ne, ν_c) at (r, z) coords
    in vehicle frame (axis along z).
    """
    profile = SheathProfile(
        ne_peak_stag=ne_peak_stag,
        nose_radius_m=geometry.effective_nose_radius_m(),
        body_length_m=geometry.characteristic_length_m(),
        half_angle_deg=geometry.effective_half_angle_deg(),
        T_e_peak_K=T_e_peak_K,
        n_neutral_peak_m3=n_neutral_peak_m3,
        mach_freestream=mach_freestream,
        shock_density_ratio=shock_density_ratio_eq,
    )

    def ne_rz(r, z):
        return profile.ne_at_rz(r, z)

    def nu_rz(r, z):
        return profile.nu_at_rz(r, z)

    return AxisymmetricField(ne_rz=ne_rz, nu_rz=nu_rz)
