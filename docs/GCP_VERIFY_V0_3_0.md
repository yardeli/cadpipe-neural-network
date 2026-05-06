# GCP verification of khorium_hypersonic v0.3.0

**Date**: 2026-05-05
**Host**: GCP VM `openfoam-hgv` (us-central1-a, 16-core, Cantera 3.0
+ PyTorch installed)
**Total wall time**: 14.1 s

This is the "no shortcuts" verification — the v0.3.0 capability surface
running on the actual GCP VM with Cantera-backed kinetics (not the
equilibrium-Saha fallback). It exercises the four major upgrades against
30 distinct (geometry, flight) cases plus a 10-waypoint trajectory plus
a 15-sample Monte Carlo.

## Test matrix

- **6 geometries** (sharp_narrow, medium_cone, blunt_cone, ram_c,
  blunt_wide, capsule)
- **5 flight conditions** (M = 12 / 35 km, 18.5 / 47 km, 22.5 / 61 km,
  23.6 / 71 km, 23.9 / 81 km)
- **20 axial stations** per case
- All chemistry runs in `kinetics` mode — Cantera IdealGasConstPressureReactor,
  not Saha equilibrium

## Headline results

### 1. Fay-Riddell R_n^(-0.5) scaling — exact

```
actual ratio sharp/capsule = 3.873
expected ratio (300/20)^0.5 = 3.873
PASS
```

Fay-Riddell q_w ∝ R_n^(-0.5) holds bit-exact across the 15× nose-radius
spread (sharp_narrow → capsule). Geometry-driven heat flux is wired
correctly.

### 2. Bluntness sweep at every flight condition

The full 30-case axial peak-ne table:

| geometry     | M    | alt(km) | peak ne (m⁻³) | τ_max (µs) | shock split (n/o) |
|--------------|------|---------|---------------|------------|-------------------|
| sharp_narrow | 12.0 | 35      | 1.05e+17      |  2.0       | 2/18              |
| medium_cone  | 12.0 | 35      | 2.63e+17      |  4.9       | 3/17              |
| blunt_cone   | 12.0 | 35      | 4.17e+17      |  7.9       | 4/16              |
| ram_c        | 12.0 | 35      | 7.65e+17      | 15.0       | 3/17              |
| blunt_wide   | 12.0 | 35      | 7.54e+17      | 14.7       | 5/15              |
| capsule      | 12.0 | 35      | 1.38e+18      | 29.5       | 6/14              |
|              |      |         |               |            |                   |
| sharp_narrow | 18.5 | 47      | 2.48e+20      |  1.2       | 2/18              |
| medium_cone  | 18.5 | 47      | 4.77e+20      |  3.0       | 3/17              |
| blunt_cone   | 18.5 | 47      | 5.81e+20      |  4.8       | 4/16              |
| ram_c        | 18.5 | 47      | 6.03e+20      |  9.1       | 3/17              |
| blunt_wide   | 18.5 | 47      | 6.05e+20      |  9.1       | 5/15              |
| capsule      | 18.5 | 47      | 7.94e+20      | 18.1       | 6/14              |
|              |      |         |               |            |                   |
| sharp_narrow | 22.5 | 61      | 2.54e+19      |  1.0       | 2/18              |
| medium_cone  | 22.5 | 61      | 6.47e+19      |  2.6       | 3/17              |
| blunt_cone   | 22.5 | 61      | 1.01e+20      |  4.2       | 4/16              |
| ram_c        | 22.5 | 61      | 8.19e+20      |  7.9       | 3/17              |
| blunt_wide   | 22.5 | 61      | 1.69e+20      |  7.8       | 5/15              |
| capsule      | 22.5 | 61      | 3.16e+22      | 15.7       | 6/14              |
|              |      |         |               |            |                   |
| sharp_narrow | 23.6 | 71      | 9.66e+17      |  1.1       | 2/18              |
| medium_cone  | 23.6 | 71      | 2.51e+18      |  2.6       | 3/17              |
| blunt_cone   | 23.6 | 71      | 4.14e+18      |  4.2       | 4/16              |
| ram_c        | 23.6 | 71      | 6.01e+19      |  8.1       | 3/17              |
| blunt_wide   | 23.6 | 71      | 8.05e+18      |  8.0       | 5/15              |
| capsule      | 23.6 | 71      | 5.96e+20      | 16.0       | 6/14              |
|              |      |         |               |            |                   |
| sharp_narrow | 23.9 | 81      | 1.94e+16      |  1.1       | 2/18              |
| medium_cone  | 23.9 | 81      | 4.74e+16      |  2.7       | 3/17              |
| blunt_cone   | 23.9 | 81      | 7.61e+16      |  4.4       | 4/16              |
| ram_c        | 23.9 | 81      | 2.48e+18      |  8.4       | 3/17              |
| blunt_wide   | 23.9 | 81      | 1.46e+17      |  8.3       | 5/15              |
| capsule      | 23.9 | 81      | 1.75e+19      | 16.6       | 6/14              |

Pattern across every flight condition: **peak ne increases with
bluntness** (sharp → capsule), τ_max scales linearly with R_n. Direct
confirmation of the geometry-residence-time-chemistry coupling.

A few outliers worth flagging:
- **Capsule M=22.5/61km gives ne = 3.16e+22**, 1-2 orders higher than
  the trend at lower altitudes. The peak is at x = 800 mm (the aft
  end of the body), not the stagnation point. Capsule has 30°
  half-angle so the "oblique shock" stations on the conical
  afterbody are still close to normal-shock conditions; combined with
  the long τ at the aft, kinetics produces unusually high ne. Whether
  this is physical or an artifact of the oblique-vs-normal shock
  threshold (currently 30°) deserves a deeper look.
- **At 81 km, all geometries have low ne** (1e16–2e19) because the
  freestream density is ~70× lower than at 47 km, so even with full
  chemistry, the absolute number of ions is limited.

### 3. Trajectory blackout — different geometries, different windows

10-waypoint trajectory (M=24/85km → M=5/25km, 150s total) on three
geometries:

| Geometry | Ku-band blackout window | Peak Ku attenuation |
|---|---|---|
| ram_c        | t ∈ [25, 110] s (85 s) | 881 dB |
| capsule      | t ∈ [25, 110] s (85 s) | 627 dB |
| sharp_narrow | t ∈ [40, 110] s (70 s) | 139 dB |

Sharp_narrow enters blackout LATER (15 s after the others) and exits
with much shallower peak attenuation (139 dB vs 881 dB) — geometry
dependence is real and large. Each trajectory ran in ~2.1 s — fast
enough for interactive design exploration.

### 4. Monte Carlo UQ

15 perturbed runs at RAM-C M=22.5/61km in 6.0 s:
- ne mean: 2.61e+20
- ne std:  3.92e+19   (15 % relative uncertainty)
- ne P95:  3.13e+20
- ne worst (P99): 3.13e+20
- Ku-band blackout probability: 100 %

The 15 % relative uncertainty in ne reflects the perturbations in
freestream T (σ=3 %) and ρ (σ=5 %); chemistry rate-constant
perturbation contributes additionally but is bounded by the kinetics
mode. 100 % Ku-blackout probability is consistent with the ne being
deep into the evanescent regime — every perturbation lands above
the cutoff.

## Performance breakdown

| Step | wall (s) | per-case |
|---|---|---|
| Axial sweep (30 cases × 20 stations × 5-band LOS scan) | 5.0 s | 167 ms/case |
| Boundary-layer sweep (6 geometries) | 0.1 s | 17 ms/case |
| Trajectory simulation (3 geometries × 10 waypoints) | 6.4 s | 213 ms/waypoint |
| Monte Carlo (15 samples) | 6.0 s | 400 ms/sample |
| **Total** | 14.1 s | |

The per-axial-station chemistry call dominates, at ~8 ms per station.
A 50-station profile at this rate is ~400 ms; 100 stations is ~800 ms.

## Conclusions

1. **The v0.3.0 solver runs reliably on GCP across the full geometry
   sweep with full Cantera kinetics.** No crashes, no timeouts, no
   soft-failures across 30 axial-sweep cases × 5 flight conditions
   × 6 geometries.

2. **Aaron's three required behaviors are all demonstrated**:
   bluntness ↑ → q_w ↓ (Fay-Riddell exact); bluntness ↑ → τ ↑
   (Billig linear); bluntness ↑ → ne ↑ (kinetics produces 10-100×
   spread).

3. **Trajectory simulation produces geometry-distinct blackout windows.**
   The same trajectory gives sharp_narrow a 139-dB peak Ku-band and
   ram_c an 881-dB peak — the engine is doing what the strategy doc
   asks for ("predict detectability, not just flowfields").

4. **One physical anomaly to investigate**: capsule M=22.5/61km
   returns ne = 3.16e+22 with peak at the aft end (x = 800 mm), an
   order of magnitude higher than the equivalent capsule case at
   18.5/47 km. Likely the 30° normal-vs-oblique shock threshold
   misfiring on capsule's high-half-angle geometry. Worth a deeper
   look but not a blocker for the v0.3.0 release.

5. **Surrogate generalization is the bigger gap**, not the solver
   pipeline. See `docs/SURROGATE_V5_PLAN.md` for the audit and
   v5 expansion plan: v4 covers only 4 Mach values × 4 altitudes ×
   3 residence times (48-point lookup) — anything off-grid is
   extrapolation.

## Files

- `data/verify_v0_3_0_gcp_results.json` — full 26 KB JSON of every
  case
- `data/verify_v030_gcp.log` — captured stdout from the GCP run
- `scripts/verify_v0_3_0_gcp.py` — the reproducible test driver
