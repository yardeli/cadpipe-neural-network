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
# Sobol-seeded Bayesian Optimization (multi-altitude RAM-C trajectory)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SobolBOResult:
    """Output of sobol_bayesian_search.

    .evaluated  Sorted list of (Mechanism, ScoringResult), ascending by
                composite_score — first entry is the best.
    .metadata   Dict with n_sobol, n_bo, GP marginal likelihoods, wall time,
                etc. Useful for logging + reproducibility.
    """
    evaluated: list
    metadata: dict


def _passes_physical_filter(bits, dissoc_mask, ion_mask) -> bool:
    """Mask must include >=1 dissociation AND >=1 ionization reaction.

    Same physical sanity filter the v3/v4 training data used: a mechanism
    with no dissociation can't produce radicals; a mechanism with no
    ionization can't produce electrons. Either failure mode reduces the
    candidate to a uselessly noisy outlier, so we skip them up-front.
    """
    import numpy as np
    return bool((bits * dissoc_mask).any() and (bits * ion_mask).any())


def _bits_to_reaction_ids(bits, valid_ids):
    """Convert a binary mask over `valid_ids` to the corresponding rxn_id list."""
    return [valid_ids[i] for i, b in enumerate(bits) if b]


def sobol_bayesian_search(
    base_mechanism: Mechanism = PARK_47,
    evaluator: str = "plasmanet_v4",
    evaluator_input_fn: Optional[EvaluatorInputFn] = None,
    benchmarks: tuple = (
        "ram_c_47km_M18.5",
        "ram_c_61km_M22.5",
        "ram_c_71km_M23.6",
        "ram_c_81km_M23.9",
    ),
    n_sobol: int = 1000,
    n_bo: int = 5000,
    residence_time_s: float = 1e-6,
    seed: int = 42,
    refit_every: int = 200,
    pool_size: int = 10000,
    save_path: Optional[Path] = None,
    progress_callback: Optional[Callable] = None,
) -> SobolBOResult:
    """Sobol-seeded Bayesian Optimization over reaction subsets.

    Stage 1: Sobol low-discrepancy sequence in [0,1]^d (d = number of
             A>0 reactions in `base_mechanism`). Threshold at 0.5 -> binary
             mask. Filter out masks lacking either dissociation or ionization
             reactions. Score all via `evaluator`.

    Stage 2: Fit sklearn GP (Matern-2.5 + WhiteKernel, normalize_y=True)
             on Sobol observations. Loop n_bo times:
                 - Generate `pool_size` random valid masks.
                 - Posterior mean + std -> Expected Improvement (minimize).
                 - Pick argmax EI. Score it. Append to GP training set.
                 - Refit GP every `refit_every` iterations (full refit;
                   sklearn doesn't support incremental fits).

    Args:
        base_mechanism: Park-47 by default. Reactions with A=0 are skipped.
        evaluator: Registered evaluator name (default "plasmanet_v4" surrogate).
        evaluator_input_fn: Optional override for the input dict; the default
            forwards both the mechanism and `residence_time_s` so Cantera-class
            evaluators can use the latter.
        benchmarks: Trajectory points to score against. Default = full RAM-C
            J&C 1972 4-point trajectory (multi-altitude is the meaningful
            search target — single-point can be gamed by Saha equilibrium).
        n_sobol: Number of Sobol seed evaluations.
        n_bo: Number of BO iterations.
        residence_time_s: Pinned to 1e-6 by default. Avoids the Saha
            equilibrium regime where mechanism identity stops mattering.
        seed: RNG seed for both Sobol and the random pool.
        refit_every: GP refit cadence (every N BO iterations).
        pool_size: Candidate pool per BO step for EI argmax.
        save_path: If set, JSON dump of {metadata, evaluated} to this path.
        progress_callback: Called after each evaluation with the SearchProgress.

    Returns:
        SobolBOResult(evaluated=[(mech, result), ...], metadata={...})
    """
    import math
    import time
    import numpy as np
    from scipy.stats import qmc, norm
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import Matern, WhiteKernel, ConstantKernel

    # Default evaluator_input_fn forwards residence_time_s; Cantera-class
    # evaluators use it, surrogate-class evaluators ignore the kwarg.
    if evaluator_input_fn is None:
        evaluator_input_fn = lambda m: {
            "mechanism": m,
            "residence_time_s": residence_time_s,
        }

    rng = np.random.default_rng(seed)
    valid_reactions = [r for r in base_mechanism.reactions if r.A > 0]
    valid_ids = [r.rxn_id for r in valid_reactions]
    d = len(valid_reactions)
    if d == 0:
        raise ValueError("base_mechanism has no A>0 reactions")

    dissoc_mask = np.array([r.is_dissociation for r in valid_reactions], dtype=int)
    ion_mask = np.array([r.is_ionization for r in valid_reactions], dtype=int)

    progress = SearchProgress()
    evaluated: list = []
    bench_list = list(benchmarks)

    t_start = time.monotonic()

    # ─── SOBOL PHASE ─────────────────────────────────────────────────────────
    sobol = qmc.Sobol(d=d, seed=seed, scramble=True)
    # Buffer 2x to absorb filter rejects (~13% reject rate at d=40 with
    # 12 dissoc + 12 ion). Real reject rate is far lower in practice.
    points = sobol.random(n_sobol * 2)
    sobol_bits_list: list = []
    sobol_score_list: list = []

    for p in points:
        if len(sobol_bits_list) >= n_sobol:
            break
        bits = (p >= 0.5).astype(int)
        if not _passes_physical_filter(bits, dissoc_mask, ion_mask):
            continue
        rxn_ids = _bits_to_reaction_ids(bits, valid_ids)
        mech = base_mechanism.subset(reaction_ids=rxn_ids)
        mech.name = f"sobol_{len(sobol_bits_list):04d}_n={int(bits.sum())}"
        result = _evaluate(mech, evaluator, evaluator_input_fn,
                           bench_list, progress)
        sobol_bits_list.append(bits)
        sobol_score_list.append(result.composite_score)
        evaluated.append((mech, result))
        if progress_callback:
            progress_callback(progress)

    # ─── GP FIT (initial) ────────────────────────────────────────────────────
    X_train = np.array(sobol_bits_list, dtype=float)
    y_train = np.array(sobol_score_list, dtype=float)
    finite = np.isfinite(y_train)
    if finite.sum() < 5:
        # Not enough finite scores to fit a GP; abort BO phase.
        evaluated.sort(key=lambda pair: pair[1].composite_score)
        return SobolBOResult(
            evaluated=evaluated,
            metadata={
                "error": "insufficient finite Sobol scores for GP fit",
                "n_finite_sobol": int(finite.sum()),
                "total_wall_time_s": time.monotonic() - t_start,
            },
        )
    X_fit = X_train[finite]
    y_fit = y_train[finite]

    kernel = (ConstantKernel(1.0, (1e-3, 1e3))
              * Matern(length_scale=1.0, length_scale_bounds=(1e-2, 1e2), nu=2.5)
              + WhiteKernel(noise_level=1e-2, noise_level_bounds=(1e-6, 1.0)))
    gp = GaussianProcessRegressor(
        kernel=kernel, normalize_y=True, n_restarts_optimizer=0, random_state=seed,
    )
    gp.fit(X_fit, y_fit)
    gp_lml_init = float(gp.log_marginal_likelihood_value_)

    # ─── BO LOOP ─────────────────────────────────────────────────────────────
    best_score = float(y_fit.min())
    n_refits = 1

    for it in range(n_bo):
        if it % 100 == 0:
            import time as _time
            print(f"[bo] iter {it}/{n_bo} elapsed={_time.monotonic()-t_start:.0f}s best={best_score:+.4f} N_train={len(X_fit)}", flush=True)
        # Sample a pool of random valid masks for EI argmax.
        pool_bits: list = []
        attempts = 0
        max_attempts = pool_size * 4
        while len(pool_bits) < pool_size and attempts < max_attempts:
            mask = rng.integers(0, 2, size=d)
            if _passes_physical_filter(mask, dissoc_mask, ion_mask):
                pool_bits.append(mask)
            attempts += 1
        if not pool_bits:
            break  # rare; means the filter is too tight for this base mech
        pool = np.asarray(pool_bits, dtype=float)

        mu, sigma = gp.predict(pool, return_std=True)
        sigma = np.maximum(sigma, 1e-9)

        # Expected Improvement (minimization variant):
        #   improvement = best - mu
        #   z = improvement / sigma
        #   EI = improvement * Phi(z) + sigma * phi(z), clipped to >=0
        improvement = best_score - mu
        z = improvement / sigma
        ei = improvement * norm.cdf(z) + sigma * norm.pdf(z)
        ei = np.where(improvement > 0, ei, 0.0)

        if ei.max() <= 0.0:
            pick = int(np.argmin(mu))   # fallback when no apparent improvement
        else:
            pick = int(np.argmax(ei))

        bits = pool[pick].astype(int)
        rxn_ids = _bits_to_reaction_ids(bits, valid_ids)
        mech = base_mechanism.subset(reaction_ids=rxn_ids)
        mech.name = f"bo_{it:04d}_n={int(bits.sum())}"
        result = _evaluate(mech, evaluator, evaluator_input_fn,
                           bench_list, progress)
        evaluated.append((mech, result))

        if math.isfinite(result.composite_score):
            X_fit = np.vstack([X_fit, bits.reshape(1, -1).astype(float)])
            y_fit = np.append(y_fit, result.composite_score)
            if result.composite_score < best_score:
                best_score = result.composite_score

        if (it + 1) % refit_every == 0:
            gp.fit(X_fit, y_fit)
            n_refits += 1

        if progress_callback:
            progress_callback(progress)

    # Final refit if last batch was partial
    if n_bo % refit_every != 0 and n_bo > 0:
        gp.fit(X_fit, y_fit)
        n_refits += 1

    t_total = time.monotonic() - t_start

    evaluated.sort(key=lambda pair: pair[1].composite_score)

    metadata = {
        "n_sobol_requested": n_sobol,
        "n_sobol_evaluated": len(sobol_bits_list),
        "n_bo": n_bo,
        "n_evaluated_total": len(evaluated),
        "best_score": float(evaluated[0][1].composite_score) if evaluated else None,
        "best_mechanism_name": evaluated[0][0].name if evaluated else None,
        "best_n_reactions": (len(evaluated[0][0].reactions) if evaluated else None),
        "gp_log_marginal_likelihood_init": gp_lml_init,
        "gp_log_marginal_likelihood_final": float(gp.log_marginal_likelihood_value_),
        "gp_n_refits": n_refits,
        "gp_n_train_final": int(len(X_fit)),
        "total_wall_time_s": float(t_total),
        "evaluator": evaluator,
        "benchmarks": bench_list,
        "residence_time_s": residence_time_s,
        "seed": seed,
        "search_dim": d,
        "n_dissociation_in_base": int(dissoc_mask.sum()),
        "n_ionization_in_base": int(ion_mask.sum()),
        "pool_size": pool_size,
        "refit_every": refit_every,
    }

    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with save_path.open("w") as f:
            json.dump({
                "metadata": metadata,
                "evaluated": [
                    {
                        "name": m.name,
                        "n_reactions": len(m.reactions),
                        "composite_score": r.composite_score,
                        "verdict": getattr(r, "verdict", None),
                    }
                    for m, r in evaluated
                ],
            }, f, indent=2)

    return SobolBOResult(evaluated=evaluated, metadata=metadata)




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
