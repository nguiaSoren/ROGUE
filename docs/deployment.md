# Deployment

ROGUE's live demo runs on three free-tier services plus a keep-warm pinger.

## Live URLs
- **Dashboard (frontend):** https://rogue-eosin.vercel.app
- **API (backend):** https://rogue-api-mr5w.onrender.com — e.g. `/api/health`
- **Repo:** https://github.com/nguiaSoren/ROGUE

## Architecture
```
Browser → Vercel (Next.js frontend) → Render (FastAPI backend) → Neon (Postgres + pgvector)
                                  ↑
                 UptimeRobot pings /api/health every 5 min (keeps Render warm)
```

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

## How DATA works (read this before "updating the website")
There are **two separate databases** — they are NOT auto-synced:
1. **Local Postgres** (Docker container `rogue-postgres`) — your local `.env` `DATABASE_URL` points here. `harvest_once.py` / `reproduce_once.py` write **here** by default.
2. **Neon** (cloud) — what the **live site** reads.

So when you find new attacks, **Neon is the DB that the live site needs updated.** Two ways:
- **A — run the pipeline straight against Neon** (set `DATABASE_URL` to the Neon `postgresql+psycopg://...` string for that run):
  ```
  DATABASE_URL='postgresql+psycopg://...neon...' uv run python scripts/harvest_once.py --since 1d
  DATABASE_URL='postgresql+psycopg://...neon...' uv run python scripts/reproduce_once.py
  # if breach data changed, refresh the snapshot:
  psql '<neon url>' -c 'REFRESH MATERIALIZED VIEW breach_matrix_daily_snapshot;'
  ```
- **B — run locally, then sync local → Neon** (dump + restore, as in the initial load):
  ```
  docker compose exec -T postgres pg_dump -U rogue -d rogue --no-owner --no-privileges | gzip > dump.sql.gz
  gunzip -c dump.sql.gz | psql '<neon url>'
  ```

New Neon data surfaces on the live site within the cache window (below), or immediately after a redeploy.

## Caching
Dashboard pages are cached and **revalidated hourly** (ISR) — see `REVALIDATE_SECONDS` in `frontend/src/lib/api.ts`. Visitors get instant loads; the data refreshes in the background every hour. The live attack ticker (SSE) is a separate client connection, so it stays real-time.
