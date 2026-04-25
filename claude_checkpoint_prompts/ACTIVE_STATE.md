# Active state snapshot — STALE WITHIN HOURS

**Snapshot taken:** 2026-04-25 ~05:30 UTC (mid-M22.5 stage of refined-mesh ramp)

⚠️ **If reading more than 12 hours after the timestamp above, re-verify directly via `gcloud compute ssh` and `git log` — this file is a snapshot, not live state.**

---

## GCP VM `openfoam-hgv` (us-central1-a)

### Current ramp run

The **refined-mesh** Mach ramp is running stage 4 of 4.

**Process tree:**
```
PID 131909 — bash ram_c_refined_phase2_low_iter.sh (the watcher)
└── PID <child> — /opt/su2-nemo/bin/SU2_CFD run.cfg  (M22.5 stage)
```

**State at snapshot:**
- M10 done (exit=0, iter=399, Rho_0 = −4.18) ✓
- M15 done (exit=0, iter=299, Rho_0 = −1.90) ✓
- M18 done (exit=0, iter=199, Rho_0 = −1.93) ✓
- M22.5 running (iter ~167/400, Rho_0 = −1.78, ~33 sec/iter)
- Memory: 13 GB used / 17 GB free
- ETA M22.5 done: **~07:15 UTC / 03:15 AM local** (about 2 hours from snapshot time)

**Stage directories on VM:**
```
/home/yarden/ram_c_runs/ramC_refined_M10_0_A61/    # M10 done
/home/yarden/ram_c_runs/ramC_refined_M15_0_A61/    # M15 done
/home/yarden/ram_c_runs/ramC_refined_M18_0_A61/    # M18 done
/home/yarden/ram_c_runs/ramC_refined_M22_5_A61/    # M22.5 running
```

**PID file the monitor reads:**
```
/home/yarden/ram_c_refined_ramp.pid
```

---

## Local monitor task

**Task ID:** `b7p28s032`
**Cadence:** 2× 30-min checks then hourly thereafter
**Stop with:** `TaskStop` tool with `task_id=b7p28s032`

The monitor polls the VM via gcloud ssh every 60 minutes and reports stage progress + Rho_0 + free memory + OOM count. Events arrive as `<task-notification>` messages.

---

## When M22.5 finishes — finalization sequence

The user will see a monitor event like:
```
[hourly] ramp=dead M22_5:done(exit=0, iter=N, rho0=−X.XX) free=NNG oom=0
```

When that fires, run:

```bash
cd "C:/Users/yarden/Desktop/Khorium Hypersonics/plasmanet"

# Dry run first to inspect
python scripts/finalize_m22_5_result.py

# If diff looks good, commit + push
python scripts/finalize_m22_5_result.py --commit-and-push
```

This script:
1. scp's the M22.5 flow.vtu (~100 MB) from VM into `data/nemo_test/`
2. Runs `validate_ram_c_nemo.py` → writes `ram_c_validation.{json,md}`
3. Runs `make_paper_figures.py` → 4 PNGs + drop-in markdown blurb
4. Patches `docs/PLASMANET_NOTION.md` §3.2 with real numbers
5. Stages + commits + pushes everything

---

## What's been pulled locally already

```
data/nemo_test/ramC_small_M22_5_A61_nemo.vtu     # First-pass M22.5 (small mesh, log10 err +1.08 robust)
data/nemo_test/ramC_refined_M10_0_A61_nemo.vtu   # Refined-mesh M10 stage
data/nemo_test/ramC_refined_M15_0_A61_nemo.vtu   # Refined-mesh M15 stage
data/nemo_test/ramC_refined_M18_0_A61_nemo.vtu   # Refined-mesh M18 stage (log10 err improved by ~7×)
```

---

## M18 partial-result check (sanity preview for M22.5)

| Stage | T_tr | T_ve | NEQ ΔT | p_stag | n_e top-50 | cells > 1e19 |
|---|---|---|---|---|---|---|
| M10 | 4106 K | 3723 K | 383 K | 3.4e4 Pa | 1.3e18 | 0 |
| M15 | 4834 K | 4369 K | 465 K | 9.7e4 Pa | 1.6e19 | 153 |
| M18 | 4573 K | 4453 K | 120 K | 6.6e4 Pa | 9.3e19 | 1077 |

M18 stagnation n_e (2.44e19) is already in J&C's published uncertainty band (1–4e19). If M22.5 follows the trend, expect log10 error around **+0.4 to +0.6** (vs +1.08 first-pass).

---

## Other instance state

The parallel Claude (Sonnet 4.6) just shipped 5 frontend commits (`365de52..118845e`):
- Storybook setup
- Extracted `LiveMockBadge` + `FlightSelectors` from `App.tsx`
- 14 stories across 4 components
- 26 vitest RTL tests
- Frontend CI job

**They reported 5 coupling concerns** — see `OPEN_TASKS.md` for the queued response.

---

## Latest commits (full session has ~50 commits)

```
fa44d81  docs: Khorium architecture alignment + open audit findings   (this Claude)
a8a48ee  refactor: extract Pydantic models from mock_server.py        (this Claude)
118845e  ci: frontend job (build + vitest)                            (other)
ad60e1a  test(frontend): RTL coverage for App + components            (other)
cc82cb9  chore(frontend): stories for all components                  (other)
34ff21b  feat(frontend): extract LiveMockBadge + FlightSelectors      (other)
365de52  chore(frontend): set up Storybook                            (other)
bd69e20  chore: cleanup — delete dead modules, archive demo           (this Claude)
b422c21  fix(api): explicit attribution in /report Validation         (other)
a6db8b1  feat(agent): generate_plasma_report tool                     (other)
25e6017  Multi-stage ramp evolution figure generator                  (this Claude)
5faff1d  feat(api): auto RAM-C benchmark in /report                   (other)
6368146  feat(agent): analyze_plasma Pydantic AI tool binding         (other)
a4faa5a  M22.5 result finalizer — one-shot pipeline                   (this Claude)
27cf8f0  feat(api): /api/plasma/report PDF generation endpoint        (other)
```

---

## Test counts at snapshot

- **Backend pytest** (3 jobs in CI): 71 tests pass in ~63s
  - 34 mock_server contract tests
  - 6 lambda tests (UUID + DescribeJobs + tags + exception + missing jobId)
  - 16 PDF tests
  - 13 agent tests + 2 health
- **Frontend vitest:** 26 tests pass in ~3s
- **CDK synth:** clean (both stacks)

**Total: 97 tests across two languages, all green.**
