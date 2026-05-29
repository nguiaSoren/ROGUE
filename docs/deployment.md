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

## How DATA works — updating the live site
Local `.env` `DATABASE_URL` now points at **Neon** (the live DB) by default, so the
pipeline writes straight to production. There is effectively **one database** — no
copy/sync step. **To push new data live, just run normally:**
```
uv run python scripts/harvest_once.py --since 1d    # new attacks    → Neon (live)
uv run python scripts/reproduce_once.py             # run them → breaches → Neon (live)
```
New data shows on the site within the cache window (below), or immediately after the next deploy.

- **The breach matrix is a live SQL view** (`breach_matrix`), computed on every request —
  so new breaches appear **automatically**. No code change, no manual "refresh." (The
  `breach_matrix_daily_snapshot` materialized view is only used by
  `scripts/snapshot_breach_matrix.py`, not the dashboard, so you never refresh it for the site.)
- **Fast local sandbox** (does NOT touch live): the old local Docker DB is kept as
  `LOCAL_DATABASE_URL` in `.env`. Start it (`docker compose up -d`) and override for one run:
  ```
  DATABASE_URL="$(grep ^LOCAL_DATABASE_URL= .env | cut -d= -f2-)" uv run python scripts/reproduce_once.py ...
  ```
  Local does NOT auto-receive Neon's data (or vice-versa) — each run writes to whichever
  DB `DATABASE_URL` names. Default = Neon.

## Caching
Dashboard pages are cached and **revalidated every 5 minutes** (ISR) — see `REVALIDATE_SECONDS` in `frontend/src/lib/api.ts`. Visitors get instant loads; data refreshes in the background every 5 min. The live attack ticker (SSE) is a separate client connection, so it stays real-time.
