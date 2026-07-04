FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better layer caching
COPY phase2/phase5/requirements.txt ./phase2/phase5/requirements.txt

RUN pip install --no-cache-dir -r phase2/phase5/requirements.txt

# Copy the Phase 5 package while preserving its package structure
COPY phase2/phase5/ ./phase2/phase5/

# Ensure all package directories are Python packages
RUN mkdir -p \
        /app/phase2 \
        /app/phase2/phase5 \
        /app/phase2/phase5/agent \
        /app/phase2/phase5/tools \
        /app/phase2/phase5/streaming \
        /app/phase2/phase5/scripts \
    && touch /app/phase2/__init__.py \
    && touch /app/phase2/phase5/__init__.py \
    && touch /app/phase2/phase5/agent/__init__.py \
    && touch /app/phase2/phase5/tools/__init__.py \
    && touch /app/phase2/phase5/streaming/__init__.py \
    && touch /app/phase2/phase5/scripts/__init__.py

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "phase2.phase5.scripts.run_agent_consumer"]