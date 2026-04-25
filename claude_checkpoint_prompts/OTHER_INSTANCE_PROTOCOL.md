# Working with the other Claude instance

There is a **second Claude Code instance** running concurrently in another bash window of the user's machine. It works in the **same repo, same working tree, same branch** as you.

This is necessarily a manual coordination dance — there's no shared state between Claude processes. The user is the broker.

---

## File-ownership boundaries

To avoid merge conflicts, we agreed on disjoint file ownership:

### Files **you** (the new Claude) own — these are mine:
```
scripts/ram_c_*.sh
scripts/mesh_ram_c_refined.py
scripts/validate_ram_c_nemo.py
scripts/add_markers_su2.py
scripts/make_paper_figures.py
scripts/make_ramp_evolution_fig.py
scripts/make_roadmap_xlsx.py
scripts/fallback_M18_*.sh
scripts/ram_c_unified_ramp.sh
scripts/finalize_m22_5_result.py
data/cfd_cases_nemo/**
data/nemo_test/**
docs/PLASMANET_NOTION.md   (RAM-C sections only)
docs/KHORIUM_ALIGNMENT.md
docs/RAM_C_VALIDATION_STATUS.md
docs/SU2_NEMO_FIX.md
docs/ROADMAP_SIMOPS_INTEGRATION.md
docs/PROJECT_OVERVIEW_POST_AUDIT.md
claude_checkpoint_prompts/**
plasmanet/cfd_field.py
plasmanet/nemo_config.py
plasmanet/ram_c_validation.py
plasmanet/physics.py
plasmanet/line_of_sight.py
plasmanet/chemistry_uq.py
plasmanet/detectability.py
plasmanet/collision_frequency.py
plasmanet/plasma_wave.py
README.md
.gitignore
pyproject.toml
legacy/**
```

### Files **they** own — DO NOT TOUCH:
```
frontend/**
cdk/**
lambda/**
Dockerfile
plasmanet/mock_server.py
plasmanet/api_models.py
plasmanet/pdf_report.py
plasmanet/agent_tools.py
tests/test_mock_server*.py
tests/test_pdf_report.py
tests/test_agent_tools.py
tests/test_simulation_complete_lambda.py
.github/workflows/ci.yml
docs/SIMOPS_INTEGRATION.md
```

If the user asks you to touch a file in their territory, push back and route via the user — don't edit directly.

---

## Push protocol — Option A

We're on **continuous push**:

- ✅ Push every commit immediately to `origin/master`
- ✅ Audit each other's work after they push (the user relays end-of-session summaries)
- ❌ NO "hold for verify" dance
- ❌ NO long-lived branches

The reason this works: file ownership is disjoint, so we never merge-conflict on push.

**Always `git pull --rebase` before each of your commits** — picks up whatever they pushed in the meantime.

---

## How tasks flow

1. **User relays end-of-session summary** from other instance to you
2. **You audit** — read the commits via `git show <hash>`, run their tests, spot bugs / coverage gaps / coupling concerns
3. **You write a next-task prompt** for them in a code-fenced block
4. **User copy-pastes the prompt** into the other Claude's window
5. **They work, push, summarize**
6. Loop

The prompt should be self-contained: file paths, test command, success criteria, push instructions.

---

## Both instances run on different models

- **You (this slot):** Claude Opus 4.7 with 1M context — heavy cognitive lifting, audits, architecture, the CFD pipeline
- **Other instance:** Sonnet 4.6 (per their commit Co-Authored-By tags) — narrower-scope tasks, frontend/api/test work

**For tasks touching the physics stack or non-trivial AWS IAM logic, prefer Opus** (you). For tasks like "add a React component matching this design" or "write pytest for this function," Sonnet is fine.

---

## Coordinating with the user

The user is the message broker. They:
- Paste the other instance's summary into your conversation
- Paste your prompts into the other instance's conversation
- Sometimes get tired of brokering and ask you to think about whether work can be parallelized

**Be efficient with the user's time:**
- Always include the full prompt in a copy-pasteable code block
- Give a one-line "send?" confirmation at the end
- Don't ask the user to look up things you can find via `gh api` or `git log`

---

## When in doubt, prefer:

1. **More frequent commits, smaller diffs** — easier to audit, less merge-conflict surface
2. **Push immediately** — never hoard local commits
3. **Document file ownership in commit messages** when ambiguous ("touched plasmanet/api_models.py because it was extracted from mock_server.py — coordinated with other instance")
4. **Pull --rebase before every push** — even if you just pulled 5 minutes ago

---

## Git remote

- **Origin:** `github.com/yardeli/cadpipe-neural-network.git`
- **Branch:** `master` (we don't use feature branches in this session)
- **Both instances push directly to master** under Option A
