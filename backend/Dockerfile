# ==============================================================================
# BrandShield AI — Production Backend Dockerfile
# Multi-stage secure build with non-root runtime
# ==============================================================================

# --- Stage 1: Builder ---
FROM python:3.12-slim AS builder

WORKDIR /build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# --- Stage 2: Production Runtime ---
FROM python:3.12-slim AS runtime

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/appuser/.local/bin:$PATH" \
    PYTHONPATH=/app

# Install runtime dependencies for PostgreSQL support
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged system user for secure execution
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Copy installed Python packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application source code and migrations
COPY --chown=appuser:appgroup alembic.ini .
COPY --chown=appuser:appgroup alembic ./alembic
COPY --chown=appuser:appgroup app ./app

# Set non-root user
USER appuser

# Health check against native API health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health').status == 200 else 1)" || exit 1

EXPOSE 8000

# Production uvicorn execution with 4 workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--proxy-headers", "--forwarded-allow-ips", "*"]
