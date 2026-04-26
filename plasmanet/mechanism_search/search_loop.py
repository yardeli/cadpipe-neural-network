"""S-4 — Search loop over reaction subsets.

Three search algorithms over the discrete space of reaction subsets:

  1. random_search  — N random subsets, sorted by composite score.
                      Baseline. Cheap. Useful for warm-starting GA.

  2. genetic_search — Genetic algorithm with binary encoding (one bit per
                      reaction). Mutation = toggle a bit; crossover =
                      uniform mixing of two parent bitstrings. Selection
                      via tournament. Works well for ~50-200 evaluations.

  3. bayesian_search — Stub. Bayesian optimization on discrete
                       reaction-subset space requires custom kernel
                       (e.g., set-similarity). Punted to future sprint.

All three return a ranked list of (mechanism, ScoringResult) tuples,
worst-to-best. Top-K can then be CFD-validated via S-5.

Usage:
    from plasmanet.mechanism_search.generator import PARK_47
    from plasmanet.mechanism_search.search_loop import genetic_search

    results = genetic_search(
        base_mechanism=PARK_47,
        evaluator='cantera_0d',
        evaluator_input_fn=lambda mech: {'mechanism': mech},
        budget=100,
        population_size=20,
        generations=5,
        benchmarks=['ram_c_61km_M22.5'],
    )
    print(f"Best score: {results[0][1].composite_score:.3f}")
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .generator import Mechanism, PARK_47
from .scoring import score_candidate, ScoringResult, BENCHMARKS


# ──────────────────────────────────────────────────────────────────────────────
# Common types
# ──────────────────────────────────────────────────────────────────────────────

EvaluatorInputFn = Callable[[Mechanism], dict]
"""Maps a mechanism candidate to the input dict expected by its evaluator."""


@dataclass
class SearchProgress:
    """Live progress snapshot — useful for the frontend ProgressCard."""
    candidates_evaluated: int = 0
    best_score_so_far: float = float("inf")
    best_mechanism_name: str = ""
    history: list[tuple[str, float]] = field(default_factory=list)
    """List of (mechanism_name, composite_score) in evaluation order."""

    def update(self, mech: Mechanism, score: ScoringResult):
        self.candidates_evaluated += 1
        self.history.append((mech.name, score.composite_score))
        if score.composite_score < self.best_score_so_far:
            self.best_score_so_far = score.composite_score
            self.best_mechanism_name = mech.name


# ──────────────────────────────────────────────────────────────────────────────
# Common evaluator wrapper — calls scoring.score_candidate with bookkeeping
# ──────────────────────────────────────────────────────────────────────────────

def _evaluate(
    mech: Mechanism,
    evaluator: str,
    evaluator_input_fn: EvaluatorInputFn,
    benchmarks: list[str],
    progress: SearchProgress,
) -> ScoringResult:
    """Evaluate a single candidate, update progress, return scoring result."""
    try:
        result = score_candidate(
            mechanism_name=mech.name,
            evaluator=evaluator,
            evaluator_input=evaluator_input_fn(mech),
            benchmark=benchmarks if len(benchmarks) > 1 else benchmarks[0],
        )
    except Exception as exc:
        # Failed evaluation = infinite score (rejected by search)
        from .scoring import ScoringResult as _SR
        result = _SR(
            mechanism_name=mech.name, evaluator=evaluator,
            composite_score=float("inf"), verdict="ERROR"
        )
        result.notes = f"evaluation failed: {exc}"
    progress.update(mech, result)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Random search baseline
# ──────────────────────────────────────────────────────────────────────────────

def random_search(
    base_mechanism: Mechanism = PARK_47,
    evaluator: str = "cantera_0d",
    evaluator_input_fn: Optional[EvaluatorInputFn] = None,
    budget: int = 100,
    benchmarks: list[str] = ("ram_c_61km_M22.5",),
    min_reactions: int = 3,
    max_reactions: int = 47,
    seed: int = 42,
    progress_callback: Optional[Callable[[SearchProgress], None]] = None,
) -> list[tuple[Mechanism, ScoringResult]]:
    """Random-subset baseline.

    Generates `budget` random reaction subsets and scores each. Useful for:
      - Establishing a "random baseline" the GA must beat to claim convergence
      - Warm-starting GA's initial population
      - Cheap exploration of the search space

    Args:
        base_mechanism: Source mechanism to take subsets from
        evaluator: Registered evaluator name ('cantera_0d', 'cfd_vtu', etc.)
        evaluator_input_fn: How to convert each Mechanism into evaluator input
        budget: Total number of candidates to evaluate
        benchmarks: Benchmark names to score against
        min_reactions / max_reactions: Subset size bounds
        seed: RNG seed for reproducibility
        progress_callback: Called after each evaluation with the progress snapshot

    Returns:
        List of (Mechanism, ScoringResult) sorted best (lowest score) first.
    """
    if evaluator_input_fn is None:
        evaluator_input_fn = lambda m: {"mechanism": m}

    rng = random.Random(seed)
    valid_ids = [r.rxn_id for r in base_mechanism.reactions if r.A > 0]
    if not valid_ids:
        raise ValueError("Base mechanism has no valid reactions (A>0).")

    progress = SearchProgress()
    evaluated: list[tuple[Mechanism, ScoringResult]] = []

    for i in range(budget):
        n = rng.randint(min(min_reactions, len(valid_ids)),
                          min(max_reactions, len(valid_ids)))
        chosen = rng.sample(valid_ids, n)
        mech = base_mechanism.subset(reaction_ids=chosen)
        mech.name = f"random_{i:04d}_n={n}"
        result = _evaluate(mech, evaluator, evaluator_input_fn, list(benchmarks), progress)
        evaluated.append((mech, result))
        if progress_callback:
            progress_callback(progress)

    evaluated.sort(key=lambda pair: pair[1].composite_score)
    return evaluated


# ──────────────────────────────────────────────────────────────────────────────
# Genetic algorithm
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _GAIndividual:
    """One member of the GA population — encodes a reaction subset as a
    bitstring (1 = reaction included, 0 = excluded)."""
    bits: list[bool]
    score: float = float("inf")
    mechanism: Optional[Mechanism] = None
    scoring_result: Optional[ScoringResult] = None


def genetic_search(
    base_mechanism: Mechanism = PARK_47,
    evaluator: str = "cantera_0d",
    evaluator_input_fn: Optional[EvaluatorInputFn] = None,
    budget: int = 200,
    population_size: int = 20,
    generations: int = 10,
    mutation_rate: float = 0.05,
    elitism: int = 2,
    tournament_size: int = 3,
    benchmarks: list[str] = ("ram_c_61km_M22.5",),
    seed: int = 42,
    progress_callback: Optional[Callable[[SearchProgress], None]] = None,
) -> list[tuple[Mechanism, ScoringResult]]:
    """Genetic algorithm over reaction-subset bitstrings.

    Each individual is encoded as a bitstring of length |reactions|
    (1 = include reaction, 0 = exclude). Operations:
      - Selection: tournament of size `tournament_size`, lowest score wins
      - Crossover: uniform (each gene from random parent)
      - Mutation: toggle each bit with probability `mutation_rate`
      - Elitism: top `elitism` individuals carried over unmodified per generation

    Args:
        base_mechanism: Reaction pool (each reaction = one bit)
        evaluator: Registered evaluator backend
        evaluator_input_fn: Mechanism → evaluator input mapping
        budget: Hard cap on total evaluations (population_size * generations
            should be ≤ budget)
        population_size: # individuals per generation
        generations: # generations to evolve (0 = just evaluate initial pop)
        mutation_rate: Per-bit flip probability
        elitism: Top-K carried directly from parent to child population
        tournament_size: # competitors in each tournament selection
        benchmarks: Benchmark names to score against
        seed: RNG seed
        progress_callback: Optional progress reporter

    Returns:
        Sorted list of (Mechanism, ScoringResult) best-first across ALL
        generations (not just final population).
    """
    if evaluator_input_fn is None:
        evaluator_input_fn = lambda m: {"mechanism": m}

    rng = random.Random(seed)
    progress = SearchProgress()

    valid_reactions = [r for r in base_mechanism.reactions if r.A > 0]
    valid_ids = [r.rxn_id for r in valid_reactions]
    n_bits = len(valid_ids)
    if n_bits == 0:
        raise ValueError("Base mechanism has no valid reactions.")

    # Hall of fame: every evaluated individual ever
    hall_of_fame: list[tuple[Mechanism, ScoringResult]] = []

    def bits_to_mechanism(bits: list[bool], gen: int, idx: int) -> Mechanism:
        chosen = [valid_ids[i] for i, b in enumerate(bits) if b]
        if not chosen:    # empty mechanism is invalid; force one reaction
            chosen = [rng.choice(valid_ids)]
        mech = base_mechanism.subset(reaction_ids=chosen)
        mech.name = f"ga_g{gen:02d}_i{idx:02d}_n={len(chosen)}"
        return mech

    def evaluate(ind: _GAIndividual, gen: int, idx: int) -> None:
        mech = bits_to_mechanism(ind.bits, gen, idx)
        result = _evaluate(mech, evaluator, evaluator_input_fn,
                            list(benchmarks), progress)
        ind.mechanism = mech
        ind.scoring_result = result
        ind.score = result.composite_score
        hall_of_fame.append((mech, result))
        if progress_callback:
            progress_callback(progress)

    # ── Initialize population: random subsets ─────────────────────────────
    population: list[_GAIndividual] = []
    for i in range(population_size):
        # Random density: between 25% and 75% of reactions
        density = rng.uniform(0.25, 0.75)
        bits = [rng.random() < density for _ in range(n_bits)]
        if not any(bits):
            bits[rng.randrange(n_bits)] = True
        ind = _GAIndividual(bits=bits)
        evaluate(ind, gen=0, idx=i)
        population.append(ind)
        if progress.candidates_evaluated >= budget:
            break

    # ── Generations ───────────────────────────────────────────────────────
    for gen in range(1, generations + 1):
        if progress.candidates_evaluated >= budget:
            break

        population.sort(key=lambda ind: ind.score)
        next_population: list[_GAIndividual] = []

        # Elitism: top-K carried over directly
        for elite in population[:elitism]:
            # Don't re-evaluate elite (score already cached)
            next_population.append(_GAIndividual(
                bits=list(elite.bits), score=elite.score,
                mechanism=elite.mechanism, scoring_result=elite.scoring_result
            ))

        # Fill the rest via tournament + crossover + mutation
        while len(next_population) < population_size:
            if progress.candidates_evaluated >= budget:
                break

            # Tournament selection of two parents
            def tournament() -> _GAIndividual:
                contenders = rng.sample(population, min(tournament_size,
                                                          len(population)))
                return min(contenders, key=lambda ind: ind.score)

            p1, p2 = tournament(), tournament()

            # Uniform crossover
            child_bits = [
                p1.bits[i] if rng.random() < 0.5 else p2.bits[i]
                for i in range(n_bits)
            ]
            # Mutation
            for i in range(n_bits):
                if rng.random() < mutation_rate:
                    child_bits[i] = not child_bits[i]
            if not any(child_bits):
                child_bits[rng.randrange(n_bits)] = True

            child = _GAIndividual(bits=child_bits)
            evaluate(child, gen=gen, idx=len(next_population))
            next_population.append(child)

        population = next_population

    # Return hall of fame sorted by score
    hall_of_fame.sort(key=lambda pair: pair[1].composite_score)
    return hall_of_fame


# ──────────────────────────────────────────────────────────────────────────────
# Bayesian optimization stub
# ──────────────────────────────────────────────────────────────────────────────

def bayesian_search(*args, **kwargs):
    """Bayesian optimization over reaction subsets.

    Stub. Discrete BO over set membership requires custom kernels
    (e.g., Hamming-distance-based). Frameworks like botorch / sklearn-bayes
    support continuous + categorical, but pure-set spaces need custom work.
    Punted to future sprint.

    For now, use genetic_search() — well-suited to discrete combinatorial
    spaces and validates against random_search baseline.
    """
    raise NotImplementedError(
        "Bayesian search over reaction subsets not yet implemented. "
        "Use genetic_search() instead.")


# ──────────────────────────────────────────────────────────────────────────────
# Persistence — save search results for the frontend / paper
# ──────────────────────────────────────────────────────────────────────────────

def save_results(
    results: list[tuple[Mechanism, ScoringResult]],
    out_dir: Path,
    top_k: int = 10,
):
    """Save search output for downstream consumption.

    Layout:
        out_dir/
            search_summary.json       # ranked list of mechanism names + scores
            top_k/
                rank_001/
                    mechanism.yaml    # Cantera mech for top-1
                    mechanism.json    # Mechanism dict (for re-loading)
                    score.json        # full ScoringResult breakdown
                rank_002/
                ...
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    top_dir = out_dir / "top_k"
    top_dir.mkdir(exist_ok=True)

    # Summary
    summary = [
        {
            "rank": i + 1,
            "mechanism_name": m.name,
            "n_reactions": m.n_reactions,
            "composite_score": s.composite_score,
            "verdict": s.verdict,
        }
        for i, (m, s) in enumerate(results[:top_k])
    ]
    (out_dir / "search_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    # Per-candidate: full mechanism + score
    for rank, (mech, score_result) in enumerate(results[:top_k], 1):
        cand_dir = top_dir / f"rank_{rank:03d}"
        cand_dir.mkdir(exist_ok=True)
        (cand_dir / "mechanism.yaml").write_text(
            mech.to_cantera_yaml(), encoding="utf-8"
        )
        (cand_dir / "mechanism.json").write_text(
            json.dumps(mech.to_dict(), indent=2), encoding="utf-8"
        )
        (cand_dir / "score.json").write_text(
            json.dumps(score_result.to_dict(), indent=2, default=str),
            encoding="utf-8"
        )

    print(f"Saved {min(top_k, len(results))} top candidates to {out_dir}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI smoke test
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Smoke test using the dummy 'cfd_vtu' evaluator on the AIR-5 baseline.
    # We don't actually run search here — just exercise the API.
    from .generator import park_air5, park_air7

    print("Search loop module loaded.")
    print()
    print(f"Available algorithms: random_search, genetic_search "
          f"(bayesian_search stubbed)")
    print()
    print(f"Park 47 base mechanism: {PARK_47.summary()}")
    print(f"Park AIR-5 subset:      {park_air5().summary()}")
    print(f"Park AIR-7 subset:      {park_air7().summary()}")
    print()
    print("To run a real search, you need an evaluator wired to actual "
          "compute. Cantera 0D evaluator is registered as 'cantera_0d' "
          "(requires Cantera install, blocked on Windows).")
