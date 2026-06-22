FROM apache/airflow:2.9.1

COPY requirements-airflow.txt .
RUN pip install -r requirements-airflow.txt

# Dockerfile
# -----------
# Single image used by all Airflow services (webserver, scheduler, init, workers).
# Extends the official Airflow 2.9 image with:
#   - spaCy en_core_web_lg  (NLP + NER)
#   - sentence-transformers all-MiniLM-L6-v2  (embeddings)
#   - project Python packages (neo4j, pydantic, requests)
#
# Build: docker compose build
# This image is built once and reused by all airflow-common services.
#
# Layer order is optimized for cache efficiency:
#   1. System deps (rarely change)
#   2. Python deps (change occasionally)
#   3. spaCy model download (large, cache separately)
#   4. Sentence-transformer model prefetch
#   5. Application code (changes frequently)
 
FROM apache/airflow:2.9.0-python3.11
 
# Switch to root for system package installs
USER root
 
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*
 
# Back to airflow user for pip installs
USER airflow
 
# ── Python dependencies ────────────────────────────────────────────────────
# Install in one RUN to keep layer count low
COPY requirements-airflow.txt /tmp/requirements-airflow.txt
 
RUN pip install --no-cache-dir -r /tmp/requirements-airflow.txt
 
# ── spaCy model ────────────────────────────────────────────────────────────
# Download en_core_web_lg at build time so container startup is instant.
# Model size: ~560 MB. Cached in image layer.
RUN python -m spacy download en_core_web_md
 
# ── sentence-transformers model prefetch ───────────────────────────────────
# Pre-download all-MiniLM-L6-v2 at build time.
# Without this, the first DAG run downloads ~90 MB from HuggingFace Hub.
# With this, the model is in the image and loads from disk.
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('all-MiniLM-L6-v2'); \
print('all-MiniLM-L6-v2 prefetched')"
 
# ── Application code ───────────────────────────────────────────────────────
# Mounted as volume in docker-compose; COPY here is for standalone image builds.
# The volume mount in docker-compose.yml takes precedence at runtime.
WORKDIR /opt/airflow/supply-chain-monitor
 
ENV PYTHONPATH=/opt/airflow/supply-chain-monitor