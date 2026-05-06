"""FastAPI router — drop-in for KhoriumBackend.

Usage from KhoriumBackend:

    from fastapi import FastAPI
    from khorium_hypersonic.api import create_router

    app = FastAPI()
    app.include_router(create_router(prefix="/api/hypersonic"), tags=["hypersonic"])

The router exposes three endpoints under the configured prefix:

    POST /analyze              — single hypersonic prediction (SolverOutput)
    POST /search/exhaustive    — exhaustive chemistry-subset search
    POST /search/sobol_bo      — Sobol-seeded BO chemistry search
    GET  /presets              — list of geometry + mechanism presets

All bodies/responses are Pydantic models from khorium_hypersonic.solver
and khorium_hypersonic.search — type-safe end-to-end.
"""
from .router import create_router

__all__ = ["create_router"]
