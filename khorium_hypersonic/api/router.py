"""FastAPI router factory.

Surface exposed to KhoriumBackend / SimOps:

  POST /api/hypersonic/analyze            — single-condition pointwise solver (v0.2.0)
  POST /api/hypersonic/analyze/axial      — geometry-resolved axial profile (v0.3.0)
  POST /api/hypersonic/analyze/strips     — azimuthal-strip mode (v0.3.1, waverider / asymmetric)
  POST /api/hypersonic/analyze/mesh       — raycast-mesh adapter (this PR, non-convex hulls / ducts)
  POST /api/hypersonic/heat_transfer      — Fay-Riddell q_w (supports swept LE)
  POST /api/hypersonic/shock_chain        — multi-stage external + internal compression (v0.3.1)
  POST /api/hypersonic/trajectory         — blackout intervals over a flight trajectory (v0.3.0)
  POST /api/hypersonic/uncertainty        — Monte Carlo over freestream perturbations (v0.3.0)
  POST /api/hypersonic/search/sobol_bo    — Sobol-seeded BO over the 2^47 mechanism axis
  GET  /api/hypersonic/presets            — built-in vehicle geometries
"""
from __future__ import annotations

from typing import Optional, Sequence

from pydantic import BaseModel, Field

from ..solver import (
    HypersonicSolver, SolverInput, SolverOutput, GeometryInput, FlightCondition,
)
from ..geometry import GEOMETRY_PRESETS


# ── Existing search endpoint schemas ─────────────────────────────────

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


# ── v0.3.x integration schemas ───────────────────────────────────────

class AxialProfileRequest(BaseModel):
    geometry: GeometryInput
    flight: FlightCondition
    n_stations: int = Field(50, ge=2, le=400)
    chemistry_mode: str = Field("auto", description="equilibrium | kinetics | auto")


class AxialStationOut(BaseModel):
    x_m: float
    surface_angle_deg: float
    shock_kind: str
    T_e_K: float
    P_e_Pa: float
    delta_local_m: float
    tau_residence_s: float
    ne_m3: float
    fp_GHz: float


class AxialProfileResponse(BaseModel):
    geometry_name: str
    mach: float
    altitude_km: float
    chemistry_mode: str
    peak_ne_m3: float
    peak_x_m: float
    stations: list[AxialStationOut]


class StripRequest(BaseModel):
    geometry: GeometryInput
    flight: FlightCondition
    n_strips: int = Field(8, ge=1, le=64)
    n_axial_per_strip: int = Field(40, ge=2, le=400)
    chemistry_mode: str = "kinetics"


class StripSummary(BaseModel):
    phi_deg: float
    peak_ne_m3: float
    peak_x_m: float


class StripResponse(BaseModel):
    geometry_name: str
    mach: float
    altitude_km: float
    n_strips: int
    strips: list[StripSummary]
    windward_to_leeward_ratio: Optional[float] = None


class MeshRequest(BaseModel):
    mesh_path: str = Field(..., description="STL/OBJ/MSH file readable on the server")
    flight: FlightCondition
    n_stations: int = Field(60, ge=2, le=400)
    n_strips: int = Field(1, ge=1, le=64,
                           description="1 = axisymmetric envelope; >1 = strip mode")
    chemistry_mode: str = "kinetics"


class HeatTransferRequest(BaseModel):
    flight: FlightCondition
    geometry: GeometryInput
    sweep_angle_deg: float = Field(0.0, ge=0.0, le=89.0,
                                    description="Swept-LE attachment-line sweep angle Λ")
    wall_T_K: float = Field(1500.0, ge=300.0, le=4000.0)


class HeatTransferResponse(BaseModel):
    q_w_W_per_m2: float
    du_e_dx_per_s: float
    sweep_correction: float
    delta_stag_m: float
    regime: str


class ShockStageSpec(BaseModel):
    kind: str = Field(..., description="oblique | normal | internal_duct")
    deflection_deg: Optional[float] = None
    length_m: Optional[float] = None


class ShockChainRequest(BaseModel):
    flight: FlightCondition
    stages: list[ShockStageSpec]


class ShockStageState(BaseModel):
    stage_index: int
    kind: str
    mach: float
    T_K: float
    P_Pa: float
    rho_kgm3: float
    beta_deg: Optional[float] = None
    duct_residence_s: Optional[float] = None


class ShockChainResponse(BaseModel):
    stages: list[ShockStageState]


class TrajectoryRequest(BaseModel):
    geometry: GeometryInput
    waypoints: list[dict] = Field(
        ..., description="List of {t, mach, altitude_km} dicts ordered by t",
    )
    chemistry_mode: str = "auto"
    blackout_threshold_dB: float = 20.0


class TrajectoryResponse(BaseModel):
    geometry_name: str
    waypoints_n: int
    bands: list[str]
    blackout_intervals: list[dict]
    peak_ne_m3: float


class UncertaintyRequest(BaseModel):
    geometry: GeometryInput
    flight: FlightCondition
    n_samples: int = Field(20, ge=2, le=500)
    sigma_T_inf: float = 0.03
    sigma_rho_inf: float = 0.05


class UncertaintyResponse(BaseModel):
    geometry_name: str
    mach: float
    altitude_km: float
    n_samples: int
    ne_mean_m3: float
    ne_std_m3: float
    ne_p95_m3: float
    blackout_probability_by_band: dict[str, float]


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

    # ── v0.3.0 / v0.3.1 endpoints ────────────────────────────────────

    @router.post("/analyze/axial", response_model=AxialProfileResponse)
    async def analyze_axial(request: AxialProfileRequest) -> AxialProfileResponse:
        """Geometry-resolved axial flowfield (ne(x), T(x), P(x), shock-kind, τ(x))."""
        from ..solver import _resolve_geometry
        from ..core.flowfield import compute_axial_profile
        try:
            geom = _resolve_geometry(request.geometry)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        prof = compute_axial_profile(
            geom, mach=request.flight.mach, altitude_km=request.flight.altitude_km,
            n_stations=request.n_stations, chemistry_mode=request.chemistry_mode,
        )
        x_peak, ne_peak = prof.peak_ne()
        return AxialProfileResponse(
            geometry_name=geom.name, mach=request.flight.mach,
            altitude_km=request.flight.altitude_km,
            chemistry_mode=request.chemistry_mode,
            peak_ne_m3=float(ne_peak), peak_x_m=float(x_peak),
            stations=[AxialStationOut(
                x_m=s.x_m, surface_angle_deg=s.surface_angle_deg,
                shock_kind=s.shock_kind, T_e_K=s.T_e_K, P_e_Pa=s.P_e_Pa,
                delta_local_m=s.delta_local_m, tau_residence_s=s.tau_residence_s,
                ne_m3=s.ne_m3, fp_GHz=s.fp_GHz,
            ) for s in prof.stations],
        )

    @router.post("/analyze/strips", response_model=StripResponse)
    async def analyze_strips(request: StripRequest) -> StripResponse:
        """Azimuthal-strip mode for non-axisymmetric bodies (waveriders,
        asymmetric afterbodies). With ``n_strips=1`` collapses to the
        single-meridian baseline."""
        import math
        from ..solver import _resolve_geometry
        from ..core.strip_field import (
            compute_azimuthal_strips, axisymmetric_strips,
        )
        try:
            geom = _resolve_geometry(request.geometry)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        pairs = axisymmetric_strips(geom, n_strips=request.n_strips)
        strips = compute_azimuthal_strips(
            pairs, mach=request.flight.mach,
            altitude_km=request.flight.altitude_km,
            n_axial_per_strip=request.n_axial_per_strip,
            chemistry_mode=request.chemistry_mode,
        )
        summaries: list[StripSummary] = []
        for s in strips:
            x_p, ne_p = s.profile.peak_ne()
            summaries.append(StripSummary(
                phi_deg=math.degrees(s.phi_rad),
                peak_ne_m3=float(ne_p), peak_x_m=float(x_p),
            ))
        ratio: Optional[float] = None
        if len(summaries) >= 2:
            wnd = summaries[0].peak_ne_m3
            lee_idx = min(range(len(summaries)),
                           key=lambda i: abs(summaries[i].phi_deg - 180.0))
            lee = summaries[lee_idx].peak_ne_m3
            ratio = float(wnd / lee) if lee > 0 else None
        return StripResponse(
            geometry_name=geom.name, mach=request.flight.mach,
            altitude_km=request.flight.altitude_km, n_strips=len(strips),
            strips=summaries, windward_to_leeward_ratio=ratio,
        )

    @router.post("/analyze/mesh", response_model=AxialProfileResponse)
    async def analyze_mesh(request: MeshRequest) -> AxialProfileResponse:
        """Raycast-mesh adapter — non-convex hulls, hollow ducts, probe-on-cone."""
        from ..geometry import RaycastMesh
        from ..core.flowfield import compute_axial_profile
        try:
            mesh = RaycastMesh(name="mesh_request", mesh_path=request.mesh_path)
        except (ValueError, ImportError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        prof = compute_axial_profile(
            mesh, mach=request.flight.mach,
            altitude_km=request.flight.altitude_km,
            n_stations=request.n_stations,
            chemistry_mode=request.chemistry_mode,
        )
        x_peak, ne_peak = prof.peak_ne()
        return AxialProfileResponse(
            geometry_name=mesh.name, mach=request.flight.mach,
            altitude_km=request.flight.altitude_km,
            chemistry_mode=request.chemistry_mode,
            peak_ne_m3=float(ne_peak), peak_x_m=float(x_peak),
            stations=[AxialStationOut(
                x_m=s.x_m, surface_angle_deg=s.surface_angle_deg,
                shock_kind=s.shock_kind, T_e_K=s.T_e_K, P_e_Pa=s.P_e_Pa,
                delta_local_m=s.delta_local_m, tau_residence_s=s.tau_residence_s,
                ne_m3=s.ne_m3, fp_GHz=s.fp_GHz,
            ) for s in prof.stations],
        )

    @router.post("/heat_transfer", response_model=HeatTransferResponse)
    async def heat_transfer(request: HeatTransferRequest) -> HeatTransferResponse:
        """Fay-Riddell q_w with optional cos²Λ swept-LE correction."""
        import math
        from ..solver import _resolve_geometry
        from ..core import (
            standard_atmosphere, normal_shock_frozen, pitot_pressure,
            stagnation_T_real_gas,
        )
        from ..core.boundary_layer import bl_summary
        try:
            geom = _resolve_geometry(request.geometry)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        fs = standard_atmosphere(request.flight.altitude_km)
        U_inf = request.flight.mach * fs["a_ms"]
        sh = normal_shock_frozen(request.flight.mach, fs["T_K"], fs["P_Pa"],
                                  fs["rho_kgm3"])
        P_t = pitot_pressure(fs["P_Pa"], request.flight.mach)
        rg = stagnation_T_real_gas(
            T_inf_K=fs["T_K"], P_inf_Pa=fs["P_Pa"], U_inf_ms=U_inf, P_t_Pa=P_t,
        )
        T_stag = rg.get("T_t_real_K", sh["T2_K"])
        rho_t = P_t / (287.058 * max(T_stag, 300.0))
        bl = bl_summary(
            R_n_m=geom.effective_nose_radius_m(), U_inf_ms=U_inf,
            rho_e_kgm3=rho_t, T_e_K=T_stag,
            rho_w_kgm3=rho_t, T_w_K=request.wall_T_K,
            h_e_J_per_kg=2.5e7, h_w_J_per_kg=1.5e6,
            p_t_Pa=P_t, p_inf_Pa=fs["P_Pa"], rho_t_kgm3=rho_t,
            sweep_angle_rad=math.radians(request.sweep_angle_deg),
        )
        return HeatTransferResponse(
            q_w_W_per_m2=float(bl["q_w_W_per_m2"]),
            du_e_dx_per_s=float(bl["du_e_dx_per_s"]),
            sweep_correction=float(bl["sweep_correction"]),
            delta_stag_m=float(bl["delta_stag_m"]),
            regime=str(bl["regime"]),
        )

    @router.post("/shock_chain", response_model=ShockChainResponse)
    async def shock_chain(request: ShockChainRequest) -> ShockChainResponse:
        """Multi-stage shock composition for waveriders / scramjet inlets."""
        import math
        from ..core import standard_atmosphere
        from ..core.shock_chain import (
            ShockChain, ShockStage, FreestreamState,
        )
        fs = standard_atmosphere(request.flight.altitude_km)
        U_inf = request.flight.mach * fs["a_ms"]
        freestream = FreestreamState(
            mach=request.flight.mach, T_K=fs["T_K"], P_Pa=fs["P_Pa"],
            rho_kgm3=fs["rho_kgm3"], U_ms=U_inf,
        )
        stages: list[ShockStage] = []
        for s in request.stages:
            try:
                stages.append(ShockStage(
                    kind=s.kind,
                    deflection_rad=(math.radians(s.deflection_deg)
                                    if s.deflection_deg is not None else 0.0),
                    length_m=s.length_m or 0.0,
                ))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc))
        chain = ShockChain(stages=tuple(stages))
        states = chain.advance(freestream)
        out: list[ShockStageState] = []
        for i, st in enumerate(states):
            out.append(ShockStageState(
                stage_index=i, kind=st.stage_kind,
                mach=float(st.mach), T_K=float(st.T_K), P_Pa=float(st.P_Pa),
                rho_kgm3=float(st.rho_kgm3),
                beta_deg=(math.degrees(st.beta_rad) if st.beta_rad > 0 else None),
                duct_residence_s=(float(st.duct_residence_s)
                                   if st.duct_residence_s > 0 else None),
            ))
        return ShockChainResponse(stages=out)

    @router.post("/trajectory", response_model=TrajectoryResponse)
    async def trajectory(request: TrajectoryRequest) -> TrajectoryResponse:
        """Solve a flight trajectory and return blackout windows by band."""
        from ..solver import _resolve_geometry
        from ..solver_trajectory import TrajectoryPoint, solve_trajectory
        try:
            geom = _resolve_geometry(request.geometry)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        waypoints = [
            TrajectoryPoint(
                t=float(w["t"]),
                mach=float(w["mach"]),
                altitude_km=float(w["altitude_km"]),
            )
            for w in request.waypoints
        ]
        result = solve_trajectory(
            trajectory=waypoints, geometry=geom,
            chemistry_mode=request.chemistry_mode,
            blackout_threshold_dB=request.blackout_threshold_dB,
        )
        peak_ne = max((float(w.ne_peak_m3) for w in result.waypoints), default=0.0)
        return TrajectoryResponse(
            geometry_name=geom.name, waypoints_n=len(waypoints),
            bands=list(result.bands),
            blackout_intervals=[
                {"band_label": iv.band_label,
                 "t_start": iv.t_start, "t_end": iv.t_end,
                 "duration_s": iv.duration_s,
                 "peak_atten_dB": float(iv.peak_atten_dB)}
                for iv in result.blackout_intervals
            ],
            peak_ne_m3=peak_ne,
        )

    @router.post("/uncertainty", response_model=UncertaintyResponse)
    async def uncertainty(request: UncertaintyRequest) -> UncertaintyResponse:
        """Monte Carlo over freestream perturbations."""
        from ..solver import _resolve_geometry
        from ..uncertainty import UncertaintyConfig, run_monte_carlo
        try:
            geom = _resolve_geometry(request.geometry)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        base = SolverInput(
            geometry=request.geometry,
            flight=request.flight,
        )
        cfg = UncertaintyConfig(
            n_samples=request.n_samples,
            freestream_temperature_sigma_rel=request.sigma_T_inf,
            freestream_density_sigma_rel=request.sigma_rho_inf,
        )
        result = run_monte_carlo(base_request=base, config=cfg)
        return UncertaintyResponse(
            geometry_name=geom.name, mach=request.flight.mach,
            altitude_km=request.flight.altitude_km,
            n_samples=result.n_samples,
            ne_mean_m3=float(result.ne_mean_m3),
            ne_std_m3=float(result.ne_std_m3),
            ne_p95_m3=float(result.ne_p95_m3),
            blackout_probability_by_band={
                k: float(v) for k, v in result.blackout_probability.items()
            },
        )

    return router
