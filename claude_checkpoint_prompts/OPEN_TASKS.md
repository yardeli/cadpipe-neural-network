# Open tasks (prioritized) — 2026-04-25

## P0 — When M22.5 ramp finishes (ETA ~07:15 UTC)

1. Run `python scripts/finalize_m22_5_result.py --commit-and-push` (after dry-run review)
2. Audit M22.5 numbers vs J&C 1972
3. **Decision point:** if log10 err < 0.5 → C-3c milestone done, move to C-4 (40-case batch). If > 1.0 → launch AIR-11 fallback ramp (`scripts/ram_c_refined_ramp_air11.sh` already pre-staged on VM)
4. Stop the monitor `b7p28s032` once M22.5 has been validated

---

## P1 — Queued for the other instance (paste when they're free)

**Storybook a11y + trajectory-grid consolidation** — addresses their flagged coupling #2:

```
All 5 frontend commits approved (97 tests total now). Two follow-ups:

═══════════════════════════════════════════════════════════════════════════
TASK 1 — Single source of truth for the RAM-C II trajectory grid (~45 min)
═══════════════════════════════════════════════════════════════════════════

Trajectory data is duplicated in three places:
  - frontend/src/components/FlightSelectors.tsx (MACH_OPTIONS, ALT_OPTIONS arrays)
  - plasmanet/pdf_report.py (CANONICAL_RAMC_POINTS dict)
  - plasmanet/agent_tools.py (vehicle preset references it indirectly)

Consolidate into one Python module + one TypeScript module, generated
from the same JSON spec so they can never drift.

A. Create plasmanet/ram_c_trajectory.py — the canonical Python source:

   RAM_C_TRAJECTORY = [
       {"altitude_km": 81.0, "mach": 23.9, "ne_peak_m3_published": 2.0e18,
        "source": "Jones & Cross 1972 NASA TN D-6617"},
       {"altitude_km": 71.0, "mach": 23.6, "ne_peak_m3_published": 1.0e19, ...},
       {"altitude_km": 61.0, "mach": 22.5, "ne_peak_m3_published": 2.0e19, ...},
       {"altitude_km": 47.0, "mach": 18.5, "ne_peak_m3_published": 2.0e19, ...},
   ]

   plus helpers: trajectory_altitudes(), trajectory_machs(),
   find_canonical_match(mach, alt, tol_mach=0.1, tol_km=1.0).

   Move CANONICAL_RAMC_POINTS + find_canonical_match OUT of pdf_report.py
   and INTO this module. pdf_report.py imports them from here.

B. Generate frontend/src/data/ram_c_trajectory.json from the Python source
   via a new scripts/sync_trajectory_json.py. Put a unit test that
   asserts the JSON matches the Python module — catches drift on every
   CI run.

C. frontend/src/components/FlightSelectors.tsx imports from
   ram_c_trajectory.json (typed with a TS interface). MACH_OPTIONS and
   ALT_OPTIONS become derived arrays.

D. Add a Python contract test (tests/test_ram_c_trajectory.py) verifying:
   - Python module exposes the 4 canonical points
   - JSON file matches the Python module (deep equality)
   - find_canonical_match returns expected matches at exact + tolerance edges

═══════════════════════════════════════════════════════════════════════════
TASK 2 — Wire the Storybook a11y addon (~15 min)
═══════════════════════════════════════════════════════════════════════════

You installed @storybook/addon-a11y but it's not registered. Add it to
.storybook/main.ts addons array. Verify by opening a story in the
Storybook UI and confirming the Accessibility tab shows up. Fix any
contract violations the addon flags.

═══════════════════════════════════════════════════════════════════════════
WORKFLOW REMINDERS
═══════════════════════════════════════════════════════════════════════════

- git pull --rebase before each commit
- Push immediately after each commit
- Hard constraints (UNCHANGED): don't touch scripts/ram_c_*,
  scripts/mesh_ram_c_refined.py, scripts/validate_ram_c_nemo.py,
  scripts/add_markers_su2.py, scripts/make_paper_figures.py,
  scripts/make_ramp_evolution_fig.py, scripts/fallback_M18_*.sh,
  scripts/ram_c_unified_ramp.sh, scripts/finalize_m22_5_result.py,
  scripts/make_roadmap_xlsx.py, data/cfd_cases_nemo/**,
  data/nemo_test/**, docs/PLASMANET_NOTION.md (RAM-C sections),
  docs/KHORIUM_ALIGNMENT.md
```

---

## P2 — After M22.5 demo, the Khorium restructure

Per `docs/KHORIUM_ALIGNMENT.md` § 5, four sprints, ~3-4 days total:

### Sprint 1 — "Khorium-shape" the solver (1–2 days)
1. Create `src/shared/` and `src/simops/` mirroring KhoriumBackend layout
2. Move `plasmanet/physics.py` → `src/shared/physics.py`
3. Add `src/shared/aws.py` with `s3_client()` factory
4. Add `src/shared/sim_params.py` with `SU2NemoParams(BaseModel)`
5. Extract `src/simops/su2_nemo/{case_writer,runner,result_parser}.py`
6. Add `src/simops/main.py` — Batch-shaped entrypoint
7. Add `src/simops/s3.py` — copy KhoriumBackend's
8. Add per-dir `AGENTS.md` + `CLAUDE.md`

### Sprint 2 — Khorium API integration (1 day)
9. Promote `mock_server.py` → `src/api/plasma/{analyze,benchmark,report,submit_cfd}.py`
10. Generate `frontend/src/api/generated/` from `openapi.json`
11. Add `Dockerfile.simops-su2nemo`

### Sprint 3 — Test coverage + cleanup (1 day)
12. Add `tests/test_model.py`, `test_model_v2.py`, `test_nemo_config.py`
13. Archive 6 superseded ramp scripts to `scripts/archive/`
14. Local `rm -rf` 2.27 GB of dead mesh attempts in `data/cfd_cases_nemo/{ram_c_gradual,ram_c_gradual2,ram_c_meshgen,ram_c_uniform}`
15. Deferred mock_server deeper split

### Sprint 4 — Polish (½ day)
16. Add `.pre-commit-config.yaml` matching KhoriumBackend
17. Add `.python-version` for uv compatibility
18. Cross-link plasmanet docs to `KhoriumContext/designs/` paths

---

## P3 — Test coverage gaps (any time)

12 of 22 plasmanet modules without test files. Highest priority:

| Module | LOC | Risk |
|---|---|---|
| `model.py` | 414 | High — NN architecture |
| `model_v2.py` | 191 | High — production model |
| `nemo_config.py` | 193 | Medium — subtle FLUID_MODEL/CFL switches |
| `ram_c_validation.py` | 378 | Medium |

---

## P3 — Deferred refactors

- `mock_server.py` deeper split (`api_helpers.py` + `api_predict.py` + `api_benchmark.py`) — tangled imports, low ROI mid-demo
- Frontend `DataSource` type → move to `src/types/los.ts` when state lifts to context
- `msw` for richer network-shape tests when we add presigned-URL or websocket flows

---

## C-4 (after C-3 closes) — Port 40-case batch to NEMO

Scaffolding ready: `plasmanet/nemo_config.py` + `scripts/generate_nemo_batch.py`. Will need:
- Per-case mesh generation (5 geometries × 8 flight conditions = 40)
- Mach-ramp wrapper for each (NEMO needs the ramp from M10 cold)
- Batch submission via `bash scripts/run_nemo_batch.sh` OR migration to AWS Batch (post-Khorium-restructure)

---

## Decision points still open (per ROADMAP §6)

| When | Question | Default if not decided |
|---|---|---|
| After M22.5 result | Submit AFRL SBIR white paper now? | Yes if log10 err < 1.0 |
| Week 5 | Begin SimOps frontend deploy on Khorium staging? | Yes (frontend is ready) |
| Week 6 | Retrain PlasmaNet NN on NEMO batch data? | Only if held-out geom error > 3× |
