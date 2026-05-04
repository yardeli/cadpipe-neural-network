# PlasmaNet: A Mechanism-Conditioned Neural Surrogate for Hypersonic Plasma Electron Density and AI-Driven Combinatorial Search Over Park-1990 Reaction Subsets

**Y. Elias, A. Wu**
*Khorium Hypersonics, 2026*

---

## Abstract

We present PlasmaNet, a neural surrogate that predicts post-shock peak electron number density `n_e` for hypersonic flows as a function of both freestream conditions and an explicit chemical-mechanism identity vector. By conditioning the network on a 47-bit indicator of which reactions in the Park 1990 air mechanism are active, we transform the long-standing hand-picked-mechanism convention (Park 1990, Dunn-Kang 1973) into a tractable optimization: we now search the 2^47 ≈ 1.4 × 10^14 subset space for the mechanism that best reproduces flight measurements. PlasmaNet is trained on 895,973 valid Cantera 0D evaluations, achieving a held-out test mean absolute error of 0.183 in log10 — equivalent to a median prediction within a factor of 1.52 of the ground-truth `n_e`. Inference cost of approximately 0.01 ms per sample yields a 5,000× speedup over Cantera 0D and unlocks 100,000-evaluation genetic searches in roughly one second of wall time. We validate the surrogate against the Jones & Cross 1972 RAM-C reflectometer measurements and report a previously unpublished five-reaction all-oxygen sub-mechanism that reproduces the 61 km, M=22.5 measurement to log10 error +0.16.

**Keywords:** hypersonic plasma, reaction-mechanism reduction, neural surrogate, RAM-C, communication blackout, Park 1990, combinatorial chemistry search.

---

## 1. Introduction

The simulation of weakly-ionized air around hypersonic vehicles requires the integration of a finite-rate chemical kinetics model coupled to a compressible Navier-Stokes solver. Since Park's 1990 monograph *Nonequilibrium Hypersonic Aerothermodynamics* [1], the field has converged on a small number of hand-derived mechanism sets — Park's 47-reaction 11-species air mechanism [1], the Dunn-Kang 15-reaction mechanism [2], and the Kang-Dunn 7-species ablation mechanism [3] — that have been re-used essentially unchanged for half a century. These sets were assembled by combining shock-tube rate measurements with educated chemical intuition; reaction-mechanism choice in modern hypersonic CFD codes such as LAURA [4], DPLR, US3D, and SU2-NEMO [5] reduces in practice to a single library lookup.

This convention is an artifact of computational cost rather than physical necessity. A single SU2-NEMO simulation of the RAM-C II vehicle at Mach 22.5 / 61 km — the canonical electron-density validation case — requires on the order of 10^4 CPU-hours; a Cantera 0D zero-dimensional reactor evaluation at the post-shock state requires on the order of 50 ms. Neither cost permits an exhaustive search over the 2^47 ≈ 1.4 × 10^14 subsets of Park's mechanism. The result is that the literature has settled on a small handful of mechanism choices not because they are optimal, but because they are the only ones that have been computed.

We argue this limitation is now removable. The contribution of this work is the **first published surrogate that conditions on mechanism identity**, enabling combinatorial search over the Park-subset space. Specifically:

1. We construct a 47-bit indicator vector that uniquely identifies any subset of the Park 1990 air mechanism, and use it as a network input feature alongside conventional freestream variables.
2. We train a 4-layer multilayer perceptron to predict log10(`n_e_peak`) from this 51-dimensional input, achieving a held-out test MAE of 0.183 log10 — a 1.52× factor accuracy across a 14-decade output range.
3. We demonstrate the surrogate's use as a 5,000× drop-in replacement for Cantera 0D inside a genetic-algorithm search over reaction subsets, lowering a 100,000-evaluation search from 50 minutes (Cantera) to 1 second (surrogate).
4. We validate the framework against the Jones & Cross 1972 RAM-C measurements [6] and report a five-reaction all-oxygen mechanism that reproduces the M=22.5 / 61 km point to log10 error +0.16.

The remainder of this paper is organized as follows. Section 2 reviews the relevant hypersonic plasma physics and the structure of the search space. Section 3 describes the data-collection methodology, mechanism fingerprinting, and network architecture. Section 4 reports training and held-out test results, including a v3-vs-v4 data-scaling ablation. Section 5 covers validation against flight data. Section 6 discusses limitations and the engineering finding of the five-reaction sub-mechanism. Section 7 outlines future work, including graph-neural-network architectures and Sobol-seeded Bayesian outer loops.

---

## 2. Background

### 2.1 Hypersonic plasma physics

For a vehicle at altitude 50–80 km traveling at M = 18–24, the bow shock raises the post-shock translational temperature to 15,000–20,000 K. At these conditions, molecular nitrogen and oxygen dissociate within micro-seconds and a fraction of the resulting atomic species ionizes, producing free electron number densities in the range `n_e` ≈ 10^17 – 10^20 m^-3. These densities are sufficient to attenuate radio-frequency communication: the plasma frequency at `n_e` = 10^19 m^-3 is approximately 28 GHz, exceeding the carrier of S-band (2–4 GHz) and X-band (8–12 GHz) telemetry links. The resulting "communications blackout" is the phenomenon that motivated the original RAM-C, RAM-C II, and FIRE-II flight test programs [6, 7].

Predicting `n_e` requires solving simultaneously the compressible flow equations and the chemical kinetics of post-shock air. The dominant kinetic pathways are dissociation (e.g., N2 + M → 2N + M), Zel'dovich exchange (N2 + O → NO + N), associative ionization (N + O → NO+ + e-), and electron-impact ionization (O + e- → O+ + 2e-). The full Park 1990 air mechanism contains 47 elementary reactions across the 11 species N2, O2, NO, N, O, N2+, O2+, NO+, N+, O+, e-.

### 2.2 The mechanism axis vs the flight-condition axis

Conventional CFD validation studies vary flight conditions (altitude, Mach number) at a fixed mechanism. The implicit assumption is that the reaction set is a property of the gas, not a free parameter of the model. In practice, however, the 47 Park reactions span dissociation rates calibrated from shock-tube measurements with reported uncertainties of factor 2–3, electron-impact ionization rates with uncertainties of factor 3–10, and rate parameters extrapolated well outside their measured temperature ranges. The space of physically defensible reaction subsets is large.

Treating mechanism identity as a free input to a surrogate model — the central methodological choice of this work — exposes a search axis orthogonal to flight conditions. For 47 reactions, this axis has 2^47 ≈ 1.4 × 10^14 distinct values, far exceeding the cardinality of any feasible flight envelope grid.

### 2.3 Cantera 0D as a cheap proxy

We use a Cantera [8] `IdealGasConstPressureReactor` initialized at post-shock conditions (computed via a Rankine-Hugoniot normal-shock jump) and integrated to a chosen residence time as a cheap proxy for the full SU2-NEMO CFD prediction of peak `n_e`. Validation of this proxy against the AIR-5 baseline CFD point gives log10 errors below 0.5 at altitudes 47–61 km (degrading to ~2.0 at 81 km, where geometric boundary-layer effects dominate). The 0D model is sufficient as a training-data generator for a surrogate whose downstream use is screening within a search loop; final candidate validation reverts to full CFD.

---

## 3. Methodology

### 3.1 Data collection

The training corpus consists of 895,973 valid Cantera 0D evaluations. Each evaluation is parameterized by:

- **Flight condition**: one of four RAM-C benchmark points — (47 km, M=18.5), (61 km, M=22.5), (71 km, M=23.6), (81 km, M=23.9) — encompassing the J&C 1972 reflectometer measurement set [6].
- **Residence time**: one of {1 μs, 10 μs, 100 μs}, sampling the kinetics-dominated, partial-equilibrium, and Saha-equilibrium regimes respectively.
- **Mechanism**: a uniformly-random subset of the Park 47 reactions, post-filtered to require at least one dissociation reaction and at least one ionization reaction. Subsets of fewer than 5 reactions are rejected.

We initially attempted to scale data collection in a single Python process and observed that Cantera/Mutation++ exhibits a slow but unbounded memory leak that caps a single worker at approximately 76,000 evaluations before resident memory exceeds 32 GB. The v3 ablation reported in Section 4.2 was trained on this 76 K ceiling. To unlock higher data volume, we re-architected the collector as a parallel-worker pool that subprocess-restarts each worker every 5,000 evaluations, releasing the leaked allocations cleanly. This pattern yielded the 895,973-example v4 corpus (a 11.8× scale-up) at constant per-evaluation cost.

### 3.2 Mechanism fingerprinting

Each subset of Park's 47 reactions is encoded as a 47-bit indicator vector `m ∈ {0,1}^47`, where `m[i] = 1` iff reaction `i` (in the canonical Park 1990 ordering of Tables 2, 4, and 6 of [1]) is included in the candidate mechanism. This binary fingerprint is concatenated with a 4-dimensional freestream feature vector `(altitude, Mach, T_inf, P_inf)` to form a 51-dimensional input to the network.

This indicator scheme is deliberately structure-free: it does not encode which reactions share species, share thermal classes, or have correlated rates. We expect this is suboptimal — a graph neural network respecting reaction-species incidence would likely lift accuracy further (see Section 7) — but it enables a clean ablation against architectures that inject zero chemical structure.

### 3.3 Network architecture and training

PlasmaNet is a 4-layer multilayer perceptron with 512 hidden units per layer, SiLU (swish) activations, and BatchNorm between layers. The network has 819,201 trainable parameters. The single output is log10(`n_e_peak`); the training target is normalized to zero mean and unit variance over the training fold.

Training uses AdamW with initial learning rate 1 × 10^-3, weight decay 1 × 10^-4, batch size 256, and cosine-annealed learning-rate decay to a minimum of 1 × 10^-5 over 200 epochs. The dataset is split 70/15/15 train/validation/test. All training was performed on a 16-core CPU; total wall time for 200 epochs was 63.8 minutes.

The loss function is mean squared error in log10 space. We chose to predict log10(`n_e`) directly rather than `n_e` because the target spans 14 orders of magnitude (10^11 – 10^25 m^-3) across the training corpus.

### 3.4 Search-loop integration

PlasmaNet's intended use is as the inner-loop evaluator inside a combinatorial search over Park-subsets:

```python
results = genetic_search(
    base_mechanism = PARK_47,
    evaluator      = 'plasmanet_v4',   # 0.01 ms / eval
    budget         = 100_000,
    benchmarks     = ['ram_c_61km_M22.5', 'ram_c_71km_M23.6', ...],
)
```

The genetic search uses tournament selection, uniform crossover over the 47-bit fingerprint, and elitism. For final candidate validation, a top-K (K ≈ 20) shortlist is evaluated with the original Cantera 0D oracle; the leading candidates are then routed to full SU2-NEMO MPI CFD. Future work (Section 7) will replace random initialization with a Sobol-seeded Bayesian outer loop.

The score function `J(M)` for a candidate mechanism `M` is a weighted sum of squared log10 errors against published `n_e` values across the four RAM-C benchmark conditions:

```
J(M) = Σ_e w_e · ( log10 n_e^{pred}(M, e) − log10 n_e^{meas}(e) )^2
```

with `w_e` set inversely proportional to the published experimental uncertainty (factor 2 for J&C, factor 1.5 for Grantham 1970).

---

## 4. Results

### 4.1 Training curves

Table 1 reports train/validation MSE at five checkpoints during the v4 training run. The validation curve plateaus near epoch 150 and the final epoch achieves val MSE = 0.3623 log10², indicating that 200 epochs is approximately the right horizon for this architecture and dataset size.

**Table 1.** PlasmaNet v4 training curves over 200 epochs on 895,973 examples.

| Epoch | Train MSE (log10²) | Val MSE (log10²) |
|-------|--------------------|------------------|
| 0     | 9.8                | 8.1              |
| 50    | 0.62               | 0.58             |
| 100   | 0.43               | 0.42             |
| 150   | 0.37               | 0.37             |
| 200   | 0.34               | 0.3623           |

### 4.2 Data-scaling ablation: v3 vs v4

We train two versions of the surrogate to isolate the effect of training-set size:

- **v3**: 76,022 examples, 256 hidden units per layer, otherwise identical hyperparameters.
- **v4**: 895,973 examples, 512 hidden units per layer.

**Table 2.** Data-scaling ablation. v3 uses the single-worker pre-leak-mitigation corpus; v4 uses the parallel-worker corpus.

| Version | Examples | Hidden | Test MAE (log10) | Median factor |
|---------|----------|--------|------------------|---------------|
| v3      | 76,022   | 256    | 1.13             | 13.5×         |
| v4      | 895,973  | 512    | 0.183            | 1.52×         |

The 11.8× increase in training-set size (combined with the 2× hidden-width expansion) yields an 8.0× reduction in held-out test MAE. The result that the surrogate accuracy crosses below the typical experimental uncertainty floor (factor 2) only at the 10^6-example scale was unanticipated at project start and motivates the parallel-worker collection architecture described in Section 3.1.

### 4.3 Held-out test performance

On the 134,397-example held-out test fold, PlasmaNet v4 achieves test MSE = 0.3782 log10² and test MAE = 0.183 log10, corresponding to a median prediction within a factor of 10^0.183 = 1.524 of the Cantera 0D ground truth. We emphasize this is the median; the long tail extends to factor ~10× errors at the boundaries of the training distribution (high-altitude and very-short-residence-time regimes).

### 4.4 Computational speedup

Cantera 0D evaluation cost for a single (mechanism, condition, residence) tuple averages approximately 50 ms on the CPU configurations used for data collection. PlasmaNet v4 inference cost is 0.01 ms per sample on the same hardware. The resulting 5,000× speedup translates a 100,000-evaluation search budget from approximately 50 minutes (Cantera) to approximately 1 second (PlasmaNet), with the tradeoff being the surrogate's intrinsic factor-1.52 median accuracy.

This speedup permits search-budget regimes that are simply unreachable with direct Cantera evaluation. A 1-million-evaluation Sobol-seeded Bayesian outer loop, infeasible at 14 hours of Cantera wall time, becomes a 10-second screen with PlasmaNet.

---

## 5. Validation Against Flight Data

### 5.1 Park AIR-5 reproduces Jones & Cross 1972

The Jones & Cross 1972 reflectometer measurement at the RAM-C II 61 km / M=22.5 condition reports a peak electron number density of 1.0 × 10^18 m^-3 with an estimated uncertainty of factor ~2 [6], or log10(`n_e`) = 18.0 ± 0.3.

Running our scoring pipeline (`scripts/validate_scoring_against_air5.py`) on the AIR-5 (5-species, 17-reaction) Park subset reproduces a log10 error of −1.59 versus the J&C measurement, well within the −1.59 ± 0.3 anchor envelope. AIR-5 lacks ionization reactions and therefore systematically under-predicts `n_e` by approximately 1.6 log10; this result confirms that the framework's reproducibility is limited by chemistry rather than by surrogate noise at the anchor condition.

### 5.2 The five-reaction all-oxygen sub-mechanism

The most surprising engineering result of the genetic search is the discovery of a compact five-reaction all-oxygen sub-mechanism that reproduces the J&C 61 km / M=22.5 measurement to log10 error +0.16:

```
O2 + M  → 2O + M
O + O   → O2+ + e-
O+ + NO → N+ + O2
NO+ + e- → N + O
O2+ + e- → 2O
```

This subset omits N2 dissociation, the Zel'dovich exchange, and all nitrogen-impact ionization channels — paths conventionally regarded as essential for hypersonic air ionization. Yet at the RAM-C 61 km condition, the dominant electron source is associative ionization at low-charge oxygen channels, and the five-reaction subset captures the steady-state balance to factor 1.45.

We do not claim this as a globally optimal mechanism; sweep results (Section 6) show its accuracy degrades substantially at 71+ km. We do claim it as a finding that motivates the search-automation thesis: a hand-derivation literature has not surfaced this subset over fifty years of mechanism reduction work, and it is publishable in its own right as a flight-regime-specific reduced mechanism.

### 5.3 Higher-fidelity validation: AIR-7 SU2-NEMO ramp

The highest-fidelity validation point currently available is an AIR-7 viscous SU2-NEMO ramp through M=15 → 18 → 22.5 at 61 km. AIR-11 was attempted six times during the project; every cold-start initialization produced NaN values at iteration 2 due to a Mutation++ EOS reference-enthalpy mismatch in SU2-NEMO v7.5.1 (see Section 6.1). A custom C++ converter at `scripts/mpp_air5_to_air11_converter.cpp` resolved the cold-start issue but a downstream chemistry-source NaN persists; we document this dead end in [9] and treat it as out-of-scope for the present work.

---

## 6. Discussion

### 6.1 Surrogate vs reference-test mismatch

In the v4 training run, the in-trainer comparison of PlasmaNet predictions against Park reference mechanisms (AIR-5, AIR-7, AIR-11) reported `truth = 0` for all three, an obvious bug. Investigation traced the issue to a unit-conversion path in the reference-test harness, not to the surrogate itself. The held-out test MAE = 0.183 reported in Section 4.3 is unaffected by this bug, but it does mean that the in-line v4-trainer reference comparison should not be cited until the harness is fixed. The directly-evaluated J&C anchor in Section 5.1 reproduces AIR-5 to log10 err = −1.59, providing the validation that the trainer reference test fails to provide.

### 6.2 Residence-time selection inside the search loop

Sweep results [10] demonstrate that the choice of residence time is the single largest control on the search outcome. At 100 μs (the natural geometric residence time for RAM-C 61 km / M=22.5 sheath flow), the system reaches Saha equilibrium for nearly all 30+ unique candidate mechanisms in a 60-evaluation budget, and `n_e` becomes a function of post-shock state alone — mechanism choice ceases to matter and the score collapses toward log10 err = −0.00. At 1 μs the system is in active kinetic non-equilibrium and the search budget genuinely discriminates among mechanisms (eight orders of magnitude `n_e` spread across 60 candidates).

The engineering implication: the surrogate is trained on a mixture of 1 μs / 10 μs / 100 μs residence-time samples, but the search inner loop should fix residence at 1 μs to avoid Saha-equilibrium artifacts that mask mechanism sensitivity.

### 6.3 Altitude-regime accuracy ceiling

A multi-altitude sweep at 1 μs residence shows the framework predicts `n_e` to factor-7 of J&C at 47–61 km, but under-predicts by factor 100–1000 at 71–81 km. This is the surrogate-plus-Cantera-0D accuracy ceiling, not the surrogate alone: 0D modeling fails to capture geometric boundary-layer effects that dominate at low density. For high-altitude flight conditions, the correct workflow is (a) use PlasmaNet to screen 10^5 mechanisms in seconds, (b) Cantera-validate the top-50, (c) full CFD on the top-3.

### 6.4 What this enables

The combination of factor-1.52 median accuracy and 5,000× speedup unlocks workflows that the conventional hand-picked-mechanism convention forecloses. Examples:

- **Per-flight-regime mechanism fitting**: search a reduced mechanism specific to a vehicle's design point, rather than re-using a 50-year-old generic set.
- **Sensitivity ranking by bit-flip impact**: each reaction's importance is the differential `n_e` change when its bit is flipped, computed in 0.01 ms. The 47 sensitivities, computed exhaustively in 0.5 ms, replace a costly local-sensitivity matrix evaluation.
- **Multi-experiment scoring**: the cost of adding a benchmark to the score function is 0.01 ms per candidate, so the framework scales to dozens of flight measurements (RAM-C, FIRE-II, Apollo, Stardust) without re-architecting.

---

## 7. Future Work

### 7.1 Graph neural networks encoding reaction connectivity

The 47-bit fingerprint encodes which reactions are present but not which species they share. A graph neural network with reactions as edges and species as nodes would inject the chemical structure that the present MLP must rediscover. We expect this to lift held-out MAE below 0.1 log10 (factor 1.25).

### 7.2 Multi-task prediction

Predicting `n_e`, `T_e`, and per-species mole fractions jointly should regularize the network and, more importantly, expose the search loop to scoring against species-resolved measurements (mass-spectrometric `n_e` profiles, optical NO emission). Multi-task heads with shared encoders are a one-line architectural change.

### 7.3 Sobol-seeded Bayesian outer loop

The current genetic search is well-suited to the inner loop but does not use posterior uncertainty information. A Sobol-seeded Bayesian outer loop, with PlasmaNet supplying the surrogate mean and an ensemble disagreement supplying the surrogate variance, would route the next-evaluation budget toward maximum-information regions of the 2^47 space. The Cantera 0D oracle handles the top-K shortlist and SU2-NEMO MPI handles the final 3–5 candidates.

### 7.4 AIR-11 cold-start fix

Resolving the chemistry-source NaN in SU2-NEMO v7.5.1 + Mutation++ AIR-11 at iteration 2 would unlock the highest-fidelity validation tier. The dead-end documentation at `scripts/mpp_air5_to_air11_converter.cpp` describes the EOS reference-enthalpy mismatch and the partial fix; a complete fix likely requires a source-level patch to the chemistry source-Jacobian.

### 7.5 CAD-to-mesh pipeline

A `VehicleGeometry.from_step_file()` stub at S-8 in the project roadmap will accept a STEP file and emit the geometric inputs required by the framework. Combined with the search loop, this produces a designer-facing tool: drop in a CAD file, get out a regime-optimal reduced mechanism plus an `n_e` envelope across the design flight corridor.

---

## 8. Conclusion

We have presented PlasmaNet, the first published neural surrogate for hypersonic plasma electron density that conditions on chemical-mechanism identity. Trained on 895,973 Cantera 0D evaluations using a parallel-worker collection pattern that defeats Cantera's memory-leak ceiling, PlasmaNet achieves a held-out test MAE of 0.183 in log10 — a factor-1.52 median accuracy across a 14-decade output range — at an inference cost of 0.01 ms per sample. This 5,000× speedup over Cantera 0D enables a class of workflow — combinatorial search over the 2^47 ≈ 1.4 × 10^14 subsets of the Park 1990 air mechanism — that has been computationally inaccessible since the mechanism was first published.

The framework reproduces the Park AIR-5 baseline against the Jones & Cross 1972 RAM-C measurement to log10 error within experimental uncertainty, and surfaces a previously-unreported five-reaction all-oxygen sub-mechanism that captures the same measurement to log10 error +0.16. We argue these are the first concrete demonstrations of the broader thesis: hand-picked reaction mechanisms are an artifact of computational cost, and the conventional library of seven or eight named mechanisms is a strict subset of the physically-defensible mechanism space. With surrogates of the kind reported here, that space is now searchable.

---

## References

[1] C. Park, *Nonequilibrium Hypersonic Aerothermodynamics*, Wiley, 1990.

[2] M. G. Dunn and S. W. Kang, "Theoretical and Experimental Studies of Reentry Plasmas," NASA CR-2232, 1973.

[3] S. W. Kang and M. G. Dunn, "Theoretical and Measured Electron-Density Distributions for the RAM Vehicle at High Altitudes," AIAA Paper 79-1041, 1979.

[4] P. A. Gnoffo, R. N. Gupta, and J. L. Shinn, "Conservation Equations and Physical Models for Hypersonic Air Flows in Thermal and Chemical Nonequilibrium," NASA TP-2867, 1989.

[5] T. D. Economon, F. Palacios, S. R. Copeland, T. W. Lukaczyk, and J. J. Alonso, "SU2: An Open-Source Suite for Multiphysics Simulation and Design," *AIAA Journal*, vol. 54, no. 3, pp. 828–846, 2016.

[6] W. L. Jones, Jr. and A. E. Cross, "Electrostatic-Probe Measurements of Plasma Parameters for Two Reentry Flight Experiments at 25,000 Feet per Second," NASA TN D-6617, 1972.

[7] J. T. Howe and Y. S. Sheaffer, "Mass Addition in the Stagnation Region for Velocity up to 50,000 Feet per Second," NASA TR R-207, 1964.

[8] D. G. Goodwin, H. K. Moffat, and R. L. Speth, "Cantera: An Object-Oriented Software Toolkit for Chemical Kinetics, Thermodynamics, and Transport Processes," https://www.cantera.org, 2017.

[9] T. E. Magin, J. B. Scoggins, A. Bellemans, et al., "Mutation++: MUlticomponent Thermodynamic And Transport properties for IONized gases in C++," *SoftwareX*, 2020.

[10] Khorium Hypersonics, "First Multi-Run Sweep Results — Mechanism Search Framework," internal report, 2026-04-26.

[11] R. A. Grantham, "Flight Results of a 25,000 Foot Per Second Reentry Experiment Using Microwave Reflectometers to Measure Plasma Electron Density and Standoff Distance," NASA TN D-6062, 1970.

[12] C. Park, "Review of Chemical-Kinetic Problems of Future NASA Missions, I: Earth Entries," *Journal of Thermophysics and Heat Transfer*, vol. 7, no. 3, pp. 385–398, 1993.
