# phase2/webhooks/Dockerfile

FROM python:3.11-slim

# ─────────────────────────────────────────────
# System deps
# gcc needed for some pydantic/uvicorn builds
# on slim base. curl for healthcheck.
# ─────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       curl \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────
# Working directory
# ─────────────────────────────────────────────
WORKDIR /app

RUN mkdir -p /app/data && chmod 777 /app/data

WORKDIR /app

# ─────────────────────────────────────────────
# Install dependencies first (layer caching)
# Copy requirements before source code so a
# code-only change doesn't reinstall packages.
# ─────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir \
    fastapi==0.111.* \
    uvicorn==0.30.* \
    pydantic==2.* \
    neo4j==5.* \
    redis==5.* \
    requests==2.* \
    python-dateutil==2.*

# ─────────────────────────────────────────────
# Copy source
# Copy the whole project so phase2 imports work.
# .dockerignore keeps this clean (see below).
# ─────────────────────────────────────────────
COPY . .

# ─────────────────────────────────────────────
# Non-root user — never run as root in prod
# ─────────────────────────────────────────────
RUN useradd -m -u 1001 webhookuser
USER webhookuser

# ─────────────────────────────────────────────
# Port
# ─────────────────────────────────────────────
EXPOSE 8001

# ─────────────────────────────────────────────
# Healthcheck
# Docker will mark the container unhealthy if
# /health stops responding. Checked every 30s.
# ─────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# ─────────────────────────────────────────────
# Entrypoint
# --host 0.0.0.0 required — default 127.0.0.1
# is unreachable from outside the container.
# --workers 2 handles burst webhook traffic
# without spinning up a full Gunicorn stack.
# ─────────────────────────────────────────────
CMD ["uvicorn", "phase2.webhooks.usgs_webhook:app", \
     "--host", "0.0.0.0", \
     "--port", "8001", \
     "--workers", "2"]