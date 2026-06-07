# Deployment

ROGUE's live demo runs on three free-tier services plus a keep-warm pinger.

## Live URLs
- **Dashboard (frontend):** https://rogue-eosin.vercel.app
- **API (backend):** https://rogue-api-mr5w.onrender.com — e.g. `/api/health`
- **Repo:** https://github.com/nguiaSoren/ROGUE
- **Replay the intro (for the demo):** **https://rogue-eosin.vercel.app/?intro** — force-plays the 16s intro overlay every time. (Normally the intro is first-visit-only, gated by `localStorage`; a hard refresh does NOT replay it because refreshes don't clear localStorage. The `?intro` query param is the escape hatch.)

## Architecture
```
Browser → Vercel (Next.js frontend) → Render (FastAPI backend) → Neon (Postgres + pgvector)
                                  ↑
                 UptimeRobot pings /api/health every 5 min (keeps Render warm)
```

Two distinct health endpoints, by design:
- **`/api/livez`** — pure liveness, touches NO database, always 200. **This is what Render's "Health Check Path" must point at.** It only proves the web process is accepting requests, so a cold/suspended Neon never makes Render declare the instance unhealthy and restart it.
- **`/api/health`** — readiness: it runs `COUNT(*)` queries against Neon for the dashboard freshness banner, and degrades gracefully to `{"db": "down"}` (never 500) if the DB is unreachable. UptimeRobot pings *this* one on purpose — the query is what keeps Neon warm. It accepts HEAD as well as GET (UptimeRobot's free plan only sends HEAD).

## Services
| Service | Role | Tier / notes | Console |
|---|---|---|---|
| **Vercel** | Next.js frontend. **Root Directory = `frontend/`** | Hobby (free) | vercel.com |
| **Render** | FastAPI backend, built from `docker/backend.Dockerfile` | Free Web Service — sleeps after ~15 min idle (cold start ~30-50s) | dashboard.render.com |
| **Neon** | Postgres 17 + pgvector — **the database** | Free (0.5 GB, scales to zero) | console.neon.tech |
| **UptimeRobot** | Pings the backend so it doesn't sleep | Free, 5-min interval | dashboard.uptimerobot.com/monitors |

## How deploys work (CODE)
- Push to `main` on GitHub → **Vercel rebuilds the frontend AND Render rebuilds the backend automatically.**
- This updates **code only** — it does **not** change the data.

## Environment variables (set in the service dashboards, never in the repo)
- **Vercel:** `NEXT_PUBLIC_API_BASE` = the Render API URL (baked into the build).
- **Render:** `DATABASE_URL` = the Neon connection string, with the scheme **`postgresql+psycopg://`** (the app uses psycopg v3 — the plain `postgresql://` form crashes on boot).

## How DATA works — updating the live site
Local `.env` `DATABASE_URL` now points at **Neon** (the live DB) by default, so the
pipeline writes straight to production. There is effectively **one database** — no
copy/sync step. **To push new data live, just run normally:**
```
uv run python scripts/harvest/harvest_once.py --since 1d    # new attacks    → Neon (live)
uv run python scripts/reproduce/reproduce_once.py             # run them → breaches → Neon (live)
```
New data shows on the site within the cache window (below), or immediately after the next deploy.

- **The breach matrix is a live SQL view** (`breach_matrix`), computed on every request —
  so new breaches appear **automatically**. No code change, no manual "refresh." (The
  `breach_matrix_daily_snapshot` materialized view is only used by
  `scripts/ops/snapshot_breach_matrix.py`, not the dashboard, so you never refresh it for the site.)
- **The bandit widget is live too** — its state lives in Neon (`bandit_state` table, upserted
  by the harvest), so `/api/bandit/stats` reflects the latest harvest automatically (no redeploy).
- **Fast local sandbox** (does NOT touch live): the local Docker DB (`LOCAL_DATABASE_URL`
  in `.env`, also Postgres 17) is for quick experiments. Start it (`docker compose up -d`)
  and override for one run:
  ```
  DATABASE_URL="$(grep ^LOCAL_DATABASE_URL= .env | cut -d= -f2-)" uv run python scripts/reproduce/reproduce_once.py ...
  ```

## Keeping local ↔ Neon in sync
The two databases are separate copies (both Postgres 17). There is **no real-time
auto-sync** — a laptop DB and a cloud DB can't cleanly stream to each other, and it's not
worth the fragility. Instead, `scripts/ops/sync_db.sh` does a one-command full copy (runs the
pg17 tools inside the local container, so nothing to install):
```
./scripts/ops/sync_db.sh pull     # Neon → local : mirror the live DB into local (run after a harvest)
./scripts/ops/sync_db.sh push     # local → Neon : publish local to live (overwrites live — confirms first)
```
Typical loop: `harvest`/`reproduce` → Neon (live), then `./scripts/ops/sync_db.sh pull` so your
local copy matches for fast experiments.

## Caching
Dashboard pages are cached and **revalidated every 5 minutes** (ISR) — see `REVALIDATE_SECONDS` in `frontend/src/lib/api.ts`. Visitors get instant loads; data refreshes in the background every 5 min. The live attack ticker (SSE) is a separate client connection, so it stays real-time.

## Neon-serverless resilience invariants
Neon free tier drops idle server-side connections (and a regional incident drops them en masse — this caused the 2026-06-01 outage). The live-serving path holds these invariants:
- **Liveness is DB-free** — Render's health check points at `/api/livez`, which never touches Postgres. App import and startup are zero-IO; the engine is lazily created on first request, and platform `/v1` wiring is wrapped so a DB-down state can't block boot.
- **Every serving-path engine hardens the pool** — `pool_pre_ping=True` (validates/replaces a dead connection on checkout), `pool_recycle=300` (retires connections before Neon's idle timeout), `pool_timeout=10` (fails fast with a clean error the frontend retries, instead of a 30s hang the platform turns into a 502). This holds for the API engine (`api/main.py`) and the platform stores (`store.py`, `secrets.py`, `repertoire.py`, `integration_store.py`, `engine.py`).
- **No DB connection is held across an LLM call or a stream** — the SSE feed (`/api/sse/feed`) scopes its session to the initial snapshot and returns the connection to the pool before the heartbeat loop; the escalation context is built in a short session closed before the ladder's LLM calls.

Known gaps (tracked, not yet hardened — engine code untouched in this pass):
- `platform/queue.py` `build_postgres_job_queue()` and the public MCP server engine (`mcp_server/server.py`) create their engines **without** the pool-hardening args, yet both run on a live Neon-backed path (the queue engine is wired into the `/v1` API at startup; the MCP server serves the public read-only tools). They should adopt the same `pool_pre_ping`/`pool_recycle`/`pool_timeout` as the other platform engines.
- `platform/tenancy.py` `_build_session` spins up a fresh engine per call and disposes it (no pooling/reuse, so stale-idle accumulation can't happen), but a first connection to a cold Neon is still unvalidated; lower-risk than the pooled cases above.
- CLI/batch engines (`reproduce/escalation_ladder.py`, `db/neon_sync.py`, `db/image_cache.py`) are not on the request-serving path, so their lack of pool args is acceptable.
