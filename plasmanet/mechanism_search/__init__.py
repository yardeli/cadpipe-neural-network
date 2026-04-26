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
    save_results,
)

__all__ = [
    # generator
    "Reaction", "Mechanism", "PARK_47",
    "AIR_5_SPECIES", "AIR_7_SPECIES", "AIR_11_SPECIES",
    "park_air5", "park_air7", "park_air11", "random_subset",
    # scoring
    "BENCHMARKS", "BenchmarkCondition", "BenchmarkResult", "ScoringResult",
    "score_against_benchmark", "score_candidate", "register_evaluator",
    "log10_err", "db_margin_to_published",
    # cantera
    "cantera_0d_evaluate", "HAVE_CANTERA",
    # search loop
    "SearchProgress", "random_search", "genetic_search", "save_results",
]
