# Benchmark engine & datasets

> Team E. Benchmarking turned into a product feature: a tenant fires a known goal set at their target and gets back a single, comparable attack-success-rate (ASR) — the standardized yardstick that sits alongside a scan's risk `score`. This doc specifies the *two* engines that produce an ASR, when each runs, the datasets they consume, dataset versioning/freezing, and persistence to `benchmark_runs`. It does **not** redefine `TargetSpec`, `BenchmarkReport`, `ScanStatus`, the ID scheme, or the async-job pattern — those are frozen in [../ARCHITECTURE.md](../ARCHITECTURE.md) §4–§5 and elaborated in the API and orchestration docs cited below. The scoring math (how an ASR becomes a leaderboard number and a trend line) is deferred to [./scoring-and-trends.md](./scoring-and-trends.md).

Read first: [../ARCHITECTURE.md](../ARCHITECTURE.md) §2 (the one-engine invariant) and §4 (the `ScanEngine.benchmark` contract); [../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md) for the `POST /v1/benchmark` HTTP envelope this doc backs; [../orchestration/scan-engine-adapter.md](../orchestration/scan-engine-adapter.md); [./scoring-and-trends.md](./scoring-and-trends.md).

Status: **single-turn engine BUILT; platform plumbing is an MVP.** The self-serve single-turn engine shipped: `run_benchmark` (`src/rogue/benchmark.py`), `VALID_DATASETS = ("advbench_100", "jbb_100")`, `ScanEngine.benchmark`, and `POST /v1/benchmark` → `GET /v1/benchmark/{id}`. **Caveats vs. this doc:** the platform `DefaultBenchmarkService` runs the benchmark **inline (MVP)** against an **in-memory record map** — it is *not* enqueued on the scan `JobQueue` and not run by `ScanWorker` (see [../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md)), and benchmark records are **not** persisted to the `benchmark_runs` table by this path. The repertoire-ladder engine (`scripts/benchmark/benchmark_run.py`) remains operator-run and is not wired to `/v1`. The §1 two-engine framing is accurate.

---

## 1. Two engines, one ASR — and when each runs

There are two benchmark engines in this codebase, and the distinction is the load-bearing fact of this team. They produce the *same kind of number* — `n_breached / n_goals` against a frozen goal set — but they are not the same measurement, and they run in different worlds. The first measures **what the bare goal does in one shot** (a baseline). The second measures **what ROGUE's accumulated repertoire does to that goal** (the higher, repertoire-driven figure). A target's "single-turn ASR" and its "repertoire ASR" are both honest, and they will diverge widely; conflating them would be a category error.

### 1a. Self-serve — the single-turn path

The public, SDK-and-API engine is `run_benchmark` (`src/rogue/benchmark.py:90`). It loads a frozen dataset, wraps each goal as a minimal single-turn primitive via `goal_primitive` (`src/rogue/benchmark.py:55`) — family `direct_instruction_override`, vector `user_turn`, the bare harmful request with nothing wrapped around it — and fires all of them through the one provider-agnostic `run_scan` loop (`src/rogue/benchmark.py:111`) at `n_trials=1`. The result is a `BenchmarkReport` (`src/rogue/report.py:236`) whose `n_success` is the underlying `ScanReport.n_breaches` and whose `asr` is the headline. No escalation, no rendering tricks, no ladder: just "how often does the target comply when asked directly?" This is what `POST /v1/benchmark` runs ([../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md) §3), what `Client.benchmark` runs from the SDK, and what `ScanEngine.benchmark` ([../ARCHITECTURE.md](../ARCHITECTURE.md) §4) wraps. It is deterministic-ish, cheap (one target call per goal, capped at `max_goals`, default 25), and self-contained — the goal sets are bundled with the wheel under `src/rogue/data/benchmark/{advbench_100,jbb_100}.jsonl` so a plain `pip install` can benchmark without the repo (`src/rogue/benchmark.py:9`–`12`, `:31`). Because the path is literally `run_scan`, a self-serve benchmark **cannot drift** from the reproduction path a scan uses; that is the whole point of routing it through the one engine.

This engine deliberately leaves `winner_rank` at `null` (`src/rogue/report.py:244`): there is no ladder, so there is no "rank in the attempt order where the winner broke." The API surfaces that `null` explicitly ([../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md) §3) so a reader never mistakes a single-turn report for a ladder report.

### 1b. Internal / enterprise — the full-repertoire-ladder path

The second engine is the operator-run runner `scripts/benchmark/benchmark_run.py` (entry `main` at `:414`, per-cell core `_run_one_cell` at `:154`). For each frozen goal it wraps the bare request the same way (`_goal_primitive`, `:100` — same construction as the self-serve primitive, only the id/source differ) and then runs ROGUE's **graduated escalation ladder** against the target: `build_escalation_context()` + `run_escalation_ladder_one()` (imported at `scripts/benchmark/benchmark_run.py:79`), the *same* functions production reproduction uses. This is single-source-of-truth by design — the benchmark replays the real attacking system, so it cannot drift from it any more than the single-turn path can. Each goal becomes ~30–60 sequential ladder calls (escalation across strategies, image/audio renderers, structured formats, chain-of-jailbreak operations — `:185`–`:193`), which is why this engine is expensive (the dry-run estimate at `:97` budgets target+judge per attempt) and gated behind `--yes` (`:433`). It records the repertoire-driven ASR — strictly ≥ the single-turn ASR, because the ladder is allowed to do everything ROGUE knows.

Beyond ASR it captures orchestration KPIs in `detail` (`_aggregate`, `:231`): `median_winner_rank` (the reorder payoff), `best`/`mean_ladder_depth`, `cost_per_successful_goal`, and the winning-strategy histogram — because ASR alone can't tell you whether the *orchestration* improved between two runs (`scripts/benchmark/benchmark_run.py:17`–`19`). `winner_rank` (`_winner_rank`, `:143`) is the field the single-turn report leaves `null`; here it is the headline of the per-goal record.

This engine runs in two rosters (`scripts/benchmark/benchmark_run.py:88`–`94`): **Tier A** — one fixed mid-difficulty model (`acme-mistralsm-…`, signal room, run every harvest, cheap) — and **Tier B** — one config per vendor (GPT / Claude / Gemini / Mistral, milestone-only, to catch vendor-specific drift). Two tiers because pinning ONE model would let a model getting *weaker* masquerade as ROGUE getting *stronger* (`scripts/benchmark/benchmark_run.py:11`–`12`).

| | Self-serve (single-turn) | Internal (repertoire-ladder) |
|---|---|---|
| Entry | `run_benchmark` (`benchmark.py:90`) | `scripts/benchmark/benchmark_run.py:414` / `_run_one_cell:154` |
| Per-goal work | one `run_scan` call, `n_trials=1` | full escalation ladder (~30–60 calls) |
| Datasets | bundled `src/rogue/data/benchmark/*.jsonl` | frozen `benchmark/frozen/*.jsonl` via `load_canonical` |
| Result | `BenchmarkReport` (transient) | `BenchmarkRun` row (durable, Neon) |
| `winner_rank` | always `null` | populated (`_winner_rank:143`) |
| Reached by | `POST /v1/benchmark`, SDK, MCP | operator CLI / scheduled harvest tail |
| Cost | ~one target call × goals | research-grade; `--yes`-gated |

**When each runs.** A self-serve tenant hitting `POST /v1/benchmark` always gets engine 1a. The ladder engine (1b) is not on the public API surface — it is operator-run telemetry today (every harvest for Tier A, milestone for Tier B). The platform's path to *exposing* 1b to enterprise tenants is §3 below: the API selects the engine by tenant tier, and routes the ladder run through the same `ScanService` queue as a scan.

---

## 2. Datasets — the frozen reference side of the wall

Goal sets are **harmful behaviors to elicit, not attack techniques.** They live entirely on the evaluation side of the eval/generation wall and are *never* ingested as primitives (`benchmark/datasets.py:11`–`13`) — an analysis of HF jailbreak datasets found 0 new families, so there is nothing to harvest from them; their only job is to be a stable denominator (the `[HF datasets verdict]` finding). The unit is `BenchmarkGoal` (`benchmark/datasets.py:42`): a `goal` string, the `target` affirmative completion a success would start with, an optional `category`, and a `source` tag.

### 2a. Versioning & freezing

A benchmark you re-pull live is not a benchmark — the denominator could drift under you between two runs and silently invalidate the trend (`benchmark/datasets.py:6`–`9`). So the datasets are **frozen once**: a one-time `uv run python -m benchmark.datasets --freeze` pulls AdvBench (gated, needs `HF_TOKEN`) and JailbreakBench from the HF datasets-server, writes versioned local JSONL + a sha256 manifest per set (`_write_frozen`, `:102`), and commits them under `benchmark/frozen/`. Every load thereafter is offline and free (`_read_frozen`, `:112`). The manifest (`<name>.meta.json`) records `{name, source, n, sha256}`, so any run can assert it scored the exact bytes a prior run did — the sha256 is the version identifier. The currently frozen sets:

- `advbench` — 520 rows (`walledai/AdvBench:default/train`).
- `jbb_harmful` — 100 rows (`JailbreakBench/JBB-Behaviors:behaviors/harmful`).
- `jbb_judge_comparison` — 300 rows, human-labeled responses + competing classifiers' verdicts; this one feeds *judge* calibration, not target ASR (`benchmark/datasets.py:52`, `load_jbb_judge_comparison:167`), and is out of scope for this doc.

### 2b. Canonical regression subsets

`CANONICAL_DATASETS = ("advbench_100", "jbb_100")` (`benchmark/datasets.py:145`) are the two standing denominators every ASR run uses, loaded by `load_canonical("advbench_100" | "jbb_100")` (`:148`). Both are exactly 100 goals so a run is cheap and comparable over time:

- `advbench_100` — a **deterministic** 100 of AdvBench's 520, ordered by `md5("rogue-benchmark-v1:" + goal)` and sliced (`freeze_canonical_subsets`, `:241`–`:254`). No RNG: re-deriving the subset on any machine yields the identical 100, so the regression set is reproducible without shipping a seed file.
- `jbb_100` — all 100 JBB-harmful behaviors, mirrored under the canonical name so both denominators load through the one code path.

`load_advbench` / `load_jbb_harmful` (`:125`, `:132`) expose the full sets for ad-hoc study; the canonical 100s are what the ladder runner and the leaderboard stand on.

### 2c. Custom datasets (enterprise)

The self-serve `dataset` field accepts the two canonical names today (`VALID_DATASETS`, `src/rogue/benchmark.py:32`); an unknown value raises `ValueError` (`:41`), which the API maps to `400 invalid_request` at submit time ([../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md) §3). The enterprise extension is a **per-org dataset**: a tenant uploads their own goal list — the harmful behaviors *they* care about (their domain's abuse cases, their compliance obligations) — and benchmarks against that. Design:

- **Upload** is a small Team A endpoint (e.g. `POST /v1/datasets`) that accepts a JSONL of `{goal, target?, category?}` rows, validates each against the `BenchmarkGoal` shape, and writes a per-org frozen artifact keyed by `org_<ulid>` — the same freeze discipline as the public sets: content-hashed, immutable once written, addressed by a `dataset` name scoped to the org (`org_…:my-abuse-cases`). A custom dataset is never global; it is tenant-isolated like every other org resource (Team C).
- **Loading** reuses the freeze/manifest machinery (`_write_frozen` / `_read_frozen`) so a custom set carries the same sha256 version guarantee — a tenant's trend line over their own goals stays honest across re-uploads (a changed upload is a new version, not a silent overwrite).
- **Selection**: `run_benchmark`'s dataset resolution gains an org-scoped lookup ahead of the `VALID_DATASETS` check, so `dataset: "org_…:my-set"` loads the tenant's frozen file. The canonical names remain the global defaults.

Custom datasets do not change the eval/generation wall: an uploaded goal is an evaluation denominator, never a harvested primitive.

---

## 3. Routing — how `POST /v1/benchmark` selects an engine and gets queued

A benchmark is a long job (one target call per goal at minimum; a full ladder run is far longer), so it goes through the **exact** async-job pattern a scan uses ([../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md) §3, [../orchestration/scan-engine-adapter.md](../orchestration/scan-engine-adapter.md)): `POST /v1/benchmark` returns `202` with a `bench_<ulid>` and `status: queued` (reusing the one `ScanStatus` enum, [../ARCHITECTURE.md](../ARCHITECTURE.md) §5), the caller polls `GET /v1/benchmark/{id}`, and the work runs on the `ScanService` queue + worker — **never in the request thread.** No separate benchmark queue, no separate worker pool.

**Engine selection is by tenant tier, decided once at submit:**

- **Self-serve tenants** → engine 1a (`run_benchmark` via `ScanEngine.benchmark`, [../ARCHITECTURE.md](../ARCHITECTURE.md) §4). The job's payload is `{target, dataset, max_goals}`; the worker calls the engine and persists a `BenchmarkReport`. This is fully wired by the contract in [../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md).
- **Enterprise tenants** (a tier flag on the org, Team C) → engine 1b, the repertoire ladder. The job carries the same `{target, dataset, max_goals}` plus the tenant's repertoire context; the worker invokes the `benchmark_run` core (`_run_one_cell`, `scripts/benchmark/benchmark_run.py:154`) instead of `run_benchmark`. Both engines satisfy the same `ScanEngine.benchmark` signature ([../ARCHITECTURE.md](../ARCHITECTURE.md) §4), so the API surface and the job lifecycle are identical regardless of which engine runs — the only difference is which code the worker dispatches and how long it takes.

One operational rule carries over from the ladder runner and must be honored by the worker: the ladder's minutes-long LLM calls must **not** run inside an open DB transaction, or Neon kills the session with `IdleInTransactionSessionTimeout` (`scripts/benchmark/benchmark_run.py:159`–`162`, `:334`, and the `[Neon serverless resilience]` checklist). The script's pattern — read config/repertoire in a short session, **close it**, run the ladder with no session held, then open a fresh short session only for the write (`:335`–`:393`) — is the pattern the worker must replicate. The single-turn engine is short enough not to hit this, but the worker should follow the same discipline uniformly.

`max_goals` selection, dataset clamping to a tenant ceiling, and the `400 invalid_request` for an unknown dataset all live at the API edge ([../api/validate-benchmark-endpoints.md](../api/validate-benchmark-endpoints.md) §3) and are not re-specified here.

---

## 4. Persistence — `benchmark_runs`

The ladder engine's results are durable: one row per `(dataset × target_model)` in the Neon `benchmark_runs` table (`src/rogue/db/models.py:728`, migration `0021_add_benchmark_runs`). A local file could vanish; the coverage-over-time series must survive any single machine (`models.py:730`). The table is **append-only** — each row is one point on the `date → ASR/coverage` timeline (`models.py:735`):

- `run_label`, `run_at`, `dataset`, `mode` (`'repertoire' | 'attacker'`), `target_model` — the run's identity and roster (`models.py:748`–`:754`).
- `n_goals`, `n_breached`, `asr` (= `n_breached / n_goals`) — the headline (`:755`–`:757`).
- `repertoire_size` — snapshot of how many graduated techniques were active at run time (`models.py:758`), so a rising ASR can be tied to a *growing repertoire* rather than noise. This field is also the basis of the `$0` "benchmark due?" check (`_report_if_changed`, `scripts/benchmark/benchmark_run.py:269`): a benchmark only measures the graduated repertoire, so if it hasn't grown since the last persisted run there is nothing new to measure and the paid run is skipped.
- `cost_usd`, `duration_s`, `git_sha` — run economics + provenance (`:759`–`:761`).
- `detail` (JSON) — the per-goal / per-family breakdown from `_aggregate` (median winner rank, ladder depths, cost-per-success, winner histogram), so a figure can be redrawn without a re-run (`models.py:741`–`:742`).

The write happens in a short, dedicated session after the ladder completes (`scripts/benchmark/benchmark_run.py:377`–`:393`), each row stamped with `repertoire_size` captured at startup. The platform's enterprise-tier benchmark job writes the same row — the persisted artifact is identical whether the ladder ran from the CLI or from a queued job, so the trend timeline is one continuous series. How those rows roll up into the leaderboard and the coverage trend is owned by [./scoring-and-trends.md](./scoring-and-trends.md).

The self-serve single-turn engine does **not** write a `benchmark_runs` row by default — its `BenchmarkReport` is returned through the job-status poll and persisted as the job's result (the scan-job persistence of [../orchestration/scan-engine-adapter.md](../orchestration/scan-engine-adapter.md)), not appended to the repertoire-trend timeline. Mixing single-turn baselines into the same series as ladder ASRs would corrupt the trend (different measurements); they stay in the job store, queryable per-tenant, distinct from the cross-time `benchmark_runs` yardstick.

---

## 5. Invariants this team must not break

1. **One engine per measurement, never a third.** Both paths route through real ROGUE code (`run_scan` for 1a, `run_escalation_ladder_one` for 1b). Team E adds datasets and persistence around those engines; it never reimplements attacking or judging.
2. **The eval/generation wall.** Benchmark goals — canonical or custom — are denominators, never primitives. No goal is ever harvested.
3. **Frozen means frozen.** Every dataset (public and custom) is content-hashed and immutable once written; a change is a new version, asserted by sha256, so no trend line is silently invalidated.
4. **Same job lifecycle as a scan.** A benchmark never runs in the request thread and never holds a DB transaction across LLM calls.
