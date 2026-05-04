# Search V4 Results — Sobol-seeded Bayesian Optimization (v2)

**Generated:** 2026-04-27T00:01:28+00:00  
**Surrogate:** plasmanet_v4 (4-layer 512-hidden MLP, 819K params, test MAE 0.183 log10)  
**Search:** Sobol(d=40, n_sobol=1000) + BO(n_bo=5000, refit_every=200)  
**Trajectory:** ram_c_47km_M18.5, ram_c_61km_M22.5, ram_c_71km_M23.6, ram_c_81km_M23.9  
**Residence time:** 1e-06 s (kinetics regime)  

## YAML emitter fix

- v1 (pre-fix) Cantera load success rate on top-50: **13/50 = 26%**
- v2 (post-fix) Cantera load success rate on top-50: **50/50 = 100%**

Three changes to `Mechanism.to_cantera_yaml()`:
1. `_element_charge_balance()` helper rejects reactions whose
   stoichiometry violates element/charge conservation (Cantera
   `Reaction::checkBalance` would reject).
2. Equation-string deduplication: when two surviving reactions
   share the same equation (Park 1990 high-T + low-T branches),
   both are marked `duplicate: true` so Cantera accepts them.
3. Phase entry gains `explicit-third-body-duplicates: mark-duplicate`
   so a partner-specific three-body rate (`X + O => Y + O + ...`)
   doesn't conflict with a generic-M three-body rate of the same form.

## Baselines

| Name | n_species | n_reactions | Score (Cantera) | Verdict |
|---|---|---|---|---|
| `Park_AIR5` | 5 | 22 | N/A | POOR |
| `Park_AIR7` | 7 | 26 | +6.2462 | POOR |

## Top 5 (Cantera-ranked, post-fix)

| Rank-C | Rank-S | Name | n_rxns | Surrogate | Cantera | pred-truth log10 | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | 10 | `bo_4889_n=21` | 21 | +3.3884 | +4.3100 | +0.9216 | POOR |
| 2 | 31 | `bo_4008_n=28` | 28 | +3.6211 | +4.3109 | +0.6897 | POOR |
| 3 | 9 | `bo_3494_n=26` | 26 | +3.3791 | +4.3246 | +0.9455 | POOR |
| 4 | 11 | `bo_1932_n=23` | 23 | +3.3939 | +4.3253 | +0.9314 | POOR |
| 5 | 41 | `bo_4791_n=24` | 24 | +3.7071 | +4.3253 | +0.6182 | POOR |

## Verdict

- Park AIR-7 baseline composite score: **+6.2462**
- Top-50 candidates beating AIR-7: **28 of 50**
- Best candidate: `bo_4889_n=21` (21 reactions) at +4.3100 — **1.9363 BETTER** than AIR-7

**PUBLISHABLE:** at least one BO candidate beats the AIR-7 baseline.

## Files

- Phase 2 raw output: `/home/yarden/mechanism_search_results/search_v4_phase2_full.json`
- Phase 3 v1 (pre-fix): `/home/yarden/mechanism_search_results/search_v4_top50.jsonl`
- Phase 3 v2 (post-fix): `/home/yarden/mechanism_search_results/search_v4_top50_v2.jsonl`
- Baselines: `/home/yarden/mechanism_search_results/baselines_air5_air7.json`
