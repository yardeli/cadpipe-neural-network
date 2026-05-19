"""v5.2 multi-fuel mechanism axis.

Extends the Park-AIR-7 47-reaction axis with optional H2/O2 and CH4/Air
combustion chemistry, so the surrogate-search framework can score
scramjet ingestion of fuel into the plasma sheath. Pure-air callers
keep the v5_prime behaviour bit-exact (FuelKind.NONE adds nothing).

Two fuels are implemented at v5.2:

  - **H2/O2**: 9 species, 11 reactions. Compact, well-validated. The
    H2/O2 system is the natural first cut because radiative scramjets
    historically test on H2 (e.g. X-43A flew on hydrogen).

  - **CH4/Air**: GRI-Mech-skeletal 16-reaction reduced mechanism over
    14 species. Roughly captures the steady-state CH4 oxidation
    behaviour relevant to plasma sheath chemistry (full GRI-Mech 3.0
    has 53 species × 325 reactions — too wide for the search axis).

The rate constants below are literature-grade for the *framework*
plumbing; the v5.2 training run is expected to load a higher-fidelity
mechanism (Connaire 2004 for H2, GRI-Mech 3.0 for CH4) once the data-
collection budget is approved. See ``docs/SURROGATE_V5_2_PLAN.md`` §3.

Composite mechanism construction
--------------------------------

``composite_air_fuel_mechanism(air, fuel_kind, equivalence_ratio)``
returns a new :class:`Mechanism` whose species/reactions are the union
of:

  - the input ``air`` Mechanism (Park-AIR-7 by default, or a subset
    proposed by the AI search)
  - the fuel's reactions filtered to species present in the union

The composite Mechanism inherits ``to_cantera_yaml`` from the base
class so the existing ``cantera_evaluator.evaluate`` path Just Works
on any composite — the YAML leak fix landed last commit means we
can run many composite evaluations without disk-filling the VM.

Freestream feature for the v5.2 surrogate
-----------------------------------------

The v5_prime 5-d feature ``(alt, M, T, P, log10(τ))`` extends to 7-d
for v5.2:

  - feature[5] = ``equivalence_ratio_norm``     (φ_fuel / 4.0)
  - feature[6] = ``fuel_kind_id / 2.0``         (0 = AIR, 1 = H2, 2 = CH4)

``equivalence_ratio = 0`` and ``fuel_kind = AIR`` collapse the v5.2
surrogate back to the v5_prime behaviour on pure air (verifies as a
regression test before any new training is started).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

from .generator import Mechanism, Reaction


# ── Public enum ─────────────────────────────────────────────────────

class FuelKind(Enum):
    AIR = 0      # no fuel — pure-air axis, v5_prime-compatible
    H2 = 1       # hydrogen/oxygen scramjet (X-43A class)
    CH4 = 2      # methane/air scramjet (HyShot III heritage)


# ── Hydrogen / oxygen mechanism (11 reactions) ─────────────────────
# Source: Li, Zhao, Kazakov, Dryer (2004) Int. J. Chem. Kinet. 36, 566-575,
# subset to the 11 most-important reactions per their sensitivity ranking.
# Forward rates in cm^3/(mol·s), theta_a in K.

H2_SPECIES = ["H2", "O2", "H2O", "H", "O", "OH", "HO2", "H2O2"]

H2_REACTIONS: list[Reaction] = [
    Reaction(rxn_id=100, formula="H2 + O2 <=> H + HO2",
              reactants={"H2": 1, "O2": 1}, products={"H": 1, "HO2": 1},
              A=7.4e5, n=2.43, theta_a=26926.0,
              is_exchange=True, notes="Li 2004 R1 — slow initiation"),
    Reaction(rxn_id=101, formula="H + O2 <=> O + OH",
              reactants={"H": 1, "O2": 1}, products={"O": 1, "OH": 1},
              A=3.55e15, n=-0.41, theta_a=8348.0,
              is_exchange=True, notes="Li 2004 R2 — chain branching"),
    Reaction(rxn_id=102, formula="O + H2 <=> H + OH",
              reactants={"O": 1, "H2": 1}, products={"H": 1, "OH": 1},
              A=5.08e4, n=2.67, theta_a=3166.0,
              is_exchange=True, notes="Li 2004 R3"),
    Reaction(rxn_id=103, formula="OH + H2 <=> H + H2O",
              reactants={"OH": 1, "H2": 1}, products={"H": 1, "H2O": 1},
              A=2.16e8, n=1.51, theta_a=1726.0,
              is_exchange=True, notes="Li 2004 R4 — major H2O producer"),
    Reaction(rxn_id=104, formula="OH + OH <=> O + H2O",
              reactants={"OH": 2}, products={"O": 1, "H2O": 1},
              A=2.10e8, n=1.40, theta_a=-200.0,
              is_exchange=True, notes="Li 2004 R5"),
    Reaction(rxn_id=105, formula="H2 + M <=> H + H + M",
              reactants={"H2": 1, "M": 1}, products={"H": 2, "M": 1},
              A=4.58e19, n=-1.40, theta_a=52525.0,
              has_third_body=True, is_dissociation=True,
              notes="Li 2004 R6 — H2 dissociation"),
    Reaction(rxn_id=106, formula="O2 + M <=> O + O + M",
              reactants={"O2": 1, "M": 1}, products={"O": 2, "M": 1},
              A=4.58e19, n=-1.40, theta_a=59500.0,
              has_third_body=True, is_dissociation=True,
              notes="Li 2004 R7"),
    Reaction(rxn_id=107, formula="H2O + M <=> H + OH + M",
              reactants={"H2O": 1, "M": 1}, products={"H": 1, "OH": 1, "M": 1},
              A=6.06e27, n=-3.32, theta_a=60790.0,
              has_third_body=True, is_dissociation=True,
              notes="Li 2004 R10 — endothermic"),
    Reaction(rxn_id=108, formula="H + O2 + M <=> HO2 + M",
              reactants={"H": 1, "O2": 1, "M": 1}, products={"HO2": 1, "M": 1},
              A=6.37e20, n=-1.72, theta_a=261.0,
              has_third_body=True,
              notes="Li 2004 R12 — pressure-dependent, treated as Lindemann here"),
    Reaction(rxn_id=109, formula="HO2 + H <=> H2 + O2",
              reactants={"HO2": 1, "H": 1}, products={"H2": 1, "O2": 1},
              A=1.66e13, n=0.0, theta_a=413.0,
              is_exchange=True, notes="Li 2004 R14"),
    Reaction(rxn_id=110, formula="HO2 + OH <=> H2O + O2",
              reactants={"HO2": 1, "OH": 1}, products={"H2O": 1, "O2": 1},
              A=2.89e13, n=0.0, theta_a=-250.0,
              is_exchange=True, notes="Li 2004 R16"),
]


# ── Methane / air skeletal mechanism (16 reactions) ────────────────
# Source: Smooke (1991) "Reduced kinetic mechanisms for methane-air",
# Lecture Notes in Physics 384. Chosen as the smallest validated
# CH4-air kinetic set; v5.2 training is expected to upgrade to full
# GRI-Mech 3.0 once the data-collection budget is approved (see plan).

CH4_SPECIES = ["CH4", "O2", "N2", "H2O", "CO", "CO2", "H", "O", "OH",
                "H2", "HO2", "CH3", "CH2O", "HCO"]

CH4_REACTIONS: list[Reaction] = [
    Reaction(rxn_id=200, formula="CH4 + O2 <=> CH3 + HO2",
              reactants={"CH4": 1, "O2": 1}, products={"CH3": 1, "HO2": 1},
              A=7.94e13, n=0.0, theta_a=28200.0,
              is_exchange=True, notes="Smooke R1 — initiation"),
    Reaction(rxn_id=201, formula="CH4 + OH <=> CH3 + H2O",
              reactants={"CH4": 1, "OH": 1}, products={"CH3": 1, "H2O": 1},
              A=1.56e7, n=1.83, theta_a=1400.0,
              is_exchange=True, notes="Smooke R2 — major CH4 sink"),
    Reaction(rxn_id=202, formula="CH4 + O <=> CH3 + OH",
              reactants={"CH4": 1, "O": 1}, products={"CH3": 1, "OH": 1},
              A=1.02e9, n=1.50, theta_a=4330.0,
              is_exchange=True, notes="Smooke R3"),
    Reaction(rxn_id=203, formula="CH4 + H <=> CH3 + H2",
              reactants={"CH4": 1, "H": 1}, products={"CH3": 1, "H2": 1},
              A=2.20e4, n=3.0, theta_a=4045.0,
              is_exchange=True, notes="Smooke R4"),
    Reaction(rxn_id=204, formula="CH3 + O <=> CH2O + H",
              reactants={"CH3": 1, "O": 1}, products={"CH2O": 1, "H": 1},
              A=8.43e13, n=0.0, theta_a=0.0,
              is_exchange=True, notes="Smooke R5"),
    Reaction(rxn_id=205, formula="CH2O + OH <=> HCO + H2O",
              reactants={"CH2O": 1, "OH": 1}, products={"HCO": 1, "H2O": 1},
              A=3.43e9, n=1.18, theta_a=-225.0,
              is_exchange=True, notes="Smooke R6"),
    Reaction(rxn_id=206, formula="CH2O + H <=> HCO + H2",
              reactants={"CH2O": 1, "H": 1}, products={"HCO": 1, "H2": 1},
              A=2.19e8, n=1.77, theta_a=1510.0,
              is_exchange=True, notes="Smooke R7"),
    Reaction(rxn_id=207, formula="HCO + H <=> CO + H2",
              reactants={"HCO": 1, "H": 1}, products={"CO": 1, "H2": 1},
              A=9.00e13, n=0.0, theta_a=0.0,
              is_exchange=True, notes="Smooke R8"),
    Reaction(rxn_id=208, formula="HCO + OH <=> CO + H2O",
              reactants={"HCO": 1, "OH": 1}, products={"CO": 1, "H2O": 1},
              A=1.00e14, n=0.0, theta_a=0.0,
              is_exchange=True, notes="Smooke R9"),
    Reaction(rxn_id=209, formula="HCO + M <=> H + CO + M",
              reactants={"HCO": 1, "M": 1}, products={"H": 1, "CO": 1, "M": 1},
              A=2.50e14, n=0.0, theta_a=8455.0,
              has_third_body=True, is_dissociation=True,
              notes="Smooke R10 — HCO thermal decomp"),
    Reaction(rxn_id=210, formula="CO + OH <=> CO2 + H",
              reactants={"CO": 1, "OH": 1}, products={"CO2": 1, "H": 1},
              A=4.40e6, n=1.50, theta_a=-373.0,
              is_exchange=True, notes="Smooke R11 — main CO oxidation"),
    Reaction(rxn_id=211, formula="H + O2 <=> O + OH",
              reactants={"H": 1, "O2": 1}, products={"O": 1, "OH": 1},
              A=3.55e15, n=-0.41, theta_a=8348.0,
              is_exchange=True, notes="(also in H2/O2 — duplicate is OK)"),
    Reaction(rxn_id=212, formula="O + H2 <=> H + OH",
              reactants={"O": 1, "H2": 1}, products={"H": 1, "OH": 1},
              A=5.08e4, n=2.67, theta_a=3166.0, is_exchange=True),
    Reaction(rxn_id=213, formula="OH + H2 <=> H + H2O",
              reactants={"OH": 1, "H2": 1}, products={"H": 1, "H2O": 1},
              A=2.16e8, n=1.51, theta_a=1726.0, is_exchange=True),
    Reaction(rxn_id=214, formula="H + OH + M <=> H2O + M",
              reactants={"H": 1, "OH": 1, "M": 1}, products={"H2O": 1, "M": 1},
              A=2.20e22, n=-2.0, theta_a=0.0,
              has_third_body=True,
              notes="Smooke R15 — termination"),
    Reaction(rxn_id=215, formula="H + H + M <=> H2 + M",
              reactants={"H": 1, "H": 1, "M": 1}, products={"H2": 1, "M": 1},
              A=9.21e16, n=-0.60, theta_a=0.0,
              has_third_body=True, notes="Smooke R16"),
]


# ── Composite mechanism builder ─────────────────────────────────────

def composite_air_fuel_mechanism(
    air: Mechanism,
    fuel_kind: FuelKind = FuelKind.AIR,
    equivalence_ratio: float = 0.0,
    name_suffix: Optional[str] = None,
) -> Mechanism:
    """Build a Mechanism with the union of air + optional fuel reactions.

    Parameters
    ----------
    air : the input air mechanism (typically Park-AIR-7 or a search-
        proposed subset). Returned unchanged when ``fuel_kind = AIR``.
    fuel_kind : one of FuelKind.{AIR, H2, CH4}.
    equivalence_ratio : recorded on the returned Mechanism via the
        ``name`` suffix; the actual fuel/air ratio is applied at the
        cantera-evaluator initial-composition stage, not here.
    name_suffix : override for the composite mechanism name; defaults
        to ``f"{air.name}_{fuel_kind.name}_phi{phi:.2f}"``.

    Returns
    -------
    Mechanism with combined species + reactions and an updated name.
    For ``FuelKind.AIR`` returns ``air`` unchanged (object identity).
    """
    if fuel_kind == FuelKind.AIR or equivalence_ratio <= 0.0:
        return air

    if fuel_kind == FuelKind.H2:
        fuel_species, fuel_reactions = H2_SPECIES, H2_REACTIONS
    elif fuel_kind == FuelKind.CH4:
        fuel_species, fuel_reactions = CH4_SPECIES, CH4_REACTIONS
    else:
        raise ValueError(f"Unsupported fuel kind: {fuel_kind}")

    combined_species = list(dict.fromkeys([*air.species, *fuel_species]))
    combined_reactions = [*air.reactions, *fuel_reactions]

    name = (name_suffix
            or f"{air.name}_{fuel_kind.name}_phi{equivalence_ratio:.2f}")
    return Mechanism(
        name=name,
        species=combined_species,
        reactions=combined_reactions,
    )


def fuel_initial_composition(
    fuel_kind: FuelKind, equivalence_ratio: float,
) -> dict[str, float]:
    """Compute mass-fraction initial composition for the composite reactor.

    Stoichiometric combustion:
      H2:  2 H2 + O2 -> 2 H2O   (mass ratio fuel:O2 = 0.252)
      CH4: CH4 + 2 O2 -> CO2 + 2 H2O   (mass ratio fuel:O2 = 0.250)

    For equivalence ratio φ:
      mass_fuel / mass_O2_avail = φ × stoichiometric_mass_ratio

    Caller passes the result to ``cantera_evaluator.evaluate`` via
    the future ``initial_composition_override`` knob (v5.2 worker
    contract — see SURROGATE_V5_2_PLAN.md §4).
    """
    if fuel_kind == FuelKind.AIR or equivalence_ratio <= 0.0:
        return {"N2": 0.77, "O2": 0.23}
    if fuel_kind == FuelKind.H2:
        f_st = 0.252
        fuel_name = "H2"
    else:                                                   # CH4
        f_st = 0.250
        fuel_name = "CH4"
    # Available O2 in air is 0.23 mass fraction; for fuel-rich mixing
    # we displace inert N2 by the fuel mass.
    m_fuel = equivalence_ratio * f_st * 0.23
    m_o2 = 0.23
    m_n2 = max(1.0 - m_fuel - m_o2, 0.0)
    return {fuel_name: m_fuel, "O2": m_o2, "N2": m_n2}


__all__ = [
    "FuelKind",
    "H2_SPECIES", "H2_REACTIONS",
    "CH4_SPECIES", "CH4_REACTIONS",
    "composite_air_fuel_mechanism",
    "fuel_initial_composition",
]
