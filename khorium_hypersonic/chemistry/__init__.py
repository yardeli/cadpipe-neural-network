"""Pluggable chemistry layer — mechanism + evaluator + surrogate.

Aaron's vision: AI-exhaustive search over mechanism subset space at
hypersonic Mach. Built on top of the audited plasmanet.mechanism_search
module which provides Park-1990 47-reaction air mechanism + Cantera 0D
evaluator + neural surrogate (4-layer 512-hidden MLP, factor-of-1.52 of
truth, 0.01 ms inference).

This package re-exports the stable surface so callers don't need to
depend on plasmanet.mechanism_search internals:

    Mechanism                — generic dataclass for any reaction set
    PARK_47                  — Park 1990 47-reaction air mechanism
    park_air5, air7, air11   — canonical subsets
    cantera_evaluator(...)   — score one mechanism via Cantera 0D
    load_surrogate(weights)  — load PlasmaNet v4 neural surrogate

For arbitrary mechanisms (NOT Park-47-derived), construct a
Mechanism(name, reactions=[Reaction(...), ...]) directly. The evaluator
and surrogate work on any Mechanism.

Soft dependencies:
    cantera   — optional (cantera_evaluator falls back to None if absent)
    torch     — optional (only needed by load_surrogate)
"""
from plasmanet.mechanism_search.generator import (
    Reaction, Mechanism, PARK_47, AIR_5_SPECIES, AIR_7_SPECIES, AIR_11_SPECIES,
    park_air5, park_air7, park_air11, random_subset,
)
from plasmanet.mechanism_search.cantera_evaluator import (
    evaluate as cantera_evaluator,
    HAVE_CANTERA,
)
from plasmanet.mechanism_search.surrogate import (
    MechanismSurrogate, MechanismFingerprint,
    register_surrogate_evaluator, freestream_features,
    HAVE_TORCH,
)
from plasmanet.mechanism_search.scoring import (
    score_candidate, score_against_benchmark, register_evaluator,
    BENCHMARKS, BenchmarkCondition, BenchmarkResult, ScoringResult,
)

__all__ = [
    "Reaction", "Mechanism", "PARK_47",
    "AIR_5_SPECIES", "AIR_7_SPECIES", "AIR_11_SPECIES",
    "park_air5", "park_air7", "park_air11", "random_subset",
    "cantera_evaluator", "HAVE_CANTERA",
    "MechanismSurrogate", "MechanismFingerprint",
    "register_surrogate_evaluator", "freestream_features", "HAVE_TORCH",
    "score_candidate", "score_against_benchmark", "register_evaluator",
    "BENCHMARKS", "BenchmarkCondition", "BenchmarkResult", "ScoringResult",
]
