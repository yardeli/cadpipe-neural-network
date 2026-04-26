# Plasmanet / Khorium Hypersonics — Session Checkpoint
**Date**: 2026-04-25 (late evening UTC)
**Author**: Claude Opus 4.7 (1M context)
**Purpose**: Hand-off to the next Claude instance picking up this work.

---

## 1. The full vision (Aaron Wu's pitch)

> "If we create a framework that allows the AI to try exhaust method on the
> chemistry reaction search, there is a way that we can do something that
> nobody has ever done before in human history."  — Aaron Wu, Slack
> (2026-04-25 ~14:18)

**Translation**: The deliverable is not "get one CFD run to log10 err = 0
on RAM-C." The deliverable is a **system that lets AI search through the
combinatorially-large space of chemistry mechanisms automatically against
multi-experiment ground truth** (J&C 1972 RAM-C, Grantham 1970, FIRE-II,
Apollo).

Existing literature picks mechanisms by hand (Park 1990, Dunn-Kang 1973,
Kang-Dunn 1979, etc.). Our contribution: **automate the search**. Park
1990's full mechanism has 47 reactions across 11 species → 2^47 ≈ 1.4×10¹⁴
subsets. No published work has automated a search over this space.

**What the framework does**:
1. Programmatically generates Cantera/SU2 cfgs for arbitrary reaction
   subsets of Park 47.
2. Evaluates each candidate cheaply via Cantera 0D + 1D corrections.
3. Trains a PlasmaNet surrogate on (mechanism, conditions) → ne field.
4. Searches via Bayesian optimization or genetic algorithm; top-K
   candidates get full SU2-NEMO MPI CFD validation.
5. Scores against published ne and dB attenuation across multiple
   flight conditions.

This is what every previous CFD validation, every dead end, every
working pipeline piece has been groundwork FOR. The current CFD
validation work is no longer the goal — it's training data for the
search system.

Read `docs/MECHANISM_SEARCH_FRAMEWORK.md` for the full architecture
sketch (just-written design doc with build order, search space size,
scoring function, etc.).

---

## 2. Where we are right now

### Running on the GCP VM (DO NOT DISTURB)
- **AIR-7 v7 inviscid ramp**: PID 197922 on `openfoam-hgv` (zone
  `us-central1-a`). Currently in M15 stage of M15 → M18 → M22.5 chain.
  ETA ~12 more hours. Output goes to
  `/home/yarden/ram_c_runs/ramC_refined_air7v7b_*_A61/`. This becomes
  data point #2 in the search space (AIR-5 baseline = data point #1).
- Memory headroom is tight (~12 GB free of 31 GB). Don't launch any
  large parallel SU2 jobs without first either killing v7 or upping VM
  size.

### Background pieces installed but idle on the VM
- `/opt/su2-nemo/` — original serial SU2-NEMO, AIR-5 + AIR-7 capable.
- `/opt/su2-nemo-mpi/` — MPI-enabled rebuild done by other Claude
  instance today. 10–15× speedup expected vs serial. Ready for any
  future inviscid AIR-5 / AIR-7 work.
- `/tmp/mpp_converter` — compiled C++ binary that emits AIR-11 ASCII
  restart with Mutation++-self-consistent (E, E_ve). Source at
  `scripts/mpp_air5_to_air11_converter.cpp`.
- Mutation++ headers + Eigen at `/tmp/mutationpp-src/` and
  `/tmp/SU2-build-mpi/subprojects/Mutationpp/`.

### Local repo state (`Desktop/Khorium Hypersonics/plasmanet/`)
- All recent commits pushed to `yardeli/cadpipe-neural-network` master
  (latest: `c527575` — S-2 thermo fix).
- `plasmanet/mechanism_search/` — newly created today, full module:
  - `generator.py` — Park 47 mechanism scaffolding (18/47 reactions
    filled; placeholders 19-47 are skipped in YAML emission). Now uses
    `thermo_data.py` for real NASA-9 polynomials in Cantera output.
  - `geometry.py` — `VehicleGeometry` abstraction (S-8 entry point for
    the drop-a-CAD-file pipeline). Predefined: RAM_C, APOLLO_CM,
    FIRE_II, GENERIC_HGV. body_radius_at_x() for sphere_cone, capsule,
    cylinder, wedge, custom.
  - `thermo_data.py` — Real NASA-9 polynomial coefficients for all 11
    AIR-11 species across 200K..1000K..6000K..20000K T ranges.
  - `scoring.py` — BenchmarkCondition + 4 RAM-C benchmarks + composite
    scoring. Anchor test passes (reproduces measured AIR-5 −1.59).
    Refactored to consume VehicleGeometry — no RAM-C hardcoding.
  - `cantera_evaluator.py` — Normal-shock + dissoc-extent correction
    + Cantera IdealGasConstPressureReactor + Appleton-Hartree dB.
    Cosmetic fixes for Cantera 3.2 (clone=False) and CVode-crash
    survival (flush=True + try/except around sim.advance).
  - `search_loop.py` — random_search() + genetic_search() + GA with
    tournament selection / uniform crossover / elitism. bayesian_search()
    stubbed.
  - `__init__.py` — full public API surface.
- `examples/custom_vehicle_example.py` — designer's-eye walkthrough of
  defining a custom vehicle without modifying framework code.
- `scripts/validate_scoring_against_air5.py` — anchor test that runs the
  AIR-5 baseline VTU through `score_candidate('cfd_vtu', ...)` and asserts
  log10 err matches our prior measurement.
- `scripts/mpp_air5_to_air11_converter.cpp` — Mutation++-aware C++ EOS
  converter (kept for AIR-11 dead-end documentation).

---

## 3. Critical path forward (what to do next)

### Status as of last check-in:

| Task | % | What's working |
|------|---|----------------|
| **S-1 Generator** | 50% | Reaction/Mechanism dataclasses, subset() filter, Cantera YAML emitter (with real NASA-9 thermo), SU2 cfg snippet emitter. Park 18/47 reactions filled. |
| **S-6 Scoring** | ✅ | Anchor test PASSES — reproduces measured AIR-5 log10 err = −1.588 vs −1.590 (diff 0.002). Refactored to use VehicleGeometry — no RAM-C hardcoding. |
| **S-2 Cantera 0D** | 65% | Pre-chemistry T/P works. **Real NASA-9 thermo wired today** — should let CVode integrate without NaN. VM retest needed. |
| **S-4 Search loop** | 60% | random_search + genetic_search scaffolded with elitism, tournament, uniform crossover. Blocked on S-2 working end-to-end. |
| **S-3 PlasmaNet retrain** | 0% | Pending — needs ~50-100 evaluations from S-2 as training data. |
| **S-5 CFD batch validator** | 0% | Pending — uses /opt/su2-nemo-mpi/ binary built today. |
| **S-7 Paper draft** | 0% | Pending. |
| **S-8 CAD → VehicleGeometry** | 5% | Stubbed (`VehicleGeometry.from_step_file()` raises NotImplementedError). Future-work entry point for designer drop-a-CAD-file pipeline. |

### Critical path:

```
S-1 (50%) ──→ S-6 (✅) ──→ S-2 (65% — VM retest needed)
                              ↓
                         S-4 (60%) ──→ S-3 (0%) ──→ S-5 (0%) ──→ S-7
                                                                   ↑
                                          S-8 (CAD pipeline) ──────┘
```

### Immediate next step
1. Other instance retests Cantera evaluator on VM with real NASA-9 thermo
   (commit c527575). If CVode integrates → AIR-7 surrogate produces finite ne.
2. Compare surrogate ne to AIR-5 CFD baseline (5.17e17 m⁻³) — must agree
   within 0.5 log10 to be trustworthy for search.
3. If surrogate validated → unblock S-4 with real evaluator → run first
   GA search across reaction subsets → find top-K candidates.
4. CFD-validate top-K via S-5 (using /opt/su2-nemo-mpi/ binary).

### Modularity & vehicle-class extension
The framework was refactored mid-session to remove all RAM-C hardcoding.
Designers add new vehicles by instantiating `VehicleGeometry` (or using
predefined APOLLO_CM_GEOMETRY, FIRE_II_GEOMETRY, GENERIC_HGV_GEOMETRY) and
attaching it to a `BenchmarkCondition`. See `examples/custom_vehicle_example.py`.
S-8 will eventually auto-extract this from STEP files.

Each S-task is a roadmap entry in `scripts/make_roadmap_xlsx.py` (look for
the "Search Framework" rows). Roadmap xlsx is regenerated by running that
script.

### The next concrete sub-tasks (in order of priority)

1. **Finish S-1: Park 47 reactions 19-47.**
   File: `plasmanet/mechanism_search/generator.py`. Look for
   `_add(i, "placeholder_rxn_..." for i in range(19, 48)`. Replace these
   with real Park 1990 reactions. Sources: Park 1990 *Nonequilibrium
   Hypersonic Aerothermodynamics* Tables 2 (dissociation), 4 (exchange),
   6 (ionization) — also cross-reference SU2-NEMO source at
   `/tmp/SU2-7.5.1/SU2_CFD/src/fluid/CSU2TCLib.cpp` lines around 2200–2600
   which encodes Park rates for AIR-7 already (extract and extend to AIR-11).
   Estimated time: 2-4 hours of careful mechanical work.

2. **Build S-6: scoring framework.**
   Refactor `scripts/validate_ram_c_nemo.py` into a Python module
   `plasmanet/mechanism_search/scoring.py` exposing:
   ```python
   def score(vtu_or_data, ground_truth_set='ram_c_61km_M22.5') -> dict:
       """Returns {'log10_err_ne': float, 'db_margin': float,
                   'composite_score': float, 'verdict': str}"""
   ```
   Composite is a weighted sum across all benchmarks. The old script's
   logic stays, just becomes a callable interface.

3. **Build S-2: Cantera 0D evaluator.**
   File: `plasmanet/mechanism_search/cantera_evaluator.py`. Takes a
   `Mechanism` object → writes Cantera YAML → runs `IdealGasReactor` at
   post-shock conditions (T=8000K, P=10 atm, freestream M=22.5 stagnation
   estimates) → integrates to steady state → returns species mass
   fractions including ne. ~1 day of work.

4. **Anchor the surrogate against existing CFD points.**
   Run S-2 on `park_air5()` mechanism, compare predicted ne to the AIR-5
   CFD baseline (data/nemo_test/ramC_refined_M22_5_A61_nemo.vtu). If
   the surrogate disagrees with CFD by more than 0.5 log10, the surrogate
   is broken — fix before proceeding.

---

## 4. Documented dead ends (don't re-attempt these)

The following paths were exhausted today; do NOT re-attempt without first
reading the rationale:

| Attempt | Conclusion | Documented in |
|---------|------------|----------------|
| AIR-11 + Mutation++ cold-start | NaN-frozen at iter 0 (electrons at machine zero) | `scripts/ram_c_refined_ramp_air11.sh` comments + commits 6b72f33, 65b105d |
| AIR-11 + Mutation++ warm-start (charge balance, species floor, smaller seed) | Still NaN-frozen — 89%+ cells flagged "non-physical" | commits 5cababc, ac73c94, fcb9bdd |
| AIR-11 + Mutation++ + Mutation++-self-consistent restart (EOS-aware) | Iter 0 starts cleanly (ne actually evolves) but iter 2 hits a SECOND chemistry-source NaN issue. AIR-11 has multiple compounding bugs in v7.5.1 — source patches required. | commit f393b1d + `scripts/mpp_air5_to_air11_converter.cpp` |
| AIR-7 + viscous + non-cat wall (NEMO_NAVIER_STOKES) | Patched validator (CConfig.cpp:6094-6095 to add AIR-7 to allowlist), built `/opt/su2-nemo-mpi-air7v/`. Heap corruption in NEMO_NS preprocessing for AIR-7 species. Patched binary deleted. | other-instance session log + roadmap F-13 |
| AIR-7 + CFL_ADAPT=YES with limit-cycle physics | Adapter dropped CFL toward floor 0.05 due to shock-wobble residual bouncing → 30-min/iter. Disable CFL_ADAPT for stiff chemistry runs. | commit ed89d0d |

**The big one to remember**: **CSU2TCLib (built-in NEMO) and Mutation++
have different formation-enthalpy reference points.** AIR-5 wrote E=+1.84e4
J/m³ for a freestream cell; the same physical state in Mutation++ AIR-11
conventions is E=−1.08e5 J/m³. Difference is ~127,000 J/m³ on a cell with
600 J/m³ thermal energy. The C++ converter at
`scripts/mpp_air5_to_air11_converter.cpp` documents and works around this.

---

## 5. Files of interest (with their roles)

### Search framework (NEW — phase S, just started this session)
- `docs/MECHANISM_SEARCH_FRAMEWORK.md` — Architecture sketch, build order
- `plasmanet/mechanism_search/__init__.py` — Module exports
- `plasmanet/mechanism_search/generator.py` — Park 47 mechanism
  scaffolding + subset generation. Read this first. 18/47 reactions
  filled.

### CFD pipeline + validation (working)
- `scripts/validate_ram_c_nemo.py` — Per-station ne extraction +
  J&C comparison + dB margin scoring. 500+ lines, well-tested.
- `scripts/compare_air5_vs_air7_ramc.py` — Side-by-side mechanism
  comparison report generator.
- `scripts/paraview_3d_diagnostic.py` — pyvista-based 3D figures
  (ne isosurface, slices, axial profile).
- `scripts/plot_air7_chemistry_dev.py` — pulls v7 history.csv from VM,
  plots residual evolution.
- `plasmanet/cfd_field.py` — `extract_nemo_field()` handles 5/7/11
  species automatically.
- `plasmanet/ram_c_validation.py` — published ground-truth values.

### Mechanism converters
- `scripts/mpp_air5_to_air11_converter.cpp` — C++ Mutation++-aware
  EOS converter. Build instructions in the file's comment block.
- `scripts/convert_air5_to_air7_restart.py` — AIR-5 → AIR-7 (works,
  used by current v7 ramp).
- `scripts/convert_air5_to_air11_restart.py` — AIR-5 → AIR-11 hardcoded
  (kept for reference; superseded by EOS-aware C++ version).
- `scripts/convert_air5_to_air11_eos_aware.py` — pure-Python EOS-aware
  variant using NASA-Park polynomials (~10% mismatch with Mutation++,
  documented).

### CFD launchers (status as of this session)
- `scripts/ram_c_refined_ramp_air7_v7.sh` — current AIR-7 inviscid
  cold-start (CFL=0.2 fixed, no CFL_ADAPT)
- `scripts/ram_c_air7_resume_from_m10.sh` — resume from M10 checkpoint
- `scripts/ram_c_air7_resume_from_m15.sh` — resume from M15 checkpoint
  (this is what's running now as PID 197922 v7b)
- `scripts/ram_c_refined_ramp_air7_v3_cold.sh` and v4/v5/v6 — all
  failed iterations; kept for the lessons-learned record.

### Dead-end documentation (kept for reference, don't re-run)
- `scripts/ram_c_refined_ramp_air11.sh` — AIR-11 attempts 1-6
- `scripts/ram_c_refined_ramp_air7.sh` — original AIR-7 attempt with
  wrong species ordering (set 0.77 mass fraction electrons)
- `scripts/ram_c_refined_ramp_air7_v2.sh` — AIR-7 warm-start that
  hung in BCGSTAB

### Roadmap + checkpoints
- `scripts/make_roadmap_xlsx.py` — Generates `ROADMAP_STATUS.xlsx`.
  Run this after editing tasks to update the spreadsheet.
- This file (`docs/CHECKPOINT_2026-04-25.md`)

### MEMORY.md auto-memory references (these are auto-loaded by Claude)
- `project_plasmanet.md` — High-level project overview
- `reference_su2_nemo_chemistry.md` — AIR-5/AIR-7/AIR-11 selection in v7.5.1
- `project_hypersonic_hgv.md` — Sister HGV project context
- `reference_gcloud_ssh_background.md` — How to run things on the VM
  without the SSH session blocking

---

## 6. The other Claude instance (parallel)

The other instance is operating on the cadpipe-frontend codebase and
also has VM access. Today it (a) built the MPI binary at
`/opt/su2-nemo-mpi/` and (b) attempted (and abandoned) AIR-7 viscous due
to source-level heap corruption.

Its working areas:
- `cadpipe-frontend` (CDK + React + Storybook + Chromatic)
- VM-side build/install/test work (no production CFD launches)

Constraint to respect: **do not have it launch large CFD jobs** without
first coordinating memory budget with the v7 ramp running.

---

## 7. Resume instructions for the next Claude

1. **Read these files in order**:
   - This checkpoint (`docs/CHECKPOINT_2026-04-25.md`)
   - `docs/MECHANISM_SEARCH_FRAMEWORK.md` (architecture)
   - `plasmanet/mechanism_search/generator.py` (current state of S-1)
   - `scripts/validate_ram_c_nemo.py` (you'll refactor this for S-6)
   - `scripts/make_roadmap_xlsx.py` (S-1..S-7 task entries)

2. **Confirm v7 ramp state** before starting:
   ```bash
   gcloud compute ssh openfoam-hgv --zone=us-central1-a --command="
     pgrep -fa SU2_CFD; tail -1 /home/yarden/ram_c_runs/ramC_refined_air7v7b_*_A61/history.csv
   "
   ```
   Don't disturb the running ramp.

3. **Pick up where this session ended**: critical path is S-1 → S-6 →
   S-2. The user wants Aaron's "AI-exhaustive search framework" delivered
   as a real research contribution. This is bigger than any single
   log10 number on RAM-C.

4. **When v7 finishes** (maybe ~12h after this checkpoint), run
   `scripts/compare_air5_vs_air7_ramc.py` to extract the comparison.
   Both AIR-5 and AIR-7 ne data become anchor data points for surrogate
   training.

5. **Babysit cadence**: 30-min intervals are the right balance. Use
   Monitor with the templates already in this session's log.

---

## 8. What the user needs to do (you, the human)

To make the next Claude instance load this checkpoint properly, paste the
following at the start of the new session:

```
Read C:\Users\yarden\Desktop\Khorium Hypersonics\plasmanet\docs\CHECKPOINT_2026-04-25.md
Then read docs/MECHANISM_SEARCH_FRAMEWORK.md and plasmanet/mechanism_search/generator.py.
This is the Khorium hypersonics chemistry-search project. Aaron Wu's vision is the
"AI-exhaustive mechanism search" framework documented in those files. We're
mid-build on phase S. Continue from S-1 (finish Park 47 reactions) → S-6
(scoring framework) → S-2 (Cantera 0D evaluator). v7 AIR-7 ramp is still
running on PID 197922 on the VM — do not disturb.
```

The auto-memory `MEMORY.md` is already loaded by Claude on session start, so
the project context is partially present. The checkpoint above fills in
session-specific state.

---

## 9. Open questions you may want to think about

- Is the "AI-exhaustive search framework" research contribution
  something you want to write up as a standalone paper, or fold into
  the existing PlasmaNet AIAA paper (P-4 in roadmap)?
- Do we have access to FIRE-II flight data (Bjork 1969, Sutton 1971)
  to extend the ground-truth set beyond RAM-C?
- After Park 47 is filled out, do you want to also include
  Dunn-Kang 1973 and Park 1993 update reactions? Each adds 5-15
  reactions to the search space.
- Is there a budget for a larger VM if we want to run S-5 (top-K CFD
  validation) at scale? Current 32 GB / 16 core box can do ~16
  validation runs/day with the MPI binary.

---

End of checkpoint. Good luck to the next Claude.
