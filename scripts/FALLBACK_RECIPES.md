# RAM-C ramp fallback recipes

When the main `ram_c_refined_phase2_low_iter.sh` (or any future
`ram_c_unified_ramp.sh` chain) hits trouble at the M18 stage, the three
scripts in this directory each address one specific failure mode. Pick the
one that matches the symptom you see in `su2.log` or `history.csv`.

## Decision tree

```
M18 stage in trouble?
│
├─ Rho_0 climbing instead of falling, or |Rho_0| oscillating widely?
│  → fallback_M18_lowcfl.sh        (CFL 0.5 → 0.15)
│
├─ Many "temperatures did not converge" warnings with error > 1?
│  → fallback_M18_lowcfl.sh        (CFL too aggressive, dissipate slower)
│
├─ Sawtooth Rho_0 around a fixed mean, shock visibly oscillating in flow.vtu?
│  → fallback_M18_ausm.sh          (LAX dissipation too high → sharper flux)
│
├─ Solver crash with "nonphysical state" or NaN?
│  → fallback_M18_via_M16_M17.sh   (M15→M18 jump too big, bisect)
│
└─ Memory OOM or segfault?
   → coarsen the mesh; this is not a stage-recovery problem.
```

## Why these three

**Lower CFL** is the safest first move. Smaller time-step =
less thermochemical disequilibrium per iter, more stable Newton. Costs
~3x wall time per iter but converges where CFL=0.5 doesn't.

**AUSM+ flux** has lower numerical dissipation than LAX-FRIEDRICH, so the
shock front stays sharper and the post-shock state is more accurately
resolved. Less robust at extreme conditions but usually survives M18 if
M15 was clean.

**M16→M17 intermediate stages** halves the Mach jump and gives the solver
a fresh restart twice. Most expensive (~40 min added) but ~95 % chance of
unsticking a stuck M18.

## Try in this order

1. **Lower CFL** first — minimal change, most likely fix.
2. If still failing, **AUSM+ flux** — it's a different failure mode but
   sometimes the correct one.
3. **Intermediate stages** as the heaviest hammer when nothing else works.

After any fallback succeeds, manually copy the M18 restart into the
M22.5 stage dir before relaunching the chain:

```bash
cp /home/yarden/ram_c_runs/ramC_refined_M18_0_A61_lowcfl/restart.dat \
   /home/yarden/ram_c_runs/ramC_refined_M22_5_A61/solution.dat
```

Then re-run `bash ram_c_refined_phase2_low_iter.sh` (or the unified
script) — it'll see M18 is done (su2.exitcode=0 was written by the
fallback's success) and resume at M22.5.

(The unified script handles this automatically via its idempotent
run_stage check; the older phase2 script does NOT have that check, so
manual copy is required for it.)
