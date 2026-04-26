"""Coordinator for parallel mechanism-data collection at scale.

Spawns N workers in parallel, each runs data_collection_worker.py for a
batch of K evaluations and exits. Coordinator restarts them in batches
until target reached. Each worker exit fully releases its accumulated
Cantera/Mutation++ state — this is the workaround for the per-process
memory leak that limited single-process collection to ~76K examples.

Memory footprint:
  - per worker peak: ~1-2 GB at 5000 evals
  - N workers concurrent: ~N × 2 GB
  - Default: 4 workers → 8 GB peak (safe alongside v7 ramp at 18 GB)

Throughput:
  - Single worker: ~150 evals/sec
  - N=4 workers: ~600 evals/sec (CPU-bound, scales linearly until cores saturate)
  - 1M target with 4 workers: ~28 minutes
  - 1M target with 16 workers (after v7 finishes): ~7 minutes

Run:
    cd /home/yarden/plasmanet && PYTHONPATH=. python3 \\
        scripts/parallel_data_collection.py --workers 4 --target 1000000
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def merge_jsonl(input_files: list[Path], output: Path):
    """Concatenate worker JSONL files into a single combined JSONL."""
    n = 0
    with open(output, "w") as out:
        for f in input_files:
            if f.exists():
                with open(f) as fin:
                    for line in fin:
                        if line.strip():
                            out.write(line)
                            n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4,
                     help="Number of parallel worker processes")
    ap.add_argument("--evals-per-batch", type=int, default=5000,
                     help="Evaluations per worker per batch (lower = more "
                          "frequent restarts = lower memory peak)")
    ap.add_argument("--target", type=int, default=1_000_000,
                     help="Total valid evaluations to collect")
    ap.add_argument("--out", type=Path,
                     default=Path("/home/yarden/mechanism_search_results/training_data_v3_parallel"))
    ap.add_argument("--combined-out", type=Path,
                     default=Path("/home/yarden/mechanism_search_results/training_data_v3.jsonl"))
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    repo_root = Path(__file__).parent.parent

    n_collected = 0
    batch = 0
    total_t0 = time.time()
    seed_base = int(time.time()) % 1000000   # randomize start

    print(f"Parallel data collection")
    print(f"  workers:         {args.workers}")
    print(f"  evals per batch: {args.evals_per_batch}")
    print(f"  target:          {args.target:,}")
    print(f"  out dir:         {args.out}")
    print(f"  combined out:    {args.combined_out}")
    print()

    while n_collected < args.target:
        batch += 1
        t0 = time.time()

        # Spawn workers
        procs = []
        out_files = []
        for w in range(args.workers):
            seed = seed_base + (batch * args.workers + w) * args.evals_per_batch
            of = args.out / f"worker_b{batch:04d}_w{w}.jsonl"
            out_files.append(of)
            p = subprocess.Popen([
                sys.executable,
                str(repo_root / "scripts" / "data_collection_worker.py"),
                "--n", str(args.evals_per_batch),
                "--seed-base", str(seed),
                "--out", str(of),
            ], cwd=str(repo_root),
               env={**os.environ, "PYTHONPATH": str(repo_root)})
            procs.append(p)

        # Wait for all
        for p in procs:
            p.wait()

        # Tally batch
        batch_collected = 0
        for of in out_files:
            if of.exists():
                with open(of) as f:
                    batch_collected += sum(1 for line in f if line.strip())
        n_collected += batch_collected

        dt = time.time() - t0
        elapsed = time.time() - total_t0
        rate = n_collected / max(elapsed, 1)
        eta_min = (args.target - n_collected) / max(rate, 1) / 60
        print(f"Batch {batch}: {batch_collected} valid in {dt:.1f}s "
              f"({batch_collected/dt:.0f}/s), "
              f"total {n_collected:,}/{args.target:,} ({100*n_collected/args.target:.1f}%), "
              f"eta {eta_min:.1f} min")

        # Periodic merge (every 10 batches) so partial progress is usable
        if batch % 10 == 0:
            n_merged = merge_jsonl(
                sorted(args.out.glob("worker_b*.jsonl")),
                args.combined_out,
            )
            print(f"  merged → {args.combined_out} ({n_merged:,} lines)")

        # Safety check: if we got nothing this batch, break to avoid infinite loop
        if batch_collected == 0:
            print("WARNING: zero collected this batch — workers may be failing")
            if batch > 3:
                print("Aborting after 3 failed batches")
                break

    # Final merge
    n_merged = merge_jsonl(
        sorted(args.out.glob("worker_b*.jsonl")),
        args.combined_out,
    )
    total_dt = time.time() - total_t0
    print()
    print(f"DONE: {n_collected:,} collected in {total_dt/60:.1f} min")
    print(f"Combined output: {args.combined_out} ({n_merged:,} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
