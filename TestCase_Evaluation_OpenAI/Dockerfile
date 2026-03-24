# ─────────────────────────────────────────────────────────────
# CEV Rules Test Portal — Dockerfile
# Multi-stage build: keeps final image lean (~200 MB)
# ─────────────────────────────────────────────────────────────

# ── Stage 1: Build — install dependencies ────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools needed for faiss-cpu and numpy compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first — leverages Docker layer cache
# (this layer only rebuilds when requirements.txt changes)
COPY requirements.txt .

# Install into a prefix directory so we can copy cleanly to final stage
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime — minimal final image ───────────────────
FROM python:3.11-slim AS runtime

# Create a non-root user for security
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source code
COPY --chown=appuser:appuser agents.py        .
COPY --chown=appuser:appuser config.py        .
COPY --chown=appuser:appuser main.py          .
COPY --chown=appuser:appuser mock_api.py      .
COPY --chown=appuser:appuser vector_store.py  .
COPY --chown=appuser:appuser excel_reporter.py .
COPY --chown=appuser:appuser templates/       templates/
COPY --chown=appuser:appuser static/          static/

# Create runtime directories with correct ownership
RUN mkdir -p data/faiss_store outputs \
    && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose the application port
EXPOSE 8000

# Health check — hits the config endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/config')" \
    || exit 1

# Start the server
# reload=False in production — use --reload only for local dev
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
