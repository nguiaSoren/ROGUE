# Platform go-live runbook

How to take the ROGUE platform (the multi-tenant `/v1` scan API + its execution worker) live. This is an ordered checklist — run the steps in order; each step says how to verify it before moving on. The platform layer is additive on top of the existing research stack: nothing here touches the research tables, the existing dashboard, or the existing `/api` surface.

## Architecture

The platform runs as **two processes against one database**. The split is deliberate: the request path is cheap (enqueue and return), and execution scales horizontally by running more workers — see `src/rogue/platform/worker.py` for the lease loop and the rationale.

```
                       Neon Postgres (one DATABASE_URL)
                  ┌──────────────────────────────────────┐
                  │  organizations · users · memberships  │
                  │  projects · api_keys                   │
                  │  scan_runs · scan_jobs · reports       │
                  └──────────────────────────────────────┘
                       ▲ enqueue                  ▲ lease + finalize
                       │                          │
        ┌──────────────┴───────────┐   ┌──────────┴───────────────────┐
        │  WEB service             │   │  WORKER service               │
        │  docker/backend.Dockerfile│   │  docker/worker.Dockerfile     │
        │  uvicorn rogue.api.main  │   │  python -m rogue.platform.worker│
        │                          │   │                               │
        │  serves /api  +  /v1     │   │  ScanWorker.run_forever():    │
        │  POST /v1/scans → ENQUEUE│   │   lease → engine.run → score  │
        │  (never runs a scan)     │   │   → save_report → finalize    │
        └──────────────────────────┘   └───────────────────────────────┘
                  ▲                              │ reaches out to
                  │ HTTPS                        ▼ customer target + judge
            customer (SDK / curl / CI)     OpenAI / Anthropic / OpenRouter
```

- The **WEB service** (existing, `docker/backend.Dockerfile`) serves the whole API, including the new `/v1` routes (`src/rogue/api/v1/scans.py`). `POST /v1/scans` only *enqueues* — it folds the request body into a `ScanSpec`, writes a `scan_runs` row plus a `scan_jobs` row, and returns `202` immediately. It never executes a scan in the request thread.
- The **WORKER service** (new, `docker/worker.Dockerfile`) is a long-lived background process — no HTTP port. It leases jobs from `scan_jobs`, drives the `ScanEngine`, streams progress back into the `scan_runs` row, persists the `reports` payload, and finalizes the record (see `ScanWorker.run_once` in `src/rogue/platform/worker.py`).
- Both share the **same Neon `DATABASE_URL`**. The queue *is* the `scan_jobs` table (Postgres-backed lease, `src/rogue/platform/queue.py`); there is no separate broker. `REDIS_URL` is optional and only relevant if a future deployment swaps the queue/cache backend — the default Postgres queue needs nothing beyond `DATABASE_URL`.

## Step 1 — migration

The platform tables ship in **migration `0022`** (`src/rogue/db/migrations/versions/0022_platform_tables.py`). It is **additive only** — it creates eight new tables (`organizations`, `users`, `memberships`, `projects`, `api_keys`, `scan_runs`, `scan_jobs`, `reports`) and touches nothing that already exists. The alembic `env.py` reads `DATABASE_URL` from `.env` via dotenv, so point it at Neon and run:

```bash
uv run alembic upgrade head
```

**Verify** — the eight tables now exist:

```bash
docker compose exec -T postgres psql -U rogue -d rogue -c "\dt"   # local
# or against Neon directly:
psql "$DATABASE_URL" -c "\dt"
```

You should see `organizations`, `users`, `memberships`, `projects`, `api_keys`, `scan_runs`, `scan_jobs`, and `reports` in the list alongside the existing research tables. Confirm the revision landed:

```bash
uv run alembic current   # → 0022 (head)
```

**Rollback** — `downgrade` drops the eight tables in FK-safe order (`reports` → `scan_jobs` → `scan_runs` → `api_keys` → `projects` → `memberships` → `users` → `organizations`):

```bash
uv run alembic downgrade 0021
```

## Step 2 — deploy the worker

Add a **new Render background worker service** built from `docker/worker.Dockerfile` (Render service type "Background Worker" — no port, no health check). It mirrors the web image exactly except for its `CMD`, which runs `python -m rogue.platform.worker` instead of uvicorn.

Worker env vars:

| Var | Purpose |
|---|---|
| `DATABASE_URL` | The Neon connection string — **same value as the web service**. The worker leases from `scan_jobs` and finalizes `scan_runs`/`reports` here. |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` | Provider keys. The worker needs these to (a) reach the customer's target model and (b) run the judge. Set whichever providers your customers' targets and your `JUDGE_MODEL` route through. |
| `JUDGE_MODEL` | The independent judge model — **point it at a credited model** the keys above can actually call (default `anthropic/claude-sonnet-4-6`, routed via `OPENROUTER_API_KEY`; see `src/rogue/reproduce/judge.py` and `src/rogue/config.py`). If the judge model has no credit, every scan fails at grading. |
| `REDIS_URL` | Optional. Not needed for the default Postgres-backed queue; leave unset unless a deployment swaps the backend. |

The **WEB service** must carry the **same `DATABASE_URL`** (it writes the `scan_runs`/`scan_jobs` rows the worker leases). The web service does *not* need the provider keys to enqueue — only the worker executes — but it shares the DB. The `/v1` routes are wired **defensively**: the service getters in `src/rogue/api/v1/deps.py` return **`503 {"error":{"code":"unavailable"}}`** until the platform services are wired, and the DB-backed paths degrade rather than crash if Neon is cold. So bringing `/v1` up before the migration or before the services are wired returns a clean `503`, never a `500` or a downed service (same DB-free-liveness discipline as the web image's non-fatal migration in `docker/backend.Dockerfile`).

**Verify** — after the worker boots, its logs should show the migration line (non-fatal) and then the lease loop running. With no queued jobs the worker idles (it sleeps `poll_interval` between empty leases, per `run_forever`).

### Option B — in-process worker ($0, recommended to start)

Render background workers are a **paid** service (no free tier). For a $0 launch, run the worker loop **inside the web service** instead of deploying the separate worker above. Set `ROGUE_INPROCESS_WORKER=1` on the WEB service, plus the same execution credentials the worker needs — `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` and `JUDGE_MODEL` (the web service otherwise only needs `DATABASE_URL` to enqueue). On startup, `rogue.api.main`'s lifespan starts a `ScanWorker.run_forever` background task in the same process — off the request thread (scans are awaited I/O, so the API stays responsive) — and cancels it cleanly on shutdown. One free Docker web service then both serves `/v1` and executes scans; **skip Step 2 entirely.** Trade-offs: the dyno's CPU is shared between request handling and scan execution, and a free dyno that sleeps won't run scans while asleep (keep it warm — UptimeRobot already pings `/api/health`). The two paths are interchangeable — same `ScanWorker`, same DB — so flip `ROGUE_INPROCESS_WORKER` off and deploy the separate worker service (Step 2) when scan volume warrants it.

## Step 3 — seed a tenant

Mint an organization and its first API key with the seeding tool. The raw `rk_live_…` key is printed **exactly once** and is never stored (only its sha256 hash + a display prefix land in `api_keys` — see `generate_api_key` in `src/rogue/platform/tenancy.py`):

```bash
python scripts/ops/seed_org.py --name "Acme"
```

Copy the printed `rk_live_…` key and give it to the customer. If you lose it, mint a new one — it cannot be recovered from the database.

## Step 4 — verify end to end

Drive one scan all the way through with the key from Step 3. Set `API` to your web service URL (e.g. `https://rogue-api-mr5w.onrender.com`).

```bash
# 1) Enqueue — returns 202 with {"scan_id","status":"queued"} and a Location header.
curl -X POST "$API/v1/scans" \
  -H "Authorization: Bearer rk_live_…" \
  -H "Content-Type: application/json" \
  -d '{"endpoint":"https://api.openai.com/v1/chat/completions","api_key":"<customer-target-key>","pack":"default"}'

# 2) Poll — status walks queued → running → completed; progress climbs to 100.
curl -H "Authorization: Bearer rk_live_…" "$API/v1/scans/<scan_id>"

# 3) Report — once status == completed, fetch the customer artifact (json|html|pdf via ?format=).
curl -H "Authorization: Bearer rk_live_…" "$API/v1/scans/<scan_id>/report"
```

A scan stuck at `queued` means **no worker is leasing** (see caveats). The report endpoint returns `404 report_not_ready` until the scan reaches `completed` — that is expected while it runs, not an error.

## Caveats

- **The example CI workflow runs on push.** `.github/workflows/rogue-scan.example.yml` is an *example* meant to be copied into a customer repo, but it currently sits in `.github/workflows/` with `on: pull_request` — so **this repo's** GitHub Actions will try to run it. Before any `git push`, change it to `on: workflow_dispatch` (manual-only) **or move it out of `workflows/`** (e.g. to `.github/examples/`). Otherwise every PR triggers a real scan job in CI against whatever secrets are configured.
- **The worker must be scaled to ≥1 instance, or scans sit `queued` forever.** Nothing in the web service executes a scan; if the Render worker service is at 0 instances (or crash-looping), `POST /v1/scans` keeps succeeding with `202` but no job is ever leased and every scan stays `queued`. Confirm the worker is up as the first thing you check when a scan doesn't progress. To increase throughput, run more worker instances against the same DB — they coordinate through the `scan_jobs` lease and won't double-run a job.
- **Provider rate limits.** Each trial hits the customer's target model and the judge model. Large `max_tests` / `n_trials`, or many concurrent scans across workers, can trip provider rate limits (429s) on `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` — a failed trial surfaces as a `failed` scan with the error recorded on the record (`ScanWorker.run_once` never lets an engine exception escape). Throttle by capping per-scan `max_tests`/`n_trials` and worker count, not by removing keys.
- **Neon connection ceiling.** Neon's free/launch tiers cap concurrent connections. The web service, every worker instance, and `resolve_principal_from_token`'s short-lived auth engine all open connections to the same `DATABASE_URL`. The auth path and migration path are short-lived (built and disposed per call — see `_build_session` in `src/rogue/platform/tenancy.py`), but each running worker holds a steady connection. If you scale workers up, watch the Neon connection count and use Neon's pooled connection string (pgbouncer) for the `DATABASE_URL` if you approach the ceiling.
- **Cold-Neon startup is safe by design.** Both images run `alembic upgrade head` non-fatally and then `exec` the long-lived process, so a suspended/cold Neon can degrade data paths but can never stop the web port from binding or the worker from starting. Once Neon wakes, the worker's lease loop drains whatever queued while it was cold.
