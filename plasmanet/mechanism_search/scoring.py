"""S-6 — Scoring framework for mechanism candidates.

A mechanism candidate is scored against a panel of published flight measurements
(Jones & Cross 1972 RAM-C, Grantham 1970, etc.) by:
  1. Running the candidate through an evaluator (Cantera 0D, PlasmaNet, or full
     CFD).
  2. Extracting peak ne and dB-attenuation predictions at each benchmark
     condition.
  3. Comparing to the published values via composite log10 error + dB margin.

The composite score is a weighted sum across all benchmarks. Lower is better.
For the search loop (S-4) this is the objective function.

Usage:
    from plasmanet.mechanism_search.scoring import score_candidate, BENCHMARKS

    # From a CFD result file
    result = score_candidate(
        mechanism_name='Park_AIR7',
        evaluator='cfd',
        evaluator_input={'vtu_path': '/path/to/flow.vtu'},
        benchmark='ram_c_61km_M22.5',
    )
    print(result.composite_score)  # lower = better

    # From a Cantera 0D evaluator (S-2)
    result = score_candidate(
        mechanism_name='Park_subset_30rxn',
        evaluator='cantera_0d',
        evaluator_input={'mechanism': mech, 'condition': cond},
        benchmark='ram_c_61km_M22.5',
    )
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, Any


# ──────────────────────────────────────────────────────────────────────────────
# Published-data benchmark suite
# ──────────────────────────────────────────────────────────────────────────────
# Each benchmark is one flight condition with measured ne (peak in sheath)
# and detection status across radio bands. Built from Jones & Cross 1972
# (RAM-C II reflectometer) and Grantham 1970 (RAM-C earlier altitudes).
#
# More can be added: FIRE-II (NASA TR-R-348), Apollo CM (NASA TM-X-2348),
# Bjork 1969 RAM-C calorimeter probes.

@dataclass
class BenchmarkCondition:
    """One flight measurement we score predictions against."""
    name: str
    altitude_km: float
    mach: float
    velocity_ms: float
    pressure_pa: float        # freestream static
    temperature_k: float      # freestream
    # Measured peak ne in sheath (m^-3)
    ne_published_m3: float
    ne_lower_m3: float
    ne_upper_m3: float
    # Measured detection status by frequency
    detection_status_by_freq_hz: dict[float, str]   # e.g. {2.25e8: "BLACKOUT"}
    # Source citation
    source: str
    # Confidence weight in the composite score
    weight: float = 1.0


BENCHMARKS: dict[str, BenchmarkCondition] = {
    "ram_c_61km_M22.5": BenchmarkCondition(
        name="ram_c_61km_M22.5",
        altitude_km=61.0,
        mach=22.5,
        velocity_ms=7300.0,    # approx. flight value
        pressure_pa=253.7116,
        temperature_k=242.65,
        ne_published_m3=2.0e19,
        ne_lower_m3=1.0e19,
        ne_upper_m3=4.0e19,
        detection_status_by_freq_hz={
            2.25e8: "BLACKOUT",   # VHF 225 MHz
            4.50e8: "BLACKOUT",   # VHF 450 MHz
            9.20e9: "BLACKOUT",   # X-band 9.2 GHz
        },
        source="Jones & Cross 1972 (NASA TN D-6617) — primary RAM-C anchor",
        weight=2.0,   # primary anchor: extra weight
    ),
    "ram_c_71km_M23.6": BenchmarkCondition(
        name="ram_c_71km_M23.6",
        altitude_km=71.0,
        mach=23.6,
        velocity_ms=7200.0,
        pressure_pa=58.5,
        temperature_k=216.65,
        ne_published_m3=1.0e19,
        ne_lower_m3=5.0e18,
        ne_upper_m3=2.0e19,
        detection_status_by_freq_hz={
            2.25e8: "BLACKOUT",
            4.50e8: "DEGRADED",
            9.20e9: "DEGRADED",
        },
        source="Jones & Cross 1972",
        weight=1.0,
    ),
    "ram_c_81km_M23.9": BenchmarkCondition(
        name="ram_c_81km_M23.9",
        altitude_km=81.0,
        mach=23.9,
        velocity_ms=7100.0,
        pressure_pa=10.1,
        temperature_k=210.65,
        ne_published_m3=2.0e18,
        ne_lower_m3=1.0e18,
        ne_upper_m3=3.5e18,
        detection_status_by_freq_hz={
            2.25e8: "DEGRADED",
            4.50e8: "DETECTABLE",
            9.20e9: "DETECTABLE",
        },
        source="Jones & Cross 1972",
        weight=1.0,
    ),
    "ram_c_47km_M18.5": BenchmarkCondition(
        name="ram_c_47km_M18.5",
        altitude_km=47.0,
        mach=18.5,
        velocity_ms=6400.0,
        pressure_pa=110.9,
        temperature_k=270.65,
        ne_published_m3=2.0e19,
        ne_lower_m3=1.5e19,
        ne_upper_m3=3.0e19,
        detection_status_by_freq_hz={
            2.25e8: "BLACKOUT",
            4.50e8: "BLACKOUT",
            9.20e9: "BLACKOUT",
        },
        source="Grantham 1970 (NASA TN D-6062)",
        weight=1.0,
    ),
}


# ──────────────────────────────────────────────────────────────────────────────
# Score result types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Score against ONE benchmark condition."""
    benchmark_name: str
    mechanism_name: str
    # Predicted values
    ne_predicted_m3: float
    db_predicted_by_freq_hz: dict[float, float] = field(default_factory=dict)
    # Errors
    log10_err_ne: float = 0.0           # log10(predicted / published); 0 = perfect
    db_margins_by_freq_hz: dict[float, float] = field(default_factory=dict)
    db_verdicts_by_freq_hz: dict[float, str] = field(default_factory=dict)
    # Composite score for this benchmark (lower = better)
    score: float = 0.0
    # Optional notes
    notes: str = ""


@dataclass
class ScoringResult:
    """Aggregated score across ALL benchmarks for one mechanism."""
    mechanism_name: str
    evaluator: str
    per_benchmark: list[BenchmarkResult] = field(default_factory=list)
    # Composite score is weighted sum of per-benchmark scores
    composite_score: float = 0.0
    verdict: str = ""    # EXCELLENT (<0.3) / GOOD (<0.7) / OK (<1.5) / POOR

    def to_dict(self) -> dict:
        return {
            "mechanism_name": self.mechanism_name,
            "evaluator": self.evaluator,
            "composite_score": self.composite_score,
            "verdict": self.verdict,
            "per_benchmark": [
                {
                    "benchmark": r.benchmark_name,
                    "ne_predicted_m3": r.ne_predicted_m3,
                    "log10_err_ne": r.log10_err_ne,
                    "db_predicted_by_freq_hz": r.db_predicted_by_freq_hz,
                    "db_margins_by_freq_hz": r.db_margins_by_freq_hz,
                    "db_verdicts_by_freq_hz": r.db_verdicts_by_freq_hz,
                    "score": r.score,
                }
                for r in self.per_benchmark
            ],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Scoring primitives
# ──────────────────────────────────────────────────────────────────────────────

def log10_err(predicted: float, published: float) -> float:
    """Log10 of ratio; 0 = perfect, sign-preserving for under/over prediction."""
    if predicted is None or predicted <= 0 or published <= 0:
        return float("nan")
    return math.log10(predicted / published)


def db_margin_to_published(predicted_db: float, published_status: str) -> tuple[float, str]:
    """Distance (dB) from the published status band; verdict tells you direction.

    Bands: DETECTABLE < 2 dB < DEGRADED < 20 dB < BLACKOUT
    Returns (margin, verdict) where:
      - verdict: 'CONSISTENT' (inside band, by margin), 'BORDERLINE'
        (within 1 dB of edge), 'INCONSISTENT' (outside band)
      - margin: signed; negative inside, positive outside
    """
    DET_MAX = 2.0
    DEG_MAX = 20.0
    if predicted_db != predicted_db:    # nan
        return (float("nan"), "n/a")

    if published_status == "DETECTABLE":
        # band [0, 2]
        margin = max(0, predicted_db - DET_MAX)
        if predicted_db <= DET_MAX:
            return (-(DET_MAX - predicted_db), "CONSISTENT")
        if predicted_db <= DET_MAX + 1:
            return (margin, "BORDERLINE")
        return (margin, "INCONSISTENT")
    elif published_status == "DEGRADED":
        # band [2, 20]
        if predicted_db < DET_MAX:
            return (DET_MAX - predicted_db, "INCONSISTENT")
        if predicted_db < DET_MAX + 1:
            return (DET_MAX - predicted_db, "BORDERLINE")
        if predicted_db <= DEG_MAX:
            return (-(DEG_MAX - predicted_db), "CONSISTENT")
        if predicted_db <= DEG_MAX + 1:
            return (predicted_db - DEG_MAX, "BORDERLINE")
        return (predicted_db - DEG_MAX, "INCONSISTENT")
    elif published_status == "BLACKOUT":
        # band [20, +inf]
        if predicted_db < DEG_MAX - 1:
            return (DEG_MAX - predicted_db, "INCONSISTENT")
        if predicted_db < DEG_MAX:
            return (DEG_MAX - predicted_db, "BORDERLINE")
        return (-(predicted_db - DEG_MAX), "CONSISTENT")
    return (0.0, "n/a")


def score_against_benchmark(
    mechanism_name: str,
    benchmark: BenchmarkCondition,
    ne_predicted_m3: float,
    db_predicted_by_freq_hz: Optional[dict[float, float]] = None,
) -> BenchmarkResult:
    """Score one prediction against one benchmark.

    The composite score for this benchmark is:
        |log10_err_ne| * 1.0 + sum(|db_margin| * 0.05) over each frequency

    Wait! Smaller |log10_err| AND smaller |db_margin| = better, so the
    weighted sum lower = better. dB-margin weight 0.05/dB so a 20-dB
    miss equals 1.0 in log10 ne err.
    """
    db_predicted_by_freq_hz = db_predicted_by_freq_hz or {}

    log10_err_ne_val = log10_err(ne_predicted_m3, benchmark.ne_published_m3)
    db_margins = {}
    db_verdicts = {}
    for f_hz, status in benchmark.detection_status_by_freq_hz.items():
        if f_hz in db_predicted_by_freq_hz:
            margin, verdict = db_margin_to_published(
                db_predicted_by_freq_hz[f_hz], status
            )
            db_margins[f_hz] = margin
            db_verdicts[f_hz] = verdict

    # Composite score: log10 ne error + verdict-based dB penalty.
    # Being "deep inside the right band" should NOT penalize (it's the
    # correct status). Only INCONSISTENT or BORDERLINE adds penalty.
    if log10_err_ne_val != log10_err_ne_val:
        score_val = float("inf")
    else:
        score_val = abs(log10_err_ne_val)
        for f_hz, verdict in db_verdicts.items():
            if verdict == "CONSISTENT":
                pass    # right band = no penalty
            elif verdict == "BORDERLINE":
                score_val += 0.3
            elif verdict == "INCONSISTENT":
                # 1.0 base + 0.05/dB how far past the correct band edge
                margin = db_margins.get(f_hz, 0.0)
                score_val += 1.0 + 0.05 * abs(margin)

    return BenchmarkResult(
        benchmark_name=benchmark.name,
        mechanism_name=mechanism_name,
        ne_predicted_m3=ne_predicted_m3,
        db_predicted_by_freq_hz=db_predicted_by_freq_hz,
        log10_err_ne=log10_err_ne_val,
        db_margins_by_freq_hz=db_margins,
        db_verdicts_by_freq_hz=db_verdicts,
        score=score_val,
    )


def aggregate_score(per_benchmark: list[BenchmarkResult]) -> ScoringResult:
    """Combine per-benchmark scores into a composite, weighted by confidence."""
    if not per_benchmark:
        return ScoringResult(mechanism_name="?", evaluator="?",
                              composite_score=float("inf"), verdict="POOR")

    total_w = 0.0
    total_score = 0.0
    for r in per_benchmark:
        bk = BENCHMARKS.get(r.benchmark_name)
        w = bk.weight if bk else 1.0
        if r.score != float("inf"):
            total_score += r.score * w
            total_w += w

    composite = total_score / total_w if total_w > 0 else float("inf")

    if composite < 0.3:
        verdict = "EXCELLENT"
    elif composite < 0.7:
        verdict = "GOOD"
    elif composite < 1.5:
        verdict = "OK"
    else:
        verdict = "POOR"

    return ScoringResult(
        mechanism_name=per_benchmark[0].mechanism_name,
        evaluator="aggregate",
        per_benchmark=per_benchmark,
        composite_score=composite,
        verdict=verdict,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Evaluator dispatch — call the right backend to get ne, dB
# ──────────────────────────────────────────────────────────────────────────────

EvaluatorFn = Callable[[Any, BenchmarkCondition], dict[str, Any]]
_EVALUATORS: dict[str, EvaluatorFn] = {}


def register_evaluator(name: str, fn: EvaluatorFn) -> None:
    """Register an evaluator backend.

    The function must accept (input_data, benchmark) and return a dict:
        {'ne_m3': float, 'db_by_freq_hz': dict[float, float]}
    """
    _EVALUATORS[name] = fn


def score_candidate(
    mechanism_name: str,
    evaluator: str,
    evaluator_input: Any,
    benchmark: str | list[str] = "all",
) -> ScoringResult:
    """Top-level scoring entry point.

    Args:
        mechanism_name: Identifier for the mechanism being evaluated.
        evaluator: Name of the registered evaluator backend.
        evaluator_input: Whatever the evaluator backend needs (vtu_path,
            mechanism object, etc.)
        benchmark: 'all' to score against every benchmark, a single name,
            or a list of names.
    """
    if evaluator not in _EVALUATORS:
        raise ValueError(
            f"Evaluator '{evaluator}' not registered. "
            f"Available: {list(_EVALUATORS.keys())}"
        )
    fn = _EVALUATORS[evaluator]

    if benchmark == "all":
        bk_names = list(BENCHMARKS.keys())
    elif isinstance(benchmark, str):
        bk_names = [benchmark]
    else:
        bk_names = list(benchmark)

    per_benchmark = []
    for bk_name in bk_names:
        bk = BENCHMARKS.get(bk_name)
        if bk is None:
            print(f"[scoring] WARNING: unknown benchmark '{bk_name}' — skip")
            continue
        prediction = fn(evaluator_input, bk)
        per_benchmark.append(score_against_benchmark(
            mechanism_name=mechanism_name,
            benchmark=bk,
            ne_predicted_m3=prediction.get("ne_m3", 0.0),
            db_predicted_by_freq_hz=prediction.get("db_by_freq_hz"),
        ))

    result = aggregate_score(per_benchmark)
    result.evaluator = evaluator
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Built-in evaluator: CFD VTU file → ne via existing extract_nemo_field
# ──────────────────────────────────────────────────────────────────────────────

def _cfd_vtu_evaluator(input_data: dict, benchmark: BenchmarkCondition) -> dict:
    """Evaluator that reads a SU2-NEMO VTU and returns ne + dB attenuation.

    Mirrors the sheath-peak logic of scripts/validate_ram_c_nemo.py:
      - ne is the MAX p99 over the 5 reflectometer stations (z/L ∈
        {0.14, 0.32, 0.48, 0.67, 0.88}) within the sheath shell
        (r_wall < r < r_wall + 0.3m). NOT the domain peak (which would
        be the stagnation point and is 100× higher than what J&C
        actually measured with body-mounted probes).
      - dB attenuation per frequency is the WORST aspect from a 7-angle
        scan (0..180 deg in xz plane).
    """
    import math
    import numpy as np
    from plasmanet.cfd_field import extract_nemo_field, build_unstructured_field

    vtu_path = input_data.get("vtu_path")
    if not vtu_path:
        return {"ne_m3": 0.0, "db_by_freq_hz": {}}

    cfd = extract_nemo_field(
        str(vtu_path), geometry="ram_c",
        mach=benchmark.mach, altitude_km=benchmark.altitude_km,
        verbose=False,
    )

    # ── Sheath peak ne (apples-to-apples with J&C reflectometer)
    RAM_C_BODY_LENGTH_M = 2.54
    RAM_C_NOSE_RADIUS_M = 0.1524
    RAM_C_HALF_ANGLE_DEG = 9.0
    STATION_ZL = [0.14, 0.32, 0.48, 0.67, 0.88]

    def body_radius_at_x(x: float) -> float:
        if x <= 0:
            return 0.0
        half = math.radians(RAM_C_HALF_ANGLE_DEG)
        R_n = RAM_C_NOSE_RADIUS_M
        x_tang = R_n * (1 - math.sin(half))
        if x <= x_tang:
            return math.sqrt(max(R_n * R_n - (R_n - x) ** 2, 0.0))
        r_tang = R_n * math.cos(half)
        return r_tang + (x - x_tang) * math.tan(half)

    sheath_peaks = []
    dz = 0.05
    sheath_thickness = 0.3
    for zL in STATION_ZL:
        z_target = zL * RAM_C_BODY_LENGTH_M
        r_wall = body_radius_at_x(z_target)
        ax_mask = np.abs(cfd.coordinates[:, 0] - z_target) < dz
        if ax_mask.sum() == 0:
            continue
        r = np.linalg.norm(cfd.coordinates[ax_mask, 1:3], axis=1)
        sheath_mask = (r >= r_wall) & (r <= r_wall + sheath_thickness)
        ne_slice = cfd.ne_m3[ax_mask][sheath_mask]
        if ne_slice.size > 0 and ne_slice.max() > 0:
            sheath_peaks.append(float(np.percentile(ne_slice, 99)))

    ne_peak = max(sheath_peaks) if sheath_peaks else 0.0

    # ── dB attenuation per frequency (worst aspect across angular scan)
    db_by_freq = {}
    try:
        from plasmanet.line_of_sight import scan_aspect
        field = build_unstructured_field(cfd)
        target = cfd.stag_point["xyz"]
        angles = np.array([0, 30, 60, 90, 120, 150, 180])
        for f_hz in benchmark.detection_status_by_freq_hz:
            results = scan_aspect(
                field, target_position=target,
                f_hz=f_hz, source_distance=10.0,
                angles_deg=angles, plane="xz",
                n_samples=2000, adaptive=True,
            )
            db_by_freq[f_hz] = float(max(r.attenuation_db for r in results))
    except Exception as exc:
        print(f"[scoring] LOS scan failed: {exc}")

    return {"ne_m3": ne_peak, "db_by_freq_hz": db_by_freq}


register_evaluator("cfd_vtu", _cfd_vtu_evaluator)


if __name__ == "__main__":
    # Smoke test — evaluate AIR-5 baseline against the primary benchmark
    print("Available benchmarks:")
    for name, bk in BENCHMARKS.items():
        print(f"  {name}: ne={bk.ne_published_m3:.2e} ± "
              f"[{bk.ne_lower_m3:.1e}, {bk.ne_upper_m3:.1e}] m^-3, "
              f"weight={bk.weight}")

    # Try scoring a fake prediction
    result = score_against_benchmark(
        mechanism_name="test_perfect_match",
        benchmark=BENCHMARKS["ram_c_61km_M22.5"],
        ne_predicted_m3=2.0e19,    # exact match to published
        db_predicted_by_freq_hz={2.25e8: 30.0, 4.50e8: 30.0, 9.20e9: 25.0},
    )
    print(f"\nPerfect prediction score:")
    print(f"  log10_err_ne = {result.log10_err_ne:+.3f}")
    print(f"  composite score = {result.score:.3f}")
    print(f"  dB verdicts: {result.db_verdicts_by_freq_hz}")
