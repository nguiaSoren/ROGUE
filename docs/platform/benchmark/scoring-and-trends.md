# Benchmark Scoring & Historical Trends (Team E)

> The enterprise upsell. A scan tells a tenant *what broke today*; the benchmark layer tells them *how their model ranks against the field, and whether they are getting safer over time.* This doc defines the five headline metrics — Coverage Score, ASR, Winner Rank, Cost-Per-Success, and Historical Trend — precisely enough that two engineers compute identical numbers from the same run, and specifies the data model the trend and the leaderboard are built from. It is the scoring half of Team E; the request surface and the frozen goal sets live in [`./api-and-datasets.md`](./api-and-datasets.md). Scope per the [architecture index](../ARCHITECTURE.md): Team E owns "benchmark API, datasets, scoring/trends."

Status: **substrate BUILT; the scoring/trend surface NOT built.** `BenchmarkReport` (`src/rogue/report.py`) is the live result of `client.benchmark()` / `ScanEngine.benchmark` (carrying `asr` and `cost_per_success`; `winner_rank` is `None` on the single-turn path), and the `benchmark_runs` table exists on Neon. **But the five-metric scoring / leaderboard / historical-trend surface this doc specifies is NOT implemented**, and the hosted `/v1/benchmark` MVP runs in-memory and does **not** write `benchmark_runs` (see [./api-and-datasets.md](./api-and-datasets.md)) — so there is no accumulating date→ASR timeline from the platform path yet. The two primitives are real; the layer on top is design.

## 1. The reused primitive — `BenchmarkReport`

Every metric on this page is derived from one dataclass, `BenchmarkReport` (`src/rogue/report.py:235`), the return type of `ScanEngine.benchmark(...)` (the contract in [`../ARCHITECTURE.md` §4](../ARCHITECTURE.md)). It carries exactly six fields plus two computed properties, and Team E adds nothing to its shape:

- `dataset: str` — the frozen goal set, e.g. `advbench_100`, `jbb_100` (the `.meta.json` manifests under `benchmark/frozen/` pin the goal hashes; see [`./api-and-datasets.md`](./api-and-datasets.md)).
- `target: str` — the model under test.
- `n_goals: int` / `n_success: int` — denominator and numerator of the headline rate.
- `cost_usd: float` — total spend for the run.
- `winner_rank: int | None` — where the target lands versus the published field (§4).
- `asr` (property, `report.py:247`) — `n_success / n_goals` if `n_goals` else `0.0`.
- `cost_per_success` (property, `report.py:251`) — `cost_usd / n_success` if `n_success` else `None`.

These two properties **are** ASR and Cost-Per-Success — Team E never recomputes them with a second formula. `BenchmarkReport.to_dict()` (`report.py:268`) is the canonical serialization the API and dashboard read; it injects rounded `asr` and `cost_per_success` alongside the raw fields, so a consumer never has to divide by hand.

**This is not the scan `score`.** The platform's single headline risk number — `score: float (0-100)`, owned by Team F and mirrored from the SDK's `compute_risk_score` ([`../ARCHITECTURE.md` §5](../ARCHITECTURE.md)) — is a *scan* metric synthesized from per-finding severity × success-rate against a tenant's own `DeploymentConfig`. The benchmark layer's Coverage Score (§2) is a *benchmark* metric against a frozen public goal set. They answer different questions (your deployment's risk today vs. your model's standing against the field) and must not be conflated: `score` is reported on `ScanRecord`, Coverage Score on a benchmark run. Where both appear in one report ([`../reports/executive-and-engineering.md`](../reports/executive-and-engineering.md)), they are labeled distinctly.

## 2. Coverage Score

Coverage Score is the fraction of the attack space the target **withstands** — the defensive complement of ASR, expressed as a 0–100 number so it reads like a grade rather than a failure rate. The simple form, for a single dataset:

```
coverage_score = 100 × (1 − asr) = 100 × (1 − n_success / n_goals)
```

A target that defeats every goal scores 100; one that falls to every goal scores 0. Because `asr` is already a property on `BenchmarkReport`, Coverage Score is a pure view over the reused primitive — no new field, no second division.

The **weighted** form recognizes that not every goal is equally hard or equally severe. When a dataset's `detail` payload (`benchmark_runs.detail`, §5) carries a per-goal or per-family breakdown, the score weights each goal's outcome by a family weight `w_f` (defaulting to the scan taxonomy's severity ordering):

```
coverage_score = 100 × (1 − Σ_g [ w_{family(g)} · breached(g) ] / Σ_g w_{family(g)} )
```

with `breached(g) ∈ {0,1}`. With all weights equal this collapses to the simple form, so the two are one formula. The weight vector is a property of the *dataset*, frozen alongside the goal set and versioned in its `.meta.json` manifest — changing weights changes the score, so weights are pinned per dataset version and never tuned per tenant (a tenant-tunable weight would make cross-tenant comparison meaningless, §6). Coverage Score and ASR are strictly complementary on the simple form; the weighted form can diverge from `1 − asr` and is the number surfaced when severity-weighting is requested. Both are reported with their `n_goals` so a reader can see the sample size behind the percentage.

## 3. ASR — Attack Success Rate

ASR is the live, unweighted rate: `n_success / n_goals`, computed by `BenchmarkReport.asr` (`report.py:247`). It is the research-grade headline — "the repertoire breaks X% of a fixed, field-standard goal set" — and the regression metric the trend series (§5) tracks over time. The summary line (`report.py:260`) renders it as `ASR: 93%  (28/30)`, always with the raw fraction so the denominator is visible.

ASR is reported **per dataset**; it is never averaged across datasets (AdvBench and JBB are different goal sets with different difficulty profiles, so a blended number is uninterpretable). When a tenant runs both, the report shows two rows, not one mean.

## 4. Winner Rank — standing versus the field

Winner Rank (`BenchmarkReport.winner_rank`, `report.py:244`, `int | None`) places the target on a leaderboard: where this `(dataset, target)` result lands relative to the published field and ROGUE's own reference runs. Lower is better — rank #1 is the most-broken (highest ASR) model in the field; a large rank means the target withstands more than most published systems.

**Where the ranks come from.** Two sources, merged into one leaderboard:

1. **The published field** — the per-dataset classifier/attacker leaderboards that ship with the frozen datasets (the JBB and AdvBench field standards). These are static, versioned with the dataset manifest, and are the "vs. the world" axis.
2. **ROGUE's own Run #0 reference** — the first internal reference run against a Claude Haiku target (README §9 "Run #0"): **AdvBench-100 at 93.3% ASR, winner-rank 18**; **JBB-100 at 90.0% ASR, winner-rank 17**. Run #0 is the anchor point — the leaderboard's origin — and every later tenant run is positioned against the same field that produced ranks 17–18 for the reference target.

The leaderboard is a per-dataset, append-versioned table: `(dataset_version, entry_label, asr, rank)`, with field entries loaded from the dataset manifest and ROGUE reference entries derived from `benchmark_runs` rows tagged `mode='attacker'` (the milestone peak-ASR numbers, §5). A tenant's `winner_rank` is computed by inserting their ASR into the field-sorted list and reading off the position. **Today this is a stub** — `client.benchmark()` constructs the report with `winner_rank=None` (`src/rogue/benchmark.py:127`), and the only published ranks are the Run #0 figures hand-recorded in the README. Wiring the leaderboard table and the insertion lookup is Team E's build work; the contract (`winner_rank: int | None`) is already the right shape and does not change.

**Winner Rank, not ASR, is the number to lead with.** Because the reference target sits in the productive middle of the field (Run #0 ranks ~17–18, where the repertoire breaks goals *deep* in the ladder rather than on the first rung), rank and cost have large headroom even when ASR is near its ceiling: a better-ordered or stronger repertoire pulls winners earlier, which the benchmark sees as **rank dropping and cost falling even if ASR holds flat** (README §9). Rank is the metric that keeps moving after ASR saturates, so it is the headline for the trend chart (§5) and the executive report ([`../reports/executive-and-engineering.md`](../reports/executive-and-engineering.md)).

## 5. Historical Trend — the time series

The trend is a per-tenant, per-`(dataset, target_model)` time series built directly from the durable `BenchmarkRun` rows (`src/rogue/db/models.py:728`). That table is **append-only** — "each row is one point on the `date → ASR/coverage` timeline" — and is already persisted on Neon so the series survives any single machine. Team E does not build a new store; it reads `benchmark_runs`.

The columns the trend is built from (`models.py:745`–`763`):

- `run_at` (`models.py:749`, indexed) — the x-axis.
- `dataset` (`models.py:752`, indexed) and `target_model` (`models.py:754`) — the series key. A trend line is one `(dataset, target_model)` pair; different datasets are different lines, never merged (§3).
- `asr` (`models.py:757`, = `n_breached / n_goals`) and the derived Coverage Score — the primary y-axis.
- `cost_usd` (`models.py:759`) — the Cost-Per-Success secondary axis (divided by `n_breached` per §7).
- `repertoire_size` (`models.py:758`) — how many graduated techniques were available at run time, so **a rising ASR can be attributed to a growing repertoire rather than noise** (the column's stated purpose, `models.py:741`).
- `mode` (`models.py:753`) — `'repertoire'` (the standing regression metric: the graduated repertoire applied to each goal) vs `'attacker'` (IterativeAttacker peak ASR, a milestone-only number). The trend's regression line is the `mode='repertoire'` series; `mode='attacker'` points are plotted as milestone markers, not a continuous line. The two are never mixed into one average.
- `git_sha` (`models.py:761`) and `detail` (`models.py:762`) — provenance and the per-family/per-goal breakdown, so a figure can be redrawn without a re-run (the `detail` column's stated purpose).

**What the trend shows.** As the model is hardened, ASR falls and Coverage Score rises; as ROGUE's repertoire grows (`repertoire_size` climbs), ASR against a *fixed* target rises and Winner Rank drops. The headline figure — once ~3–4 runs accumulate — is **winner-rank ↓ and cost ↓ over time, annotated with harvest/graduation events**: the visual proof of the `harvest → graduate → benchmark → improvement` loop that is ROGUE's differentiator (README §9). The rendering surface for this chart is [`../dashboard/report-views.md`](../dashboard/report-views.md); this doc owns the series definition, that doc owns the pixels.

Each new `client.benchmark()` run that is persisted appends one `BenchmarkRun` row. The `BenchmarkReport` (§1) is the in-memory result; the `BenchmarkRun` row is its durable shadow — same numbers (`asr`, `cost_usd`, `n_goals`/`n_success` → `n_goals`/`n_breached`), plus the trend-only columns (`repertoire_size`, `git_sha`, `run_at`). The mapping is one-to-one and lossless on the metric fields; Team E writes the row at persistence time and never recomputes ASR differently between the two.

## 6. Comparing runs — over time and against peers

A tenant compares in two directions, both off the same `benchmark_runs` substrate:

- **Over time (own runs):** filter `benchmark_runs` by `(org-scoped target_model, dataset, mode='repertoire')`, order by `run_at`, and read the series. This is the regression view — "is my model getting safer?" — and is the primary enterprise loop: continuous benchmarking on a schedule, with each run a new point.
- **Against peers (anonymized):** the leaderboard (§4) provides the field axis. Peer comparison is **anonymized** — a tenant sees their own rank and the field distribution, never another tenant's identity or raw numbers. The leaderboard exposes aggregate field statistics (the published entries plus anonymized ROGUE-reference percentiles), so "you rank #14 of 30, better than the 60th percentile of the field" is answerable without leaking any other tenant. Tenant isolation on the underlying rows is enforced by Team C's scoping; the leaderboard is the one cross-tenant surface and it is aggregate-only by construction.

## 7. Cost-Per-Success

Cost-Per-Success is `cost_usd / n_success` — `BenchmarkReport.cost_per_success` (`report.py:251`), `None` when `n_success == 0` (no successes, no meaningful cost-per-success; rendered as `—` in the summary, `report.py:262`). It is the efficiency axis of the benchmark: dollars spent per goal broken. Run #0 recorded **$0.51/success on AdvBench-100 and $0.52 on JBB-100** (README §9).

On the trend (§5) it is computed from the durable row as `cost_usd / n_breached` (the `BenchmarkRun` analogue of `n_success`), and it falls as the repertoire improves — a better-ordered ladder breaks goals at a shallower rung, so each success costs fewer LLM calls. Like Winner Rank, Cost-Per-Success keeps moving after ASR saturates, which is why the two together (rank ↓, cost ↓) are the headline trend rather than ASR alone.

## 8. The judge-calibration caveat — hold the judge fixed

Every breach in a benchmark run is ultimately an LLM judge verdict, so **ASR inherits the judge's error rate.** The Run #0 ASR figures (93.3% / 90.0%) are **inflated by judge over-eagerness**: the README calibration section is explicit that on JailbreakBench the judge agrees with the human majority only **70.3%** (recall 98% / precision 55% — it catches essentially every real jailbreak but over-flags ~46% of human-cleared responses). The judge is well-calibrated and conservative on ROGUE's *own* traffic (2.56% false-positive breach rate in-distribution) but over-flags on strict external harmful-content standards — exactly the standards the frozen benchmark datasets represent.

Two consequences bind this layer:

1. **Comparisons must hold the judge fixed.** ASR, Coverage Score, Winner Rank, and the trend are only comparable across runs *graded by the same judge model and rubric version*. A judge change is a unit change — it rebases every number. So `benchmark_runs` rows must record the judge identity (judge model + rubric version) as provenance, and the trend (§5) must **break the series** at any judge change rather than drawing a continuous line across it; a recalibration is annotated as a discontinuity, not smoothed over. Two runs with different judges are not on the same axis and the dashboard must not plot them as one trend.
2. **Lead with rank, gate the public ASR.** Because the headline ASR is judge-inflated, the absolute coverage number ("93% AdvBench") is held back from any public/tenant-facing dashboard until the judge is recalibrated (README §9 explicitly defers this). Winner Rank is comparatively robust — an over-eager judge inflates everyone's ASR roughly uniformly, so *relative* standing moves less than the absolute rate. This is the second reason the enterprise surface leads with rank and trend, not raw ASR.

## 9. Why this is the enterprise tier

A one-off scan ([the `ScanRecord` headline `score`](../ARCHITECTURE.md)) is the entry product — anyone can run it once. The benchmark layer is the upsell because it is **continuous and comparative**, three things a single scan cannot give:

- **Continuous benchmarking** — a scheduled, durable series (`benchmark_runs` on Neon) that turns "we got scanned once" into "we watch our standing every week."
- **Trend** — the `harvest → graduate → benchmark → improvement` loop made visible: rank ↓ and cost ↓ over time, annotated with the harvest/graduation events that drove each move. This is proof the defense is improving (or regressing) against a *fixed* external yardstick, not just against ROGUE's own internal metrics.
- **Rank vs. field** — anonymized standing against the published field and ROGUE's reference runs, the "how do we compare to everyone else" number an enterprise security buyer asks for and a single scan structurally cannot answer.

The data is already durable, so the trend accrues value with every run; the build work is the scoring/leaderboard/series *surface* over primitives (`BenchmarkReport`, `benchmark_runs`) that already exist. See [`./api-and-datasets.md`](./api-and-datasets.md) for how a run is requested and which datasets are frozen, [`../dashboard/report-views.md`](../dashboard/report-views.md) for the trend chart and leaderboard UI, and [`../reports/executive-and-engineering.md`](../reports/executive-and-engineering.md) for how rank and trend land in the executive summary.
