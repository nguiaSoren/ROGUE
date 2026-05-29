# Backend image for ROGUE — FastAPI + SQLAlchemy + Postgres+pgvector via DATABASE_URL.
# Built by docker-compose.full.yml (§A.27). At startup: alembic upgrade head → seed → uvicorn.
# Standard Python 3.11 pattern; uv for fast deterministic dep resolution from uv.lock.

FROM python:3.11-slim

WORKDIR /app

# uv handles deps; pinned to a stable minor for reproducibility.
RUN pip install --no-cache-dir uv==0.4.20

# Install ONLY dependencies, not the project itself. The app runs from /app/src
# via PYTHONPATH (set below), so the `rogue` package is never built/installed —
# and --no-install-project avoids hatchling trying to build its wheel here, before
# src/ has been copied (which fails: "no directory matches the project name").
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code + migrations + fixtures (the seed script needs the goldens).
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY alembic.ini ./
COPY tests/fixtures/ ./tests/fixtures/

# Bandit state file so /api/bandit/stats renders populated in prod (relative
# path Path("data/discovery_bandit.json") resolves from WORKDIR /app). The rest
# of data/ is excluded via .dockerignore.
COPY data/discovery_bandit.json ./data/discovery_bandit.json

# Make the venv's binaries (uvicorn, alembic, python) discoverable + place src/ on PYTHONPATH.
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/src"

EXPOSE 8000 8001

# Prod start: apply migrations (idempotent — Neon is pre-migrated, this is a
# safety net), then serve on the platform-injected $PORT (Render) or 8000.
# No seed_demo_data here — real data is restored into Neon out of band.
# docker-compose.full.yml overrides this with its own alembic + seed + uvicorn chain.
CMD ["sh", "-c", "alembic upgrade head && uvicorn rogue.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
