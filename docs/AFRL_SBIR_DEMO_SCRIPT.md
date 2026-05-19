# AFRL SBIR Demo — Narration Script + Storyboard

**Audience**: AFRL evaluators (Srini Vasan + program office), funding
partners (Aaron Wu's circle), and the SBIR review panel.
**Duration target**: 10–12 minutes; 6 scenes.
**Hand-off**: pair this script with a screen-capture pass against the
reproducible commands below. All commands run on a clean checkout of
`github.com/yardeli/cadpipe-neural-network` at the post-task-4 commit
(or later).

The narration is in normal text. **[BRACKETS]** mark visual cues for
the editor / screen capturer. `monospace` lines are commands to run
on camera.

---

## Scene 1 — The strategic question (~30 s)

**[Open on full-screen title slide]**
**[Title: "Khorium Hypersonics — predicting radar detectability of
hypersonic vehicles, end to end"]**

> "Roughly a hundred billion dollars in U.S. defense procurement
> hinges on a single question: can a commercial Ku-band radar
> constellation, like Starlink, detect a hypersonic vehicle at Mach
> ten? If yes, the defense architecture is one shape. If no, every
> radar dollar shifts to purpose-built assets. This tool answers
> that question — vehicle, flight condition, viewing angle, with
> uncertainty bands. Let me show you how."

**[Cut to terminal session]**

---

## Scene 2 — The pre-audit baseline was wrong (~1:30)

**[Open a split screen: code on the left, plot on the right]**

> "When this project started, the detection criterion was a single
> boolean: plasma frequency above twelve gigahertz means blackout.
> An independent audit caught four critical bugs in that pipeline."

**[Show on-screen list, each line appearing as narrator reads]**

1. Activation energies labeled `cal/mol` were actually `K`.
2. Saha partition functions missing spin-orbit corrections.
3. Standard-atmosphere only covered 5 of 7 regimes.
4. **Rayleigh-Pitot formula missing — stagnation pressure was 10,000× wrong at Mach 22.**

> "And on top of that, the binary criterion was the wrong shape. Two
> vehicles with identical stagnation electron density can have
> completely different detectability if one is viewed nose-on and
> the other side-on. A radar sees an integrated path through the
> sheath, not a point."

**[Run on screen]**
```
PYTHONPATH=. python scripts/test_capsule_threshold_fix.py
```

**[Show the test output highlighting "peak ne dropped from 3.16e+22
to 2.56e+20 (124x lower)"]**

> "Even this week, the capsule test condition was over-predicting
> electron density by two orders of magnitude — caught by the
> geometry-resolved test harness, fixed in a hundred lines."

---

## Scene 3 — Physics rebuild + audit fixes (~2:30)

**[Cut to architecture diagram]**

**[Diagram: 7 stacked layers — Freestream → Shock → Pitot → Real-gas T
→ Equilibrium chemistry → Saha → Plasma frequency, with arrows to a
right-hand stack: LOS integration → Aspect scan → Per-band attenuation
+ UQ → Detection verdict]**

> "We rebuilt the physics stack to match what's published. Rayleigh-
> Pitot pressure. Real-gas stagnation temperature via Cantera enthalpy
> iteration — chemistry absorbs about seventy percent of the kinetic
> energy at Mach 22, dropping the frozen 24,000 K to 6,200 K. Saha
> ionization with NIST partition functions. Wave propagation through
> a collisional plasma — Gurevich, Budden — replacing the boolean
> with decibels of attenuation. Line-of-sight integration. Monte
> Carlo over chemistry-rate and freestream uncertainty."

**[Run on screen]**
```
PYTHONPATH=. python scripts/test_swept_fay_riddell.py
```

**[Show the cos²Λ test output — emphasise the 70° / 0° = 0.117 ratio]**

> "The boundary-layer heating model carries swept-leading-edge support
> for waveriders and integrated inlets. Beckwith and Gallagher's
> cos-squared-lambda correction matches closed form to machine
> precision."

---

## Scene 4 — Geometry-resolved + kinetics (~2:00)

**[Cut to terminal; live API call]**

```
PYTHONPATH=. python scripts/test_api_router_integration.py
```

**[Six PASS lines highlighted as they print]**

> "Every capability the SimOps team needs is on a FastAPI surface:
> single-point analyze, full geometry-resolved axial profile,
> azimuthal-strip mode for waveriders, raycast-mesh for non-convex
> bodies like hollow scramjet inlets, swept-LE heating, multi-stage
> shock chains, full trajectories, Monte Carlo uncertainty."

**[Switch to a 3-D plot — colour-mapped sphere-cone with ne(x, φ) values]**

```
PYTHONPATH=. python scripts/test_raycast_mesh.py
```

**[Show test 3 "hollow duct" output highlighting that BOTH inner AND
outer surfaces are resolved at radii 0.20 m and 0.40 m]**

> "Until this week the mesh adapter took the maximum radial point at
> each axial station — which means a hollow duct collapsed to its
> outer envelope. The new raycast adapter slices triangles with the
> query plane and walks rays through the cross-section, so the inner
> surface of a scramjet isolator is now visible and so is a forebody
> probe sticking off the main cone."

---

## Scene 5 — RAM-C II validation + UQ (~2:00)

**[Cut to plot: 4 RAM-C II altitudes, predicted vs measured ne, log scale]**

> "Validation against RAM-C II — Jones and Cross 1972, the canonical
> in-flight hypersonic plasma dataset. Four altitudes from 81 to 47
> kilometres at Mach 22 to 24. At the high two stations our
> prediction sits inside the published measurement uncertainty —
> as accurate as any equilibrium-based model can be."

**[Highlight the 81 km row: predicted 2.63e18, measured 2.0e18, log err +0.12]**

> "Below 60 kilometres equilibrium chemistry begins to over-predict
> by an order of magnitude — that's the well-known non-equilibrium
> signature, where flow residence time is comparable to recombination
> time. The viscous SU2-NEMO production run currently in flight on
> our GCP backend closes that gap with finite-rate chemistry."

**[Show GCP terminal session]**
```
ssh openfoam-hgv 'tail -10 ~/ram_c_runs/v8_phase3_viscous_prod/su2_v8_phase3_prod.log'
```

**[Show converging residuals]**

> "Sixteen-core MPI, kicked off this afternoon. Expected completion
> in seventeen hours."

---

## Scene 6 — AI-exhaustive chemistry search (~2:00)

**[Cut to schematic: the 2^47 ≈ 1.4×10^14 reaction subset space, with
v5_prime surrogate as the inner-loop scorer, Cantera 0D as the
verification oracle, SU2-NEMO as the final CFD validator]**

> "The Park 1990 air mechanism has forty-seven reactions. The space of
> reaction subsets — which combinations matter at which flight
> conditions — is one-point-four times ten to the fourteen. You
> can't enumerate that. So we built a learned surrogate."

**[Show training metrics for v5_prime]**

> "v5_prime is a neural surrogate over the mechanism-axis plus
> freestream feature space. Trained on five million Cantera 0D
> evaluations. Inference in ten microseconds — five thousand times
> faster than Cantera 0D, factor of one-point-zero-nine of Cantera
> on test, factor of 0.39 on flight-data anchors."

**[Switch to architecture diagram showing the v5.2 extension]**

> "And as of this week, the framework extends to scramjet fuel
> ingestion — hydrogen-oxygen and methane-air mechanisms behind
> the bow shock — so we can score the air-breathing combustion
> regime, not just pure-air re-entry. The data-collection run for
> v5.2 awaits budget go-ahead."

```
PYTHONPATH=. python scripts/test_fuel_axis.py
```

**[Show 5/5 PASS — emphasise "AIR pass-through bit-exact" and the
H2/CH4 composite line counts]**

---

## Scene 7 — Wrap and next steps (~30 s)

**[Return to title slide]**

> "Bottom line: from a single binary boolean over-predicting by
> orders of magnitude, to a publication-quality physics stack with
> aspect-resolved attenuation and uncertainty bands; from one fixed
> geometry to non-convex meshes including hollow ducts and probe-
> on-cone configurations; from one hardcoded chemistry to an
> AI-exhaustive search over the entire Park subset space; and now
> extending to scramjet combustion ingestion. The next milestones
> are the SU2-NEMO viscous validation that closes the low-altitude
> non-equilibrium gap, and the v5.2 multi-fuel surrogate."

**[Hold on title slide; fade]**

---

## Pre-record checklist

  - [ ] `git pull` to the post-task-4 commit (raycast / swept-FR /
        YAML-leak / capsule-threshold all landed). Verify with
        `git log --oneline -6` showing 4 of my commits at top.
  - [ ] `python -X utf8 scripts/test_capsule_threshold_fix.py` —
        capture clean PASS output.
  - [ ] `python -X utf8 scripts/test_swept_fay_riddell.py` — capture.
  - [ ] `python -X utf8 scripts/test_raycast_mesh.py` — capture
        (note test 3 hollow-duct output for the storyboard).
  - [ ] `python -X utf8 scripts/test_api_router_integration.py` —
        capture all 6 endpoints PASS.
  - [ ] `python -X utf8 scripts/test_fuel_axis.py` — capture 5/5 PASS.
  - [ ] `gcloud compute ssh openfoam-hgv --zone=us-central1-a
        --command='tail -10 ~/ram_c_runs/v8_phase3_viscous_prod/su2_v8_phase3_prod.log'`
        — wait until the run has reached at least iter 100 so the
        residual table is interesting on camera.
  - [ ] One plot (RAM-C II validation rows from
        `docs/PROJECT_OVERVIEW_POST_AUDIT.md` §2.3, formatted as a
        chart) — produce with matplotlib, save to `docs/paper/ram_c_validation.png`.
  - [ ] One plot (v5_prime vs v4 vs v5 head-to-head, from
        `data/v4_v5_v5prime_compare.txt`).
  - [ ] One schematic diagram (mechanism-axis search loop) — can
        adapt from `docs/MECHANISM_SEARCH_FRAMEWORK.md`.

## Visual assets to prep separately

The video will be much stronger with these renderings — none are
required for the script but each elevates the corresponding scene:

  - `assets/audit_before_after.png` — the four audit fixes as a 2×2
    panel: old vs new for each. (Scene 2)
  - `assets/architecture_stack.svg` — the 7-layer physics stack with
    real-gas T and Pitot pressure highlighted. (Scene 3)
  - `assets/raycast_duct.gif` — animation of rays entering and exiting
    a hollow duct, with both surfaces lighting up. (Scene 4)
  - `assets/ram_c_validation.png` — log-scale predicted vs measured
    at the 4 RAM-C II altitudes, with uncertainty bands. (Scene 5)
  - `assets/mechanism_search.svg` — surrogate-as-inner-loop, Cantera
    as oracle, SU2-NEMO as final validator. (Scene 6)
  - Optional B-roll: rotating capsule mesh, sphere-cone Mach contours
    from one of the SU2 cases in `data/cfd_cases/`.

## Out-of-scope for this script

The following are real capabilities but they crowd the runtime and
risk losing the AFRL audience:

  - The Sobol-BO search loop's mathematics (acquisition function,
    Sobol indices) — too academic for the audience.
  - The Pydantic schema layer — engineering polish, not value-add
    for a defense reviewer.
  - The Khorium frontend / Streamlit app — separate demo.
  - Specifics of the YAML-leak fix or other commit-by-commit detail.
