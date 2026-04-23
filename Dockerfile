# PlasmaNet inference server — minimal Docker image
# No Cantera needed at runtime (only for training data generation)
FROM python:3.12-slim

WORKDIR /app

# Install PyTorch CPU-only (smaller image)
RUN pip install --no-cache-dir \
    torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
    numpy \
    fastapi \
    uvicorn[standard]

# Copy application code
COPY plasmanet/ /app/plasmanet/
COPY demo.py /app/

# Copy model checkpoint (baked into image for fast cold start)
# In production, mount from S3 or volume instead
COPY checkpoints/plasmanet_best.pt /app/checkpoints/plasmanet_best.pt

EXPOSE 8100

# Health check
HEALTHCHECK --interval=30s --timeout=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/health')"

# Run inference server
CMD ["python", "-m", "plasmanet.serve", "--model", "checkpoints/plasmanet_best.pt", "--port", "8100"]
