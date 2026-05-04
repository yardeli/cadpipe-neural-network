#!/usr/bin/env python3
"""Phase 2 + Phase 3 driver for v4 search.

Phase 2: Sobol-seeded BO over Park-47 with the plasmanet_v4 surrogate.
         Validates first at small scale (n_sobol=100, n_bo=500) against
         a matched-budget random_search before scaling to full
         (n_sobol=1000, n_bo=5000).

Phase 3: Cantera-verify the top 50 candidates from Phase 2. Save JSONL +
         results doc.

Usage (must be run from /home/yarden/plasmanet, with PYTHONPATH=.):
    python3 -u scripts/run_search_v4.py [--phase 2|3|all] [--small]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── repo plumbing ────────────────────────────────────────────────────────────
# Paths default to repo-relative locations so the script runs on the GCP VM
# (where weights live in /home/yarden/mechanism_search_results) and on a
# local checkout (data/search_v4/, checkpoints/) without modification.
# Override with env vars: PLASMANET_RESULTS_DIR, PLASMANET_SURROGATE_PATH.

import os

REPO = Path(__file__).resolve().parent.parent
_VM_RESULTS = Path("/home/yarden/mechanism_search_results")
RESULTS_DIR = Path(os.environ.get("PLASMANET_RESULTS_DIR",
                                   str(_VM_RESULTS if _VM_RESULTS.exists()
                                       else REPO / "data" / "search_v4")))
TOP50_PATH = RESULTS_DIR / "search_v4_top50.jsonl"
PHASE2_FULL_PATH = RESULTS_DIR / "search_v4_phase2_full.json"
PHASE2_SMALL_PATH = RESULTS_DIR / "search_v4_phase2_small.json"
RESULTS_DOC = REPO / "docs" / "SEARCH_V4_RESULT.md"

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# ── Wire surrogate evaluator (idempotent registration) ──────────────────────

import torch
from plasmanet.mechanism_search.surrogate import (
    MechanismSurrogate, register_surrogate_evaluator,
)
from plasmanet.mechanism_search.search_loop import (
    sobol_bayesian_search, random_search, save_results,
)
from plasmanet.mechanism_search.scoring import score_candidate, BENCHMARKS
from plasmanet.mechanism_search.generator import (
    PARK_47, park_air5, park_air7,
)

_DEFAULT_SURROGATE = (REPO / "checkpoints" / "surrogate_v4.pt")
if not _DEFAULT_SURROGATE.exists():
    _DEFAULT_SURROGATE = RESULTS_DIR / "surrogate_v4.pt"
SURROGATE_PATH = Path(os.environ.get("PLASMANET_SURROGATE_PATH",
                                       str(_DEFAULT_SURROGATE)))

BENCHMARKS_TRAJECTORY = (
    "ram_c_47km_M18.5",
    "ram_c_61km_M22.5",
    "ram_c_71km_M23.6",
    "ram_c_81km_M23.9",
)


def load_surrogate_v4() -> MechanismSurrogate:
    """Load v4 weights and register the evaluator under name 'plasmanet_v4'.

    v4 architecture: 4-layer 512-hidden, 819K params. Constructor takes
    `freestream_dim=4, mechanism_dim=47, hidden_dim=512, n_layers=4`.
    """
    print(f"[run] loading surrogate from {SURROGATE_PATH}", flush=True)
    sd = torch.load(str(SURROGATE_PATH), map_location="cpu", weights_only=False)
    if isinstance(sd, dict) and "state_dict" in sd:
        sd_only = sd["state_dict"]
    elif isinstance(sd, dict):
        sd_only = sd
    else:
        sd_only = sd
    model = MechanismSurrogate(
        freestream_dim=4, mechanism_dim=47, hidden_dim=512, n_layers=4,
    )
    model.load_state_dict(sd_only, strict=False)
    model.eval()
    register_surrogate_evaluator(model, name="plasmanet_v4")
    print(f"[run] surrogate registered as 'plasmanet_v4'", flush=True)
    return model


# ── Phase 2 ──────────────────────────────────────────────────────────────────

def phase2_small_validation():
    """Cheap sanity check: BO at small budget should beat random at the same budget.

    Confirms the GP+EI loop is wired correctly before committing to the
    full run.
    """
    print("\n=== Phase 2 small validation (n_sobol=100, n_bo=500) ===", flush=True)
    t0 = time.monotonic()
    bo_result = sobol_bayesian_search(
        base_mechanism=PARK_47,
        evaluator="plasmanet_v4",
        benchmarks=BENCHMARKS_TRAJECTORY,
        n_sobol=100,
        n_bo=500,
        residence_time_s=1e-6,
        seed=42,
        save_path=PHASE2_SMALL_PATH,
    )
    bo_dt = time.monotonic() - t0
    bo_best = bo_result.evaluated[0][1].composite_score
    print(f"[bo small] best={bo_best:.6f} wall={bo_dt:.1f}s "
          f"(n_eval={len(bo_result.evaluated)})", flush=True)

    print("[rand small] running random_search at matched budget (600)...",
          flush=True)
    t0 = time.monotonic()
    rs = random_search(
        base_mechanism=PARK_47,
        evaluator="plasmanet_v4",
        budget=600,
        benchmarks=BENCHMARKS_TRAJECTORY,
        seed=42,
    )
    rs_dt = time.monotonic() - t0
    rs_best = rs[0][1].composite_score
    print(f"[rand small] best={rs_best:.6f} wall={rs_dt:.1f}s", flush=True)

    if bo_best <= rs_best:
        print(f"[validate] PASS — BO best ({bo_best:.6f}) <= "
              f"random best ({rs_best:.6f})", flush=True)
        return True
    else:
        print(f"[validate] FAIL — BO best ({bo_best:.6f}) > "
              f"random best ({rs_best:.6f}); not scaling to full run",
              flush=True)
        return False


def phase2_full() -> "SobolBOResult":
    """Full-budget Sobol-BO: n_sobol=1000, n_bo=5000."""
    print("\n=== Phase 2 full (n_sobol=1000, n_bo=5000) ===", flush=True)
    t0 = time.monotonic()
    result = sobol_bayesian_search(
        base_mechanism=PARK_47,
        evaluator="plasmanet_v4",
        benchmarks=BENCHMARKS_TRAJECTORY,
        n_sobol=1000,
        n_bo=5000,
        residence_time_s=1e-6,
        seed=42,
        save_path=PHASE2_FULL_PATH,
    )
    dt = time.monotonic() - t0
    print(f"[bo full] complete in {dt:.1f}s "
          f"({len(result.evaluated)} candidates)", flush=True)
    print(f"[bo full] best={result.metadata['best_score']:.6f} "
          f"({result.metadata['best_mechanism_name']}, "
          f"{result.metadata['best_n_reactions']} reactions)", flush=True)
    return result


# ── Phase 3 ──────────────────────────────────────────────────────────────────

def phase3_cantera_verify(top50_pairs):
    """Re-evaluate each of the top 50 surrogate candidates with cantera_0d.

    Saves JSONL ranked by score_cantera (best first).
    """
    print(f"\n=== Phase 3 Cantera verification (top {len(top50_pairs)}) ===",
          flush=True)

    records = []
    t0 = time.monotonic()
    for i, (mech, surr_result) in enumerate(top50_pairs):
        t_mech = time.monotonic()
        try:
            cantera_result = score_candidate(
                mechanism_name=mech.name,
                evaluator="cantera_0d",
                evaluator_input={
                    "mechanism": mech,
                    "residence_time_s": 1e-6,
                },
                benchmark=list(BENCHMARKS_TRAJECTORY),
            )
            cantera_score = cantera_result.composite_score
            cantera_verdict = getattr(cantera_result, "verdict", None)
            cantera_per_bench = getattr(cantera_result, "per_benchmark", None)
        except Exception as exc:
            cantera_score = float("inf")
            cantera_verdict = "ERROR"
            cantera_per_bench = None
            print(f"[verify {i:02d}] EXCEPTION: {exc}", flush=True)

        rec = {
            "rank_surrogate": i + 1,
            "mechanism_name": mech.name,
            "n_reactions": len(mech.reactions),
            "reaction_ids": [r.rxn_id for r in mech.reactions],
            "score_surrogate": float(surr_result.composite_score),
            "score_cantera": (
                float(cantera_score) if math.isfinite(cantera_score) else None
            ),
            "verdict_cantera": cantera_verdict,
            "log10_err_pred_truth": (
                float(cantera_score - surr_result.composite_score)
                if (cantera_score is not None
                    and math.isfinite(cantera_score)
                    and math.isfinite(surr_result.composite_score))
                else None
            ),
            "cantera_per_benchmark": _serialize_per_benchmark(cantera_per_bench),
        }
        records.append(rec)
        dt = time.monotonic() - t_mech
        print(f"[verify {i:02d}] {mech.name}: surrogate={surr_result.composite_score:+.4f} "
              f"cantera={cantera_score if isinstance(cantera_score, float) and math.isfinite(cantera_score) else 'INF':+.4f} "
              f"({dt:.1f}s)" if isinstance(cantera_score, float) and math.isfinite(cantera_score)
              else f"[verify {i:02d}] {mech.name}: surrogate={surr_result.composite_score:+.4f} "
                   f"cantera=ERR ({dt:.1f}s)",
              flush=True)

    # Re-rank by Cantera score (None / inf go to the bottom).
    def cantera_sort_key(rec):
        s = rec["score_cantera"]
        return (s if s is not None else float("inf"), rec["rank_surrogate"])
    records.sort(key=cantera_sort_key)
    for new_rank, rec in enumerate(records, start=1):
        rec["rank_cantera"] = new_rank

    TOP50_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TOP50_PATH.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    dt_total = time.monotonic() - t0
    print(f"[verify] saved {len(records)} records to {TOP50_PATH} "
          f"in {dt_total:.1f}s", flush=True)
    return records


def _serialize_per_benchmark(pb):
    """Best-effort serialization of per-benchmark scoring breakdown."""
    if pb is None:
        return None
    if isinstance(pb, list):
        out = []
        for entry in pb:
            if isinstance(entry, dict):
                out.append({k: v for k, v in entry.items()
                            if isinstance(v, (str, int, float, bool, type(None)))
                            or isinstance(v, dict)})
            else:
                # dataclass-ish
                try:
                    out.append({k: getattr(entry, k) for k in
                                ("benchmark", "ne_predicted_m3", "log10_err_ne",
                                 "score")
                                if hasattr(entry, k)})
                except Exception:
                    pass
        return out
    return str(pb)[:1000]


# ── Baseline scoring (for the results doc) ───────────────────────────────────

def score_baseline(name: str, mech) -> dict:
    """Score Park AIR-5 / AIR-7 for the doc."""
    try:
        cr = score_candidate(
            mechanism_name=name, evaluator="cantera_0d",
            evaluator_input={"mechanism": mech, "residence_time_s": 1e-6},
            benchmark=list(BENCHMARKS_TRAJECTORY),
        )
        return {
            "name": name,
            "n_reactions": len(mech.reactions),
            "score_cantera": float(cr.composite_score)
                              if math.isfinite(cr.composite_score) else None,
            "verdict": getattr(cr, "verdict", None),
        }
    except Exception as exc:
        return {"name": name, "n_reactions": len(mech.reactions),
                "score_cantera": None, "verdict": f"ERROR: {exc}"}


# ── Results doc ──────────────────────────────────────────────────────────────

def write_results_doc(records, baselines, phase2_meta):
    """Write docs/SEARCH_V4_RESULT.md with top 5 + baseline comparison."""
    top = records[:5]

    def fmt_score(s):
        if s is None:
            return "N/A"
        return f"{s:+.4f}"

    park_air5 = next((b for b in baselines if b["name"] == "Park_AIR5"), None)
    park_air7 = next((b for b in baselines if b["name"] == "Park_AIR7"), None)

    air7_score = park_air7["score_cantera"] if park_air7 else None
    n_beat_air7 = sum(
        1 for r in records
        if (r["score_cantera"] is not None and air7_score is not None
            and r["score_cantera"] < air7_score)
    )

    lines = []
    lines.append("# Search V4 Results — Sobol-seeded Bayesian Optimization")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}  ")
    lines.append(f"**Surrogate:** plasmanet_v4 (4-layer 512-hidden MLP, 819K params, "
                 f"test MAE 0.183 log10)  ")
    lines.append(f"**Search:** Sobol(d={phase2_meta.get('search_dim', '?')}, "
                 f"n_sobol={phase2_meta.get('n_sobol_evaluated', '?')}) + "
                 f"BO(n_bo={phase2_meta.get('n_bo', '?')}, "
                 f"refit_every={phase2_meta.get('refit_every', 50)})  ")
    lines.append(f"**Trajectory:** {', '.join(phase2_meta.get('benchmarks', []))}  ")
    lines.append(f"**Residence time:** {phase2_meta.get('residence_time_s', 1e-6):g} s  ")
    lines.append(f"**Phase 2 wall time:** {phase2_meta.get('total_wall_time_s', 0):.1f} s  ")
    lines.append(f"**Phase 2 GP marginal log-likelihood:** init "
                 f"{phase2_meta.get('gp_log_marginal_likelihood_init', 0):.2f} → "
                 f"final {phase2_meta.get('gp_log_marginal_likelihood_final', 0):.2f}  ")
    lines.append("")
    lines.append("## Top 5 mechanisms (Cantera-verified)")
    lines.append("")
    lines.append("| Rank (Cantera) | Rank (surrogate) | Name | n_reactions | "
                 "Score (surrogate) | Score (Cantera) | log10 err pred-truth | Verdict |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in top:
        lines.append(
            f"| {r.get('rank_cantera', '?')} | {r['rank_surrogate']} | "
            f"`{r['mechanism_name']}` | {r['n_reactions']} | "
            f"{fmt_score(r['score_surrogate'])} | {fmt_score(r['score_cantera'])} | "
            f"{fmt_score(r.get('log10_err_pred_truth'))} | "
            f"{r.get('verdict_cantera') or '?'} |"
        )
    lines.append("")
    lines.append("## Baselines")
    lines.append("")
    lines.append("| Name | n_reactions | Score (Cantera) | Verdict |")
    lines.append("|---|---|---|---|")
    for b in baselines:
        lines.append(
            f"| `{b['name']}` | {b['n_reactions']} | "
            f"{fmt_score(b['score_cantera'])} | {b['verdict'] or '?'} |"
        )
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    if park_air7 and air7_score is not None:
        lines.append(
            f"- **Park AIR-7 baseline composite score:** {air7_score:+.4f}  ")
        lines.append(
            f"- **Top-50 candidates beating AIR-7:** {n_beat_air7} of "
            f"{len(records)}")
        if records and records[0]["score_cantera"] is not None:
            best = records[0]["score_cantera"]
            delta = air7_score - best
            sign = "better" if delta > 0 else "worse"
            lines.append(
                f"- **Best candidate:** `{records[0]['mechanism_name']}` "
                f"({records[0]['n_reactions']} reactions, score "
                f"{best:+.4f}) — {abs(delta):.4f} {sign} than AIR-7")
    else:
        lines.append("- Park AIR-7 baseline did not score; cannot compare.")
    lines.append("")
    lines.append("## Files")
    lines.append("")
    lines.append(f"- Phase 2 raw output: `{PHASE2_FULL_PATH}`")
    lines.append(f"- Phase 3 top-50 JSONL: `{TOP50_PATH}`")
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```bash")
    lines.append("cd /home/yarden/plasmanet")
    lines.append("PYTHONPATH=. python3 -u scripts/run_search_v4.py")
    lines.append("```")
    lines.append("")

    RESULTS_DOC.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_DOC.write_text("\n".join(lines))
    print(f"[doc] wrote {RESULTS_DOC}", flush=True)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["small", "2", "3", "all"], default="all")
    p.add_argument("--skip-validation", action="store_true",
                   help="skip the small-budget BO-vs-random validation")
    args = p.parse_args()

    load_surrogate_v4()

    if args.phase in ("small",):
        phase2_small_validation()
        return

    if args.phase in ("2", "all") and not args.skip_validation:
        ok = phase2_small_validation()
        if not ok:
            print("[main] small validation failed; aborting before full run",
                  flush=True)
            sys.exit(2)

    if args.phase in ("2", "all"):
        phase2 = phase2_full()
        top50_pairs = phase2.evaluated[:50]
        phase2_meta = phase2.metadata
    else:
        # Phase 3 only — load saved Phase 2 results and re-derive top 50
        if not PHASE2_FULL_PATH.exists():
            print(f"[main] {PHASE2_FULL_PATH} not found; run --phase 2 first",
                  flush=True)
            sys.exit(2)
        # Without the actual Mechanism objects we can't re-evaluate; this
        # path is just a stub — full Phase 3 needs to follow Phase 2 in the
        # same process invocation.
        print("[main] phase=3-only requires Phase 2 in same process; skipping",
              flush=True)
        return

    if args.phase in ("3", "all"):
        records = phase3_cantera_verify(top50_pairs)
        baselines = [
            score_baseline("Park_AIR5", park_air5()),
            score_baseline("Park_AIR7", park_air7()),
        ]
        write_results_doc(records, baselines, phase2_meta)

    print("\n[main] DONE", flush=True)


if __name__ == "__main__":
    main()
