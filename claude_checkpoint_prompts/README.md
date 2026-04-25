# Claude checkpoint prompts

**Purpose:** hand off this Claude Code session to the next instance with zero context loss.

**Created:** 2026-04-25 (mid-M22.5 ramp, ~50 commits into the SimOps integration sprint)

## How to use

When starting a new Claude Code session in this repo:

1. **Paste `RESUME_PROMPT.md`** as the first message — it's the full briefing.
2. Then have Claude read these files in order:
   - `ACTIVE_STATE.md` — what's running RIGHT NOW (will go stale within hours)
   - `OPEN_TASKS.md` — prioritized TODO list
   - `OTHER_INSTANCE_PROTOCOL.md` — how to coordinate with the parallel Claude
   - `LESSONS_LEARNED.md` — gotchas to avoid repeating
3. Reference docs (already in the repo, but copies cached here for cold-start convenience) live in `reference/`.

## Files in this folder

| File | Use |
|---|---|
| `README.md` | This file |
| `RESUME_PROMPT.md` | **Paste this into a new Claude session.** Self-contained briefing. |
| `ACTIVE_STATE.md` | Runtime state: what processes / monitors / VM jobs are alive |
| `OPEN_TASKS.md` | Prioritized work queue |
| `OTHER_INSTANCE_PROTOCOL.md` | Conventions for working with the parallel Claude instance |
| `LESSONS_LEARNED.md` | Gotchas (gcloud-ssh hangs, cwd-vs-cmdline pkill, etc.) |
| `reference/` | Cached copies of the most-referenced project docs |

## Freshness

| Section | Decay |
|---|---|
| `RESUME_PROMPT.md` | Stable for ~2 weeks (project fundamentals don't change fast) |
| `ACTIVE_STATE.md` | Stale within hours (CFD ramp finishes, monitors expire, PIDs die) |
| `OPEN_TASKS.md` | Stale within days (other instance ships things, priorities shift) |
| `OTHER_INSTANCE_PROTOCOL.md` | Stable until we change the parallel-work protocol |
| `LESSONS_LEARNED.md` | Append-only — old lessons stay relevant |
| `reference/` | Cache of `docs/`; canonical version is in `docs/` |

If `ACTIVE_STATE.md` was written more than ~12 hours ago, treat it as a snapshot, not current state — re-check the VM and `git log` directly.
