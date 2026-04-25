# Resume prompt — paste this into a new Claude Code session

You are picking up an in-flight Claude Code session in the **plasmanet** repo at:

```
C:\Users\yarden\Desktop\Khorium Hypersonics\plasmanet
```

The previous Claude (Opus 4.7, 1M context) ran out of context window. This briefing has everything you need to continue.

---

## What this project is

**Plasmanet** is a neural surrogate for hypersonic plasma prediction. It's part of the broader **Khorium SimOps** ecosystem (KhoriumBackend / KhoriumFrontend / KhoriumContext at github.com/KhoriumAI). The goal is to integrate plasmanet's SU2-NEMO coupled-chemistry CFD solver alongside the existing Khorium solvers (CalculiX, OpenFOAM) so it deploys via the same AWS Batch infrastructure.

**Active long-running work:** the RAM-C II Mach-ramp validation (M10 → M15 → M18 → M22.5) on a GCP VM, validating against Jones & Cross 1972 (NASA TN D-6617) electrostatic-probe measurements at 61 km altitude.

**The repo's GitHub remote** is `yardeli/cadpipe-neural-network` (older name; this is the active repo).

---

## Where to read first

In the repo, read in this order:

1. **`docs/PLASMANET_NOTION.md`** — stakeholder-facing project overview (current state, validation table, architecture)
2. **`docs/KHORIUM_ALIGNMENT.md`** — gap analysis vs the Khorium architecture pattern + prioritized restructure plan (post-M22.5 work)
3. **`docs/SIMOPS_INTEGRATION.md`** — the API contract (4 routes + 2 agent tools)
4. **`docs/ROADMAP_SIMOPS_INTEGRATION.md`** — sprint-by-sprint plan
5. **`docs/SU2_NEMO_FIX.md`** — the breakthrough that unblocked Path C (FLUID_MODEL= SU2_NONEQ was missing)
6. **`scripts/finalize_m22_5_result.py`** — the one-shot script to run when M22.5 finishes (scp + validate + figures + Notion + commit)
7. **`scripts/ram_c_unified_ramp.sh`** — the consolidated ramp runner; supersedes 6 older scripts
8. **`claude_checkpoint_prompts/ACTIVE_STATE.md`** — what's running on the VM right now

Then check `git log --oneline -20` to see the latest commits.

---

## Key architecture facts

- **22 Python modules** in `plasmanet/` (core), **~25 scripts** in `scripts/`, FastAPI `mock_server.py` is the canonical SimOps API server, `pdf_report.py` generates A4 PDFs, `agent_tools.py` exposes Pydantic AI tools (`analyze_plasma`, `generate_plasma_report`)
- **AWS CDK stacks** in `cdk/` (PlasmaNetServiceStack = Fargate, PlasmaNetWorkerStack = Batch + Spot/OD compute envs + S3 + EventBridge → Lambda)
- **Lambda webhook** in `lambda/simulation_complete/` — UUID detection + DescribeJobs fallback for simulation_id resolution
- **Frontend** in `frontend/` — React 18 + Vite + Tailwind + TypeScript, polar attenuation chart + station-profile chart + LIVE/MOCK badge fallback. Has Storybook (14 stories) + vitest RTL tests (26 tests) + frontend CI job.
- **97 tests passing** total (71 backend pytest + 26 frontend vitest), all in CI on every push
- **Recent refactor:** `mock_server.py` Pydantic models extracted to `plasmanet/api_models.py` (commit `a8a48ee`). Backward-compat preserved via `from .api_models import *`.
- **Recent cleanup:** `bd69e20` deleted 1,068 lines of dead code (`extract_cfd_results.py`, `run_cfd_batch.py`), archived pre-React demo to `legacy/`, fixed `pyproject.toml` extras

---

## How we work with the parallel Claude

There is a **second Claude Code instance** running in another bash window of the user's machine. It works in the **same repo, same working tree**.

**File ownership** (DO NOT touch the other instance's files):
- **My files (CFD / scripts / docs):** `scripts/ram_c_*`, `scripts/mesh_ram_c_refined.py`, `scripts/validate_ram_c_nemo.py`, `scripts/add_markers_su2.py`, `scripts/make_paper_figures.py`, `scripts/make_ramp_evolution_fig.py`, `scripts/fallback_M18_*.sh`, `scripts/ram_c_unified_ramp.sh`, `scripts/finalize_m22_5_result.py`, `scripts/make_roadmap_xlsx.py`, `data/cfd_cases_nemo/**`, `data/nemo_test/**`, `docs/PLASMANET_NOTION.md` (RAM-C sections), `docs/KHORIUM_ALIGNMENT.md`
- **Other instance's files:** `frontend/**`, `cdk/**`, `lambda/**`, `Dockerfile`, `plasmanet/mock_server.py`, `plasmanet/api_models.py`, `plasmanet/pdf_report.py`, `plasmanet/agent_tools.py`, `tests/test_mock_server*.py`, `tests/test_pdf_report.py`, `tests/test_agent_tools.py`, `tests/test_simulation_complete_lambda.py`, `.github/workflows/ci.yml`

**Push protocol:** Option A — push every commit immediately to origin. The other instance audits on push, no "hold for verify" dance. The user manually relays end-of-session summaries between us.

**See `OTHER_INSTANCE_PROTOCOL.md` for full details.**

---

## What I was about to do

**Last queued task for the other instance** (paste into the user's relay if they ask):
- Frontend trajectory-grid consolidation + Storybook a11y addon
- Full prompt is in `OPEN_TASKS.md` § "Queued for other instance"

**My next moves once M22.5 finishes:**
1. Run `python scripts/finalize_m22_5_result.py` (dry run first, then `--commit-and-push`)
2. Audit the M22.5 numbers vs J&C
3. Update PLASMANET_NOTION.md §3.2 (the finalizer does this automatically — verify)
4. Decide if AIR-11 fallback ramp is needed (only if log10 err > 1.0)
5. Begin the Khorium-shaped restructure per `docs/KHORIUM_ALIGNMENT.md` § 5

---

## Important environment

- **Platform:** Windows 11, Python 3.13, bash via Git Bash. **Run all Python with `PYTHONIOENCODING=utf-8`** — Windows cp1252 default crashes on `→`, `×`, `m⁻³`, etc.
- **GCP VM:** `openfoam-hgv` in `us-central1-a`. SU2-NEMO at `/opt/su2-nemo/bin/SU2_CFD`, Mutation++ data at `/opt/su2-nemo/mpp-data/`. **OpenMP-only build (no MPI)** — single-threaded preprocessing is the bottleneck on big meshes.
- **gcloud ssh + background processes:** must use `setsid bash -c "..." < /dev/null > /dev/null 2>&1` or the local channel hangs. See `LESSONS_LEARNED.md`.
- **Git auto-line-ending warnings** are normal on Windows; the `LF will be replaced by CRLF` warnings are cosmetic.

---

## Memory / persistent context

You have access to my persistent memory at `C:\Users\yarden\.claude\projects\C--Users-yarden\memory\`. The plasmanet-relevant entries:

- `project_plasmanet.md` — project location + status
- `reference_gcloud_ssh_background.md` — the setsid pattern (CRITICAL — read this before launching anything on the VM)
- `feedback_push_frequently.md` — push every ~15 min during long sessions

---

## When in doubt

- **Run `git log --oneline -20`** to see what landed recently — most state changes faster than docs.
- **Read `claude_checkpoint_prompts/ACTIVE_STATE.md`** for live PIDs / monitor IDs / VM state.
- **Don't touch the other instance's files** — coordinate via the user.
- **Always commit + push your own work** under Option A protocol.

Good luck. The previous Claude has been running this for ~24 hours and the architecture is in good shape — just keep the momentum going.
