# khorium_hypersonic — physics audit + integration notes

This document is the audit you asked for: what the math actually does,
where it can be trusted, what's still hand-wavey, and what the
integration story for KhoriumBackend looks like.

## What's textbook-correct in this package

| Layer | Reference | Verified by |
|---|---|---|
| `core.atmosphere` USSA76 | NASA-TM-X-74335 | Within 8% of USSA76 table at h = 60 km after the 2026-05-03 sign-fix in plasmanet/physics.py (was 12× off at 51-71 km) |
| `core.shock.normal_shock_frozen` | Anderson 2006 §3.6 | Closed-form RH; matches textbook to numerical precision |
| `core.stagnation.pitot_pressure` | Anderson 2006 Eq. 9.65 (Rayleigh-Pitot) | Verified against textbook from M=2 to M=30, ratio = 1.000 |
| `core.stagnation.stagnation_T_real_gas` | h_t = h_∞ + 0.5 U_∞² | Bisection on Cantera enthalpy; converges to 0.5% rel err vs CFD vtu T_tr |
| `core.chemistry.saha_ne` | Saha 1920, Bekefi 1966 | Sums NO+, O+, N+ contributions with NIST-2019 ionization energies |
| `core.plasma.appleton_hartree_attenuation_dB` | Stix 1992, Bekefi 1966 §4.3 | Cold-plasma dispersion; collision-corrected for both regimes |
| `core.standoff.billig_sphere_standoff` | Billig 1967 (AIAA-67-148) | Empirical sphere-bow-shock formula + equilibrium ρ-ratio correction |

## What's geometry-agnostic (works on any vehicle)

- **Stagnation T, P, ne, plasma frequency** — depend only on (M, T_∞, P_∞)
  under perfect-gas Pitot. This is correct textbook physics. Geometry
  does NOT enter the equilibrium chemistry calculation.
- **Bow-shock standoff** — Billig 1967 takes only the effective nose
  radius. The `Geometry` Protocol's `effective_nose_radius_m()` works
  for sphere-cones (returns the parametric nose radius) and for
  arbitrary meshes (algebraic sphere fit to the most-forward 5% of the
  body).
- **LOS attenuation** — `signals.scan_aspect` integrates ne along
  arbitrary ray paths through whatever (ne, ν_c) field you supply.
  Works for analytical sheaths AND CFD-extracted fields.
- **AI-exhaustive chemistry search** — `search.exhaustive_search` works
  on ANY `Mechanism` (not just Park-47). Construct a `Mechanism` with
  custom reactions and the search loop will enumerate / Sobol-sample /
  GA over its subset space.

## What's still RAM-C-flavored (intentionally, as defaults)

- The named `GEOMETRY_PRESETS` includes RAM-C as one option among 6.
  Useful for demos and reproducing J&C 1972 comparisons. None of the
  physics layers reference RAM-C constants.
- The `chemistry.BENCHMARKS` registry (re-exported from
  `plasmanet.mechanism_search.scoring`) contains RAM-C 47/61/71/81 km
  trajectory points as scoring anchors. The `search` API takes a
  `benchmark` parameter so callers can register their own anchors for
  arbitrary flight-data sources.
- The `chemistry.PARK_47` mechanism is the canonical Park 1990 air
  mechanism — it's used as the default `base_mechanism` for searches.
  For non-air chemistry (CO₂ for Mars EDL, etc.), construct a custom
  `Mechanism` and pass it to the search functions.

## Known gaps (carried forward from underlying plasmanet stack)

1. **Stagnation chemistry is geometry-independent.** Correct under
   perfect-gas Pitot, but real flight data shows nose-radius-dependent
   chemistry (Fay-Riddell heating, finite-rate residence time, BL
   chemistry). Adding geometry-dependent chemistry would require:
   - Fay-Riddell wall heat flux: q_w = 0.94·(ρ_e μ_e)^0.5 ·
     (du_e/dx)^0.5 · (h_w − h_aw). Scales as q_w ∝ R_n^(-0.5).
   - 1D Park-style boundary-layer integration.
   - Finite-rate Cantera 0D with residence time = δ/U_e (Billig sets δ).
   None of these are in the current solver. They're designed-in slots:
   `core.chemistry` exposes Saha at known (T, p), so a future
   `core.boundary_layer` module can compute T_BL, P_BL and feed those.

2. **Equilibrium chemistry over-predicts ne at high altitudes.** RAM-C
   M=22.5/61km published peak ne = 2e+19; equilibrium Saha gives
   1.18e+20 (~6× over). Real flight residence time (~10 µs) doesn't
   fully equilibrate. The PlasmaNet v4 surrogate (in
   `chemistry.MechanismSurrogate`) is trained on Cantera 0D at a fixed
   1 µs residence time and captures this kinetics regime — the search
   layer uses the surrogate, not equilibrium chemistry, by default.

3. **Appleton-Hartree band ordering inverted in deep evanescent
   regime.** `plasma_wave.attenuation_rate_db_per_m` returns
   atten(VHF) < atten(X) < atten(Ku) where textbook says atten should
   be roughly band-INDEPENDENT or DECREASING with frequency far below
   ω_p. Bug flagged but not fixed — `core.plasma.appleton_hartree_*`
   in this package uses a corrected closed-form that doesn't have
   the inversion, so callers who go through the new `solver.analyze()`
   get correct band ordering. Callers that go directly to
   `plasmanet.line_of_sight.scan_aspect` are still affected.

4. **Sheath profile is parametric, not CFD-derived.** The analytical
   `SheathProfile` underlying `sheath.build_analytical_sheath_field` is
   a smooth ne(r, z) that decays exp(-3·s/L) along the body. For real
   CFD-derived ne use `sheath.build_sheath_field_from_cfd` with a
   SU2-NEMO vtu — that path is geometry-agnostic via the
   `extract_nemo_field` reader.

5. **Mesh adapter is convex-hull-friendly only.** `MeshGeometry`'s
   `body_radius_at_axial_station(x)` returns max-radial-distance among
   surface points within ±0.5% of x. Works for solid sphere-cones,
   capsules, and HGV-class waveriders. Does NOT handle multi-component
   geometries (probe + cone), inlet bodies, or non-convex shapes.

## Integration into KhoriumBackend

### Option 1 — vendor as a subdirectory
```
KhoriumBackend/
├── khorium_hypersonic/         (copy of this package)
├── pyproject.toml              (add khorium_hypersonic deps to project deps)
└── ...
```

### Option 2 — pip install -e from local checkout
```bash
cd KhoriumBackend
pip install -e /path/to/plasmanet/khorium_hypersonic
```

### Option 3 — git submodule
```bash
cd KhoriumBackend
git submodule add <repo>/khorium_hypersonic external/khorium_hypersonic
pip install -e external/khorium_hypersonic
```

In any case, register the FastAPI router in your app factory:

```python
# KhoriumBackend/app.py (or wherever you create the FastAPI app)
from fastapi import FastAPI
from khorium_hypersonic.api import create_router

app = FastAPI()
app.include_router(create_router(prefix="/api/hypersonic"), tags=["hypersonic"])
```

### What you get

```
GET  /api/hypersonic/presets               → list of geometry presets
POST /api/hypersonic/analyze               → SolverInput → SolverOutput
POST /api/hypersonic/search/sobol_bo       → SearchRequest → top-50 mechanisms
```

All bodies are Pydantic v2 models so OpenAPI/Swagger UI will document
them automatically at `/docs`.

### Soft dependencies

Core physics (atmosphere, shock, plasma frequency, Billig) requires
only numpy + scipy + pydantic. To unlock everything:

| Feature | Extra dep |
|---|---|
| Cantera real-gas T_stag + chemistry | `cantera>=3.0` |
| Neural surrogate inference | `torch>=2.0` |
| Mesh-derived geometry | `meshio>=5.3` (STL/OBJ) or `cadquery>=2.4` (STEP) |
| FastAPI router | `fastapi>=0.100` + `uvicorn>=0.23` |

`pip install -e .[all]` pulls everything; `pip install -e .[api]` is
the minimum for the FastAPI integration.
