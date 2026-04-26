# S-3 Surrogate Training Result (2026-04-26)

## Summary

PlasmaNet mechanism-axis surrogate training pipeline works end-to-end. The
trained model itself is NOT accurate enough for production search use.

## Training data

| Source | Examples | ne range (m⁻³) |
|--------|----------|----------------|
| sweep results (8 dirs × 5-10 candidates) | 80 | 1.6e15 .. 2.8e23 |
| collect_surrogate_training_data.py (full grid) | 307 | 2.4e14 .. 6.1e23 |

Both datasets span 9 orders of magnitude in ne — broad coverage of
mechanism behavior across altitude × residence time × random reaction
subsets.

## Trained model performance

| Run | Examples | Val MSE | Effective error (log10) |
|-----|----------|---------|------------------------|
| v1 (80 examples, 200 epochs) | 80 | 2.03 | ±1.43 |
| v2 (307 examples, 300 epochs) | 307 | 3.66 | ±1.91 |

The v2 result is WORSE than v1 even with more data. Diagnosis: v1 used
top-K examples (already-good candidates from GA); v2 used random subsets
including many that produce ne=0 or ne=1e23. The data is too noisy.

## Why this happened

1. **Class imbalance**: Many random Park-47 subsets have NO ionization
   channels, giving ne ≈ 0 (machine zero) regardless of conditions.
2. **Numerical artifacts**: Some stiff Cantera subsets diverge to
   ne ≈ 1e23 m⁻³, which is unphysical (saturated post-shock equilibrium).
3. **Architecture mismatch**: A dense 4-layer MLP doesn't naturally
   encode the structure of "this reaction must be present for any
   prediction to be meaningful." A graph neural net or attention-based
   model would be a better fit.

## Path to a usable surrogate

If we want sub-0.5-log10 surrogate accuracy:

1. Collect ~10K examples filtered to:
   - Only mechanisms with ≥1 associative-ionization reaction
   - Only mechanisms with ≥1 dissociation channel
   - Drop ne values outside [1e10, 1e22] m⁻³ as numerical outliers
2. Use multi-task learning: predict (ne, T_e, mole_fractions) jointly
3. Switch to graph neural net architecture:
   - Each reaction is a node
   - Connectivity from species sharing
   - Output is a single scalar per (mechanism, conditions)
4. Train with attention to which reactions matter (cf. SHAP/LIME)

This is a 1-2 week ML research project. Scoped OUT of the current
mechanism-search MVP.

## What this means for the framework

The framework still works **without** the surrogate:
- Cantera 0D evaluator: ~50 ms/eval, ~1000 evals/min
- GA search budget realistically 1K–10K evaluations
- Wall time per search: 1–10 minutes
- More than enough for design-iteration use cases

The surrogate is a NICE-TO-HAVE for:
- Million-evaluation searches (real-time interactive UI)
- Bayesian optimization that needs many candidate evaluations
- Multi-vehicle / multi-condition batch screening

For now, marking S-3 as **scaffolded but not delivered**. Framework's
primary path is Cantera 0D + GA → CFD-validate top-K via S-5.
