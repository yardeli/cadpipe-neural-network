"""khorium_hypersonic — geometry-agnostic hypersonic plasma solver.

Designed to support Aaron Wu's vision: an AI-exhaustive chemistry-reaction
search at hypersonic Mach numbers, paired with rigorous textbook physics
that adapts to any vehicle geometry. Outputs include radar/satellite
signal-processing predictions (per-band attenuation, blackout status,
plasma frequency).

Packaging
---------
The package is layered so each piece can be replaced without rewriting
the others:

    khorium_hypersonic/
        core/          freestream + shock + stagnation + plasma primitives
        geometry/      Geometry protocol + sphere-cone + capsule + mesh
        sheath/        analytical sheath + CFD-derived sheath
        signals/       LOS attenuation + detection thresholds
        chemistry/     Mechanism + Cantera 0D + neural surrogate
        search/        exhaustive + Sobol+BO + genetic over reaction subsets
        api/           FastAPI router for KhoriumBackend integration

Stable public surface (re-exported below):

    HypersonicSolver        — top-level orchestrator: geometry + flight + mechanism -> Result
    SolverInput, SolverOutput — Pydantic schemas (FastAPI-friendly)
    Geometry, SphereCone, Capsule, MeshGeometry — geometry adapters
    Mechanism, PARK_47, RAW_PARK_REACTIONS — chemistry primitives
    exhaustive_search, sobol_bayesian_search, genetic_search — AI search
    create_router            — drop-in FastAPI router for KhoriumBackend

All physics is documented inline against textbook references (Anderson
2006 "Modern Compressible Flow", Park 1990 "Nonequilibrium Hypersonic
Aerothermodynamics", Bertin 1994 "Hypersonic Aerothermodynamics",
Billig 1967 AIAA 67-148, Fay-Riddell 1958, USSA76 NASA TN-1976).
"""
_OLD_VERSION = "0.1.0"

from .solver import HypersonicSolver, SolverInput, SolverOutput
from .solver_trajectory import (
    TrajectoryPoint, TrajectoryResult, BlackoutInterval, solve_trajectory,
)
from .geometry import (
    Geometry, SphereCone, Capsule, MeshGeometry, GEOMETRY_PRESETS,
)
from .chemistry import Mechanism, PARK_47
from .search import exhaustive_search, sobol_bayesian_search, genetic_search
from .core.flowfield import compute_axial_profile, AxialProfile, AxialStation
from .core.boundary_layer import bl_summary, fay_riddell_full
from .uncertainty import UncertaintyConfig, MonteCarloResult, run_monte_carlo

__version__ = "0.3.0"

__all__ = [
    "__version__",
    # Pointwise solver
    "HypersonicSolver", "SolverInput", "SolverOutput",
    # Trajectory simulator
    "TrajectoryPoint", "TrajectoryResult", "BlackoutInterval", "solve_trajectory",
    # Geometry
    "Geometry", "SphereCone", "Capsule", "MeshGeometry", "GEOMETRY_PRESETS",
    # Chemistry + search
    "Mechanism", "PARK_47",
    "exhaustive_search", "sobol_bayesian_search", "genetic_search",
    # Geometry-resolved flowfield
    "compute_axial_profile", "AxialProfile", "AxialStation",
    # Boundary layer
    "bl_summary", "fay_riddell_full",
    # Uncertainty
    "UncertaintyConfig", "MonteCarloResult", "run_monte_carlo",
]
