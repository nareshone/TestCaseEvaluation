# ── Base image ────────────────────────────────────────────────
FROM python:3.11-slim

# ── Working directory ─────────────────────────────────────────
WORKDIR /app

# ── Install dependencies ──────────────────────────────────────
# Copy only requirements first so Docker caches this layer
COPY requirements_api_server.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── Copy application code ─────────────────────────────────────
COPY test_api_server.py .

# ── Render injects PORT env var automatically ─────────────────
# We read it as API_PORT in test_api_server.py
# Default fallback is 10000 (Render's default)
ENV API_PORT=10000
ENV API_HOST=0.0.0.0
ENV API_BEARER_TOKEN=test-bearer-token-123

# ── Expose port ───────────────────────────────────────────────
EXPOSE 10000

# ── Start server ──────────────────────────────────────────────
CMD ["python", "test_api_server.py"]
