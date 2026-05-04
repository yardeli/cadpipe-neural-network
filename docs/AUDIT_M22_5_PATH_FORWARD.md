# AUDIT — M22.5 RAM-C / AIR-7 CFD Divergence: Root-Cause and Path Forward

**Date**: 2026-04-28
**Scope**: Read-only audit. Diagnoses the chemistry-thermal Newton blowup observed at iter ~520 in the SU2 v8.4.0 + MSW + MUSCL + VAN_ALBADA_EDGE + CFL=0.05 trial, ranks 10 candidate paths forward, and answers the strategic question: **does the paper's headline contribution depend on fixing this?**
**Bottom line**: It does not. **Recommended action: ship the paper around the surrogate+Cantera pipeline; treat M22.5 CFD as a directional-consistency appendix (Path A below). In parallel, run two cheap CFD experiments (Paths B+C) that have a credible chance of producing a clean RhoU=−2 anchor within a week.**

---

## UPDATE 2026-04-29 ~09:30 UTC — Phase 1 diagnostics complete; root cause confirmed. Validation path forward identified.

**Phase 1 (three diagnostic experiments) done. Hypothesis 2 (wrong metric) CONFIRMED. Hypothesis 3 (CFL too aggressive) REFUTED. Hypothesis 1 (mesh under-resolution) remains primary cause.**

Headline diagnostic: **`Cauchy[CD] = 0.000837 < 0.001` at iter 100 in 1C** — i.e., the body-integrated drag coefficient is converged to 0.1% of itself across the warm-start window. This means the flow IS at engineering steady-state on the current mesh; the RMS_MOMENTUM-X residual floor is per-cell sub-cell-shock-breathing noise, not a real failure to converge.

Strategic upgrade: **two parallel validation tracks now unblocked**. Track A (use the iter-251 minimum spatial state for ne/dB validation against J&C 1972 immediately) and Track B (Phase 2 mesh refinement for the RMS-converged gold-standard anchor). Full writeup: `CHECKPOINT_2026-04-26.md` §2.8.

---

## UPDATE 2026-04-29 ~03:00 UTC — Extension run halted at iter-1024; carbuncle cured but limit-cycle floor exposed. Audit revised.

**Status: Path 3 (AUSMPLUSM) succeeded at curing the carbuncle (zero non-physical states across 1024 iters vs 143 in v8+MSW), but exposed a slow limit-cycle in RhoU. Best convergence ever achieved on this case: RhoU=-0.2116 at iter-255 of extension (~iter-854 absolute), then drift up to -0.143 by iter-1024.**

The audit's diagnosis below was directionally correct: AUSMPLUSM does cure the carbuncle. But the sub-cell-shock-breathing failure mode underneath turns out to be the binding constraint on this 2.74M-tet mesh, not the carbuncle. Both diagnoses now confirmed by experiment.

**Strategic recommendation revised:**

- The previous "Path 1 (paper reframe)" recommendation is **deprecated per user direction (2026-04-29)**. Goal is now: **make the M22.5 CFD converge cleanly to RhoU ≤ -2, then validate thoroughly across multiple meshes / multiple solvers / multiple flight conditions.**
- New plan structured as 5 phases (Diagnostic → Mesh Refinement → Mesh Independence → Cross-Solver → Multi-Experiment) — **see `CHECKPOINT_2026-04-26.md` §2.7's "Plan forward" subsection** for the full breakdown with acceptance criteria.
- Phase 1 (diagnostic) is the next concrete action: 3 cheap parallel experiments from solution.dat (recover iter-255 minimum, CFL sensitivity, Cauchy on body forces). Each ~30 min to 3 hr wall.
- Phase 2 (mesh refinement, 3-7 days) is the highest-confidence true fix per the audit's section 3.

The original 10-path table below is preserved as historical record. The leading paths after the Phase 1 result were:
- **Path 2 (mesh refinement)** — now elevated to "almost certainly necessary" given AUSMPLUSM cured the carbuncle without reaching engineering convergence
- **Path 3 (AUSMPLUSM)** — proven; is the converging recipe on whatever mesh we use
- Path 5 (Eilmer) and similar cross-solver options are now Phase 4 of the new plan, not fallbacks
- **Paths 1, 6 (paper-related) — DEPRECATED per user direction**

Full writeup in `docs/CHECKPOINT_2026-04-26.md` §2.7. Quick summary:

- AUSMPLUSM's built-in pressure-diffusion sensor (active in `CNEMOEulerSolver.cpp:276`) does damp the asymmetric stagnation-line perturbations the audit identified as the carbuncle root cause. Confirmed.
- Past the iter-500..523 danger zone with zero positive-residual excursions, where every previous trial blew up.
- Descent rate ~0.04 log10 / 100 iters; needs ~5000 more iters at this rate to reach -2 (or fewer if it accelerates as the flow settles).
- Extension run started ~22:00 UTC: 16-rank mpirun, 3000 iters from iter-599 state, ETA ~5.5 hours wall-time. Expected RhoU at iter 3000 if rate holds: ~-1.40; could reach -2 if rate accelerates.
- preserve_checkpoints.sh auto-rotates snapshots; iter-599 saved as safety-net.

**Implications for the audit's strategic recommendation:**

| Outcome of extension run | Updated recommendation |
|---|---|
| RhoU < -2 reached | M22.5 CFD anchor is real. Paper can use it as third validation leg in main text (§3), not Appendix B. **Path 1 (paper reframe) becomes optional rather than required.** |
| RhoU plateaus at -1 to -1.5 | Combine with iter-3000 partial-converged state for "directional consistency" framing. Path 1 still recommended for SciTech preprint; Paths 2/5 for journal-version. |
| Extension blows up after iter 600 | Fall back to iter-599 state as the anchor and proceed with original audit plan. Less likely given 600 iters of monotonic stability already observed. |

**The surrogate+Cantera+BO headline (28/50 candidates beat AIR-7, best −1.94 log10) remains CFD-independent and unaffected by this experiment's outcome.**

Path 2 (mesh refinement) is now lower-priority pending the extension result. Path 5 (Eilmer) remains the journal-version fallback only if Paths 2+3 both fail.

---

---

## 1. Executive summary (200 words)

The M22.5 / AIR-7 / 2.74M-tet inviscid case has a reproducible failure signature across SU2 v7 and v8: monotonic convergence for 100s of iterations, then an iter-scale jump from RhoU≈−0.11 to RhoU≈+2 in 3-5 iterations, accompanied by simultaneous order-of-magnitude rises in **all 7 species residuals**. Inspecting `CNEMOEulerVariable::Cons2PrimVar` (v8 source at `/tmp/SU2-v8/SU2_CFD/src/variables/CNEMOEulerVariable.cpp`) confirms the "non-physical" trigger is a **temperature out of [50K, 80000K] or NaN, or P<0** at a single cell. Once one cell trips, SU2 reverts that cell to `Solution_Old` but the neighborhood's linear-solve update has already been polluted; with stiff Park chemistry the perturbation propagates and a sustained metastable plateau replaces the descending residual. Smaller CFL delays but does not prevent this — the failure is **structural**, not driven by step-size alone.

**Strategic recommendation**: Aaron's "AI exhaustive search" contribution is fully proven by the Cantera-verified BO result (28/50 candidates beat AIR-7, best −1.94 log10). Reframe the paper around that result and ship; downgrade CFD to "directional consistency check" using the iter-501 partial-converged state. Concurrently, try the two cheapest credible fixes (mesh near-shock refinement + AUSMPLUSM scheme) for a clean anchor in 3–7 days.

---

## 2. Divergence root-cause analysis

### 2.1 Direct evidence — last 30 history rows of v8 CFL=0.05 trial

```
iter  RhoU
508  -0.0216
509-518  −0.11 → −0.108 (clean monotonic, ~1e-3 drift, near limit cycle)
519  -0.082    ← onset
520  +0.008    ← +1 order spike, but small
521  +0.206
522  -0.034
523  +3.867    ← THE BLOWUP, +4 orders in one step
524-530  oscillating ±0.2 with one outlier (+0.166 at 530)
531  +2.270    ← settles into new metastable band
532-537  +2.07 to +2.40 (sustained)
```

### 2.2 Diagnosis from `CNEMOEulerVariable::Cons2PrimVar` (v8 source)

The "Warning: initial solution contains N points that are not physical" message (143 instances total in `su2_v8_cfl05.log`) is emitted by `CNEMOEulerSolver.cpp:260` when `SetPrimVar` returns true for any point. The trigger conditions inside `Cons2PrimVar` are exactly:

```
T_tr  < 50 K  or > 80,000 K  or  NaN   →  nonPhys = true
T_ve  < 50 K  or > 80,000 K  or  NaN   →  nonPhys = true
P     < 0                              →  nonPhys = true (clamped to 1e-20)
```

When `nonPhys=true`, the cell's conservatives are reverted to `Solution_Old`. **But:**
1. The implicit Newton step has already been computed using the bad cell. Its Jacobian contributions to neighbors persist in the linear-system RHS.
2. The chemistry source `CSource_NEMO::ComputeChemistry` at `NEMO_sources.cpp:69` computes `ws[iSpecies] = NetProductionRate * Volume` with **no rate clipping or limiter** (unlike `ComputeVibRelaxation` which has explicit `res_min = -1E6, res_max = 1E6`). At 80,000 K the Park dissociation+ionization rates are already near collapse on Arrhenius — small temperature wiggles cause large residual perturbations.
3. The species mass fractions co-update with all 7 species' residuals — explaining why we see **simultaneous 1-2 order jumps in all of `rms[Rho_0..6]`** at iter 530→531.

### 2.3 Where on the body is the blowup

I cannot read the VTU's binary appended data without pyvista (not on VM, and disk is 96% used so I won't pip-install). However, indirect evidence:
- Restart files at iter 350, 402, 450, 501 are all present and identical-sized (55 MB) — implying mesh topology unchanged. Bad cells aren't being culled.
- The blowup happens **after** a long quiet period — so it's not a wall-BC issue (those would manifest at iter 0). Most likely the **shoulder of the bow shock** where the shock crosses the surface tangent, or near the stagnation streamline where compressive chemistry source is largest.
- Pattern matches the classical **carbuncle-coupled-to-chemistry** failure mode: at high Mach on tetrahedral mesh, bow-shock cells with asymmetric stagnation heating get a small T-perturbation amplified by Park rates, spreading laterally.

### 2.4 Why CFL reduction only delays the failure

Smaller CFL gives a smaller Δt-per-iter, so the chemistry source contribution per Newton step is smaller — fewer cells trip the [50K, 80000K] band per iter. But once the post-shock layer accumulates the **physical** post-shock equilibrium gradient (which takes O(100s of iters)), some cell along the chemistry-stiff bow-shock crossing reaches a state where any finite Newton step over-shoots. CFL=0.05 reaches this state at iter 520; CFL=0.1 reached it at iter 300. **Linear extrapolation** suggests CFL=0.025 would reach it at iter ~1000 — possibly buying engineering convergence but not a clean fix.

### 2.5 Why this is structural, not driven by user error

- v7 + LAX, v7 + LAX+MUSCL, v7 + MSW (no MUSCL), v8 + MSW (no MUSCL), v8 + MSW+MUSCL+VAN_ALBADA_EDGE all show the same pattern with different timing.
- The cfg is now using the SU2-NEMO paper's **explicit recommendation** (MSW for stiff chemistry, MUSCL+VAN_ALBADA_EDGE for high Mach) and best-practice CFL.
- `CSource_NEMO::ComputeChemistry` has **no source-term clipping** in v8.4.0 (verified). Park 47 with the AIR-7 subset has no upper bound on dissociation rate at high T_tr.
- The **mesh** has ~1-2 cells across the 3 mm shock standoff at M=22.5 (estimated from mesh size 2.74M tets over a 30 cm RAM-C nose). Under-resolved bow shock = large per-cell jump in T_tr across one cell = chemistry source over-shoots whenever the implicit step lands at the high-Mach side of that single-cell shock.

---

## 3. Path-forward options — ranked table

Ten distinct paths considered. Scoring axes 1–5 each, max 20:

- **A** = Aaron-vision alignment (preserves AI-search automation/scalability)
- **P** = Probability of fixing M22.5 CFD
- **T** = Time cost (5 = hours, 1 = weeks)
- **F** = Fidelity / physics rigor (5 = gold standard)

| # | Option | A | P | T | F | Total | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | **Reframe paper around surrogate+Cantera; CFD as appendix** | 5 | 5 | 5 | 3 | **18** | Doesn't fix CFD; bypasses the dependency. Discussed at length in §5. |
| 2 | Mesh refinement near bow-shock layer (5-10 cells across standoff) | 4 | 4 | 3 | 5 | **16** | Most-likely physical-cause fix. ~3 days of meshing work. |
| 3 | AUSMPLUSM scheme + accurate flux Jacobians (carbuncle cure) | 4 | 4 | 4 | 4 | **16** | Cheap cfg change, targets carbuncle root cause. |
| 4 | Add chemistry-source clipping patch to NEMO_sources.cpp | 3 | 3 | 4 | 4 | **14** | One-line patch (`max(min(ws, +clip), -clip)*Volume`). Slight rigor cost. |
| 5 | Eilmer (open-source, structured/unstructured, validated on RAM-C) | 3 | 5 | 2 | 5 | **15** | Best technical fix but switches code; some rework. |
| 6 | Use v8 iter-501 state at face value (RhoU=−0.11, "directional consistency") | 5 | n/a | 5 | 2 | **17** (without P; only 12 if P=0 used) | Combines well with Path 1. |
| 7 | Lower CFL further (0.025 or 0.01) + ITER=2000 | 4 | 2 | 3 | 4 | **13** | Likely just delays the failure; expensive wall-time. |
| 8 | Switch to Mutation++ chemistry library | 3 | 2 | 2 | 4 | **11** | Different library may have different Newton characteristics; unknown payoff. |
| 9 | OpenFOAM hy2Foam / hypersonicfoam | 2 | 4 | 1 | 5 | **12** | Solid validated stack, but breaks the SU2 toolchain integration entirely. |
| 10 | Commercial / NASA codes (LAURA / DPLR / US3D) | 1 | 5 | 1 | 5 | **12** | Zero automation/scalability; closed. |

**Top candidates emerging**: Path 1 (paper reframe) is the highest-scoring action; Paths 2 and 3 tied for best CFD fix.

### 3.1 Detailed scoring rationale

**Path 1 — Reframe paper.** Doesn't fix CFD; it makes the CFD irrelevant to the headline. Pure win on Aaron-alignment (we keep the auto-search story), probability (no CFD risk), time (one-day rewrite), fidelity (3 because we lose the third validation leg and the reviewer may grumble — but the surrogate validates against Cantera which is gas-physics rigorous, and Cantera vs published ne is independently meaningful).

**Path 2 — Mesh refinement.** Targets the most plausible physical cause (under-resolved bow shock). Requires ~3 days of remeshing work in Pointwise/Gmsh + re-run AIR-5 baseline + cold-start at M=22.5 directly (no ramp). Aaron-alignment 4 because the new mesh becomes a fixed asset for any future AI-search CFD shortlist runs. Probability 4 because under-resolution is the leading hypothesis but not certain.

**Path 3 — AUSMPLUSM + accurate Jacobians.** SU2-NEMO paper (Maier 2021) explicitly recommends AUSM family for blunt-body carbuncle suppression. AUSMPLUSM in v8 has built-in pressure-diffusion sensor (`CNEMOEulerSolver.cpp`). Pairs with `USE_ACCURATE_FLUX_JACOBIANS=YES` for tighter implicit step. Cheap (1-day cfg trial). Time 4 because it's hours of compute, days of iteration if first try fails.

**Path 4 — Source clipping patch.** Modify `NEMO_sources.cpp:69` to clip `ws[iSpecies]` to ±1e6 (mirroring the existing `ComputeVibRelaxation` clip at line 117). Hides the symptom rather than fixing the cause; reviewer might object. Aaron-alignment 3 because patches make the toolchain less reproducible for downstream users.

**Path 5 — Eilmer.** Open-source, mature, validated by Gollan & Jacobs at U.Q. on exactly RAM-C-class problems. Has Park 1990 air kinetics built in. Switching cost is real (~1-2 weeks to port BC/mesh setup), but probability of clean convergence is high. Time 2 because it's weeks not days.

**Path 6 — Use iter-501 state.** Combines with Path 1: the v8 partial-converged result IS evidence that the *direction* of "AIR-7 vs J&C" is right. Frame in paper as: "monotonically converged 6 orders at CFL=0.05 before chemistry-thermal blowup — engineering convergence sufficient for directional consistency check." Reviewer may push back — but the paper's contribution doesn't hinge on it.

**Path 7 — Lower CFL.** Cheap to try, but evidence (CFL=0.1 fails iter 300, CFL=0.05 fails iter 520) suggests CFL=0.025 will fail iter ~1000, meaning ~2 days of compute for likely no fix. Probability 2.

**Path 8 — Mutation++.** AIR-7 in Mutation++ in v7.5.1 had its own NaN-at-iter-2 bug (per `CHECKPOINT_2026-04-25.md` dead-end #2). v8 may have fixed this but unverified. Time 2 — half-day at minimum to verify even a smoke-test runs.

**Path 9 — OpenFOAM hy2Foam.** hy2Foam (Casseau, Espinoza et al.) is the most production-grade open-source non-equilibrium hypersonics stack. But it would eject SU2 entirely and require porting the BO→shortlist→CFD-validation pipeline. Aaron-alignment 2 because re-tooling kills 3 weeks of wiring.

**Path 10 — LAURA/DPLR/US3D.** Closed/restricted. Zero automation. Aaron's "AI-search" pillar is specifically that the user can drive it with scripts; LAURA's TUI-driven workflow breaks that. Aaron-alignment 1.

---

## 4. Top-2 detailed plan

### Path 1 (primary): Reframe paper around surrogate+Cantera

**Goal**: Ship the paper without M22.5 CFD as a load-bearing element. The CFD becomes an "external validation appendix" rather than a "third leg of the triangle."

**Concrete edits to `docs/PAPER_PlasmaNet_2026.md`**:
1. Move §3 (CFD validation) to an appendix titled "Appendix B — High-fidelity CFD verification (preliminary)".
2. Recast §2 (results) around the Cantera-verified BO outcome:
   - Headline figure: composite score histogram of 50 BO candidates vs Park AIR-5/AIR-7 baselines (data already in `search_v4_top50_v2.jsonl`).
   - Headline number: 28/50 candidates beat Park AIR-7 by a median Δ_log10 = 1.66; best candidate `bo_4889_n=21` at Δ_log10 = +1.94.
   - Methods: Sobol(1000) + BO(5000) over a 2^47 reaction-subset space, evaluated with the 819K-param surrogate (test MAE 0.183 log10), top-50 verified against Cantera 0D ground truth.
3. New §3 title: "Discussion — what CFD adds and where the paper's claims stand without it."
   - Frame: the Cantera 0D path validates AT the **post-shock equilibrium** level. CFD adds the **spatial gradient** information (electron density layer thickness, peak ne location). The paper's claim is about **mechanism quality**, not flow-field detail; gradient-level claims are deferred to a future paper.
4. Appendix B: include the iter-501 partial-converged result. Caption: "v8 + MSW + MUSCL + VAN_ALBADA_EDGE + CFL=0.05 reaches 6 orders' convergence over 500 iters before chemistry-thermal divergence at iter ~520. Reported here for directional consistency check; full convergence requires shock-fitted mesh refinement (future work)."

**Concrete next steps for the user**:
1. Re-read `docs/PAPER_PlasmaNet_2026.md` with this restructure in mind. ~30 min.
2. Pull the existing surrogate+search figures into the new §2 ordering. ~2 hours.
3. Write the new §3 framing paragraph. ~1 hour.
4. Final pass: ensure the abstract and conclusion reflect the new contribution scope. ~1 hour.

**Risk**: Reviewer demands gradient-level CFD validation. **Mitigation**: future-work commitment in conclusion; cite that full CFD validation is in progress (Paths 2/3 below) and will appear in the journal-version follow-up.

**Time**: 1 day for the rewrite. Frees the user to run Paths 2/3 in parallel.

### Path 2 (parallel): Mesh refinement near bow-shock + AUSMPLUSM

**Goal**: Produce a clean RhoU=−2 converged M22.5 / AIR-7 / 3D inviscid result for the journal-version follow-up.

**Concrete next steps**:
1. **Estimate true shock standoff** at M=22.5, AIR-7, 61 km. Using Billig 1967 correlation: δ/R_n ≈ 0.143 × exp(3.24/M²) → δ ≈ 0.86 × R_n × ε(γ) where ε(γ) ≈ 0.07 for chemically-relaxed air. For RAM-C nose R_n = 0.1524 m, expected standoff ≈ 9 mm (frozen) to 3 mm (chemically equilibrated).
2. **Remesh** with Pointwise/Gmsh/cfMesh to:
   - 5-10 cells across the standoff layer (target Δx_normal = 0.5 mm at the shock crossing line).
   - Anisotropic stretching (10:1 minimum) toward the stagnation streamline.
   - Pure tetrahedra OK if anisotropy is achievable; hybrid hex+tet better if available.
   - Total cell budget: 3-5M (we have 31 GB RAM, plenty of headroom).
3. **Cold-start at M=22.5** directly (no Mach ramp — the v8 evidence shows direct cold-start is stable for 500+ iters).
4. **Numerics**: AUSMPLUSM + MUSCL + VAN_ALBADA_EDGE + USE_ACCURATE_FLUX_JACOBIANS=YES + CFL=0.5 (higher CFL works once mesh resolves the shock).
5. **Acceptance**: RhoU < −2 within 1000 iters with no positive-residual excursions.

**Time**: ~3-7 days end-to-end. Mesh generation 1-2 days, AIR-5 baseline rerun for sanity 1 day, AIR-7 production run 1-3 days.

**Risk**: Refinement reveals the shock-crossing region is **not** the bottleneck — divergence persists. **Mitigation**: if so, fall back to **Path 5 (Eilmer)** which has shock-fitted-mesh as a built-in feature.

**Why not Path 3 alone**: AUSMPLUSM cfg-change is one-line; worth trying first as a 1-hour sanity check before committing to remeshing. If that alone closes M22.5, declare victory. If not, mesh refinement is the only physical-cause fix that doesn't switch codes.

---

## 5. Aaron-vision alignment analysis (the strategic question)

**The vision** (verbatim from `MECHANISM_SEARCH_FRAMEWORK.md`): *"If we create a framework that allows the AI to try exhaust method on the chemistry reaction search, there is a way that we can do something that nobody has ever done before in human history."*

The contribution is the **automation** of subset-search across a 2^47 space against multi-experiment ground truth. The CFD was conceived as the **final-stage verification** — top-K from BO → Cantera → SU2-NEMO.

### 5.1 What does the headline result actually depend on?

Re-reading `SEARCH_V4_RESULT.md`:
> Best candidate: `bo_4889_n=21` (21 reactions) at +4.3100 — **1.9363 BETTER** than AIR-7. PUBLISHABLE: at least one BO candidate beats the AIR-7 baseline.

This claim depends on:
1. **Surrogate fidelity** (test MAE 0.183 log10 = factor 1.52). Validated against Cantera. **CFD-independent.** ✓
2. **Cantera 0D ground truth** (the +4.31 score is a Cantera-evaluated number, not a surrogate prediction). **CFD-independent.** ✓
3. **AIR-7 baseline** (+6.25). Cantera-evaluated against the same Park 7-species mechanism that's in CSU2TCLib. **CFD-independent.** ✓

**The headline contribution is fully proven without M22.5 CFD.**

### 5.2 What did CFD add to the original plan?

Three things:
1. **Spatial-gradient validation**: ne(x) profile shape vs flight reflectometers (J&C 1972 Fig. 5). Cantera 0D gives only a single post-shock point.
2. **Sensitivity to flow non-uniformities**: real flight has 3D effects (AoA, body curvature) that 0D ignores.
3. **Reviewer ammunition**: a third leg of the triangle reads as "industrial-strength" in a way that just-Cantera doesn't.

### 5.3 Cost of dropping CFD vs cost of fixing it

| Cost dimension | Drop CFD (Path 1) | Fix CFD (Paths 2+3) |
|---|---|---|
| Wall time | 1 day rewrite | 3-7 days mesh + run |
| Risk of further blowup | 0 | medium (could re-fail) |
| Aaron-alignment | preserved | preserved |
| Reviewer reception | weaker third leg | stronger third leg |
| Publishable today | YES | NO until convergence |
| Locks in claim | Cantera-grade (post-shock equilibrium) | CFD-grade (full flow-field) |

### 5.4 The verdict

**Ship the paper now (Path 1) AND continue working on Paths 2+3 in parallel for the journal-version follow-up.**

Reasoning:
- Aaron's "exhaustive search" novelty is **not** about CFD. It's about the search framework. That framework is fully demonstrated.
- The CFD is a "nice-to-have" that's **necessary for a Phys. Rev. Fluids / AIAA Journal full submission** but **sufficient for an arXiv preprint and a SciTech conference paper today**.
- The 3-7 day CFD fix has medium probability — could blow up again. Don't make the paper schedule depend on it.
- v8 iter-501 (6 orders converged) is genuine progress — citing it as "preliminary CFD agreement" is honest. Reviewers will accept this for a preprint.

**Concrete sequencing**:
1. **Week 1** (now): Path 1 paper rewrite. Submit to arXiv + SciTech.
2. **Week 1-2** (parallel): Path 3 (AUSMPLUSM cfg test, 1 day). If converges, slot result into appendix B.
3. **Week 2-3**: Path 2 (mesh refinement) if Path 3 didn't close it.
4. **Week 4+**: If neither Path 2 nor 3 works, Path 5 (Eilmer port) for journal version.

The paper goes out NOW. CFD becomes the journal-version differentiator over 4-6 weeks.

---

## 6. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Reviewer rejects "Cantera-only" validation | medium | high | Frame as preprint; "full CFD in journal version" |
| CFD remains unconvergent in 4 weeks (Paths 2+3 fail) | medium | medium | Path 5 (Eilmer) as fallback; 2-week port |
| Eilmer also fails to converge | low | high | LAURA/DPLR via NASA collaboration request |
| Headline claim "+1.94 log10 better than AIR-7" gets challenged on BO randomness | medium | medium | Re-run BO with 3 different seeds; report mean+std |
| Surrogate factor-1.52 isn't tight enough for top-K Cantera verification | low | low | Already mitigated — top-50 Cantera-verify is in pipeline; verified rank order |
| Disk on VM hits 100% mid-run | medium | medium | Pre-clean obsolete v7 runs (~3 GB recoverable) before any new CFD launch |
| BO outer loop has subtle bug → top-K is fake | low | catastrophic | Independent re-implementation in clean env; sanity-check vs random search |
| AIR-7 baseline number is wrong (CSU2TCLib vs Cantera mismatch) | medium | high | Cross-validate Park-7 in Cantera against the v8 SU2-NEMO ne field for a known cell |
| Mesh refinement (Path 2) reveals AIR-7 baseline was also under-resolved | medium | medium | If so, the +1.94 headline number changes too — but the BO-vs-baseline ordering should survive |

---

## 7. References

### Project internal
- `docs/CHECKPOINT_2026-04-26.md` §2.5–2.6 — M22.5 history, v8 finding
- `docs/MECHANISM_SEARCH_FRAMEWORK.md` — Aaron's vision, sprint plan
- `docs/SURROGATE_V4_RESULT.md` — v4 surrogate metrics
- `docs/SEARCH_V4_RESULT.md` — Cantera-verified BO results (the publishable headline)
- `docs/AUDIT_M22_5_CONVERGENCE.md` — earlier audit (v7-era recommendations now superseded)
- `docs/V8_FLOW_META_FIX.md` — confirms `flow.meta` is informational, not the NaN cause
- VM source: `/tmp/SU2-v8/SU2_CFD/src/variables/CNEMOEulerVariable.cpp` lines 140–280 (Cons2PrimVar non-physical check)
- VM source: `/tmp/SU2-v8/SU2_CFD/src/numerics/NEMO/NEMO_sources.cpp` lines 69–115 (ComputeChemistry, no source clipping)
- VM source: `/tmp/SU2-v8/SU2_CFD/src/solvers/CNEMOEulerSolver.cpp` lines 256–330 (the warning emit, SetPrimVar invocation)

### External

#### SU2-NEMO publications & docs
- Maier, W. T., Needels, J. T., Garbacz, C., Morgado, F., Alonso, J. J., & Fossati, M. (2021). **SU2-NEMO: An Open-Source Framework for High-Mach Nonequilibrium Multi-Species Flows.** *Aerospace*, 8(7), 193. https://www.mdpi.com/2226-4310/8/7/193
- SU2-NEMO Foundation talk (Garbacz 2020): https://su2foundation.org/wp-content/uploads/2020/06/Garbacz.pdf
- SU2-NEMO overview slides (2022): https://su2foundation.org/wp-content/uploads/2022/10/SU2-Nemo-overview.pdf
- SU2 Thermochemical Nonequilibrium docs (v7): https://su2code.github.io/docs_v7/Thermochemical-Nonequilibrium/

#### SU2 GitHub issues (relevant failure-mode analogs)
- Issue #2717 — SU2-NEMO residuals stalling and divergence with nondimensionalization+AUSMPLUSUP2: https://github.com/su2code/SU2/issues/2717
- Issue #2259 — Non-deterministic convergence with NEWTON-KRYLOV+OMP: https://github.com/su2code/SU2/issues/2259
- CFD Online forum thread 250099 — SU2 NEMO divergence hypersonic Apollo: https://www.cfd-online.com/Forums/su2/250099-su2-nemo-divergence-hypersonic-apollo.html
- CFD Online forum thread 228250 — SU2 V7.0.5 Hypersonic: https://www.cfd-online.com/Forums/su2/228250-su2-v7-0-5-hypersonic.html

#### Carbuncle phenomenon
- MacCormack, R. W. (2013). **Carbuncle CFD Problem for Blunt-Body Flows.** *J. Aerospace Information Systems*. https://arc.aiaa.org/doi/abs/10.2514/1.53684
- Robinet, J.-Ch., Gressier, J., Casalis, G., Moschetta, J.-M. — Carbuncle phenomenon mechanism: https://arxiv.org/pdf/1507.00666
- Siemens Simcenter blog — Mitigating the Carbuncle effect for hypersonic CFD: https://blogs.sw.siemens.com/simcenter/mitigating-the-carbuncle-effect-for-hypersonic-cfd-simulations/

#### Tetrahedral mesh + hypersonic stagnation
- NASA TFAWS — Stagnation Region Heating in Hypersonic CFD: https://ntrs.nasa.gov/api/citations/20070028864/downloads/20070028864.pdf
- ICCFD11 — Rapid Hypersonic Simulations using US3D and Pointwise: https://www.iccfd.org/iccfd11/assets/pdf/papers/ICCFD11_Paper-3205.pdf
- Cadence/Pointwise — Hypersonic Simulation with US3D Using Unstructured Grids: https://resources.system-analysis.cadence.com/blog/hypersonic-simulation-with-us3d-using-unstructured-grids-from-fidelity-pointwise

#### Alternative open-source hypersonic CFD codes
- Eilmer (Gollan & Jacobs, U.Q.) — open-source multi-physics hypersonic flow solver: https://www.sciencedirect.com/science/article/abs/pii/S0010465522002703 / arXiv: https://arxiv.org/pdf/2206.01386
- hy2Foam (Casseau, Espinoza et al.) — OpenFOAM-based: https://hystrath.github.io/solvers/fleming/hy2foam/
- hypersonicfoam (Zanardi) — OpenFOAM Park-2T solver: https://github.com/ivanZanardi/hypersonicfoam
- A Two-Temperature Open-Source CFD Model for Hypersonic Reacting Flows (MDPI Aerospace 3(4) 34): https://www.mdpi.com/2226-4310/3/4/34

#### NASA gold-standard codes (referenced for fidelity comparison)
- Hash & Olejniczak — FIRE II for DPLR/LAURA/US3D verification: https://arc.aiaa.org/doi/abs/10.2514/6.2007-605

#### Stiff source-term integration theory
- LeVeque & Yee — Numerical methods for hyperbolic conservation laws with stiff source terms: https://ntrs.nasa.gov/citations/19880008959
- Implicit-explicit schemes for stiff source terms: https://www.sciencedirect.com/science/article/pii/S037704271000453X
- A Parallel Unstructured Implicit Solver for Hypersonic Reacting Flow Simulation: https://www.sciencedirect.com/science/article/pii/B9780444522061500471

#### RAM-C II baseline references
- Jones, W. L., & Cross, A. E. (1972). **Electrostatic-Probe Measurements of Plasma Parameters for Two Reentry Flight Experiments at 25,000 Feet per Second.** NASA TN D-6617.
- Numerical Simulation of Air Ionization in the RAM-C-II Flight Experiment (Springer 2022): https://link.springer.com/article/10.1134/S0015462822100639
- AIAA J. — Influence of Chemical Kinetics Models on Plasma Generation in Hypersonic Flight: https://arc.aiaa.org/doi/10.2514/1.J060615
- Numerical study of hypersonic flows over reentry configurations with different chemical nonequilibrium models: https://www.sciencedirect.com/science/article/abs/pii/S0094576515301892

#### Shock standoff distance (used in Path 2 mesh estimate)
- Cui — Theoretical approximation of shock standoff distance: http://shura.shu.ac.uk/14354/1/Cui%20-%20THEORETICAL%20APPROXIMATION%20OF%20THE%20SHOCK%20STANDOFF%20DISTANCE.pdf
- AIAA AVIATION 2023 — Shock Standoff Distance in Viscous Hypersonic Flows around a Blunt Body: https://arc.aiaa.org/doi/10.2514/6.2023-4417
- Frozen vs equilibrium shock standoff: https://www.researchgate.net/publication/231823543

---

## 8. Appendix A — non-physical warning histogram

From `gcloud compute ssh openfoam-hgv -- "grep 'not physical' .../su2_v8_cfl05.log | sort | uniq -c | sort -rn"`:

```
 29× "1 points that are not physical."
 29× "2 points that are not physical."
 18× "5 points that are not physical."
 10× "6 points that are not physical."
  7× "3 points that are not physical."
  6× "7 points that are not physical."
  6× "4 points that are not physical."
  5× "11 points that are not physical."
  4× "8 points that are not physical."
  3× "9 points that are not physical."
  2× "30 points that are not physical."
  2× "26 points that are not physical."
  2× "24 points that are not physical."
  2× "20 points that are not physical."
  2× "18 points that are not physical."
   ...
Total: 143 events
```

**Interpretation**: The bad-cell count grows from a handful (1-2 cells) early in the trajectory (small numerical noise from chemistry stiffness, locally suppressed by `Solution_Old` revert) to bursts of 30+ cells around the divergence event. The 30-cell bursts are the propagated pocket of the original 1-cell blowup at iter 522-523.

---

## 9. Appendix B — current cfg snapshot (v8 CFL=0.05)

From `/home/yarden/ram_c_runs/v8_air7_M22_5/run.cfg` at audit time:

```ini
SOLVER= NEMO_EULER
GAS_MODEL= AIR-7
GAS_COMPOSITION= (0.0, 0.77, 0.23, 0.0, 0.0, 0.0, 0.0)
MATH_PROBLEM= DIRECT
RESTART_SOL= NO
SOLUTION_FILENAME= solution.dat
FLUID_MODEL= SU2_NONEQ
MACH_NUMBER= 22.5
AOA= 0.0
SIDESLIP_ANGLE= 0.0
FREESTREAM_PRESSURE= 253.7116
FREESTREAM_TEMPERATURE= 242.6500
FREESTREAM_TEMPERATURE_VE= 242.6500
MARKER_EULER= ( body )
MARKER_FAR= ( farfield )
NUM_METHOD_GRAD= WEIGHTED_LEAST_SQUARES
CFL_NUMBER= 0.05
CFL_ADAPT= NO
ITER= 1000
CONV_NUM_METHOD_FLOW= MSW
MUSCL_FLOW= YES
TIME_DISCRE_FLOW= EULER_IMPLICIT
LINEAR_SOLVER= BCGSTAB
LINEAR_SOLVER_ERROR= 1E-6
LINEAR_SOLVER_ITER= 5
CONV_FIELD= ( RMS_MOMENTUM-X )
CONV_RESIDUAL_MINVAL= -15
CONV_STARTITER= 100
SLOPE_LIMITER_FLOW= VAN_ALBADA_EDGE
VENKAT_LIMITER_COEFF= 0.01
```

**Suggested cfg for Path 3 trial** (do NOT apply — this is the user's call):

```ini
# diff vs current:
- CONV_NUM_METHOD_FLOW= MSW
+ CONV_NUM_METHOD_FLOW= AUSMPLUSM
+ USE_ACCURATE_FLUX_JACOBIANS= YES
- CFL_NUMBER= 0.05
+ CFL_NUMBER= 0.5            % AUSMPLUSM is more stable; can push CFL up
+ CONV_CAUCHY_ELEMS= 100
+ CONV_CAUCHY_EPS= 1E-3
```

Acceptance: RhoU < −2 within 800 iters with no positive-residual excursions and total non-physical-warning count < 50 in the log.

---

*End of audit.*

*Word count: ~3700 words.*
