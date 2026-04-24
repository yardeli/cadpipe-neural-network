# PlasmaNet multi-stage image.
#
# Two tags are built from this file (see cdk/plasmanet_service_stack.py):
#
#   :plasmanet-service   — FastAPI mock server (Layer A: Fargate inference service)
#                          Lightweight: no torch. Add it once the NN surrogate
#                          is integrated and the mock_server physics fallback is
#                          replaced with real model inference.
#
#   :plasmanet-worker    — SU2-NEMO post-processor (Layer B: Batch worker)
#                          Requires SU2-NEMO + Mutation++ base image; this
#                          Dockerfile is a placeholder — build the worker image
#                          from a dedicated su2-nemo base in a follow-up commit.
#
# Build:
#   docker build --target service -t plasmanet:plasmanet-service .
#   docker build --target worker  -t plasmanet:plasmanet-worker  .   # placeholder
#
# Run locally (mirrors mock server port used by the frontend):
#   docker run --rm -p 8200:8200 plasmanet:plasmanet-service

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build-time deps into a prefix so the runtime stage gets a clean copy.
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/deps fastapi "uvicorn[standard]" pydantic

# ── Stage 2: service runtime ──────────────────────────────────────────────────
FROM python:3.11-slim AS service

# Non-root user for Fargate / ECS (least-privilege security posture).
RUN useradd --create-home --shell /bin/bash --uid 1001 plasmanet

WORKDIR /app

# Copy only the installed packages from the builder stage.
COPY --from=builder /deps /usr/local

# Copy application code — plasmanet package only (no training scripts, data, etc.).
COPY plasmanet/ ./plasmanet/

# Switch to non-root before the final CMD.
USER plasmanet

EXPOSE 8200

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8200/health')"

# CMD matches the mock_server entry-point; replace with the real inference server
# once the NN surrogate is integrated.
CMD ["python", "-m", "plasmanet.mock_server", "--host", "0.0.0.0", "--port", "8200"]

# ── Stage 3: worker placeholder ───────────────────────────────────────────────
# The SU2-NEMO worker image requires a pre-built base that bundles SU2-NEMO
# and Mutation++ libraries.  This is a placeholder that inherits from the
# service stage so `docker build --target worker` succeeds.
# Replace FROM with a real su2-nemo base image in a follow-up commit.
FROM service AS worker

# Override the command — the real worker entry-point is the post-processing
# pipeline (extract_nemo_field → scan_aspect → DetectabilityReport → S3).
# For now it falls back to the mock server so the image is runnable.
# Remove this override once the worker entry-point is implemented.
CMD ["python", "-m", "plasmanet.mock_server", "--host", "0.0.0.0", "--port", "8200", \
     "--dry-run"]
