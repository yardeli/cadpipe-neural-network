"""FastAPI router factory."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..solver import (
    HypersonicSolver, SolverInput, SolverOutput, GeometryInput, FlightCondition,
)
from ..geometry import GEOMETRY_PRESETS


class SearchRequest(BaseModel):
    base_mechanism: str = Field("PARK_47", description="Mechanism name; "
                                "default Park 1990 47-reaction air mechanism")
    benchmark: str = Field("ram_c_61km_M22.5",
                            description="Published flight-condition anchor "
                            "for the search ground truth")
    residence_time_s: float = 1e-6
    n_sobol: int = 1000
    n_bo: int = 5000
    surrogate_path: Optional[str] = None


class TopKResponse(BaseModel):
    metadata: dict
    top_k: list[dict]


def create_router(prefix: str = "/api/hypersonic"):
    """Build a FastAPI APIRouter with all hypersonic endpoints registered."""
    try:
        from fastapi import APIRouter, HTTPException
    except ImportError:
        raise ImportError(
            "create_router requires fastapi. pip install fastapi"
        )

    router = APIRouter(prefix=prefix)
    solver = HypersonicSolver()

    @router.post("/analyze", response_model=SolverOutput)
    async def analyze(request: SolverInput) -> SolverOutput:
        """Run the single-condition hypersonic prediction."""
        try:
            return solver.analyze(request)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @router.get("/presets")
    async def presets():
        """List available vehicle geometry presets."""
        return {
            "geometry_presets": [
                {"name": name,
                 "nose_radius_m": g.nose_radius_m,
                 "half_angle_deg": g.half_angle_deg,
                 "length_m": g.length_m}
                for name, g in GEOMETRY_PRESETS.items()
            ],
        }

    @router.post("/search/sobol_bo", response_model=TopKResponse)
    async def search_sobol_bo(request: SearchRequest) -> TopKResponse:
        """Run Sobol-seeded Bayesian Optimization over reaction subsets.

        Returns top-50 candidates ranked by composite score (lower = better
        fit to the benchmark ground truth). With the v4 surrogate this
        completes in ~10 seconds for n_sobol=1000 + n_bo=5000.
        """
        from ..chemistry import (
            PARK_47, MechanismSurrogate, register_surrogate_evaluator,
        )
        from ..search import sobol_bayesian_search

        if request.base_mechanism != "PARK_47":
            raise HTTPException(
                status_code=422,
                detail=f"Only PARK_47 currently supported via API; "
                       f"use the Python interface for custom mechanisms",
            )
        base = PARK_47

        if request.surrogate_path:
            try:
                import torch
                model = MechanismSurrogate(
                    freestream_dim=4, mechanism_dim=47,
                    hidden_dim=512, n_layers=4,
                )
                model.load_state_dict(
                    torch.load(request.surrogate_path, map_location="cpu",
                                weights_only=False),
                    strict=False,
                )
                model.eval()
                register_surrogate_evaluator(model, name="plasmanet_v4")
                evaluator = "plasmanet_v4"
            except Exception as exc:
                raise HTTPException(status_code=500,
                                     detail=f"Failed to load surrogate: {exc}")
        else:
            evaluator = "cantera_0d"   # slow but always available

        result = sobol_bayesian_search(
            base_mechanism=base,
            evaluator=evaluator,
            benchmarks=(request.benchmark,),
            n_sobol=request.n_sobol, n_bo=request.n_bo,
            residence_time_s=request.residence_time_s,
            seed=42,
            save_path=None,
        )
        return TopKResponse(
            metadata=result.metadata,
            top_k=[{
                "mechanism_name": m.name,
                "n_reactions": len(m.reactions),
                "rxn_ids": [r.rxn_id for r in m.reactions],
                "score": float(s.composite_score),
            } for m, s in result.evaluated[:50]],
        )

    return router
