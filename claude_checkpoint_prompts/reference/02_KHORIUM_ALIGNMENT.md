# Khorium architecture alignment + audit findings

**Purpose:** make plasmanet's repo structure match KhoriumBackend / KhoriumContext conventions exactly, so a Khorium engineer can drop the SU2-NEMO solver into `simops/` alongside CalculiX and OpenFOAM with zero translation overhead.

**Source-of-truth repos (read 2026-04-25):**
- `KhoriumAI/KhoriumBackend` — FastAPI backend, `src/simops/` is the solver-container pattern
- `KhoriumAI/KhoriumContext` — design docs (architecture-overview.md, api-contract.md, cdk-colocation.md, simulation-infra.md)
- `KhoriumAI/KhoriumFrontend` — React app with `src/{api,components,stores,hooks,routes}` layout

---

## 1. Khorium `simops/` pattern (reference architecture)

```
KhoriumBackend/src/simops/
├── AGENTS.md                ← per-dir agent instructions (concise, file-purpose table)
├── CLAUDE.md                ← per-dir Claude instructions
├── __init__.py
├── main.py                  ← Batch entrypoint: env vars → dispatch by SOLVER_TYPE
├── s3.py                    ← shared S3 helpers (download_case, upload_results, checkpoints)
├── calculix/                ← FEA solver
│   ├── __init__.py
│   ├── inp_writer.py        ← write the input deck
│   ├── runner.py            ← subprocess-execute ccx, collect outputs
│   └── result_parser.py     ← parse .dat/.frd into result_summary.json
└── openfoam/                ← CFD solver
    ├── AGENTS.md            ← solver-specific physics notes
    ├── __init__.py
    ├── case_writer.py       ← build case dir (0/, system/, constant/)
    ├── runner.py            ← run OpenFOAM solver, stream log
    └── result_parser.py     ← parse log into result_summary.json
```

### 1.1 Triadic per-solver pattern

Every solver subdirectory has the same three-file shape:

| File | Responsibility |
|---|---|
| `*_writer.py` (`inp_writer.py` / `case_writer.py`) | Translate typed sim_params → solver-native input files on disk |
| `runner.py` | Subprocess-run the solver, stream stdout to a log file, raise on nonzero exit |
| `result_parser.py` | Read solver output files → write `result_summary.json` for DB ingestion |

### 1.2 `main.py` dispatch contract

```python
# Reads env vars set by Batch containerOverrides:
JOB_ID, INPUT_S3_KEY, OUTPUT_S3_KEY, S3_BUCKET, SOLVER_TYPE,
SIM_PARAMS (JSON), AWS_BATCH_JOB_ATTEMPT

# Pipeline (every job, every solver):
1. download_case(bucket, input_key, case_dir)
2. (optional) build_sim_case(case_dir, params)        ← solver-specific
3. (retry path) _try_resume_checkpoint(...)            ← optional, OpenFOAM only today
4. <solver>_runner.run(case_dir, output_dir)
5. <solver>_result_parser.extract_*_summary(...) → result_summary.json
6. upload_results(bucket, output_key, output_dir)
7. upload_result_summary(bucket, output_key, output_dir)
```

### 1.3 S3 conventions (`simops/s3.py`)

- **Inputs**: `simulations/{jobId}/input.tar.gz` — case archive (mesh + params)
- **Outputs**: `simulations/{jobId}/output.tar.gz` — flat tar (no wrapping dir; ParaView opens `case.foam` directly)
- **Result summary**: `simulations/{jobId}/result_summary.json` — small JSON for DB ingestion
- **Checkpoints**: `simulations/{jobId}/checkpoints/{timeStep}/...` + `_latest.json` manifest
- All transfers via `shared.aws.s3_client()` (single source of credential + region config)

### 1.4 Typed parameters (`shared/sim_params.py`)

Pydantic models in `shared/sim_params.py` define the `SIM_PARAMS` env-var schema:

```python
SimType = Literal["cfd", "fea", "thermal"]
Solver  = Literal["openfoam", "calculix"]

class OpenFoamParams(BaseModel): ...
class CalculixParams(BaseModel): ...
```

Lists vs scalars are meaningful: `list[float]` marks a DOE sweep axis; scalar = single simulation. Validated at the study-config → simulation boundary.

### 1.5 Per-directory `AGENTS.md` + `CLAUDE.md`

Every meaningful subdirectory has both files, matching this style:
- **Concise** (2-3 paragraphs + file-purpose table)
- **Architecture diagram** of how files relate inside that dir
- **Env vars table** if relevant
- **Cross-link** to KhoriumContext design doc via relative path
- **Local commands** (test invocations, regression runs)

### 1.6 KhoriumContext as design hub

`KhoriumContext/designs/` holds the architectural source of truth:
- `architecture-overview.md`, `api-contract.md`, `auth.md`, `billing-and-usage.md`
- `cdk-colocation.md`, `chat-persistence.md`, `ci-cd-pipeline.md`
- `simulation-infra.md` (Batch design)

All other repos cross-reference these docs by relative path: `../../KhoriumContext/designs/X.md`.

### 1.7 Frontend conventions (`KhoriumFrontend/src/`)

```
src/
├── animations/         ← framer-motion variants
├── api/                ← typed API client; src/api/generated/ has openapi-typescript output
├── components/         ← reusable UI primitives
├── constants/          ← magic numbers, enums, lookup tables
├── content/            ← marketing copy, MDX
├── hooks/              ← custom React hooks
├── lib/                ← utility functions
├── main.tsx            ← React root
├── routeTree.gen.ts    ← Tanstack Router auto-generated
├── router.tsx          ← Router setup
├── routes/             ← file-based routes
├── stores/             ← Zustand stores; agentSetterMap.ts wires LLM-callable setters
├── stories/            ← Storybook stories (centralized, NOT alongside components)
├── test/               ← vitest setup + helpers
├── types/              ← shared TS types
├── utils/              ← misc utilities
└── workers/            ← web workers
```

Notable conventions:
- `api/generated/` — OpenAPI-generated TS client (regenerated from KhoriumBackend's `openapi.json`)
- `stores/agentSetterMap.ts` + `bridge.ts` — pattern for letting LLM agents call setters in Zustand stores
- `routeTree.gen.ts` — Tanstack Router generated artifact (gitignored in some setups, committed here)

---

## 2. Plasmanet current state vs Khorium target

| Convention | Khorium | Plasmanet (today) | Gap |
|---|---|---|---|
| Solver-triad layout | `simops/<solver>/{writer,runner,parser}.py` | flat `plasmanet/{cfd_field,nemo_config,run_cfd_batch}.py` | **HIGH** — needs `simops/su2_nemo/` subdir |
| `main.py` Batch entrypoint | `simops/main.py` reads env vars + dispatches | none — we have ad-hoc bash scripts on the VM | **HIGH** |
| `s3.py` shared helpers | `simops/s3.py` with `download_case`, `upload_results`, etc. | none — scripts use `gcloud scp` directly | **HIGH** |
| `shared/sim_params.py` typed Pydantic | exists, used by both solvers | `plasmanet/api_models.py` covers some, but not solver params | **MEDIUM** |
| `shared/aws.py` S3 client | single `s3_client()` factory | none | **MEDIUM** |
| `shared/logging.py` structlog setup | `configure_structlog()` at every entrypoint | print-based logging | **MEDIUM** |
| `shared/db.py` + `models/` | SQLAlchemy ORM (KhoriumBackend) | n/a — plasmanet doesn't own DB schema | None (intentional) |
| Per-dir `AGENTS.md` + `CLAUDE.md` | every subdir | only repo-root README | **MEDIUM** |
| `Dockerfile.simops-<solver>` per solver | `Dockerfile.simops-calculix`, `Dockerfile.simops-openfoam` | one root `Dockerfile` (placeholder for SU2-NEMO base) | **HIGH** |
| Frontend `src/api/generated/` | openapi-typescript output | hand-written types in `frontend/src/types/` | **MEDIUM** |
| Frontend `src/stores/` (Zustand + agent bridge) | `useStore.ts`, `agentSetterMap.ts` | none — App.tsx local state only | **LOW** (works for now) |
| Frontend `src/stories/` centralized | `src/stories/` | inline `__stories__/` dirs alongside components | **LOW** (cosmetic) |
| KhoriumContext design cross-links | `../../KhoriumContext/designs/X.md` | none | **MEDIUM** |
| Pre-commit + linting (`.pre-commit-config.yaml`) | yes | none | **LOW** |
| Alembic migrations | `alembic.ini` + `alembic/` | n/a (no DB) | None |
| Result-summary JSON contract | `RESULT_SUMMARY_FILENAME = "result_summary.json"` | none | **HIGH** |

---

## 3. Recommended restructure (plasmanet → Khorium-shaped)

### 3.1 Top-level: split `plasmanet/` into Khorium-style modules

```
plasmanet/                          ← thin wrapper, future-deprecated
├── ... (current modules stay)

src/                                ← NEW (matches KhoriumBackend layout)
├── shared/
│   ├── __init__.py
│   ├── AGENTS.md
│   ├── CLAUDE.md
│   ├── aws.py                      ← s3_client() factory (mirror KhoriumBackend)
│   ├── logging.py                  ← configure_structlog()
│   ├── sim_params.py               ← extend KhoriumBackend's SimType/Solver
│   │                                  with Solver = Literal["openfoam","calculix","su2_nemo"]
│   │                                  + class SU2NemoParams(BaseModel)
│   └── physics.py                  ← move plasmanet/physics.py here (foundational, not solver-specific)
├── simops/
│   ├── __init__.py
│   ├── AGENTS.md                   ← copy Khorium's, add SU2-NEMO bullet
│   ├── CLAUDE.md
│   ├── main.py                     ← Khorium-shaped entrypoint, dispatches by SOLVER_TYPE
│   │                                  including new "su2_nemo" branch
│   ├── s3.py                       ← copy Khorium's; add get_checkpoint_manifest() etc.
│   └── su2_nemo/
│       ├── __init__.py
│       ├── AGENTS.md               ← physics notes (FLUID_MODEL=SU2_NONEQ, AIR-5/AIR-11 choice)
│       ├── case_writer.py          ← extracted from current scripts/generate_ram_c.py +
│       │                              plasmanet/nemo_config.py (writes run.cfg + mesh)
│       ├── runner.py               ← subprocess SU2_CFD; streams log; iter-progress callback
│       └── result_parser.py        ← reads flow.vtu → result_summary.json
│                                      (peak ne, T_tr/T_ve stag, p_stag, log10 err vs J&C)
└── api/                            ← FUTURE — promote mock_server to Khorium-shaped routes
    └── plasma/
        ├── analyze.py
        ├── benchmark.py
        ├── report.py
        └── submit_cfd.py
```

### 3.2 Dockerfile per solver

Match `Dockerfile.simops-calculix` / `Dockerfile.simops-openfoam`:
```
Dockerfile.simops-su2nemo            ← base: SU2-NEMO + Mutation++ + AIR-5/AIR-11 mpp-data
                                       runtime CMD: python -m simops.main
                                       env: MPP_DATA_DIRECTORY, LD_LIBRARY_PATH preset
```

### 3.3 Per-directory docs

Add to every meaningful subdirectory:
- `AGENTS.md` — file-purpose table, dispatch flow, env-var reference
- `CLAUDE.md` — `@./AGENTS.md` (one-line transclude) OR Claude-specific extras

### 3.4 Result summary contract

`result_summary.json` (matches Khorium's per-solver schema):
```json
{
  "solver": "su2_nemo",
  "mach": 22.5,
  "altitude_km": 61.0,
  "stagnation": {"T_tr_K": 6064, "T_ve_K": 5911, "p_Pa": 2.31e5, "ne_m3": 5.64e20},
  "peak_sheath_ne": {"ne_m3": 2.41e20, "ne_m3_max": 6.46e20, "n_top_cells": 50},
  "validation": {
    "reference_source": "Jones & Cross 1972",
    "reference_ne_m3": 2.0e19,
    "log10_error": 1.08
  },
  "convergence": {"final_iter": 599, "final_rho0_residual": -2.90}
}
```

This is what KhoriumBackend's status Lambda will write to `simulations.result_summary` JSONB column.

### 3.5 Minimum-viable Khorium integration

When KhoriumBackend wants to add SU2-NEMO to its `simops/` container, the import chain becomes:

```python
# In KhoriumBackend src/simops/main.py — ONE-LINE addition:
from simops.su2_nemo import runner as su2_nemo_runner

if solver_type == "su2_nemo":
    sim_params = SU2NemoParams.model_validate(json.loads(sim_params_raw))
    su2_nemo_runner.run(case_dir, output_dir, sim_params)
```

That's it — provided plasmanet exposes the matching shape: `simops.su2_nemo.runner.run(case_dir, output_dir, params)`, with side effects: writes `result_summary.json` to `output_dir`.

---

## 4. Earlier code-structure audit findings (still open)

From the audit pass on 2026-04-25:

### 4.1 🔴 Already done (commit `bd69e20`)

- ✅ Deleted `plasmanet/extract_cfd_results.py` (343 lines, zero callers)
- ✅ Deleted `plasmanet/run_cfd_batch.py` (234 lines, zero callers)
- ✅ Moved `demo.py` + `plasmanet/serve.py` → `legacy/` with explanatory README
- ✅ Added `cdk.out/`, `frontend/dist/`, `frontend/storybook-static/` to `.gitignore`
- ✅ `pyproject.toml` extras (`[serve]`, `[agent]`, `[dev]`) + `[tool.pytest.ini_options]`
- ✅ Updated `README.md` module map

### 4.2 🟡 In progress / partially done

- **Mock server split** — commit `a8a48ee` extracted `api_models.py` (mock_server 966 → 842 LOC). Deeper split (`api_helpers.py` for `_predict`, `_build_benchmark`, `_compute_scan_data`) deferred — entangled imports, low ROI mid-demo. Pick up after M22.5 demo.
- **Mach-ramp script consolidation** — `ram_c_unified_ramp.sh` written and uploaded to VM. The 6 superseded scripts (`ram_c_ramp_stages.sh`, `ram_c_refined_ramp.sh`, `ram_c_refined_resume_M15.sh`, `ram_c_refined_phase2_low_iter.sh`, `mach_ramp_nemo.sh`, `ram_c_refined_ramp_air11.sh`) still live alongside — current ramp uses phase2. Archive after M22.5 lands.

### 4.3 🟡 Test coverage gaps

12 of 22 plasmanet modules without test files. Highest-priority adds:

| Module | LOC | Risk |
|---|---|---|
| `model.py` | 414 | High — NN architecture, used in inference |
| `model_v2.py` | 191 | High — current production model |
| `nemo_config.py` | 193 | Medium — config gen has subtle FLUID_MODEL/CFL/timescheme switches |
| `ram_c_validation.py` | 378 | Medium |

Add smoke tests for `model.py`/`model_v2.py`: `forward()` on synthetic input + `load_checkpoint()` with a fixture file.

### 4.4 🟡 `mock_server.py` deeper split (deferred)

- `api_helpers.py` → `_plasma_freq_ghz`, `_detection_status`, `_load_validation_json`, `_estimated_runtime`, `_build_station_profile`
- `api_predict.py` → `_try_real_physics`, `_mock_from_validation_json`, `_predict`
- `api_benchmark.py` → `_build_benchmark`, `_resolve_benchmark_error`, `_compute_scan_data`
- `mock_server.py` → just `create_app()` + `main()` + the FastAPI route wiring

Hold for after demo. Pure refactor, zero new functionality.

### 4.5 🔴 Local data cruft (gitignored, eats disk)

```
1.6 GB  data/cfd_cases_nemo/ram_c_gradual/      (abandoned)
503 MB  data/cfd_cases_nemo/ram_c_gradual2/     (abandoned)
 84 MB  data/cfd_cases_nemo/ram_c_meshgen/      (abandoned)
 82 MB  data/cfd_cases_nemo/ram_c_uniform/      (abandoned)
```

Local-only `rm -rf` after M22.5 demo. 2.27 GB freed.

### 4.6 🟡 Frontend coupling flags (from other instance)

1. `DataSource` type lives in `LiveMockBadge.tsx` — move to `src/types/los.ts` when we lift state to a context
2. Trajectory grid duplicated in 3 places — fix planned (consolidate to `plasmanet/ram_c_trajectory.py` + auto-generated JSON for the frontend)
3. `StationEntry` type now has more importers — fine, it's the right shared type
4. Playwright cached locally but not in CI — non-issue
5. `vi.spyOn(globalThis, "fetch")` is sufficient now; bring in `msw` when network-shape tests grow

---

## 5. Prioritized fix order (post-M22.5 demo)

### 5.1 Sprint 1 — "Khorium-shape" the solver (1–2 days)

1. **Create `src/shared/` and `src/simops/` mirroring KhoriumBackend** (no behavior change yet — just new locations)
2. **Move `plasmanet/physics.py` → `src/shared/physics.py`** (foundational, shared between any solver)
3. **Add `src/shared/aws.py`** with `s3_client()` factory (matches Khorium signature)
4. **Add `src/shared/sim_params.py`** with `SU2NemoParams(BaseModel)` matching KhoriumBackend's `OpenFoamParams` style
5. **Extract `src/simops/su2_nemo/{case_writer,runner,result_parser}.py`** from current scripts + `nemo_config.py`
6. **Add `src/simops/main.py`** — Batch-shaped entrypoint that runs locally too (`SOLVER_TYPE=su2_nemo`)
7. **Add `src/simops/s3.py`** — copy KhoriumBackend's, adjust for our case shape
8. **Add per-dir `AGENTS.md` + `CLAUDE.md`** matching Khorium style

### 5.2 Sprint 2 — Khorium API integration (1 day)

9. **Promote `plasmanet/mock_server.py` → `src/api/plasma/{analyze,benchmark,report,submit_cfd}.py`** (Khorium splits routes by file)
10. **Generate `frontend/src/api/generated/` from `openapi.json`** (openapi-typescript)
11. **Add `Dockerfile.simops-su2nemo`** matching `Dockerfile.simops-openfoam` style

### 5.3 Sprint 3 — Test coverage + cleanup (1 day)

12. Add `tests/test_model.py`, `test_model_v2.py`, `test_nemo_config.py`
13. Archive 6 superseded ramp scripts to `scripts/archive/`
14. Local cleanup: `rm -rf` 2.27 GB of dead mesh attempts
15. Deferred mock_server deeper split (helpers/predict/benchmark)

### 5.4 Sprint 4 — Polish (½ day)

16. Add `.pre-commit-config.yaml` matching KhoriumBackend
17. Add `.python-version` for uv compatibility
18. Cross-link plasmanet docs to `KhoriumContext/designs/` paths
19. Frontend `src/types/` consolidation per coupling flag #1

---

## 6. The drop-in test

When this is all done, a Khorium engineer should be able to:

```bash
# 1. Add SU2-NEMO solver to their backend in 3 lines:
echo 'from simops.su2_nemo import runner as su2_nemo_runner' >> KhoriumBackend/src/simops/main.py

# Edit dispatch:
# if solver_type == "su2_nemo":
#     params = SU2NemoParams.model_validate_json(sim_params_raw)
#     su2_nemo_runner.run(case_dir, output_dir, params)

# 2. Build the worker image:
docker build -f Dockerfile.simops-su2nemo -t plasmanet:simops-su2nemo .

# 3. Submit a job via Batch — same S3 contract as openfoam/calculix:
aws batch submit-job \
  --job-name $(uuidgen) \
  --job-queue plasmanet-nemo \
  --job-definition plasmanet-nemo:1 \
  --container-overrides 'environment=[
    {name=SOLVER_TYPE,value=su2_nemo},
    {name=SIM_PARAMS,value="{...SU2NemoParams JSON...}"},
    {name=INPUT_S3_KEY,value=simulations/abc/input.tar.gz},
    {name=OUTPUT_S3_KEY,value=simulations/abc/output.tar.gz},
    {name=S3_BUCKET,value=khorium-simulations},
    {name=JOB_ID,value=abc}
  ]'
```

If that works on day-one with no Khorium-side changes, we've nailed the alignment.
