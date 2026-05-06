"""AI-exhaustive chemistry-reaction search framework.

Three search strategies over the discrete subset space of an N-reaction
mechanism (default Park-47, but works on any Mechanism):

    exhaustive_search        — brute-force enumeration of all 2^N subsets
                               (only feasible for N ≲ 24; uses surrogate
                               at 0.01 ms per eval to make N=20-24
                               tractable; pure-Cantera version cooks)
    sobol_bayesian_search    — Sobol-seed (low-discrepancy) + GP / max-EI
                               BO outer loop. Default driver — handles
                               N=47 in 5000 evals
    genetic_search           — bitstring GA, useful when subset structure
                               has strong epistasis

All three share the same scoring contract: a `score_candidate` callable
that takes a Mechanism and returns a ScoringResult (composite_score
where lower = better fit to ground truth).

The "AI-exhaustive" framing in the package name refers to the fact that
the surrogate makes brute-force search of an N=24 subspace tractable
(16M evals × 0.01 ms = 3 minutes), unlocking subset-space mining that
was prohibitively expensive with Cantera 0D alone.
"""
from plasmanet.mechanism_search.search_loop import (
    sobol_bayesian_search,
    SobolBOResult,
    genetic_search,
    random_search,
    SearchProgress,
    save_results,
)

from .exhaustive import exhaustive_search, ExhaustiveResult

__all__ = [
    "sobol_bayesian_search", "SobolBOResult",
    "genetic_search", "random_search",
    "exhaustive_search", "ExhaustiveResult",
    "SearchProgress", "save_results",
]
