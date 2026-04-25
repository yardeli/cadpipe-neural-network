"""PlasmaNet inference server.

FastAPI server that loads a trained PlasmaNet checkpoint and serves
predictions at /predict and /predict_batch endpoints.
"""
import argparse
import math
import time
from pathlib import Path

import numpy as np
import torch

from .model import PlasmaNet, load_checkpoint
from .physics import plasma_frequency_ghz, radar_status, STARLINK_FREQ_HZ


def create_app(model_path: str):
    """Create FastAPI app with loaded model."""
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="PlasmaNet", version="0.1.0",
                  description="Real-time hypersonic plasma prediction")
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                      allow_methods=["*"], allow_headers=["*"])

    # Load model at startup
    print(f"Loading model from {model_path}...")
    model, norm, metrics = load_checkpoint(model_path)
    model.eval()
    print(f"  Model loaded. Test metrics: {metrics.get('ne_orders_mae', '?')} orders MAE on ne")

    def _predict_single(mach, altitude_km, nose_radius_m=0.08,
                        radar_freq_ghz=12.0):
        """Run inference for one condition."""
        from .physics import standard_atmosphere, stagnation_pressure
        T_inf, p_inf, _, _ = standard_atmosphere(altitude_km)
        p_stag = stagnation_pressure(p_inf, mach)
        log10_p = math.log10(max(p_stag, 1.0))

        x = torch.tensor([[mach, altitude_km, nose_radius_m, log10_p]],
                         dtype=torch.float32)

        with torch.no_grad():
            y = model.predict_raw(x)

        y = y[0].numpy()
        T_stag = float(y[0])
        species = {
            "N2": max(0.0, float(y[1])),
            "O2": max(0.0, float(y[2])),
            "O": max(0.0, float(y[3])),
            "N": max(0.0, float(y[4])),
            "NO": max(0.0, float(y[5])),
        }
        log10_ne = float(y[6])
        ne = 10.0 ** log10_ne if log10_ne > 0 else 0.0
        fp = plasma_frequency_ghz(ne)
        status = radar_status(fp, radar_freq_ghz)

        return {
            "mach": mach,
            "altitude_km": altitude_km,
            "nose_radius_m": nose_radius_m,
            "T_stag_K": round(T_stag, 1),
            "ne_m3": f"{ne:.3e}",
            "fp_GHz": round(fp, 2),
            "status": status,
            "species": {k: round(v, 6) for k, v in species.items() if v > 1e-6},
        }

    @app.get("/")
    async def root():
        return {"service": "PlasmaNet", "version": "0.1.0",
                "model_metrics": metrics}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/predict")
    async def predict_get(mach: float = 10, altitude_km: float = 35,
                          nose_radius_m: float = 0.08, radar_freq_ghz: float = 12.0):
        """GET version for browser testing. Use query params:
        /predict?mach=10&altitude_km=35
        """
        t0 = time.monotonic()
        result = _predict_single(mach, altitude_km, nose_radius_m, radar_freq_ghz)
        result["inference_ms"] = round((time.monotonic() - t0) * 1000, 3)
        return result

    @app.post("/predict")
    async def predict(request: Request):
        try:
            body = await request.json()
            t0 = time.monotonic()

            result = _predict_single(
                mach=float(body.get("mach", 10)),
                altitude_km=float(body.get("altitude_km", 35)),
                nose_radius_m=float(body.get("nose_radius_m", 0.08)),
                radar_freq_ghz=float(body.get("radar_freq_ghz", 12.0)),
            )

            dt_ms = (time.monotonic() - t0) * 1000
            result["inference_ms"] = round(dt_ms, 3)
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/predict_batch")
    async def predict_batch(request: Request):
        try:
            body = await request.json()
            conditions = body.get("conditions", [])
            radar_freq = float(body.get("radar_freq_ghz", 12.0))

            if not conditions:
                return JSONResponse({"error": "No conditions provided"}, status_code=400)

            t0 = time.monotonic()
            results = []
            for cond in conditions:
                r = _predict_single(
                    mach=float(cond.get("mach", 10)),
                    altitude_km=float(cond.get("altitude_km", 35)),
                    nose_radius_m=float(cond.get("nose_radius_m", 0.08)),
                    radar_freq_ghz=radar_freq,
                )
                results.append(r)

            dt_ms = (time.monotonic() - t0) * 1000
            return JSONResponse({
                "results": results,
                "n_conditions": len(results),
                "total_inference_ms": round(dt_ms, 3),
                "avg_inference_ms": round(dt_ms / len(results), 3),
            })
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/predict_envelope")
    async def predict_envelope(request: Request):
        """Compute full detection envelope (Mach x altitude grid)."""
        try:
            body = await request.json()
            machs = body.get("machs", [5, 8, 10, 12, 15, 20, 25])
            alts = body.get("altitudes", [20, 25, 30, 35, 40, 45, 50])
            nose_r = float(body.get("nose_radius_m", 0.08))
            radar_freq = float(body.get("radar_freq_ghz", 12.0))

            t0 = time.monotonic()
            grid = {}
            for m in machs:
                row = []
                for a in alts:
                    r = _predict_single(float(m), float(a), nose_r, radar_freq)
                    row.append({
                        "fp_GHz": r["fp_GHz"],
                        "status": r["status"],
                        "ne_m3": r["ne_m3"],
                        "T_stag_K": r["T_stag_K"],
                    })
                grid[str(m)] = row

            dt_ms = (time.monotonic() - t0) * 1000
            return JSONResponse({
                "machs": machs,
                "altitudes": alts,
                "nose_radius_m": nose_r,
                "radar_freq_ghz": radar_freq,
                "grid": grid,
                "total_inference_ms": round(dt_ms, 3),
            })
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/uncertainty")
    async def uncertainty(request: Request):
        """Predict with Monte Carlo dropout uncertainty."""
        try:
            body = await request.json()
            from .physics import standard_atmosphere, stagnation_pressure

            mach = float(body.get("mach", 10))
            alt = float(body.get("altitude_km", 35))
            nose_r = float(body.get("nose_radius_m", 0.08))
            n_samples = int(body.get("n_samples", 100))

            T_inf, p_inf, _, _ = standard_atmosphere(alt)
            p_stag = stagnation_pressure(p_inf, mach)
            log10_p = math.log10(max(p_stag, 1.0))

            x = torch.tensor([[mach, alt, nose_r, log10_p]], dtype=torch.float32)

            t0 = time.monotonic()
            mean, std = model.predict_with_uncertainty(x, n_samples=n_samples)
            dt_ms = (time.monotonic() - t0) * 1000

            mean = mean[0].numpy()
            std = std[0].numpy()

            ne_mean = 10.0 ** float(mean[6])
            ne_low = 10.0 ** float(mean[6] - 2 * std[6])
            ne_high = 10.0 ** float(mean[6] + 2 * std[6])

            return JSONResponse({
                "mach": mach, "altitude_km": alt,
                "T_stag_K": {"mean": round(float(mean[0]), 1),
                             "std": round(float(std[0]), 1)},
                "ne_m3": {"mean": f"{ne_mean:.3e}",
                          "low_95": f"{ne_low:.3e}",
                          "high_95": f"{ne_high:.3e}"},
                "log10_ne_std": round(float(std[6]), 3),
                "n_samples": n_samples,
                "inference_ms": round(dt_ms, 3),
            })
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    return app


def main():
    parser = argparse.ArgumentParser(description="Serve PlasmaNet predictions")
    parser.add_argument("--model", type=str, default="checkpoints/plasmanet_v1.pt")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    app = create_app(args.model)

    import uvicorn
    print(f"\nStarting PlasmaNet server on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
