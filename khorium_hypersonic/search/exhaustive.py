"""Exhaustive enumeration of all 2^N reaction subsets.

For mechanisms with N ≲ 24 reactions and the surrogate evaluator at
~0.01 ms/eval, brute-force search is tractable (2^24 evals × 0.01 ms ≈
2.8 hours; use 2^20 ≈ 10 min for a quick sweep). Beyond N=24, prefer
sobol_bayesian_search.

This is the "AI-exhaustive method" Aaron Wu refers to — having the
surrogate evaluate every possible reaction subset against the published
flight-test ground truth, finding mechanisms that nobody would have
hand-engineered. The exhaustive search is enabled by the v4 surrogate's
5000× speedup vs Cantera 0D.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from plasmanet.mechanism_search.generator import Mechanism
from plasmanet.mechanism_search.scoring import (
    score_candidate, ScoringResult,
)


@dataclass
class ExhaustiveResult:
    """Container for exhaustive-search output.

    `evaluated` is a list of (mechanism, scoring_result) sorted ascending
    by composite_score. Top-K can be extracted with `evaluated[:K]`.
    """
    evaluated: list[tuple[Mechanism, ScoringResult]] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def top_k(self, k: int = 10) -> list[tuple[Mechanism, ScoringResult]]:
        return self.evaluated[:k]


def exhaustive_search(
    base_mechanism: Mechanism,
    evaluator: str = "plasmanet_v4",
    benchmarks: tuple = ("ram_c_61km_M22.5",),
    residence_time_s: float = 1e-6,
    min_reactions: int = 1,
    max_reactions: Optional[int] = None,
    require_dissociation: bool = True,
    require_ionization: bool = True,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    save_path: Optional[str] = None,
) -> ExhaustiveResult:
    """Score every valid subset of `base_mechanism`.

    Total enumeration is 2^N — call only with the surrogate evaluator
    (`plasmanet_v4`) and ideally on a base_mechanism subsetted down to
    N ≤ 24 reactions. For Park-47 (N=47, 1.4×10^14 subsets), use
    sobol_bayesian_search instead.

    Validity filters (applied during enumeration so the brute-force
    walker doesn't waste time on infeasible mechanisms):
      - subset has ≥ min_reactions, ≤ max_reactions
      - require_dissociation: ≥ 1 dissociation reaction
      - require_ionization:   ≥ 1 ionization reaction
    """
    valid_reactions = [r for r in base_mechanism.reactions if r.A > 0]
    N = len(valid_reactions)
    if N > 24:
        raise ValueError(
            f"exhaustive_search refuses N={N} reactions (2^N too large). "
            f"Subset base_mechanism first, or use sobol_bayesian_search."
        )

    if max_reactions is None:
        max_reactions = N

    rxn_ids = [r.rxn_id for r in valid_reactions]

    def evaluator_input_fn(mech):
        return {"mechanism": mech, "residence_time_s": residence_time_s}

    evaluated: list[tuple[Mechanism, ScoringResult]] = []
    n_total = 2 ** N
    n_done = 0
    n_skipped = 0
    t0 = time.monotonic()

    for mask in range(1, n_total):  # skip empty subset
        bits = [(mask >> i) & 1 for i in range(N)]
        n_chosen = sum(bits)
        if n_chosen < min_reactions or n_chosen > max_reactions:
            n_skipped += 1
            continue
        chosen_reactions = [valid_reactions[i] for i in range(N) if bits[i]]
        if require_dissociation and not any(r.is_dissociation for r in chosen_reactions):
            n_skipped += 1
            continue
        if require_ionization and not any(r.is_ionization for r in chosen_reactions):
            n_skipped += 1
            continue
        chosen_ids = [valid_reactions[i].rxn_id for i in range(N) if bits[i]]
        mech = base_mechanism.subset(reaction_ids=chosen_ids)
        mech.name = f"exhaustive_{mask:0{(N+3)//4}x}_n={n_chosen}"
        try:
            result = score_candidate(
                mechanism_name=mech.name,
                evaluator=evaluator,
                evaluator_input=evaluator_input_fn(mech),
                benchmark=list(benchmarks) if len(benchmarks) > 1 else benchmarks[0],
            )
        except Exception:
            continue
        evaluated.append((mech, result))
        n_done += 1
        if progress_callback and (n_done & 0xFFF) == 0:
            progress_callback(n_done, n_total)

    evaluated.sort(key=lambda pair: pair[1].composite_score)
    dt = time.monotonic() - t0

    out = ExhaustiveResult(
        evaluated=evaluated,
        metadata={
            "n_total_subsets": n_total,
            "n_evaluated": n_done,
            "n_skipped": n_skipped,
            "wall_seconds": dt,
            "evaluator": evaluator,
            "benchmarks": list(benchmarks),
            "residence_time_s": residence_time_s,
        },
    )

    if save_path is not None:
        from pathlib import Path
        import json
        Path(save_path).write_text(
            json.dumps({
                "metadata": out.metadata,
                "top_50": [
                    {"name": m.name,
                     "n_reactions": len(m.reactions),
                     "rxn_ids": [r.rxn_id for r in m.reactions],
                     "score": float(s.composite_score)}
                    for m, s in out.top_k(50)
                ],
            }, indent=2),
            encoding="utf-8",
        )
    return out
