# PlasmaNet — Neural Surrogate for Hypersonic Plasma Prediction

**Repo**: github.com/yardeli/cadpipe-neural-network
**Last updated**: April 23, 2026
**Status**: Active development — clean retrain in progress, CFD batch running on GCP

---

## What This Project Does

Predicts whether radar can detect a hypersonic vehicle (Mach 5+) by computing the electron density of the plasma sheath around the vehicle. If plasma frequency > radar frequency → vehicle is invisible (BLACKOUT).

**Input**: Mach number, altitude, vehicle nose radius
**Output**: stagnation temperature, electron density, plasma frequency, species composition, detection status

## Current State (Honest)

| What | Status | Evidence |
|------|--------|---------|
| Stagnation-point equilibrium prediction | Working, validated | Cantera equilibrium is exact. 0.32 orders ne MAE on clean data |
| Detection classification (BLACKOUT/DETECT) | 97% accuracy | Tested against Cantera at 18 conditions |
| Geometry generalization | NOT working | Trained on one shape. CFD batch running to fix this (24/40 cases done) |
| Non-equilibrium correction | REMOVED from training | Was a dirty curve fit. Clean model trains on pure equilibrium only |
| Condition-adaptive mechanism map | DONE (transient DRGEP) | N2 dissociation is bottleneck. Peak complexity at Mach 15 (6 reactions) |
| Reaction search (pyMARS/DRGEP) | Custom DRGEP working | pyMARS broken on Cantera 3.x. Our implementation validated on transient reactor |

## Architecture

```
plasmanet/
├── physics.py              # Standalone physics (no external deps at inference)
│   ├── standard_atmosphere()   US Std Atm 1976
│   ├── stagnation_temperature_real()  Cantera enthalpy inversion
│   ├── janaf_equilibrium()     JANAF dissociation (Cantera fallback)
│   ├── saha_ionization()       NIST partition functions, 20-iter convergence
│   ├── plasma_frequency_ghz()  Exact formula
│   └── radar_status()          BLACKOUT/ATTENUATED/DETECTABLE
│
├── model.py                # PlasmaNet v1 (4 inputs: Mach, alt, nose_R, log10_p)
│   ├── PlasmaNet class         5-layer FC, SiLU, BatchNorm, dropout
│   ├── prepare_data()          Load NPZ, normalize, split
│   ├── train_model()           AdamW, cosine anneal, weighted loss, early stopping
│   ├── evaluate_model()        MAE, relative error, status accuracy
│   ├── save/load_checkpoint()  Stores architecture + normalization + metrics
│   └── main()                  CLI training entry point
│
├── model_v2.py             # PlasmaNet v2 (6 inputs: adds cone_angle, body_length)
│   ├── PlasmaNetV2 class       Same architecture, 2 more input dims
│   ├── prepare_cfd_data()      Handles geometry columns from CFD data
│   └── merge_equilibrium_and_cfd_data()  Combines data sources
│
├── generate_data.py        # Training data from Cantera equilibrium
│   ├── latin_hypercube()       LHS sampling
│   ├── generate_dataset()      Cantera 11-species at each point
│   └── main()                  CLI: --n-points, --output, --seed
│
├── generate_geometries.py  # Parametric vehicle shapes for CFD
│   ├── generate_sphere_cone()  CadQuery sphere-cone body
│   ├── create_flow_domain()    Boolean subtract body from sphere
│   ├── mesh_domain()           Gmsh tet mesh with body/farfield tags
│   └── generate_su2_config()   SU2 Euler config for each condition
│
├── extract_cfd_results.py  # Process SU2 VTU output → training data
│   ├── read_vtu_fields()       meshio reader for binary VTU
│   ├── find_stagnation_point() Max pressure point
│   ├── sample_body_surface()   Top 5% pressure points
│   ├── cantera_postprocess()   Chemistry at each (T,p) point
│   └── process_all_results()   Batch process → NPZ for training
│
├── serve.py                # FastAPI inference server
│   ├── GET/POST /predict       Single condition
│   ├── POST /predict_batch     1000+ conditions
│   ├── POST /predict_envelope  Mach x altitude grid
│   └── POST /uncertainty       MC dropout uncertainty
│
├── active_learning.py      # Uncertainty-guided data acquisition
├── train_loop.py           # Continuous training loop
├── run_cfd_batch.py        # GCP VM automation for SU2 runs
│
├── demo.py                 # Self-contained SBIR demo (browser UI)
└── Dockerfile              # CPU-only image for SimOps deployment

data/
├── training_clean_5k.npz       # CURRENT clean training data (no NEQ correction)
├── training_clean_15k.npz      # GENERATING: larger clean dataset
├── drgep_complete_map.json     # Condition-adaptive mechanism map (2000-20000K)
├── drgep_transient_results.json # Earlier DRGEP results
└── cfd_cases/                  # 5 geometries, 40 SU2 configs, meshes
    ├── manifest.json
    ├── sharp_narrow/           # R=0.02m, 7deg cone
    ├── medium_cone/            # R=0.05m, 12deg
    ├── blunt_cone/             # R=0.08m, 15deg (baseline)
    ├── blunt_wide/             # R=0.15m, 20deg
    └── capsule/                # R=0.30m, 30deg

checkpoints/
├── plasmanet_clean_v1.pt       # CURRENT: clean model (no NEQ in training)
├── plasmanet_best.pt           # OLD: best model from dirty training (has NEQ baked in)
├── plasmanet_v1-v6.pt          # OLD: various architecture experiments
└── training_log.json           # Historical training metrics

tests/
├── test_physics.py             # 10 physics validation tests (all passing)
└── test_e2e.py                 # End-to-end model vs Cantera comparison
```

## Key Physics References

| Constant/Data | Value | Source |
|--------------|-------|--------|
| NO ionization energy | 9.2642 eV | NIST Atomic Spectra Database |
| O ionization energy | 13.618 eV | NIST |
| N ionization energy | 14.534 eV | NIST |
| StarLink radar freq | 12 GHz (Ku-band) | Specification |
| Blackout threshold | ne > 1.78e18 m^-3 | When fp > 12 GHz |
| Mechanism | Park (1993) + Gupta (1990) | 11 species, 13 reactions |
| Atmosphere model | US Standard 1976 | 5 regimes, 0-60 km |
| Partition functions | NIST ASD | NO: 174K spin-orbit, O: 228K fine structure |

## DRGEP Chemistry Findings (Validated)

Transient 0D Cantera reactor analysis. These are the reactions that matter during the approach to equilibrium, NOT at equilibrium (where all net rates = 0).

| T (K) | Mach | Essential Reactions | Regime |
|--------|------|-------------------|--------|
| <3000 | <8 | None | Too cold |
| 3000-4000 | 8-9 | R1(O2 dissoc), R2(N2 dissoc), R3(NO dissoc), R13(e-impact N) | Dissociation onset |
| 4000-6000 | 9-11 | R1, R2, R3, R4(Zeldovich exchange) | Full dissociation |
| 7000-8000 | 12-13 | R1, R2, R3 | Dissociation dominant |
| 10000 | 15 | R1, R2, R3, R5, R12(e-impact O), R13(e-impact N) | PEAK: 6 reactions |
| 12000 | 17 | R2, R3, R5, R12, R13 | High ionization |
| 15000-20000 | 20-25 | R2, R3, R5 | Full ionization |

**Key finding**: N2 dissociation (R2) dominates 17-95% of chemical activity across all temperatures. Peak mechanism complexity at Mach 15 (10000K) where 6 reactions are needed.

## Methodology Corrections Made

These are mistakes we caught and fixed. An auditor should verify the fixes are complete.

| Original Claim | Why It Was Wrong | Correction |
|---------------|-----------------|-----------|
| "R06 dominates 90% of ionization" | Leave-one-out search measured pathway existence, not rate importance. At equilibrium, removing the only pathway to NO+ trivially zeros ne. | Transient DRGEP shows R2 (N2 dissoc) is the bottleneck, not R06 |
| "DRGEP shows R12/R13 dominate" | Applied DRGEP to equilibrium where all net rates = 0 (detailed balance). Was measuring numerical noise. | Rerun on transient 0D reactor where rates are real |
| "325 → 2 reactions" | GRI-Mech equilibrium analysis. Same problem — equilibrium can't rank reactions. | Need finite-rate data (Eilmer) for GRI-Mech reduction |
| "500,000x speedup" | Batch-mode theoretical. Measured single-call is 36x vs Cantera. | Use honest 36x number |
| "Geometry-aware" | Nose radius input was cosmetic — training data didn't vary with geometry. | Clean retrain removes this claim. CFD data will make it real. |
| "NEQ correction is validated" | Calibrated for one geometry (80mm blunt cone) against RAM-C. Never validated for other shapes. | Removed from training data. Applied only at inference, flagged as approximate. |

## How to Verify the Work

1. **Physics tests**: `python tests/test_physics.py` — all 10 should pass
2. **E2E tests**: `python tests/test_e2e.py` — model vs Cantera comparison
3. **DRGEP validation**: `data/drgep_complete_map.json` — check that R2 dominates
4. **CFD extraction**: `python -m plasmanet.extract_cfd_results` on downloaded VTU files
5. **Clean training data**: verify `data/training_clean_*.npz` has no NEQ correction (ne values should be raw Cantera equilibrium)

## Related Documents

| Document | Location | Contents |
|----------|----------|----------|
| Notion Project Overview | Desktop/Khorium Hypersonics/Notion_Project_Overview.md | Full project scope, all tools, honest status |
| Chemistry Findings | Desktop/Khorium Hypersonics/Hypersonic_Chemistry_Initial_Findings.docx | Why "90% R06" was wrong, methodology correction |
| Engineers Overview | Desktop/Khorium Hypersonics/Hypersonic_Overview_For_Engineers_Updated.docx | Technical overview with corrected findings |
| SimOps Integration | Desktop/Khorium Hypersonics/PlasmaNet_SimOps_Integration_Document.md | Architecture, API, database, deployment plan |
| Aaron's Master Plan 2 | Desktop/Aarons_Master_Plan_2.md | How PlasmaNet enables the original vision |
| Paper Draft | Desktop/Khorium Hypersonics/Paper_Draft_PlasmaNet.md | AIAA submission (needs update with corrections) |
| Original research docs | Desktop/Khorium Hypersonics/Hypersonic_AI_Chemistry_Results.md | Aaron's original findings and vision |

## Companion Repo

**cadpipe** (github.com/yardeli/cadpipe) contains:
- `agents/hypersonic_cfd_agent.py` — original plasma physics implementation
- `agents/reaction_search.py` — reaction sensitivity analysis (fixed to modulate chemistry)
- `mechanisms/air_plasma_11s.yaml` — 11-species Cantera mechanism
- `cadpipe/web/app.py` — server with PlasmaNet integration at `/api/plasma-full-analysis`
- `cadpipe/web/templates/plasma.html` — browser UI

## Running

```bash
# Tests
python tests/test_physics.py
python tests/test_e2e.py

# Generate clean training data
python -m plasmanet.generate_data --n-points 5000 --output data/training_clean.npz

# Train
python -m plasmanet.model --data data/training_clean_5k.npz --output checkpoints/plasmanet_clean.pt

# Serve
python -m plasmanet.serve --model checkpoints/plasmanet_clean_v1.pt --port 8100

# Demo (opens browser)
python demo.py

# Generate geometries for CFD
python -m plasmanet.generate_geometries

# Run CFD batch on GCP
python -m plasmanet.run_cfd_batch --manifest data/cfd_cases/manifest.json

# Extract CFD results
python -m plasmanet.extract_cfd_results --results data/cfd_results
```
