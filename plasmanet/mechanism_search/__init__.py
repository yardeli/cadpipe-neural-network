"""AI-exhaustive chemistry mechanism search framework.

See docs/MECHANISM_SEARCH_FRAMEWORK.md for the full architecture.

Phases:
  S-1  generator.py    — Park 47 mechanism + subset() filtering
  S-6  scoring.py      — Benchmark suite + composite scoring function
  S-2  cantera_evaluator.py — Fast 0D chemistry surrogate via Cantera
  S-3  surrogate.py    — PlasmaNet retrained on (mechanism, conditions) → ne
  S-4  search_loop.py  — Bayesian / GA over reaction subsets
  S-5  cfd_validator.py — Top-K validation via SU2-NEMO MPI binary
"""
from .generator import (
    Reaction,
    Mechanism,
    PARK_47,
    AIR_5_SPECIES,
    AIR_7_SPECIES,
    AIR_11_SPECIES,
    park_air5,
    park_air7,
    park_air11,
    random_subset,
)
from .geometry import (
    VehicleGeometry,
    RAM_C_GEOMETRY,
    APOLLO_CM_GEOMETRY,
    FIRE_II_GEOMETRY,
    GENERIC_HGV_GEOMETRY,
    PREDEFINED_GEOMETRIES,
    get_geometry,
)
from .scoring import (
    BENCHMARKS,
    BenchmarkCondition,
    BenchmarkResult,
    ScoringResult,
    score_against_benchmark,
    score_candidate,
    register_evaluator,
    log10_err,
    db_margin_to_published,
)
from .cantera_evaluator import (
    evaluate as cantera_0d_evaluate,
    HAVE_CANTERA,
)
from .search_loop import (
    SearchProgress,
    random_search,
    genetic_search,
    sobol_bayesian_search,
    SobolBOResult,
    save_results,
)
from .surrogate import (
    MechanismFingerprint,
    MechanismSurrogate,
    TrainingExample,
    train_surrogate,
    register_surrogate_evaluator,
    freestream_features,
    HAVE_TORCH,
)
from .fuel_axis import (
    FuelKind,
    H2_SPECIES, H2_REACTIONS,
    CH4_SPECIES, CH4_REACTIONS,
    composite_air_fuel_mechanism,
    fuel_initial_composition,
)

__all__ = [
    # generator
    "Reaction", "Mechanism", "PARK_47",
    "AIR_5_SPECIES", "AIR_7_SPECIES", "AIR_11_SPECIES",
    "park_air5", "park_air7", "park_air11", "random_subset",
    # geometry
    "VehicleGeometry",
    "RAM_C_GEOMETRY", "APOLLO_CM_GEOMETRY", "FIRE_II_GEOMETRY",
    "GENERIC_HGV_GEOMETRY", "PREDEFINED_GEOMETRIES", "get_geometry",
    # scoring
    "BENCHMARKS", "BenchmarkCondition", "BenchmarkResult", "ScoringResult",
    "score_against_benchmark", "score_candidate", "register_evaluator",
    "log10_err", "db_margin_to_published",
    # cantera
    "cantera_0d_evaluate", "HAVE_CANTERA",
    # search loop
    "SearchProgress", "random_search", "genetic_search",
    "sobol_bayesian_search", "SobolBOResult", "save_results",
    # surrogate (S-3)
    "MechanismFingerprint", "MechanismSurrogate", "TrainingExample",
    "train_surrogate", "register_surrogate_evaluator",
    "freestream_features", "HAVE_TORCH",
    # fuel axis (v5.2)
    "FuelKind",
    "H2_SPECIES", "H2_REACTIONS",
    "CH4_SPECIES", "CH4_REACTIONS",
    "composite_air_fuel_mechanism", "fuel_initial_composition",
]
