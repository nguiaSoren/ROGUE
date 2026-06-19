# Worker image for ROGUE — the scan worker that leases jobs from `scan_jobs` and runs them.
# Mirrors docker/backend.Dockerfile (same base, same uv flags, same PYTHONPATH) — the only
# difference is the CMD: instead of serving uvicorn, this runs the long-lived scan worker
# (`python -m rogue.platform.worker`). The web service ENQUEUES scans; this WORKER executes them.
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

# Bandit state file so any escalation/discovery state resolves the same relative
# path Path("data/discovery_bandit.json") the web image uses (resolved from WORKDIR
# /app). The rest of data/ is excluded via .dockerignore.
COPY data/discovery_bandit.json ./data/discovery_bandit.json

# Make the venv's binaries (python, alembic) discoverable + place src/ on PYTHONPATH.
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/src"

# Prod start: apply migrations (idempotent — Neon is pre-migrated, so this is only a
# safety net), then exec the scan worker. Same non-fatal-migration discipline as the
# web image: a cold/unreachable Neon must NOT stop the worker from starting — once the
# DB is reachable the worker's lease loop simply picks up queued jobs. No port is bound
# (the worker is a background process, not an HTTP server), so there is no EXPOSE here.
# The worker leases from `scan_jobs` and drives the engine forever (rogue.platform.worker.main()).
CMD ["sh", "-c", "alembic upgrade head || echo 'migration failed (non-fatal)'; exec python -m rogue.platform.worker"]
