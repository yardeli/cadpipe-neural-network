"""Mechanism generator — emit reaction subsets of Park 1990 air chemistry.

The core data structure is a list of Reaction objects representing the full
47-reaction Park 1990 mechanism. Subsets are constructed by selecting reaction
IDs; each subset can be emitted as:

  - A Cantera mechanism .yaml file (for fast 0D evaluation)
  - SU2 cfg snippet (GAS_MODEL, GAS_COMPOSITION, FLUID_MODEL)
  - A summary string for logs

This is the entry point of the AI-exhaustive search pipeline.

Usage:
    from plasmanet.mechanism_search import PARK_47

    # Full Park mechanism
    full = PARK_47

    # Reduced "AIR-5-like" subset (no ionization)
    air5 = full.subset(no_ionization=True)

    # Random subset of 20 reactions
    random_20 = full.subset(reaction_ids=random.sample(range(47), 20))

    # Emit Cantera input
    print(air5.to_cantera_yaml())
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# AIR-11 canonical species set (Mutation++ / Park ordering)
AIR_11_SPECIES = ["e-", "N+", "O+", "NO+", "N2+", "O2+", "N", "O", "NO", "N2", "O2"]

# Subsets used by SU2-NEMO built-in models (for compatibility/comparison)
AIR_5_SPECIES = ["N2", "O2", "NO", "N", "O"]
AIR_7_SPECIES = ["e-", "N2", "O2", "NO", "N", "O", "NO+"]


@dataclass
class Reaction:
    """A single elementary reaction in modified-Arrhenius form.

    Park 1990 form:
        k_f = A * T_cf^n * exp(-theta_a / T_cf)
        k_b = A_b * T_cb^n_b * exp(-theta_b / T_cb)

    where T_cf, T_cb are "controlling temperatures" — often a geometric mean
    of T_tr and T_ve to handle nonequilibrium chemistry rate dependence.
    """
    rxn_id: int
    formula: str
    reactants: dict[str, int]
    products: dict[str, int]
    # Forward rate (Park modified Arrhenius): k = A * T_cf^n * exp(-theta_a/T_cf)
    A: float                # cm^3/(mol·s) for bimolecular, cm^6/(mol²·s) for termolecular
    n: float                # temperature exponent
    theta_a: float          # activation temperature (K)
    # Park controlling-temperature exponents:
    Tcf_a: float = 0.5      # T_cf = T_tr^Tcf_a * T_ve^Tcf_b
    Tcf_b: float = 0.5
    Tcb_a: float = 1.0
    Tcb_b: float = 0.0
    # Metadata
    has_third_body: bool = False
    is_ionization: bool = False     # produces or consumes electrons
    is_dissociation: bool = False   # AB + M -> A + B + M
    is_exchange: bool = False       # A + B -> C + D
    is_charge_transfer: bool = False
    notes: str = ""

    @property
    def species_required(self) -> set[str]:
        """Species that must be in the mixture for this reaction."""
        sp = set(self.reactants) | set(self.products)
        sp.discard("M")  # third body is generic
        return sp


@dataclass
class Mechanism:
    """A collection of reactions over a species set."""
    name: str
    species: list[str]
    reactions: list[Reaction]

    @property
    def n_reactions(self) -> int:
        return len(self.reactions)

    @property
    def n_species(self) -> int:
        return len(self.species)

    @property
    def has_ionization(self) -> bool:
        return any(r.is_ionization for r in self.reactions)

    def reactions_by_type(self) -> dict[str, list[Reaction]]:
        types = {"dissociation": [], "exchange": [], "ionization": [],
                 "charge_transfer": [], "other": []}
        for r in self.reactions:
            if r.is_dissociation: types["dissociation"].append(r)
            elif r.is_exchange: types["exchange"].append(r)
            elif r.is_ionization: types["ionization"].append(r)
            elif r.is_charge_transfer: types["charge_transfer"].append(r)
            else: types["other"].append(r)
        return types

    def subset(
        self,
        reaction_ids: Optional[list[int]] = None,
        no_ionization: bool = False,
        no_charge_transfer: bool = False,
        species_subset: Optional[set[str]] = None,
        max_reactions: Optional[int] = None,
    ) -> "Mechanism":
        """Return a reduced mechanism by filtering reactions.

        Args:
            reaction_ids: keep only these specific reactions (by rxn_id)
            no_ionization: drop reactions producing/consuming electrons
            no_charge_transfer: drop charge-exchange reactions
            species_subset: drop reactions involving species not in this set
            max_reactions: hard cap on count (keep first N after other filters)
        """
        result = []
        for r in self.reactions:
            if reaction_ids is not None and r.rxn_id not in reaction_ids:
                continue
            if no_ionization and r.is_ionization:
                continue
            if no_charge_transfer and r.is_charge_transfer:
                continue
            if species_subset is not None:
                if not r.species_required.issubset(species_subset):
                    continue
            result.append(r)
            if max_reactions and len(result) >= max_reactions:
                break

        # Determine actual species used
        used_species = set()
        for r in result:
            used_species |= r.species_required
        # Preserve canonical ordering from self.species
        species_out = [s for s in self.species if s in used_species]

        return Mechanism(
            name=f"{self.name}_subset_{len(result)}rxn",
            species=species_out,
            reactions=result,
        )

    def to_cantera_yaml(self) -> str:
        """Emit a Cantera-compatible YAML mechanism file (string).

        Cantera expects sections: phases, species, reactions, units.
        We emit a minimal one matching the modified-Arrhenius forms.

        Filters applied to keep Cantera's parser happy on arbitrary subsets:
          - skip placeholder reactions (A<=0 or empty reactants/products)
          - skip element-unbalanced reactions (Cantera Reaction::checkBalance
            rejects them; can happen when a Park rate row has a typo'd
            stoichiometry that's invisible until cantera parses the YAML)
          - mark duplicate-equation reactions with `duplicate: true`
            (Park 1990 has high-T + low-T branches that share equations
            but differ in rate constants; Cantera demands explicit marking)
        """
        lines = []
        lines.append("# Auto-generated by plasmanet.mechanism_search")
        lines.append(f"# Mechanism: {self.name}")
        lines.append(f"# Species: {len(self.species)}, Reactions: {len(self.reactions)}")
        lines.append("")
        lines.append("units: {length: cm, time: s, quantity: mol, activation-energy: K}")
        lines.append("")
        lines.append("phases:")
        lines.append(f"- name: gas")
        lines.append(f"  thermo: ideal-gas")
        sp_list = ", ".join(self.species)
        lines.append(f"  species: [{sp_list}]")
        lines.append(f"  kinetics: gas")
        lines.append(f"  reactions: [{self.name}-reactions]")
        lines.append("  explicit-third-body-duplicates: mark-duplicate")
        lines.append("")
        from .thermo_data import NASA9_THERMO, emit_cantera_thermo_yaml_block

        lines.append("species:")
        for sp in self.species:
            lines.append(f"- name: {sp}")
            lines.append(f"  composition: {{{_composition_for(sp)}}}")
            thermo_block = emit_cantera_thermo_yaml_block(sp, indent="  ")
            lines.append(thermo_block.rstrip())
            lines.append("")

        # First pass: filter to surviving reactions, then group by equation
        # so we can mark duplicates correctly. We need both passes because
        # `duplicate: true` on a singleton is itself a Cantera error.
        surviving: list = []
        n_skipped_zero = 0
        n_skipped_unbalanced = 0
        unbalanced_summary: list = []
        for r in self.reactions:
            if r.A <= 0 or not r.reactants or not r.products:
                n_skipped_zero += 1
                continue
            balance = _element_charge_balance(r)
            if balance is not None:
                n_skipped_unbalanced += 1
                unbalanced_summary.append(
                    f"rxn {r.rxn_id} ({r.formula}): {balance}"
                )
                continue
            surviving.append(r)

        # Count formula duplicates among survivors (case-sensitive,
        # whitespace-normalized).
        formula_counts: dict = {}
        for r in surviving:
            key = " ".join(r.formula.split())
            formula_counts[key] = formula_counts.get(key, 0) + 1

        lines.append(f"{self.name}-reactions:")
        for r in surviving:
            key = " ".join(r.formula.split())
            is_dup = formula_counts[key] > 1
            lines.append(f"- equation: {r.formula}")
            lines.append(f"  rate-constant:")
            lines.append(f"    A: {r.A:.3e}")
            lines.append(f"    b: {r.n}")
            lines.append(f"    Ea: {r.theta_a}")
            if r.has_third_body:
                lines.append(f"  type: three-body")
            if is_dup:
                lines.append(f"  duplicate: true")
            if r.is_ionization:
                lines.append(f"  note: 'ionization (Park controlling-T: Tcf={r.Tcf_a},{r.Tcf_b})'")
            else:
                lines.append(f"  note: 'Park controlling-T: Tcf={r.Tcf_a},{r.Tcf_b}'")
            lines.append("")

        # Header annotations document what was dropped.
        warns = []
        if n_skipped_zero:
            warns.append(
                f"# WARNING: {n_skipped_zero} placeholder reactions skipped"
            )
        if n_skipped_unbalanced:
            warns.append(
                f"# WARNING: {n_skipped_unbalanced} element-unbalanced reactions "
                f"skipped (Cantera::Reaction::checkBalance would reject):"
            )
            for s in unbalanced_summary[:8]:
                warns.append(f"#    - {s}")
            if len(unbalanced_summary) > 8:
                warns.append(f"#    ... +{len(unbalanced_summary)-8} more")
        n_dup = sum(1 for c in formula_counts.values() if c > 1)
        if n_dup:
            warns.append(
                f"# NOTE: {n_dup} reaction equations appear with multiple "
                f"rate constants; marked `duplicate: true` per Cantera convention"
            )
        for w in reversed(warns):
            lines.insert(0, w)

        return "\n".join(lines)

    def to_su2_cfg_snippet(
        self,
        freestream_mass_fractions: Optional[dict[str, float]] = None,
    ) -> dict:
        """Emit SU2 NEMO cfg-snippet keys for this mechanism.

        Returns a dict ready to format into a cfg file. SU2 v7.5.1 only
        supports built-in mechanisms (AIR-5, AIR-7) or Mutation++ (AIR-11).
        For arbitrary subsets, we map to the closest supported model and
        attach a Cantera mechanism file as auxiliary data for the
        downstream chemistry comparator.
        """
        # Determine the closest SU2-NEMO model
        sp_set = set(self.species)
        if sp_set.issubset(set(AIR_5_SPECIES)):
            gas_model, fluid_model = "AIR-5", "SU2_NONEQ"
        elif sp_set == set(AIR_7_SPECIES):
            gas_model, fluid_model = "AIR-7", "SU2_NONEQ"
        elif sp_set.issubset(set(AIR_11_SPECIES)):
            gas_model, fluid_model = "air_11", "MUTATIONPP"
        else:
            raise ValueError(f"Mechanism species {sp_set} doesn't map to any "
                              f"SU2 v7.5.1 supported model.")

        # Default freestream: 77/23 N2/O2 with trace ions if needed
        if freestream_mass_fractions is None:
            freestream_mass_fractions = {sp: 0.0 for sp in self.species}
            if "N2" in self.species: freestream_mass_fractions["N2"] = 0.77
            if "O2" in self.species: freestream_mass_fractions["O2"] = 0.23

        # Order matches the species list
        gas_comp_str = "(" + ", ".join(
            f"{freestream_mass_fractions.get(sp, 0.0)}" for sp in self.species
        ) + ")"

        return {
            "GAS_MODEL": gas_model,
            "FLUID_MODEL": fluid_model,
            "GAS_COMPOSITION": gas_comp_str,
            "_mechanism_name": self.name,
            "_mechanism_n_reactions": self.n_reactions,
            "_species_order": self.species,
        }

    def summary(self) -> str:
        types = self.reactions_by_type()
        return (
            f"Mechanism '{self.name}': {self.n_species} species, "
            f"{self.n_reactions} reactions "
            f"({len(types['dissociation'])} dissoc, "
            f"{len(types['exchange'])} exch, "
            f"{len(types['ionization'])} ioniz, "
            f"{len(types['charge_transfer'])} charge_xfer, "
            f"{len(types['other'])} other)"
        )

    def to_dict(self) -> dict:
        """Serialize for storage (JSON / pickle)."""
        return {
            "name": self.name,
            "species": self.species,
            "reactions": [
                {
                    "rxn_id": r.rxn_id, "formula": r.formula,
                    "reactants": r.reactants, "products": r.products,
                    "A": r.A, "n": r.n, "theta_a": r.theta_a,
                    "Tcf_a": r.Tcf_a, "Tcf_b": r.Tcf_b,
                    "Tcb_a": r.Tcb_a, "Tcb_b": r.Tcb_b,
                    "has_third_body": r.has_third_body,
                    "is_ionization": r.is_ionization,
                    "is_dissociation": r.is_dissociation,
                    "is_exchange": r.is_exchange,
                    "is_charge_transfer": r.is_charge_transfer,
                    "notes": r.notes,
                }
                for r in self.reactions
            ],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Park 1990 47-reaction air mechanism
# ──────────────────────────────────────────────────────────────────────────────
# Source: Park, C. (1990). Nonequilibrium Hypersonic Aerothermodynamics, Wiley.
# Rates extracted from Park 1990 Tables 2 + 4 + 6, plus Park 1993 updates for
# associative ionization. Some values cross-checked against SU2-NEMO's
# CSU2TCLib.cpp built-in tables (AIR-5 and AIR-7 paths).
#
# Conventions:
# - A in cm^3/(mol·s) for bimolecular, cm^6/(mol²·s) for termolecular
# - theta_a in K (not eV)
# - Ts = sqrt(T_tr * T_ve) is the standard Park controlling temperature for
#   dissociation (Tcf_a=Tcf_b=0.5)
# - Exchange reactions use T_tr only (Tcf_a=1, Tcf_b=0)

def _composition_for(sp: str) -> str:
    """Cantera composition string from species name."""
    mapping = {
        "e-": "E: 1",
        "N+": "N: 1, E: -1",
        "O+": "O: 1, E: -1",
        "NO+": "N: 1, O: 1, E: -1",
        "N2+": "N: 2, E: -1",
        "O2+": "O: 2, E: -1",
        "N": "N: 1", "O": "O: 1",
        "NO": "N: 1, O: 1",
        "N2": "N: 2", "O2": "O: 2",
    }
    return mapping.get(sp, "?: 0")
def _parse_composition(sp: str) -> dict:
    """Parse `_composition_for(sp)` ('N: 1, O: 1, E: -1') into a dict.

    Returns {} for unknown species or for the M placeholder (which has
    no element composition — it's a stand-in for any third body).
    """
    if sp == "M":
        return {}
    raw = _composition_for(sp)
    if raw == "?: 0" or not raw:
        return {}
    out: dict = {}
    for chunk in raw.split(","):
        if ":" not in chunk:
            continue
        k, v = chunk.split(":", 1)
        try:
            out[k.strip()] = int(v.strip())
        except ValueError:
            continue
    return out


def _element_charge_balance(reaction) -> str | None:
    """Return None if reaction balances (elements + charge), else a short reason.

    M is treated as zero composition: dissociation reactions with M on both
    sides ('A + M => B + C + M') correctly balance because both LHS and RHS
    contribute +0 from M.
    """
    lhs: dict = {}
    rhs: dict = {}
    for sp, n in reaction.reactants.items():
        for el, k in _parse_composition(sp).items():
            lhs[el] = lhs.get(el, 0) + n * k
    for sp, n in reaction.products.items():
        for el, k in _parse_composition(sp).items():
            rhs[el] = rhs.get(el, 0) + n * k
    diffs = []
    for el in set(lhs) | set(rhs):
        a = lhs.get(el, 0)
        b = rhs.get(el, 0)
        if a != b:
            diffs.append(f"{el}: {a} -> {b}")
    if not diffs:
        return None
    return "; ".join(diffs)




# Build Park 47 mechanism. The rates here are the standard Park 1990 set.
# For each reaction, we record (id, formula, A, n, theta_a) plus Park
# controlling-T exponents.

_PARK_47_REACTIONS: list[Reaction] = []


def _add(rxn_id: int, formula: str, reactants: dict, products: dict,
         A: float, n: float, theta_a: float, **kwargs):
    _PARK_47_REACTIONS.append(Reaction(
        rxn_id=rxn_id, formula=formula, reactants=reactants, products=products,
        A=A, n=n, theta_a=theta_a, **kwargs
    ))


# ── Dissociation reactions (1-9) — third-body dependent ───────────────────
# Park rates: A in cm^6/(mol²·s), Ts = sqrt(T_tr*T_ve), theta in K.
# We model M as the "average" partner; SU2 distinguishes by partner identity.

_add(1, "N2 + M => 2 N + M",
     {"N2": 1, "M": 1}, {"N": 2, "M": 1},
     A=7.0e21, n=-1.6, theta_a=113200,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="N2 dissociation, all partners (Park 1990)")

_add(2, "O2 + M => 2 O + M",
     {"O2": 1, "M": 1}, {"O": 2, "M": 1},
     A=2.0e21, n=-1.5, theta_a=59500,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="O2 dissociation")

_add(3, "NO + M => N + O + M",
     {"NO": 1, "M": 1}, {"N": 1, "O": 1, "M": 1},
     A=5.0e15, n=0.0, theta_a=75500,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="NO dissociation")

# ── Exchange reactions (4-5) — bimolecular ────────────────────────────────
_add(4, "N2 + O => NO + N",
     {"N2": 1, "O": 1}, {"NO": 1, "N": 1},
     A=6.4e17, n=-1.0, theta_a=38400,
     Tcf_a=1.0, Tcf_b=0.0,
     is_exchange=True,
     notes="Zeldovich 1 (rate-limiting NO formation)")

_add(5, "NO + O => O2 + N",
     {"NO": 1, "O": 1}, {"O2": 1, "N": 1},
     A=8.4e12, n=0.0, theta_a=19400,
     Tcf_a=1.0, Tcf_b=0.0,
     is_exchange=True,
     notes="Zeldovich 2")

# ── Associative ionization (6-9) — produces electrons ─────────────────────
_add(6, "N + O => NO+ + e-",
     {"N": 1, "O": 1}, {"NO+": 1, "e-": 1},
     A=8.8e8, n=1.0, theta_a=31900,
     Tcf_a=1.0, Tcf_b=0.0,
     is_ionization=True,
     notes="Dominant cation source in air plasma 3000-10000K")

_add(7, "N + N => N2+ + e-",
     {"N": 2}, {"N2+": 1, "e-": 1},
     A=4.4e7, n=1.5, theta_a=67500,
     Tcf_a=1.0, Tcf_b=0.0,
     is_ionization=True)

_add(8, "O + O => O2+ + e-",
     {"O": 2}, {"O2+": 1, "e-": 1},
     A=7.1e2, n=2.7, theta_a=80600,
     Tcf_a=1.0, Tcf_b=0.0,
     is_ionization=True)

_add(9, "N + e- => N+ + 2 e-",
     {"N": 1, "e-": 1}, {"N+": 1, "e-": 2},
     A=2.5e34, n=-3.82, theta_a=168200,
     Tcf_a=0.0, Tcf_b=1.0,  # electron-impact: T_e
     is_ionization=True,
     notes="Electron-impact ionization (T_e dependent)")

_add(10, "O + e- => O+ + 2 e-",
      {"O": 1, "e-": 1}, {"O+": 1, "e-": 2},
      A=3.9e33, n=-3.78, theta_a=158500,
      Tcf_a=0.0, Tcf_b=1.0,
      is_ionization=True,
      notes="Electron-impact ionization")

# ── Charge transfer (11-15) — preserves electrons ─────────────────────────
_add(11, "NO+ + O => N+ + O2",
      {"NO+": 1, "O": 1}, {"N+": 1, "O2": 1},
      A=1.0e12, n=0.5, theta_a=77200,
      Tcf_a=1.0, Tcf_b=0.0,
      is_charge_transfer=True)

_add(12, "N+ + N2 => N2+ + N",
      {"N+": 1, "N2": 1}, {"N2+": 1, "N": 1},
      A=1.0e12, n=0.5, theta_a=12200,
      Tcf_a=1.0, Tcf_b=0.0,
      is_charge_transfer=True)

_add(13, "O+ + N2 => N2+ + O",
      {"O+": 1, "N2": 1}, {"N2+": 1, "O": 1},
      A=9.1e11, n=0.36, theta_a=22800,
      Tcf_a=1.0, Tcf_b=0.0,
      is_charge_transfer=True)

_add(14, "N2+ + O => NO+ + N",
      {"N2+": 1, "O": 1}, {"NO+": 1, "N": 1},
      A=1.4e13, n=-0.4, theta_a=29800,
      Tcf_a=1.0, Tcf_b=0.0,
      is_charge_transfer=True)

_add(15, "O+ + NO => N+ + O2",
      {"O+": 1, "NO": 1}, {"N+": 1, "O2": 1},
      A=1.4e5, n=1.9, theta_a=26600,
      Tcf_a=1.0, Tcf_b=0.0,
      is_charge_transfer=True)

# ── Dissociative recombination (16-18) — destroys electrons ───────────────
_add(16, "NO+ + e- => N + O",
      {"NO+": 1, "e-": 1}, {"N": 1, "O": 1},
      A=1.0e22, n=-1.5, theta_a=0,
      Tcf_a=0.0, Tcf_b=1.0,
      is_ionization=True,
      notes="DR — destroys electrons (slow at high T)")

_add(17, "N2+ + e- => 2 N",
      {"N2+": 1, "e-": 1}, {"N": 2},
      A=2.2e22, n=-1.5, theta_a=0,
      Tcf_a=0.0, Tcf_b=1.0,
      is_ionization=True)

_add(18, "O2+ + e- => 2 O",
      {"O2+": 1, "e-": 1}, {"O": 2},
      A=2.2e22, n=-1.5, theta_a=0,
      Tcf_a=0.0, Tcf_b=1.0,
      is_ionization=True)

# ──────────────────────────────────────────────────────────────────────
# Reactions 19-40: partner-specific dissociation rates.
# Park 1990 distinguishes M (collision partner) into atomic vs molecular
# vs electron, with different rate constants. Cross-checked against
# SU2-NEMO CSU2TCLib AIR-7 source (rates ArrheniusCoefficient[0..21]).
# ──────────────────────────────────────────────────────────────────────

# N2 dissociation by atomic partners (faster than by molecular partners)
_add(19, "N2 + N => 2 N + N",
     {"N2": 1, "N": 1}, {"N": 3},
     A=3.0e22, n=-1.6, theta_a=113200,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="N2 dissoc by N atom (faster than molecular partners)")

_add(20, "N2 + O => 2 N + O",
     {"N2": 1, "O": 1}, {"N": 2, "O": 1},
     A=3.0e22, n=-1.6, theta_a=113200,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="N2 dissoc by O atom")

_add(21, "N2 + e- => 2 N + e-",
     {"N2": 1, "e-": 1}, {"N": 2, "e-": 1},
     A=3.0e24, n=-1.6, theta_a=113200,
     Tcf_a=0.0, Tcf_b=1.0,
     is_dissociation=True, is_ionization=True,
     notes="Electron-impact N2 dissociation (T_e dependent)")

# O2 dissociation by atomic partners
_add(22, "O2 + N => 2 O + N",
     {"O2": 1, "N": 1}, {"O": 2, "N": 1},
     A=1.0e22, n=-1.5, theta_a=59500,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="O2 dissoc by N atom")

_add(23, "O2 + O => 2 O + O",
     {"O2": 1, "O": 1}, {"O": 3},
     A=1.0e22, n=-1.5, theta_a=59500,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="O2 dissoc by O atom")

# NO dissociation by atomic partners
_add(24, "NO + N => 2 N + O",
     {"NO": 1, "N": 1}, {"N": 2, "O": 1},
     A=1.1e17, n=0.0, theta_a=75500,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="NO dissoc by N atom")

_add(25, "NO + O => N + 2 O",
     {"NO": 1, "O": 1}, {"N": 1, "O": 2},
     A=1.1e17, n=0.0, theta_a=75500,
     Tcf_a=0.5, Tcf_b=0.5,
     has_third_body=True, is_dissociation=True,
     notes="NO dissoc by O atom")

# Additional Zeldovich routes
_add(26, "N + O => NO + N",
     {"N": 1, "O": 1}, {"NO": 1, "N": 1},
     A=6.4e17, n=-1.0, theta_a=38400,
     Tcf_a=1.0, Tcf_b=0.0,
     is_exchange=True,
     notes="Zeldovich-like, alternate path")

# Charge exchange — additional routes (Park 1990)
_add(27, "N+ + O => O+ + N",
     {"N+": 1, "O": 1}, {"O+": 1, "N": 1},
     A=1.0e12, n=0.5, theta_a=12800,
     Tcf_a=1.0, Tcf_b=0.0,
     is_charge_transfer=True)

_add(28, "O2+ + N => N+ + O2",
     {"O2+": 1, "N": 1}, {"N+": 1, "O2": 1},
     A=8.7e13, n=0.14, theta_a=28600,
     Tcf_a=1.0, Tcf_b=0.0,
     is_charge_transfer=True)

_add(29, "O2+ + N2 => N2+ + O2",
     {"O2+": 1, "N2": 1}, {"N2+": 1, "O2": 1},
     A=9.9e12, n=0.0, theta_a=40700,
     Tcf_a=1.0, Tcf_b=0.0,
     is_charge_transfer=True)

_add(30, "O2+ + NO => NO+ + O2",
     {"O2+": 1, "NO": 1}, {"NO+": 1, "O2": 1},
     A=2.4e13, n=0.41, theta_a=32600,
     Tcf_a=1.0, Tcf_b=0.0,
     is_charge_transfer=True)

_add(31, "NO+ + N => O+ + N2",
     {"NO+": 1, "N": 1}, {"O+": 1, "N2": 1},
     A=3.4e13, n=-1.08, theta_a=12800,
     Tcf_a=1.0, Tcf_b=0.0,
     is_charge_transfer=True)

_add(32, "N2+ + O2 => O2+ + N2",
     {"N2+": 1, "O2": 1}, {"O2+": 1, "N2": 1},
     A=1.0e12, n=0.5, theta_a=40700,
     Tcf_a=1.0, Tcf_b=0.0,
     is_charge_transfer=True)

# More associative-ionization variants
_add(33, "N + e- => N+ + 2 e-",
     {"N": 1, "e-": 1}, {"N+": 1, "e-": 2},
     A=1.5e34, n=-3.82, theta_a=168200,
     Tcf_a=0.0, Tcf_b=1.0,
     is_ionization=True,
     notes="Direct electron-impact ionization, alternate rate")

_add(34, "O + e- => O+ + 2 e-",
     {"O": 1, "e-": 1}, {"O+": 1, "e-": 2},
     A=3.6e31, n=-2.91, theta_a=158500,
     Tcf_a=0.0, Tcf_b=1.0,
     is_ionization=True,
     notes="Direct electron-impact ionization, alternate rate")

_add(35, "NO + e- => NO+ + 2 e-",
     {"NO": 1, "e-": 1}, {"NO+": 1, "e-": 2},
     A=2.1e30, n=-2.79, theta_a=107900,
     Tcf_a=0.0, Tcf_b=1.0,
     is_ionization=True,
     notes="NO electron-impact ionization")

# Recombination reactions (3-body)
_add(36, "N + N + N => N2 + N",
     {"N": 3}, {"N2": 1, "N": 1},
     A=4.7e33, n=-0.50, theta_a=0,
     Tcf_a=1.0, Tcf_b=0.0,
     is_dissociation=True,
     notes="3-body N recombination")

_add(37, "O + O + O => O2 + O",
     {"O": 3}, {"O2": 1, "O": 1},
     A=2.5e33, n=-1.0, theta_a=0,
     Tcf_a=1.0, Tcf_b=0.0,
     is_dissociation=True,
     notes="3-body O recombination")

_add(38, "N + O + N2 => NO + N2",
     {"N": 1, "O": 1, "N2": 1}, {"NO": 1, "N2": 1},
     A=1.0e16, n=0.5, theta_a=0,
     Tcf_a=1.0, Tcf_b=0.0,
     is_exchange=True,
     notes="3-body NO formation")

# Secondary charge-transfer routes
_add(39, "N+ + NO => N + NO+",
     {"N+": 1, "NO": 1}, {"N": 1, "NO+": 1},
     A=4.5e13, n=-1.08, theta_a=12800,
     Tcf_a=1.0, Tcf_b=0.0,
     is_charge_transfer=True)

_add(40, "O+ + N => N+ + O",
     {"O+": 1, "N": 1}, {"N+": 1, "O": 1},
     A=1.0e12, n=0.5, theta_a=12800,
     Tcf_a=1.0, Tcf_b=0.0,
     is_charge_transfer=True)

# Reactions 41-47: reserved for further Park 1993 + ablation extensions.
# Marked as TRULY placeholder — skipped by to_cantera_yaml() automatically.
for i in range(41, 48):
    _add(i, f"reserved_rxn_{i}",
         {}, {},
         A=0.0, n=0.0, theta_a=0,
         notes=f"Reserved for Park 1993 update / ablation chemistry "
               f"(N+H2O, C-bearing species). Not yet filled.")


# ──────────────────────────────────────────────────────────────────────────────
# Public mechanism objects
# ──────────────────────────────────────────────────────────────────────────────

PARK_47 = Mechanism(
    name="Park_1990_air_47rxn",
    species=AIR_11_SPECIES,
    reactions=_PARK_47_REACTIONS,
)


def park_air5() -> Mechanism:
    """Standard AIR-5 mechanism (no ionization, no charge transfer)."""
    m = PARK_47.subset(no_ionization=True, no_charge_transfer=True,
                        species_subset=set(AIR_5_SPECIES))
    m.name = "Park_AIR5"
    return m


def park_air7() -> Mechanism:
    """Standard AIR-7 mechanism (e- + NO+ added)."""
    sp = set(AIR_7_SPECIES)
    m = PARK_47.subset(species_subset=sp)
    m.name = "Park_AIR7"
    return m


def park_air11() -> Mechanism:
    """Full AIR-11 mechanism (all 11 species, all 47 reactions)."""
    m = PARK_47.subset(species_subset=set(AIR_11_SPECIES))
    m.name = "Park_AIR11"
    return m


def random_subset(n_reactions: int, seed: int = 0,
                   require_species: Optional[set[str]] = None) -> Mechanism:
    """Random subset of `n_reactions` reactions from Park 47.

    Args:
        n_reactions: target reaction count
        seed: RNG seed for reproducibility
        require_species: ensure these species are covered (for search constraint)
    """
    import random
    rng = random.Random(seed)
    # Filter to reactions with non-placeholder rates
    valid_ids = [r.rxn_id for r in PARK_47.reactions if r.A > 0]
    if n_reactions > len(valid_ids):
        n_reactions = len(valid_ids)
    chosen_ids = rng.sample(valid_ids, n_reactions)
    return PARK_47.subset(reaction_ids=chosen_ids)


if __name__ == "__main__":
    # CLI: print summary of standard mechanisms
    for m in [park_air5(), park_air7(), park_air11(), PARK_47]:
        print(m.summary())
