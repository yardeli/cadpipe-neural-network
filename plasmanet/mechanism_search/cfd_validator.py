"""S-5: CFD validation harness for top-K mechanism-search candidates.

Driver
------
Walks a `top_k/` directory produced by the search loop, generates an SU2
NEMO cfg + stage dir per candidate, and (in live mode) sequentially runs
mpirun on each, then scores the result with `scripts/validate_ram_c_nemo.py`.

Why "closest supported AIR-N" instead of the candidate's exact subset
--------------------------------------------------------------------
SU2 v7.5.1's NEMO solver only accepts `GAS_MODEL = N2 | AIR-5 | AIR-7 |
AIR-11 | ARGON` — it does not consume arbitrary Cantera mechanisms.
Each candidate's reaction subset is therefore mapped to the smallest
SU2-supported family that covers its species set:

  no charged species             → AIR-5
  electrons + first ion (NO+)    → AIR-7
  electrons + multiple ion sp.   → AIR-11

The candidate's actual mechanism (rate constants, reaction list) is
preserved alongside the cfg as `mechanism.json` and `score.json` for
paper-trail purposes.  The CFD result is therefore a **conservative
ceiling** on the candidate's effect — it includes any reactions in the
parent AIR-N family that the candidate itself omitted.

Live launch protocol
--------------------
- Pre-flight gate: refuses to launch if `pgrep SU2_CFD` returns any
  process (avoids stomping on a long-running ramp).
- Sequential, blocking — one mpirun at a time. Each takes 1–2 hours on
  the 459K-cell mesh at 16 MPI ranks; top-5 = 5–10 hours wall.
- Saves `validation_progress_<benchmark>.json` after each candidate so
  partial results survive a crash mid-sweep.

Dry-run mode (`--dry-run`)
--------------------------
Builds the cfg + stage dir per candidate, copies the mechanism/score JSON
in for posterity, but does NOT submit. Used to inspect the planned cfg
before committing to several hours of compute.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

# ── VM defaults (override via CLI for any other host) ────────────────────────

DEFAULT_SU2_BIN = "/opt/su2-nemo-mpi/bin/SU2_CFD"
DEFAULT_LD_LIBRARY_PATH = "/opt/su2-nemo/lib"
DEFAULT_MPP_DATA_DIRECTORY = "/opt/su2-nemo/mpp-data"
DEFAULT_MPI_RANKS = 16
DEFAULT_MAX_ITERS = 1500
DEFAULT_RESULTS_ROOT = Path("/home/yarden/cfd_validation_runs")
DEFAULT_VALIDATE_SCRIPT = Path("/home/yarden/plasmanet/scripts/validate_ram_c_nemo.py")
DEFAULT_SEARCH_DIR = Path(
    "/home/yarden/mechanism_search_results/sweep/sweep5_wide_budget/top_k"
)
# Most recent v7b ramp output as of harness build — caller can override
# once v7 finishes its M22.5 stage and a `_M22p5_0_A61/` dir exists.
DEFAULT_WARM_START_DIR = Path(
    "/home/yarden/ram_c_runs/ramC_refined_air7v7b_M18_0_A61"
)


# ── Benchmarks ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Benchmark:
    name: str
    mach: float
    altitude_km: float
    p_inf_pa: float
    t_inf_k: float

    @property
    def filename_tag(self) -> str:
        # ram_c_61km_M22.5 → ram_c_61km_M22p5  (filesystem-safe)
        return self.name.replace(".", "p")


BENCHMARKS: dict[str, Benchmark] = {
    "ram_c_61km_M22.5": Benchmark(
        name="ram_c_61km_M22.5",
        mach=22.5,
        altitude_km=61.0,
        p_inf_pa=15.71,            # US Standard Atmosphere @ 61 km
        t_inf_k=242.65,
    ),
    "ram_c_61km_M10": Benchmark(
        name="ram_c_61km_M10",
        mach=10.0,
        altitude_km=61.0,
        p_inf_pa=253.7116,
        t_inf_k=242.65,
    ),
}


# ── Candidate discovery ──────────────────────────────────────────────────────

@dataclass
class Candidate:
    rank: int
    name: str
    species: list[str]
    n_reactions: int
    air_n_su2: str                  # "AIR-5" | "AIR-7" | "AIR-11"
    yaml_path: Path
    json_path: Path
    score_path: Path
    surrogate_score: dict           # raw contents of score.json


def select_su2_air_n(species: list[str]) -> str:
    """Pick the smallest SU2 v7.5.1 GAS_MODEL family that covers `species`.

    SU2 v7.5.1 supports {AIR-5, AIR-7, AIR-11} for the NEMO solver:
      AIR-5  = N2, O2, NO, N, O                              (no ions)
      AIR-7  = AIR-5 + e-, NO+                               (first ion)
      AIR-11 = AIR-7 + N+, O+, N2+, O2+                      (full ionization)
    """
    has_e = "e-" in species
    pos_ions = [s for s in species if s.endswith("+")]
    if has_e and len(pos_ions) >= 2:
        return "AIR-11"
    if has_e and len(pos_ions) >= 1:
        return "AIR-7"
    return "AIR-5"


def discover_top_k(search_dir: Path, top_k: int = 5) -> list[Candidate]:
    """Walk `search_dir/rank_NNN/`, parse {mechanism,score}.json into candidates.

    Rank dirs are assumed pre-sorted by the search; we honor that order.
    """
    if not search_dir.exists():
        raise FileNotFoundError(f"top_k search dir not found: {search_dir}")
    rank_dirs = sorted(
        d for d in search_dir.iterdir()
        if d.is_dir() and d.name.startswith("rank_")
    )
    if not rank_dirs:
        raise RuntimeError(f"No rank_*/ subdirectories in {search_dir}")

    candidates: list[Candidate] = []
    for rank_dir in rank_dirs[:top_k]:
        rank = int(rank_dir.name.split("_", 1)[1])
        mech_json = rank_dir / "mechanism.json"
        mech_yaml = rank_dir / "mechanism.yaml"
        score_json = rank_dir / "score.json"
        if not mech_json.exists():
            print(f"[discover] WARN: skipping {rank_dir} — missing mechanism.json",
                  file=sys.stderr)
            continue
        with mech_json.open() as f:
            mech = json.load(f)
        score = {}
        if score_json.exists():
            with score_json.open() as f:
                score = json.load(f)
        species = list(mech.get("species", []))
        candidates.append(Candidate(
            rank=rank,
            name=mech.get("name", f"rank_{rank:03d}"),
            species=species,
            n_reactions=len(mech.get("reactions", [])),
            air_n_su2=select_su2_air_n(species),
            yaml_path=mech_yaml,
            json_path=mech_json,
            score_path=score_json,
            surrogate_score=score,
        ))
    return candidates


# ── Cfg generation ───────────────────────────────────────────────────────────

# GAS_COMPOSITION ordering matches SU2 NEMO species lists for each AIR-N.
# Pure-freestream cold-start mass fractions: 77 % N2, 23 % O2.
_GAS_COMPOSITION = {
    "AIR-5":  "(0.77, 0.23, 0.0, 0.0, 0.0)",
    "AIR-7":  "(0.0, 0.77, 0.23, 0.0, 0.0, 0.0, 0.0)",
    "AIR-11": "(0.0, 0.77, 0.23, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)",
}


def _surrogate_ne(candidate: Candidate, benchmark_name: str) -> Optional[float]:
    """Pull the surrogate's predicted ne for `benchmark_name` from score.json."""
    pb = candidate.surrogate_score.get("per_benchmark") or []
    for entry in pb:
        if entry.get("benchmark") == benchmark_name:
            return entry.get("ne_predicted_m3")
    return None


def _surrogate_log10_err(candidate: Candidate, benchmark_name: str) -> Optional[float]:
    pb = candidate.surrogate_score.get("per_benchmark") or []
    for entry in pb:
        if entry.get("benchmark") == benchmark_name:
            return entry.get("log10_err_ne")
    return None


def build_cfg(candidate: Candidate, benchmark: Benchmark, *,
              max_iters: int = DEFAULT_MAX_ITERS,
              cfl: float = 0.2) -> str:
    """Emit the SU2 NEMO cfg as a string. Header documents the candidate
    for paper traceability; body is the standard v7-style inviscid setup."""
    surrogate_ne = _surrogate_ne(candidate, benchmark.name)
    surrogate_err = _surrogate_log10_err(candidate, benchmark.name)
    surrogate_ne_str = f"{surrogate_ne:.3e}" if surrogate_ne is not None else "?"
    surrogate_err_str = f"{surrogate_err:+.3f}" if surrogate_err is not None else "?"
    verdict = candidate.surrogate_score.get("verdict", "?")
    composite = candidate.surrogate_score.get("composite_score", "?")

    header = f"""\
% ============================================================================
% S-5 CFD validation cfg — generated by plasmanet.mechanism_search.cfd_validator
% Candidate:       rank {candidate.rank:03d}  ({candidate.name})
% Surrogate score: composite={composite}  verdict={verdict}
% Surrogate ne:    {surrogate_ne_str} m^-3 at {benchmark.name}
% Surrogate err:   log10(ne_pred / ne_ref) = {surrogate_err_str}
% Candidate set:   {len(candidate.species)} species, {candidate.n_reactions} reactions
% Full spec:       ./mechanism.json (copied from search results)
% Surrogate score: ./score.json     (copied from search results)
%
% SU2 GAS_MODEL:   {candidate.air_n_su2}  (closest v7.5.1-supported family)
%   v7.5.1 doesn't accept arbitrary species/reaction subsets, so the cfg
%   uses the full {candidate.air_n_su2} mechanism even though the candidate
%   may omit some reactions. The CFD result is a CONSERVATIVE CEILING on
%   the candidate's effect — it includes any reactions in {candidate.air_n_su2}
%   that the candidate itself doesn't define.
% ============================================================================

"""

    body = f"""\
SOLVER= NEMO_EULER
GAS_MODEL= {candidate.air_n_su2}
GAS_COMPOSITION= {_GAS_COMPOSITION[candidate.air_n_su2]}
MATH_PROBLEM= DIRECT
RESTART_SOL= YES
SOLUTION_FILENAME= solution.dat

FLUID_MODEL= SU2_NONEQ

MACH_NUMBER= {benchmark.mach}
AOA= 0.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= {benchmark.p_inf_pa}
FREESTREAM_TEMPERATURE= {benchmark.t_inf_k}
FREESTREAM_TEMPERATURE_VE= {benchmark.t_inf_k}

MARKER_EULER= ( body )
MARKER_FAR= ( farfield )
MARKER_PLOTTING= ( body )
MARKER_MONITORING= ( body )

NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
CFL_NUMBER= {cfl}
CFL_ADAPT= NO
ITER= {max_iters}
CONV_NUM_METHOD_FLOW= LAX-FRIEDRICH
MUSCL_FLOW= NO
TIME_DISCRE_FLOW= EULER_IMPLICIT

LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5

CONV_FIELD= ( RMS_MOMENTUM-X )
CONV_RESIDUAL_MINVAL= -2
CONV_STARTITER= 200

MESH_FILENAME= ram_c_refined.su2
MESH_FORMAT= SU2
CONV_FILENAME= history
VOLUME_FILENAME= flow
RESTART_FILENAME= restart
OUTPUT_WRT_FREQ= 200
OUTPUT_FILES= (RESTART, PARAVIEW)
"""
    return header + body


# ── Stage dir ────────────────────────────────────────────────────────────────

def stage_run_dir(candidate: Candidate, benchmark: Benchmark, *,
                  results_root: Path,
                  warm_start_dir: Path,
                  max_iters: int = DEFAULT_MAX_ITERS) -> tuple[Path, Path]:
    """Create stage dir, write cfg, symlink mesh + restart-as-solution.

    Returns (stage_dir, cfg_path).
    Mesh + restart are large (134 MB + 99 MB); we symlink rather than copy
    to keep disk pressure off the VM. The originals are read-only during
    a SU2 run, so symlinks are safe.
    """
    stage = results_root / f"rank_{candidate.rank:03d}_{benchmark.filename_tag}"
    stage.mkdir(parents=True, exist_ok=True)

    cfg_path = stage / "run.cfg"
    cfg_path.write_text(build_cfg(candidate, benchmark, max_iters=max_iters))

    # Copy the candidate's spec + score next to the cfg for the paper trail.
    if candidate.json_path.exists():
        shutil.copy2(candidate.json_path, stage / "mechanism.json")
    if candidate.yaml_path.exists():
        shutil.copy2(candidate.yaml_path, stage / "mechanism.yaml")
    if candidate.score_path.exists():
        shutil.copy2(candidate.score_path, stage / "score.json")

    mesh_src = warm_start_dir / "ram_c_refined.su2"
    restart_src = warm_start_dir / "restart.dat"
    mesh_dst = stage / "ram_c_refined.su2"
    sol_dst = stage / "solution.dat"

    # Use symlinks; remove existing so reruns don't trip on a stale link.
    for dst, src in [(mesh_dst, mesh_src), (sol_dst, restart_src)]:
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        if src.exists():
            dst.symlink_to(src)
        # If src doesn't exist (e.g. dry-run on Windows), skip silently —
        # cfg generation is the deliverable; live runs will fail-fast on
        # the missing file at submit time, which is the right behavior.

    return stage, cfg_path


# ── Process gate ─────────────────────────────────────────────────────────────

def check_no_su2_running() -> Optional[str]:
    """Return the offending pgrep line if any SU2_CFD is alive, else None.

    Filters out the pgrep command itself (matches its own command line).
    """
    try:
        r = subprocess.run(
            ["pgrep", "-fa", "SU2_CFD"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    for line in r.stdout.splitlines():
        if "pgrep" in line:
            continue
        if "SU2_CFD" in line:
            return line.strip()
    return None


# ── Job submission (live mode) ───────────────────────────────────────────────

def submit_blocking(stage_dir: Path, *,
                    su2_bin: str = DEFAULT_SU2_BIN,
                    ld_library_path: str = DEFAULT_LD_LIBRARY_PATH,
                    mpp_data_directory: str = DEFAULT_MPP_DATA_DIRECTORY,
                    n_ranks: int = DEFAULT_MPI_RANKS,
                    poll_interval_s: int = 60) -> tuple[bool, int, float]:
    """Run mpirun in foreground from `stage_dir`. Polls history.csv for
    progress. Returns (success, last_iter, runtime_seconds)."""
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = ld_library_path + ":" + env.get("LD_LIBRARY_PATH", "")
    env["MPP_DATA_DIRECTORY"] = mpp_data_directory

    log_path = stage_dir / "su2.log"
    cmd = ["mpirun", "-n", str(n_ranks), "--oversubscribe",
           su2_bin, "run.cfg"]

    t0 = time.monotonic()
    last_reported_iter = -1
    with log_path.open("w") as logf:
        proc = subprocess.Popen(
            cmd, cwd=str(stage_dir), env=env,
            stdout=logf, stderr=subprocess.STDOUT,
        )
        while proc.poll() is None:
            time.sleep(poll_interval_s)
            iters = _count_history_rows(stage_dir)
            if iters > last_reported_iter:
                elapsed = int(time.monotonic() - t0)
                print(f"[submit] {stage_dir.name}: iter={iters} elapsed={elapsed}s",
                      flush=True)
                last_reported_iter = iters
    runtime = time.monotonic() - t0
    success = (proc.returncode == 0)
    iters = _count_history_rows(stage_dir)
    return success, iters, runtime


def _count_history_rows(stage_dir: Path) -> int:
    h = stage_dir / "history.csv"
    if not h.exists():
        return 0
    try:
        with h.open() as f:
            return max(0, sum(1 for _ in f) - 1)   # subtract header row
    except Exception:
        return 0


# ── Score with validate_ram_c_nemo.py ────────────────────────────────────────

_NE_RE = re.compile(r"ne[_ ]predicted[_ ]m3?[:= ]+([\d.eE+\-]+)")
_ERR_RE = re.compile(r"log10[_ ]err[a-z_]*[:= ]+([+\-]?[\d.eE+\-]+)")


def score_with_validate_script(stage_dir: Path, *,
                               validate_script: Path = DEFAULT_VALIDATE_SCRIPT,
                               timeout_s: int = 600) -> dict:
    """Invoke validate_ram_c_nemo.py against flow.vtu, parse stdout."""
    flow_vtu = stage_dir / "flow.vtu"
    if not flow_vtu.exists():
        return {"status": "no_flow_vtu", "ne_m3": None, "log10_err": None,
                "raw_stdout": ""}
    try:
        r = subprocess.run(
            ["python3", str(validate_script), str(flow_vtu)],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"status": "score_timeout", "ne_m3": None, "log10_err": None,
                "raw_stdout": ""}
    out = r.stdout
    ne_m = _NE_RE.search(out)
    err_m = _ERR_RE.search(out)
    return {
        "status": "scored" if r.returncode == 0 else "score_error",
        "ne_m3": float(ne_m.group(1)) if ne_m else None,
        "log10_err": float(err_m.group(1)) if err_m else None,
        "raw_stdout": out[-2000:],
    }


# ── Validation result ────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    rank: int
    candidate_name: str
    air_n_su2: str
    n_species: int
    n_reactions: int
    surrogate_ne_m3: Optional[float]
    surrogate_log10_err: Optional[float]
    cfd_status: str
    cfd_iter_count: int
    cfd_runtime_seconds: float
    cfd_ne_m3: Optional[float]
    cfd_log10_err: Optional[float]
    cfg_path: Optional[str]
    stage_dir: Optional[str]
    notes: str = ""


# ── Top-level driver ─────────────────────────────────────────────────────────

def validate_top_k(*, search_dir: Path = DEFAULT_SEARCH_DIR,
                   top_k: int = 5,
                   benchmark: str = "ram_c_61km_M22.5",
                   results_root: Path = DEFAULT_RESULTS_ROOT,
                   warm_start_dir: Path = DEFAULT_WARM_START_DIR,
                   su2_bin: str = DEFAULT_SU2_BIN,
                   ld_library_path: str = DEFAULT_LD_LIBRARY_PATH,
                   mpp_data_directory: str = DEFAULT_MPP_DATA_DIRECTORY,
                   n_mpi_ranks: int = DEFAULT_MPI_RANKS,
                   max_iters: int = DEFAULT_MAX_ITERS,
                   validate_script: Path = DEFAULT_VALIDATE_SCRIPT,
                   dry_run: bool = True) -> list[ValidationResult]:
    """Sequentially CFD-validate top-K candidates against `benchmark`.

    Behaviour:
      dry_run=True  → emit cfg + stage dir per candidate; no mpirun.
      dry_run=False → pre-flight check, then submit one mpirun at a time,
                      blocking, scoring after each. Saves partial results
                      to `results_root/validation_progress_<benchmark>.json`
                      after every candidate so a crash mid-sweep doesn't
                      lose previous results.
    """
    bench = BENCHMARKS[benchmark]
    candidates = discover_top_k(search_dir, top_k=top_k)

    if not dry_run:
        running = check_no_su2_running()
        if running is not None:
            raise RuntimeError(
                "Refusing to launch validation: SU2_CFD already running on "
                f"this VM:\n  {running}\n"
                "Wait for that process to finish (or kill it deliberately) "
                "before invoking the harness in live mode."
            )

    results_root.mkdir(parents=True, exist_ok=True)
    progress_path = results_root / f"validation_progress_{bench.filename_tag}.json"

    results: list[ValidationResult] = []
    for cand in candidates:
        stage_dir, cfg_path = stage_run_dir(
            cand, bench,
            results_root=results_root,
            warm_start_dir=warm_start_dir,
            max_iters=max_iters,
        )

        if dry_run:
            results.append(ValidationResult(
                rank=cand.rank,
                candidate_name=cand.name,
                air_n_su2=cand.air_n_su2,
                n_species=len(cand.species),
                n_reactions=cand.n_reactions,
                surrogate_ne_m3=_surrogate_ne(cand, bench.name),
                surrogate_log10_err=_surrogate_log10_err(cand, bench.name),
                cfd_status="dry_run",
                cfd_iter_count=0,
                cfd_runtime_seconds=0.0,
                cfd_ne_m3=None,
                cfd_log10_err=None,
                cfg_path=str(cfg_path),
                stage_dir=str(stage_dir),
                notes="Dry-run: cfg + stage prepared, no mpirun submitted.",
            ))
            continue

        # Live launch — sequential, blocking.
        success, iters, runtime = submit_blocking(
            stage_dir,
            su2_bin=su2_bin, ld_library_path=ld_library_path,
            mpp_data_directory=mpp_data_directory,
            n_ranks=n_mpi_ranks,
        )
        score = score_with_validate_script(
            stage_dir, validate_script=validate_script,
        )
        results.append(ValidationResult(
            rank=cand.rank,
            candidate_name=cand.name,
            air_n_su2=cand.air_n_su2,
            n_species=len(cand.species),
            n_reactions=cand.n_reactions,
            surrogate_ne_m3=_surrogate_ne(cand, bench.name),
            surrogate_log10_err=_surrogate_log10_err(cand, bench.name),
            cfd_status=score["status"] if success else "cfd_error",
            cfd_iter_count=iters,
            cfd_runtime_seconds=runtime,
            cfd_ne_m3=score.get("ne_m3"),
            cfd_log10_err=score.get("log10_err"),
            cfg_path=str(cfg_path),
            stage_dir=str(stage_dir),
            notes=score.get("raw_stdout", "")[-200:],
        ))
        # Save partial after each candidate.
        progress_path.write_text(
            json.dumps([asdict(r) for r in results], indent=2)
        )

    # Final write covers the dry-run path too.
    progress_path.write_text(
        json.dumps([asdict(r) for r in results], indent=2)
    )
    return results


# ── CLI ──────────────────────────────────────────────────────────────────────

def _print_summary(results: list[ValidationResult], *, dry_run: bool) -> None:
    print()
    verb = "staged" if dry_run else "validated"
    print(f"=== {len(results)} candidates {verb} ===")
    print()
    for r in results:
        print(f"rank {r.rank:03d}  air-n={r.air_n_su2:6s}  "
              f"status={r.cfd_status:12s}  "
              f"species={r.n_species:2d}  rxns={r.n_reactions:2d}")
        print(f"   candidate:  {r.candidate_name}")
        if r.cfg_path:
            print(f"   cfg:        {r.cfg_path}")
        if r.stage_dir:
            print(f"   stage:      {r.stage_dir}")
        if r.surrogate_ne_m3 is not None:
            err_str = (f"{r.surrogate_log10_err:+.3f}"
                       if r.surrogate_log10_err is not None else "?")
            print(f"   surrogate:  ne={r.surrogate_ne_m3:.3e}  "
                  f"log10_err={err_str}")
        if r.cfd_ne_m3 is not None:
            err_str = (f"{r.cfd_log10_err:+.3f}"
                       if r.cfd_log10_err is not None else "?")
            print(f"   CFD:        ne={r.cfd_ne_m3:.3e}  "
                  f"log10_err={err_str}  iters={r.cfd_iter_count}  "
                  f"runtime={r.cfd_runtime_seconds:.0f}s")
        if r.notes:
            print(f"   notes:      {r.notes}")
        print()


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="S-5: CFD-validate top-K mechanism-search candidates.",
    )
    p.add_argument("--search-dir", type=Path, default=DEFAULT_SEARCH_DIR,
                   help=f"top_k/ output dir from search loop "
                        f"[default: {DEFAULT_SEARCH_DIR}]")
    p.add_argument("--top-k", type=int, default=5,
                   help="how many candidates to validate [default: 5]")
    p.add_argument("--benchmark", default="ram_c_61km_M22.5",
                   choices=sorted(BENCHMARKS.keys()))
    p.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT,
                   help=f"where to stage runs [default: {DEFAULT_RESULTS_ROOT}]")
    p.add_argument("--warm-start-dir", type=Path, default=DEFAULT_WARM_START_DIR,
                   help="directory containing ram_c_refined.su2 + restart.dat "
                        f"[default: {DEFAULT_WARM_START_DIR}]")
    p.add_argument("--n-mpi-ranks", type=int, default=DEFAULT_MPI_RANKS,
                   help=f"MPI rank count [default: {DEFAULT_MPI_RANKS}]")
    p.add_argument("--max-iters", type=int, default=DEFAULT_MAX_ITERS,
                   help=f"SU2 ITER cap [default: {DEFAULT_MAX_ITERS}]")
    p.add_argument("--dry-run", action="store_true",
                   help="Generate cfgs + stage dirs only; do not submit jobs.")
    args = p.parse_args(argv)

    results = validate_top_k(
        search_dir=args.search_dir,
        top_k=args.top_k,
        benchmark=args.benchmark,
        results_root=args.results_root,
        warm_start_dir=args.warm_start_dir,
        n_mpi_ranks=args.n_mpi_ranks,
        max_iters=args.max_iters,
        dry_run=args.dry_run,
    )
    _print_summary(results, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
