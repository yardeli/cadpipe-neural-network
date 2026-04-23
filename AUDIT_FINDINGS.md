# PlasmaNet / Cadpipe Hypersonics — Independent Audit Findings

**Audit date:** 2026-04-23
**Scope:** physics, code, methodology, claim consistency
**Repos audited:**
- `C:\Users\yarden\Desktop\Khorium Hypersonics\plasmanet\` (PlasmaNet neural surrogate)
- `C:\Users\yarden\Desktop\cadpipe\` (Cadpipe hypersonics tool)

**Executive summary.** The underlying physics formulations are mostly correct and the methodology correction documented in `Hypersonic_Chemistry_Initial_Findings.docx` is sound. However, I found **four issues that invalidate specific claims in the README and overview documents**, plus several minor physics bugs and documentation inconsistencies. Most serious: (1) the "clean" training data and the code that nominally generates it have drifted out of sync — running `generate_data.py` today would NOT reproduce `training_clean_5k.npz`; (2) the activation energies in `air_plasma_11s.yaml` are in the wrong units for Cantera; (3) the three DRGEP result files on disk give contradictory findings, only one of which matches the README claim; (4) the overview docx still carries retracted claims in its executive summary.

---

## 1. Physics Errors

### 1.1 Saha partition functions for N and O⁺ — WRONG statistical weights (minor, verified bug)

**Files:** `plasmanet/plasmanet/physics.py:233–242`

The code claims partition functions come from "NIST Atomic Spectra Database" but uses wrong statistical weights for the excited terms of atomic nitrogen and ionized oxygen. Neutral O and ionized N are correct.

| Species | State | Correct g (NIST ASD) | Code g | Location |
|---------|-------|----------------------|--------|----------|
| N I     | ²D° (at 27670 K) | 10 (= 6+4) | 6 | `physics.py:239` |
| N I     | ²P° (at 41500 K) | 6 (= 4+2)  | 2 | `physics.py:239` |
| O II    | ²D° (at 38600 K) | 10 (= 6+4) | 6 | `physics.py:235` |
| O II    | ²P° (at 58250 K) | 6 (= 4+2)  | 2 | `physics.py:235` |

NIST ASD gives, for example for O II: ⁴S°_{3/2} (g=4), ²D°_{5/2} (g=6), ²D°_{3/2} (g=4), so the combined ²D° statistical weight is 10, not 6 — same pattern for the others.

**Impact:** At T = 10,000 K the ne contribution from O and N ionization is under-predicted by ~3–5%; at T = 15,000 K the error grows to ~7%. Below ~8,000 K NO⁺ dominates ne and this error is negligible. Classification results (BLACKOUT/DETECT at Mach 10 around 35 km) are not changed. Still worth fixing since the README claims NIST values.

### 1.2 US Standard Atmosphere 1976 — only 5 of 7 regimes implemented

**Files:** `plasmanet/plasmanet/physics.py:31–55`, mirrored in `cadpipe/agents/hypersonic_cfd_agent.py:60–80`

The docstring and README state "Valid 0-60 km" and "5 regimes". USSA76 has **7 regimes up to 86 km**. The code's final `else` branch lumps everything ≥ 47 km into the stratopause (isothermal T=270.65 K), missing:
- 51–71 km mesosphere 1 (lapse −2.8 K/km)
- 71–84.85 km mesosphere 2 (lapse −2.0 K/km)

**Impact at relevant altitudes:**
- h = 55 km: code T = 270.65 K, correct T = 259.45 K (Δ ≈ 4%)
- h = 60 km: code T = 270.65 K, correct T = 245.45 K (Δ ≈ 10%)

`generate_data.py:32` samples `alt_range=(15, 55)`, so ~7% of training points (51–55 km slice) see a slightly wrong freestream T. Small effect on stagnation T, larger effect on freestream density. Fix is straightforward — add two more branches.

### 1.3 Air gas constant R_AIR = 287.058 J/(kg·K) — minor precision

`physics.py:20` uses R_AIR = 287.058. The ICAO/USSA76 standard value is **287.0528 J/(kg·K)** (from R_u/M_air_dry with M_air_dry = 0.0289644 kg/mol). Five-significant-figure agreement, fine for all downstream results. Flagging only because the file presents itself as NIST-grade.

### 1.4 Troposphere pressure exponent minor

`physics.py:40` uses `(T/288.15)^5.2561`. Derived value is 5.2559 (USSA76 Table 4, and from g₀·M_air/(R·L) = 9.80665·0.0289644/(8.31432·0.0065)). The 5.2561 value is also widely cited and originates from a slightly different choice of M_air. Difference is < 10 ppm in p at sea level. Not a problem.

### 1.5 Plasma frequency formula — CORRECT

`physics.py:318–322` exactly matches fp = (1/2π)·sqrt(ne·e²/(mₑ·ε₀)). I verified the derived blackout threshold: 12 GHz corresponds to ne = **1.787e18 m⁻³**, matching the README's quoted 1.78e18. The overview docx's shortcut `fp ≈ 8.98·√ne Hz` also checks out (the coefficient is e/(2π√(mₑε₀)) = 8.976).

### 1.6 Physical constants

All 2019 SI-defining constants (k_B, m_e, h, e, c, ε₀) are correct to at least 10 significant figures (`physics.py:13–18`). Ionization energies (`physics.py:23–25`) match NIST ASD to the precision stated: NO 9.2642 eV (NIST: 9.26438 eV), O 13.61806 eV (NIST: 13.618055 eV), N 14.53414 eV (NIST: 14.53414 eV). ✓

### 1.7 JANAF Kp tables

`physics.py:133–154` includes O2, N2 dissociation, NO formation tabulated log10(Kp). Spot-checked against Chase (1998) JANAF 4th ed.:
- O2 ↔ 2O at 5000 K: Chase log10(Kp) = +0.12 → code 0.1 (close enough given 500-K spacing).
- N2 ↔ 2N at 5000 K: Chase log10(Kp) = −5.06 → code −5.0. ✓
- NO formation at 3000 K: Chase log10(Kp) = −2.0 → code −2.03. ✓

---

## 2. Code Bugs

### 2.1 CRITICAL: "Clean" training data is not reproducible from current code

**Files involved:** `plasmanet/plasmanet/physics.py:268–315`, `plasmanet/plasmanet/generate_data.py:84–94`, `plasmanet/plasmanet/physics.py:411–412`, `plasmanet/data/training_clean_5k.npz`

Empirical test — I called `full_analysis()` on the exact (Mach, alt, nose_r) inputs stored in `training_clean_5k.npz` and compared the returned `ne_m3` to the stored `ne_m3`:

| Test index | T_stag | nose (m) | Stored ne_m3 | Reproduced ne_m3 | Reproduced ne_equil_m3 | stored / equil |
|------------|--------|----------|--------------|------------------|------------------------|----------------|
| 2000       | 4177 K | 0.018    | 2.556e21     | **2.557e18**     | 2.557e21               | **1.000**      |
| 1000       | 6284 K | 0.744    | 3.484e23     | 3.431e23         | 3.485e23               | 1.000          |
| 100        | 1268 K | 0.074    | 6.835e-2     | 6.880e-2         | 6.880e-2               | 0.993          |
| 500        | 1816 K | 0.012    | 1.856e11     | 7.744e10         | 7.744e10               | 2.396*         |

(*Index 500 has T < 3500 K so NEQ guard is inactive; the ~2x discrepancy there is a different issue with low-T Cantera equilibrium vs something else — possibly a JANAF/Cantera divergence.)

At index 2000 the result is unambiguous: `stored / ne_equil_m3 = 1.000` exactly, while `stored / reproduced_with_NEQ = 1000`. **The NPZ file contains raw Cantera equilibrium, but the current `full_analysis()` at `physics.py:412` applies `nonequilibrium_correction()`** before writing `result["ne_m3"]`. `generate_data.py:94` takes `result["ne_m3"]` and never stores `result["ne_equil_m3"]`.

So the README claim (`README.md:22–23, 146–147, 155`) that "training_clean_5k.npz has no NEQ correction" is **true for the file as it sits on disk**, but it is **not reproducible** — running `python -m plasmanet.generate_data --n-points 5000 --output data/training_clean.npz` today would overwrite it with NEQ-corrupted values. This is exactly the regression the README says was fixed.

**Required fix (pick one):**
1. In `physics.py:411–412`, gate the NEQ call behind an explicit kwarg; have `generate_data.py` pass `apply_neq=False`.
2. Or add `ne_equil_m3` to the NPZ arrays in `generate_data.py:128–144` and have `prepare_data` in `model.py` read it as the training target.
3. Or delete the NEQ call from `full_analysis()` entirely and only apply NEQ downstream of inference in `serve.py`/UI as an "approximate correction" overlay.

The same bug exists in `plasmanet/plasmanet/extract_cfd_results.py:154, 173` — CFD-derived training points would also be contaminated.

### 2.2 CRITICAL: `air_plasma_11s.yaml` activation energies are in the wrong units

**File:** `cadpipe/mechanisms/air_plasma_11s.yaml:212–324`

Every `Ea:` field contains Park's **activation temperature θ (in Kelvin)** but the inline comment claims `cal/mol`. Cantera YAML defaults activation energy units to cal/mol when no file-level `units:` block is declared, which is the case here (no `units:` anywhere in the file).

Example — O2 + M ↔ 2O + M (line 226):
```yaml
rate-constant: {A: 2.0e+21, b: -1.5, Ea: 59750}  # cal/mol
```
Park (1993) Table 1 gives θ_d = 59,500 K for O2 dissociation. The correct cal/mol value is θ·R = 59500 · 1.987 = **118,226 cal/mol**. The 59750 figure matches Park's θ (in K), not his energy.

Proof that the author meant K: the **same numbers** are used verbatim in `cadpipe/agents/hypersonic_cfd_agent.py:840` as `Ta: 59500` inside an OpenFOAM `reversibleArrheniusReaction` block — and in OpenFOAM `Ta` is **activation temperature in K**. Same for every other reaction (113200 for N2, 75500 for NO dissoc, 38370 for Zeldovich, 31900 for R6, 158500 for R12, 168600 for R13 — these are all Park θ values).

**Impact on reported results:** None so far, because every quantitative claim in the docs comes from *equilibrium* Cantera runs (Gibbs minimization uses thermodynamic data only, ignoring rate constants — the file itself notes this at lines 206–208). But:
- Any **finite-rate** use of this mechanism — including the claimed "transient DRGEP on 0D Cantera reactor" — will run with rate constants ~10²–10³× too fast at T = 5000–10,000 K.
- That in turn means the DRGEP transient-reactor findings (R2 dominates 87–95%) may be ranking reactions whose rates are all scaled by the wrong factor. The ordering happens to survive if all rates are scaled ~uniformly, but bath gas collision-partner reactions scale differently than bimolecular electron-impact ones, so the *relative* importance can shift.

**Fix:** add to the top of the YAML file:
```yaml
units: {length: cm, quantity: mol, activation-energy: K}
```
(`activation-energy: K` is valid per Cantera's supported units; alternatively use `cal/mol` and multiply every Ea by 1.987.)

### 2.3 `reaction_search.py` does not actually modulate the chemistry

**File:** `cadpipe/agents/reaction_search.py:600–628`

Despite the README's description of `reaction_search.py` as being "fixed to modulate chemistry", `run_plasmanet_condition_adaptive_search()` computes the reference ne using the full mechanism (`equilibrium_air_plasma(T_stag, p_stag)` at line 616) and then applies hardcoded scaling heuristics:

```python
if "NOp" in removed_ions:
    ne_reduced *= 0.1  # only 10% from other paths
elif removed_ions:
    ne_reduced *= max(0.5, 1.0 - 0.1 * len(removed_ions))
```

This is the exact leave-one-out pathway-existence methodology the chemistry-findings doc explicitly retracted (`Hypersonic_Chemistry_Initial_Findings.docx` §2). The function `compute_ne_error_for_mechanism` (same file, line 195) does do species-level masking through Cantera, but `run_plasmanet_condition_adaptive_search` bypasses that path.

If any figure in the docs still came from `run_plasmanet_condition_adaptive_search`, it carries the retracted methodology. I recommend either deleting this function or rewriting it to use the proper Cantera masking path.

### 2.4 Minor: `read_vtu_fields` swallows errors silently

**File:** `plasmanet/plasmanet/extract_cfd_results.py:26–32`

```python
try:
    mesh = meshio.read(vtu_path)
except ValueError:
    import warnings
    warnings.filterwarnings("ignore")
    mesh = meshio.read(vtu_path)
```

The fallback re-calls the same function with the same arguments and with warnings suppressed. If meshio raised `ValueError`, it will raise again — the "fallback" accomplishes nothing except hiding warnings from the retry. The comment "try reading with a fallback that skips bad fields" doesn't match what the code does. Either implement an actual field-skipping fallback or delete the except clause.

### 2.5 Minor: `model.py` evaluate_model uses same tensor for norm-X and raw-Y

**File:** `plasmanet/plasmanet/model.py:286–287`

```python
_, _, Y_test_raw = splits["test"]
X_test_norm, _, _ = splits["test"]
```

Harmless (the tuple is destructured the same way both times), but the two-line form is misleading. Cleaner:
```python
X_test_norm, _, Y_test_raw = splits["test"]
```

### 2.6 Minor: `ne` is silently clamped to [1, 1e26] in model.py

**File:** `plasmanet/plasmanet/model.py:122–125, 142`

```python
ne_clamped = np.clip(ne, 1.0, 1e26)
...
valid_mask = (data["T_stag_K"] <= 20000) & (log10_ne <= 26) & (log10_ne >= 0)
```

`training_clean_5k.npz` contains ne_m3 up to 5.87e+28 and T_stag up to 27,546 K (verified empirically). The mask filters extrapolation outliers. This is reasonable but worth documenting: the stored NPZ extends well beyond the physically valid region of the model, and ~O(10²) points per 5k are silently dropped. Counter the "5000 clean points" framing — the effective training size is slightly smaller.

---

## 3. Methodology Concerns

### 3.1 The three DRGEP files on disk tell three different stories

**Files:**
- `plasmanet/data/drgep_transient_results.json` (the one claimed valid by README)
- `plasmanet/data/drgep_complete_map.json`
- `plasmanet/data/drgep_condition_adaptive_map.json`

Only `drgep_transient_results.json` shows the claimed "R2 dominates 87–95%" pattern. The other two contradict it:

| Temperature | transient_results R2 | complete_map dominant | condition_adaptive (by Mach) R2 |
|-------------|---------------------|-----------------------|----------------------------------|
| 3000 K      | 0.885               | **R13 = 0.564**       | (Mach 8) 0.987                  |
| 5000 K      | 0.915               | **R3 = 0.508**        | (Mach 10) 0.884                 |
| 7000 K      | —                   | **R1 = 0.728**        | (Mach 12) 0.129 (R12=0.625)     |
| 10000 K     | 0.0 (empty)         | R13 = 0.33            | (Mach 15) 0.0066 (R13=0.931)    |
| 15000 K     | 0.0 (empty)         | **R5 = 0.602**        | (Mach 18) — (R13=0.956)         |

Three runs, three rankings. The README statement ("N2 dissociation dominates 17–95% across all temperatures, peak complexity at Mach 15 with 6 reactions") is a paraphrase of `drgep_complete_map.json` (which shows ≥4 essential reactions per T, peaking at 6 at T=10000K) — but `drgep_complete_map.json` does **not** show R2 dominant; it shows R3 dominant at 3500–5000 K and R1 dominant at 6000–8000 K. Meanwhile the "R2 dominates 87–95%" text matches `drgep_transient_results.json`, which is empty for T ≥ 10000 K (the README itself acknowledges this gap: "chemistry equilibrates in <100ns, can't sample rates").

**What to do:** designate one file as the source of truth, delete or archive the other two with a README note. If the transient-reactor result is the intended source of truth, then the README's "peak complexity at Mach 15 (6 reactions)" claim needs to come from elsewhere, because `drgep_transient_results.json` never reports that.

### 3.2 No DRGEP implementation file on disk

I searched for any `drgep*.py` in the plasmanet repo and found **none** (only the JSON outputs). The README describes DRGEP as "Our implementation validated on transient reactor" (`README.md:25`) and "Custom DRGEP working" (`README.md:25`). That implementation is either:
- Uncommitted / outside the repo
- In a notebook
- Inline inside `reaction_search.py`, where as I noted in §2.3 the condition-adaptive function is not actually doing graph-based DRGEP — it's leave-one-out with hardcoded scale factors

Without the implementation I can't verify the "custom DRGEP validated on transient 0D reactor" claim. Recommend committing whatever script produced `drgep_transient_results.json`.

### 3.3 NEQ correction as currently coded is a *single-geometry* curve fit dressed up as geometry-aware

**File:** `plasmanet/plasmanet/physics.py:268–315`

The README explicitly acknowledges this (`README.md:147` "Calibrated for one geometry (80mm blunt cone) against RAM-C. Never validated for other shapes"). The fix on disk is "Removed from training data. Applied only at inference, flagged as approximate." Per §2.1, the first half of that fix (remove from training data) is **not actually in the code path**, though it is in the NPZ file. Needs to be synchronized.

The Damkohler-ratio scaling `factor_base ** (1/Da_ratio)` for sharp noses (line 312) produces factors as small as ~1e-4 at Da_ratio=0.22 — a 3-order-of-magnitude correction based on a heuristic fit that has zero calibration support below R_nose=0.08 m. If this is kept as an "approximate" output, the serve layer should not return it as a point estimate; it should be returned with an explicit "calibration validity: R_nose = 0.08 m ± TBD" flag.

### 3.4 The methodology-correction argument is sound

`Hypersonic_Chemistry_Initial_Findings.docx` §2–3 correctly identifies the issue:
- **Leave-one-out measures pathway existence, not rate importance.** Correct. Analogous to ablating a gene to discover it is needed, then concluding the gene is the "rate-limiting step" of the organism.
- **DRGEP on equilibrium data measures numerical noise.** Correct and provable from detailed balance — at equilibrium, every elementary reaction's net rate of progress is identically zero, so any non-zero number is roundoff.
- **Transient 0D reactor has real net rates during the approach to equilibrium.** Correct; this is the standard DRGEP use case.

The physics reasoning in the document is clean. My only concern is the one flagged in §3.1 — the transient result doesn't extend above T=8000 K, yet the README extrapolates the "R2 dominates" claim to all temperatures.

### 3.5 "325 → 2 reactions" and "R06 dominates 90%" are correctly retracted in Chemistry_Initial_Findings.docx, but the **Engineers Overview docx still contains the retracted claim in its executive summary**

**File:** `Hypersonic_Overview_For_Engineers_Updated.docx`, Executive Summary paragraph (first paragraph after "Executive Summary"):

> "We built the first AI-driven chemistry search pipeline for hypersonic plasma prediction, proving that only 2 of 325 chemical reactions capture 96-100% of the plasma physics at flight conditions."

This is the retracted claim. The same document says later in §3 "Initial analysis suggested only 2 Zeldovich exchange reactions were essential, but subsequent methodology review revealed this result was based on equilibrium analysis where the question 'which reactions matter?' has no meaningful answer."

Also in the status table in §3 of the same docx:
> | Component | Status | Detail |
> | GRI-Mech reduction | WORKING | 53->7 species, 325->2 reactions via Cantera/pyMARS |

This row should be marked "RETRACTED", not "WORKING".

These two internal contradictions in the same document will be the first thing an external reviewer (e.g., an AFRL SBIR reader) catches.

---

## 4. Claims That Don't Match Reality

| # | Location | Claim | What's Actually True |
|---|----------|-------|----------------------|
| 1 | `README.md:23, 147, 155` | "Clean training data (no NEQ correction)" + "Run `generate_data.py` to produce it" | File on disk *is* clean, but `generate_data.py` produces NEQ-corrupted data (§2.1). Not reproducible. |
| 2 | `README.md:117, 174` | "Park (1993) + Gupta (1990). 13 reactions." with the implication the mechanism is runnable | Reactions are there but with wrong activation-energy units for Cantera (§2.2). Only equilibrium use is functional. |
| 3 | `README.md:25` | "Custom DRGEP working" | Implementation not on disk; I could not verify. `reaction_search.py`'s condition-adaptive function uses the retracted leave-one-out-with-hardcoded-scaling approach (§2.3, §3.2). |
| 4 | `README.md:22` | "0.32 orders ne MAE on clean data" | Not reproducible without the true training+eval script run; value comes from a checkpoint referenced as `plasmanet_clean_v1.pt` that was trained on an NPZ produced by a code version that no longer exists in the tree. Suggest re-running evaluation once §2.1 is fixed and re-reporting. |
| 5 | `README.md:134` | "Peak mechanism complexity at Mach 15 (10000K) where 6 reactions are needed" | Sourced from `drgep_complete_map.json`, but that file does not show R2 dominance — contradicts the rest of the paragraph (§3.1). |
| 6 | `Hypersonic_Overview_For_Engineers_Updated.docx` exec summary | "Only 2 of 325 reactions capture 96-100% of physics" | Retracted elsewhere in the same document (§3.5). Must be removed from the exec summary for consistency. |
| 7 | `Hypersonic_Overview_For_Engineers_Updated.docx` §3 table | "GRI-Mech reduction — WORKING — 53->7 species, 325->2 reactions via Cantera/pyMARS" | Status should be RETRACTED or REDOING (§3.5). |
| 8 | `plasmanet/plasmanet/physics.py` docstring | "Valid 0-60 km" | Correct to 51 km only; 51–60 km has a ~5–10% T error (§1.2). |
| 9 | `README.md:118` | "Partition functions: NIST ASD" | N and O⁺ excited-state degeneracies are wrong (§1.1). |
| 10 | `Notion_Project_Overview.md:43` vs `README.md:97–98` | "45,000 Cantera simulations" vs "training_clean_5k.npz" | Clarified elsewhere that 45k was the old dirty dataset and 5k is the new clean one — not a contradiction but easy to misread. Make this explicit. |

---

## 5. Recommendations (Prioritized)

### Must-fix before any external reviewer sees this

1. **Decide on and enforce the "clean data" contract** (§2.1). Either store `ne_equil_m3` separately in the NPZ, or gate `nonequilibrium_correction` behind a flag, or move NEQ out of `full_analysis` entirely. Then regenerate `training_clean_5k.npz` with the corrected pipeline and check that it is byte-identical to the current file. Until this is done, the training is not reproducible.

2. **Fix `air_plasma_11s.yaml` units** (§2.2). Add a file-level `units: {length: cm, quantity: mol, activation-energy: K}` block. This is a one-line fix. Without it, any future finite-rate work with this mechanism (including confirming the transient-DRGEP finding) silently uses wrong rates.

3. **Reconcile the three DRGEP files** (§3.1). Pick one as authoritative, move the others to `data/archive/` with a short README explaining why, and correct any README claim that was synthesized across them.

4. **Remove the "325 → 2 reactions" claim from the Engineers Overview exec summary and status table** (§3.5). It's already retracted on page 5 of the same document; leaving it on page 1 looks careless to a reviewer.

### Should-fix

5. **Fix the N and O⁺ partition-function degeneracies** (§1.1). Five-minute edit; eliminates a ~5% ne error at 10,000–15,000 K.

6. **Extend `standard_atmosphere` to 71 km** (§1.2). Ten lines; lets you honestly claim "valid 0–71 km" and covers the full HGV cruise envelope.

7. **Commit the actual DRGEP implementation** (§3.2). Whatever script produced `drgep_transient_results.json` should be in the repo with tests.

8. **Either remove or rewrite `run_plasmanet_condition_adaptive_search` in `reaction_search.py`** (§2.3). As coded it applies exactly the methodology that was retracted.

### Nice-to-have

9. Surface `ne_equil_m3` alongside `ne_m3` in `full_analysis()`'s dict (§2.1). Having both makes future audits easier and lets the serve layer flag NEQ-correction uncertainty.

10. Add a unit test that regenerates a handful of training points and checks byte-identity against `training_clean_5k.npz`. This would have caught §2.1 immediately.

11. The overview docx's "AI chemistry sensitivity — NO ionization energy identified as critical parameter" result is good and worth keeping — but the claim in §4 of the docx that this analysis ran on "actual SU2/Eilmer Mach 10 temperature and pressure fields, not theoretical conditions" should cite the specific file/run. It's currently unverifiable from the repo.

---

## 6. What's Solid and Worth Keeping

Not everything is broken — several parts are in good shape and should not be changed:

- **Plasma frequency formula and blackout threshold** (§1.5). Exact and correct.
- **SI-defining physical constants** (§1.6). All 2019 values, correct to the precision given.
- **Ionization energies** (§1.6). Match NIST ASD.
- **JANAF Kp fallback tables** (§1.7). Match Chase (1998) within table interpolation error.
- **Saha formulation** (the equation itself, `physics.py:220–265`). Correct Saha pre-factor, correct factor-of-2 for electron spin, correct self-consistent iteration for weak ionization with neutral depletion.
- **Cantera use for equilibrium** (§2.2 impact note). Because Cantera equilibrium uses Gibbs energy, not rates, the wrong-units bug doesn't invalidate any equilibrium result that has been computed and reported.
- **Methodology correction in `Hypersonic_Chemistry_Initial_Findings.docx`**. The reasoning about why equilibrium DRGEP fails (detailed balance forces all net rates to zero) and why leave-one-out conflates pathway existence with rate importance is correct and well-explained. That document is the cleanest piece of thinking in the project — use it as the template for the paper revision.
- **PlasmaNet architecture and training loop** (`model.py`). Architecture matches README description (4 inputs → 64-128-128-64 hidden → 9 outputs, SiLU, BatchNorm, 5% dropout, AdamW, cosine anneal, early stopping, MC-dropout uncertainty). MSE with hand-tuned weights on log10(ne) (5×), T_stag (2×), fp (2×), status (2×) is a reasonable choice. No bugs found here.
- **The detection envelope (BLACKOUT ≥ Mach 10 at 35–40 km)** is consistent across Cantera, SU2, Eilmer, and PlasmaNet and does not depend on any of the bugs above.

---

## 7. Deliverables Summary

- **2 physics bugs requiring edits** (Saha degeneracies, USSA76 upper regimes)
- **2 critical code bugs requiring edits** (NEQ in generate_data pipeline; Cantera YAML units)
- **1 retracted-methodology bug in reaction_search.py**
- **3 inconsistent DRGEP result files requiring triage**
- **2 documents with internal contradictions** (README overstatement vs code; Engineers Overview exec summary vs §3 retraction)
- **Numerous minor issues** (error-swallowing, misleading variable destructuring, soft clamps, precision-level constant values)

None of the findings invalidate the project's headline result — that StarLink (12 GHz Ku-band) cannot detect a Mach-10+ HGV below ~40 km altitude. The physics underlying that claim is sound. But the chain of reproducibility from the NPZ file → the training script → the documented methodology is broken at two places, and the supporting claims around mechanism reduction need tightening before publication.
