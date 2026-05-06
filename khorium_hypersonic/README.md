# khorium_hypersonic

Geometry-agnostic hypersonic plasma solver + AI-exhaustive
chemistry-reaction search framework. Designed to drop into KhoriumBackend
as a FastAPI router or be used as a Python library directly.

## Why this package

Aaron Wu's vision: an AI system that can **try every plausible chemistry
mechanism** at hypersonic Mach numbers and find configurations that
match flight-test plasma measurements better than hand-engineered
mechanisms (Park 1990 AIR-7, Dunn-Kang). With the audited PlasmaNet v4
surrogate (~0.01 ms per evaluation, factor-of-1.52 of Cantera 0D
ground truth), brute-force search over the 2^N subset space of an
N-reaction mechanism becomes tractable for N ≲ 24, and Sobol+BO covers
N=47 in 5,000 evaluations.

The package layers the supporting physics so it works on **any vehicle
geometry** — sphere-cone (RAM-C, blunt cones), capsule (Apollo-class),
or arbitrary mesh-derived bodies. No hardcoded RAM-C assumptions in the
solver — only in the catalog of named presets.

## Layered architecture

```
khorium_hypersonic/
├── core/           atmosphere · shock · stagnation · plasma · standoff
├── geometry/       Geometry Protocol + SphereCone + Capsule + MeshGeometry
├── sheath/         analytical (Billig-anchored) + CFD-derived
├── signals/        LOS attenuation + detection thresholds
├── chemistry/      Mechanism + Cantera 0D + neural surrogate
├── search/         exhaustive + Sobol+BO + genetic
├── api/            FastAPI router for KhoriumBackend
└── solver.py       Top-level HypersonicSolver class + Pydantic schemas
```

Each layer is independently importable; nothing in `core/` depends on
chemistry, signals, geometry, or anything else.

## Quick start (Python library)

```python
from khorium_hypersonic import HypersonicSolver
from khorium_hypersonic.solver import SolverInput, GeometryInput, FlightCondition

solver = HypersonicSolver()
result = solver.analyze(SolverInput(
    geometry=GeometryInput(preset_name="ram_c"),
    flight=FlightCondition(mach=22.5, altitude_km=61.0),
))

print(f"ne_peak = {result.stagnation.ne_peak_m3:.2e} m^-3")
print(f"f_p     = {result.stagnation.fp_GHz:.1f} GHz")
print(f"shock standoff (eq) = {result.geometry.bow_shock_standoff_eq_mm:.2f} mm")
for band in result.bands:
    print(f"  {band.label:10s}: peak {band.peak_atten_dB:6.1f} dB → {band.detection_status}")
```

## Quick start (KhoriumBackend FastAPI integration)

```python
# In KhoriumBackend's app factory:
from fastapi import FastAPI
from khorium_hypersonic.api import create_router

app = FastAPI()
app.include_router(create_router(prefix="/api/hypersonic"), tags=["hypersonic"])
```

Endpoints exposed:
- `POST /api/hypersonic/analyze` — single prediction (SolverInput → SolverOutput)
- `POST /api/hypersonic/search/sobol_bo` — chemistry-subset search
- `GET  /api/hypersonic/presets` — list named geometries

## Custom geometry

The `Geometry` Protocol accepts any object that exposes:

```python
class MyVehicle:
    name: str = "my_vehicle"
    def bounding_box(self): ...
    def effective_nose_radius_m(self): ...
    def characteristic_length_m(self): ...
    def body_radius_at_axial_station(self, x): ...
    def half_angle_deg(self): ...
```

For STEP/STL/OBJ files:

```python
from khorium_hypersonic.geometry import MeshGeometry
geom = MeshGeometry(name="my_hgv", mesh_path="my_hgv.stl")
result = solver.analyze(SolverInput(
    geometry=GeometryInput(name=geom.name, mesh_path="my_hgv.stl"),
    flight=FlightCondition(mach=20, altitude_km=40),
))
```

## AI-exhaustive chemistry search (Aaron's headline)

```python
from khorium_hypersonic import PARK_47
from khorium_hypersonic.chemistry import MechanismSurrogate, register_surrogate_evaluator
from khorium_hypersonic.search import sobol_bayesian_search
import torch

# Load v4 surrogate (factor-of-1.52 of Cantera, 0.01 ms/eval)
model = MechanismSurrogate(freestream_dim=4, mechanism_dim=47, hidden_dim=512, n_layers=4)
model.load_state_dict(torch.load("checkpoints/surrogate_v4.pt", map_location="cpu"))
model.eval()
register_surrogate_evaluator(model, name="plasmanet_v4")

# Search 2^47 ≈ 1.4e14 subsets in ~10 seconds via Sobol+BO
result = sobol_bayesian_search(
    base_mechanism=PARK_47,
    evaluator="plasmanet_v4",
    benchmarks=("ram_c_61km_M22.5",),
    n_sobol=1000, n_bo=5000,
    residence_time_s=1e-6,  # kinetics regime
)

for mech, score in result.evaluated[:5]:
    print(f"{mech.name}: composite={score.composite_score:+.4f}, "
          f"{len(mech.reactions)} reactions, ids={[r.rxn_id for r in mech.reactions]}")
```

For mechanisms with N ≤ 24 reactions, exhaustive enumeration:

```python
from khorium_hypersonic.search import exhaustive_search
from khorium_hypersonic import PARK_47

# Subset PARK_47 to 20 reactions and run brute force
small = PARK_47.subset(reaction_ids=list(range(1, 21)))
result = exhaustive_search(
    base_mechanism=small,
    evaluator="plasmanet_v4",
    benchmarks=("ram_c_61km_M22.5",),
    require_dissociation=True, require_ionization=True,
)
print(f"evaluated {result.metadata['n_evaluated']} subsets in "
      f"{result.metadata['wall_seconds']:.1f}s")
```

## Audit / physics-correctness

Every module has textbook references inline. The ground-truth solver is
`scripts/unified_hypersonic_solver.py` in the parent repo, which
computes each quantity twice (closed-form HC and via this package's
implementation) and prints percent-difference. Run with `--sweep` to
compare across all 6 geometry presets × 3 flight conditions.

Known caveats (not bugs in this wrapper, in the underlying physics):

- **Stagnation chemistry is geometry-independent under perfect-gas
  Pitot.** This is correct textbook physics — equilibrium ne at the
  stagnation point depends only on (M, T_∞, P_∞). Geometry effects flow
  through Billig standoff (sheath thickness) and the LOS path through
  the analytical sheath profile. To make geometry affect chemistry,
  upgrade to Fay-Riddell heat flux + finite-rate residence-time
  modeling — both planned but not in this version.

- **Equilibrium chemistry over-predicts ne at high altitude** (61, 71,
  81 km). Real flight residence time (~10 µs) doesn't reach
  equilibration; the v4 surrogate trained at fixed 1 µs residence time
  captures this — equilibrium core falls back when surrogate isn't
  available.

- **Appleton-Hartree band ordering may be inverted** in deep evanescent
  regime — bug in upstream `plasmanet.plasma_wave.attenuation_rate`,
  flagged but not yet fixed.

## Install

```bash
pip install -e .                 # core only
pip install -e .[api]            # + FastAPI for KhoriumBackend
pip install -e .[all]            # + Cantera + torch + meshio + cadquery
```
