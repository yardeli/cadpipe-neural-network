# S-3 Surrogate v3 — Training on 76K examples

## Summary

PlasmaNet mechanism-axis surrogate trained on 76,022 valid Cantera 0D
evaluations. **Test MAE = 0.586 log10 → median prediction within factor
of 3.85 of truth.** Usable for design-time screening, not production
search.

## Training data

- 76,022 valid examples from collect_surrogate_training_data_v2.py
- Pre-filtered to mechanisms with ≥1 dissociation + ≥1 ionization
- 4 RAM-C benchmarks × 3 residence times × random mechanism size 5..40
- log10(ne) range: 10.8 to 25.0 (14 orders of magnitude!)

## Model

- 4-layer dense MLP, 256 hidden units, SiLU activation, BatchNorm
- Input: 4 freestream features + 47 mechanism bits = 51-d
- Output: log10(ne) scalar
- Optimizer: AdamW (lr=1e-3, weight_decay=1e-4)
- Schedule: cosine annealing, eta_min=1e-5
- Early stopping on val plateau (patience 20)
- 70/15/15 train/val/test split

## Results

| Set | Examples | MSE (log10²) | MAE (log10) | Factor of |
|-----|----------|--------------|-------------|-----------|
| Train | 53,215 | 0.68 | — | — |
| Val | 11,403 | 1.27 | — | — |
| Test | 11,404 | 1.19 | 0.59 | ~4× |

Reference mechanism predictions vs J&C 1972 published (2.0e19 m⁻³ at
RAM-C 61km/M22.5):

| Mechanism | Surrogate ne | log10 err vs J&C |
|-----------|-------------|------------------|
| Park_AIR5 | 2.43e17 | −1.92 (under, expected — no ionization) |
| Park_AIR7 | 4.53e19 | +0.36 (factor of 2.3) |
| Park_AIR11 | 1.28e21 | +1.81 (over) |

The AIR-7 prediction at +0.36 log10 vs J&C is competitive with direct
Cantera 0D evaluation. AIR-11 over-predicts because Park_AIR11 in our
representation includes all 47 reactions including aggressive
ionization paths that the Cantera surrogate over-equilibrates at the
training residence times.

## Use cases

| Use case | Surrogate good enough? | Why |
|----------|----------------------|-----|
| Engineering screening of 1M candidates | YES | factor-of-4 is fine for ranking |
| Bayesian-search inner loop | YES | inference at 0.01ms vs 50ms |
| Sensitivity analysis ("which reactions matter?") | YES | bit-flip impact is the gradient |
| Final candidate selection for design | NO | use Cantera 0D direct |
| Production CFD anchor | NO | needs <0.5 log10 |

## Path to <0.5 log10 (deferred)

1. **More data**: 500K examples (5-10 hours of VM compute) → est ±0.3 log10
2. **Graph NN architecture**: encode reaction connectivity → est ±0.2 log10
3. **Multi-task learning**: predict ne + T_e + per-species mole fractions
   jointly → improves regularization

## What this enables NOW

The `register_surrogate_evaluator(model, name='plasmanet_v3')` function
wires the trained model into the scoring framework. From there:

```python
results = genetic_search(
    base_mechanism=PARK_47,
    evaluator='plasmanet_v3',  # 0.01ms/eval
    budget=100_000,             # vs 1000-eval budget with Cantera
    benchmarks=['ram_c_61km_M22.5'],
)
```

100K-evaluation search runs in ~1 second instead of ~50 minutes. Top-K
from this can then be CFD-validated via S-5 (in development).
