# Dashboard — Report & Benchmark Views (Team D)

> The two pages a customer actually screenshots: the **scan report** (a completed `ScanReport` rendered as headline KPIs + findings + recommendations + export) and the **benchmark views** (ASR, winner rank, cost-per-success, and a historical trend across runs). This doc specifies the Next.js components, the severity/design-system color language, and every empty/loading/error state. It defines **no new contracts** — `ScanRecord`, `score`, `ScanReport`, `Finding`, and `BenchmarkReport` are owned upstream and used here verbatim. Cross-links: [`./pages-and-routes.md`](./pages-and-routes.md) (route shells, nav, auth gate), [`../reports/report-service.md`](../reports/report-service.md) (the renderer the export buttons hit), [`../reports/executive-and-engineering.md`](../reports/executive-and-engineering.md) (the exec/eng artifact formats), and [`../benchmark/scoring-and-trends.md`](../benchmark/scoring-and-trends.md) (the `score`/ASR/trend math). Status: design spec, not yet built.

## 1. Where these pages sit

The report page lives at `/scans/[scanId]/report` and the benchmark page at `/benchmark` (per [`./pages-and-routes.md`](./pages-and-routes.md), which owns the route tree and the tenant-aware data layer). Both consume already-completed work: the report page renders a single completed scan, the benchmark page renders the history of `BenchmarkRun` rows. Neither page runs a scan, computes a score, or re-derives a finding — that is upstream. Team D's job is purely the presentation layer, reusing the established frontend patterns rather than inventing a second visual language.

The two precedents we build on already ship in `frontend/`. The **breach-matrix heatmap** (`frontend/src/app/matrix/page.tsx:28`, with its client `MatrixHeatmap` and per-cell `CellPrimitiveList` at `frontend/src/components/cell-primitive-list.tsx:12`) is the model for a findings list: worst-first cards, severity-tinted rate, payload/response excerpts, a `CopyButton`. The **threat brief page** (`frontend/src/app/brief/page.tsx:17`) is the model for a long-form report with a download cluster (`BriefDownloads`, `frontend/src/app/brief/page.tsx:53`) and KPI chips (`TierChip`, `frontend/src/app/brief/page.tsx:101`). The report page is, in effect, "the brief page for one scan"; the findings list is "the matrix cell list for one target."

## 2. The data the report page renders

The page renders a completed scan. The fetch is the report route from [`../reports/report-service.md`](../reports/report-service.md) and `api/scans-endpoints.md` §3 — `GET /v1/scans/{scanId}/report?format=json` — which returns the persisted analogue of `ScanReport.to_dict()` (`src/rogue/report.py:130`) **with the platform `score` added**. So the JSON body carries every field the `@dataclass ScanReport` exposes (`src/rogue/report.py:75`): `target`, `n_tests`, `n_breaches`, `breach_rate`, `top_attack`, `cost_usd`, and `findings[]` — plus `score` (the `0–100` headline number, ARCHITECTURE §5, distinct from raw `breach_rate`).

Each entry in `findings[]` is a `Finding` (`src/rogue/report.py:51`): `family`, `technique`, `vector`, `severity`, `title`, `success_rate`, `n_trials`, `n_breach`, and the optional `example_attack` / `example_response`. The page must **not** recompute `breach_rate`, `top_attack`, `success_pct`, or `breached` — those are properties on the dataclass (`src/rogue/report.py:67`, `:86`, `:104`) and arrive pre-derived in the JSON. Two fields the dashboard wants are **not** on the dataclass: per-finding **remediation** text and a report-level **recommendations** panel. Those are render-time concerns owned by `ReportService` (the engineering report already carries remediation — see [`../reports/executive-and-engineering.md`](../reports/executive-and-engineering.md)); the report route's JSON is expected to surface `finding.remediation` and a top-level `recommendations[]` array. If the JSON omits them (older runs), the panels degrade gracefully (§6).

The lighter `ScanRecord` (status row, ARCHITECTURE §5) is what the route shell uses to decide *whether to show the report at all*: only `status == "completed"` has a `report_id` and a non-null `score`. The shell handles `queued`/`running` (hand off to the live-scan UX in [`./pages-and-routes.md`](./pages-and-routes.md)) and `failed`/`canceled` (§6) before this view ever mounts.

## 3. Report page layout

A vertical stack inside the standard page chrome (`max-w-5xl mx-auto px-6 py-10 space-y-8`, `bg-rogue-grid bg-rogue-spotlight` — the exact frame `BriefPage` uses at `frontend/src/app/brief/page.tsx:38`), top to bottom:

**3.1 Header.** A `/scans/<id>` eyebrow in the mono uppercase tracking style (`frontend/src/app/brief/page.tsx:42`), an `<h1>` with the target name (`report.target`), a one-line subtitle (`n_tests` tests · completed `completed_at`), and the **export cluster** on the right (§5). Mirrors the brief header's `flex items-start justify-between` layout.

**3.2 Headline KPIs.** A row of KPI tiles, one component `<KpiTile>` reused across all four, in the same `.kpi` idiom the SDK HTML report already uses (label over a big bold number, `src/rogue/report.py:166`) and the matrix `StatCapsule` (`frontend/src/app/matrix/page.tsx:223`):

- **Score** — `report.score` (`0–100`), the lead tile, tinted by band (§4).
- **Breach rate** — `report.breach_pct` (e.g. `38%`), tinted red when `> 0`, green at `0` (matching `rate_color` at `src/rogue/report.py:161`).
- **Top attack** — `technique_label(report.top_attack)` (`src/rogue/report.py:47`) so the user sees "Crescendo", not `multi_turn_gradient`; em-dash when none breached.
- **Cost** — `report.cost_usd`, formatted by the same `_fmt_usd` rule (`src/rogue/report.py:37`): 2 decimals at/above a cent, 4 below, so a cheap scan never reads as a misleading `$0.00`.

Score is the headline; the other three are the supporting numbers a security engineer reads next, exactly the set `ScanReport.summary()` leads with (`src/rogue/report.py:112`).

**3.3 Top attacks.** A compact worst-first list (3–5 rows) from `report.top_findings(5)` semantics — `family/technique`, severity chip, `success_pct`, a thin inline rate bar. This is the dashboard analogue of the matrix "worst attacker today" callout (`frontend/src/app/matrix/page.tsx:145`): glanceable triage above the full per-finding detail. Each row deep-links to its `<FindingCard>` anchor below.

**3.4 Per-finding detail.** One `<FindingCard>` per breached finding (`report.breached_findings()` order, severity-then-rate, `src/rogue/report.py:96`), styled like `CellCard` (`frontend/src/components/cell-primitive-list.tsx:29`): rank + `vector` + `severity` eyebrow, `title` as `<h3>`, the severity-tinted `success_pct` with `n_breach`/`n_trials`. Below the head, three disclosure blocks:

- **Example attack** — `finding.example_attack` in a mono code block with a `CopyButton` (reuse `frontend/src/components/matrix-drawer.tsx`'s `CopyButton`). Long payloads collapse behind a "show full payload" toggle (the matrix drawer pattern).
- **Example response** — `finding.example_response`, the model's breached output, visually separated (left border, muted) so attack vs. response never blur together.
- **Remediation** — `finding.remediation` rendered with `react-markdown` (the brief already depends on it via `BriefMarkdown`, `frontend/src/components/brief-markdown.tsx`), so the report layer can ship formatted guidance. Hidden when absent.

Non-breached findings are **not** shown by default (the report is about risk, not the full test log); a "show all N tested (incl. defended)" toggle reveals them with a green status mark, mirroring the SDK HTML's 🟢/🔴 column (`src/rogue/report.py:151`).

**3.5 Recommendations panel.** A single card at the foot rendering the report-level `recommendations[]` via `react-markdown` — the "what to do next" summary, distinct from the per-finding remediation. This is the on-page echo of the executive summary in [`../reports/executive-and-engineering.md`](../reports/executive-and-engineering.md); when the JSON has no `recommendations`, the panel falls back to a one-line synthesis ("N high/critical findings — prioritize the top attack") rather than rendering empty.

## 4. Severity & score color language

There is one color vocabulary, defined in `frontend/src/app/globals.css:141` and used everywhere on these pages — no new tokens. `--rogue-green #00ff88` = OK / defended / safe band, `--rogue-orange #ff6b00` = HIGH tier, `--rogue-red #ff003c` = CRITICAL / breached. The brief and matrix already extend this to a four-tier chip palette (`frontend/src/app/brief/page.tsx:110`): red (critical), orange (high), yellow (medium), blue (low). Findings reuse it exactly, keyed off `finding.severity` (`critical | high | medium | low`, the same `_SEVERITY_RANK` ordering as `src/rogue/report.py:34`):

| severity | border / bg / text |
|---|---|
| `critical` | `border-rogue-red/40 bg-rogue-red/10 text-rogue-red` (+ `rogue-card-critical`, `globals.css:352`) |
| `high` | `border-orange-500/40 bg-orange-500/10 text-orange-300` |
| `medium` | `border-yellow-500/40 bg-yellow-500/10 text-yellow-300` |
| `low` | `border-blue-500/40 bg-blue-500/10 text-blue-300` |

Rate values use the matrix's threshold tint (`frontend/src/components/cell-primitive-list.tsx:31`): `≥0.7` red, `≥0.3` orange, else green. The **score tile** bands the `0–100` number the same way — `≥70` red, `≥40` orange, `<40` green — so the headline color and the findings colors tell one consistent story (high score = lots of red findings). The exact band thresholds are the Team-F/Team-E concern; [`../benchmark/scoring-and-trends.md`](../benchmark/scoring-and-trends.md) owns the canonical cut-points and the dashboard imports them rather than hard-coding a second copy.

## 5. Export buttons

The export cluster (a `<ReportExports>` component modeled on `BriefDownloads`, `frontend/src/app/brief/page.tsx:53`) offers **HTML**, **PDF**, and **JSON**. It does **no rendering client-side** — each button is a link/fetch to the report route `GET /v1/scans/{scanId}/report?format={html|pdf|json}` ([`../reports/report-service.md`](../reports/report-service.md), `api/scans-endpoints.md` §3), which delegates to `ReportService.build_html/build_pdf/build_json`. HTML opens the standalone `ScanReport.to_html()` artifact (`src/rogue/report.py:147`) in a new tab; PDF triggers a download (`Content-Disposition: attachment; filename="rogue-scan-<id>.pdf"`); JSON downloads the dict the page itself already fetched. Keeping the artifact source server-side guarantees the on-screen view and the exported file can never disagree — the same single-source discipline the brief enforces by deriving snapshot + markdown from one disk artifact (`frontend/src/app/brief/page.tsx:22`). The exec/eng report variants from [`../reports/executive-and-engineering.md`](../reports/executive-and-engineering.md) attach here as additional formats when that team ships them; the component takes the format list as a prop so adding one is a one-line change.

## 6. Report empty / loading / error states

- **Loading** — the route shell renders a skeleton (the `animate-pulse` block from `frontend/src/components/cell-view.tsx:109`): a header bar, four KPI ghosts, three finding-card ghosts. The page chrome and skeleton render instantly; only the finding cards stream in.
- **Not yet completed** — if a user lands on the report URL while `status` is `queued`/`running`, the shell redirects to the live-scan view ([`./pages-and-routes.md`](./pages-and-routes.md)). The route never renders a half-report; the `report_not_ready` 404 (`api/scans-endpoints.md` §3) is treated as "still polling," not an error.
- **Zero breaches** — a completed scan with `n_breaches == 0` is a *clean* result, not an empty one: KPIs render (score near 0, green), the top-attacks and per-finding sections collapse into a single green "No vulnerabilities reproduced across N tests" card (the positive analogue of the matrix "nothing in red zone," `frontend/src/app/matrix/page.tsx:135`). Export still works.
- **Failed / canceled scan** — no report exists. The shell shows the failure with the scan's `error` (ARCHITECTURE §5) and a "re-run scan" action; it never calls the report route.
- **API cold / transient** — reuse the `CellView` resilience pattern (`frontend/src/components/cell-view.tsx:24`): timeout-capped fetch, patient gateway-blip retry, and a mono "the API is waking up — retry" card with a retry button (`frontend/src/components/cell-view.tsx:127`) rather than a hard error. (Render free-tier cold-boots are a known operational reality, per the deployment notes.)

## 7. Benchmark views

The benchmark page renders research-grade ASR over standard datasets. The single-run shape is `BenchmarkReport` (`src/rogue/report.py:236`): `dataset`, `target`, `n_goals`, `n_success`, `cost_usd`, optional `winner_rank`, with derived `asr` (`src/rogue/report.py:247`) and `cost_per_success` (`src/rogue/report.py:251`). The historical view reads `BenchmarkRun` rows (one per executed benchmark) from the benchmark API in [`../benchmark/scoring-and-trends.md`](../benchmark/scoring-and-trends.md) / `api/validate-benchmark-endpoints.md`. The dashboard does **not** compute ASR or rank — it reads them.

**7.1 Single-run headline.** The same `<KpiTile>` row as the report page, four tiles straight off `BenchmarkReport.summary()` (`src/rogue/report.py:254`):

- **ASR** — `round(asr * 100)%` with `n_success/n_goals` underneath; tinted on the rate scale (§4).
- **Winner rank** — `#{winner_rank}` ("rank vs field"), the competitive headline; em-dash and dimmed when `winner_rank is None`.
- **Cost / success** — `cost_per_success` (4-decimal USD), em-dash when `n_success == 0` (mirrors the summary's `—` guard).
- **Cost** — total `cost_usd` via the `_fmt_usd` rule.

**7.2 Historical-trend chart.** One line (ASR over time) across the tenant's `BenchmarkRun` history for a given `dataset` × `target`, with cost-per-success available as a second toggled series. Keep it light: the brief's `spark` component (`frontend/src/components/spark.tsx`) and the matrix's CSS rate bars are the precedent — no heavy charting library. A small inline SVG sparkline/area chart (one polyline + axis labels + hover dots) is enough for the run counts a single tenant produces and adds zero bundle weight. We only justify pulling in a dependency (e.g. a lightweight chart lib) if the page later needs multi-series overlays or zoomable axes; the v1 spec is hand-rolled SVG. Points carry the run date and value on hover; the trend tints the most-recent delta (improved = green, regressed = red) so "are we getting safer over time" reads at a glance.

**7.3 Run table.** Below the chart, a worst-first / newest-first table of `BenchmarkRun` rows — date, dataset, target, ASR, rank, cost/success — each row linking to that run's detail (the same disclosure idiom as the findings list). This is the audit trail behind the trend line.

**7.4 Benchmark empty / loading.** Loading reuses the §6 skeleton. **No runs yet** for the tenant → a single "Run your first benchmark" card pointing at the benchmark API, not an empty chart. **One run** → render the headline tiles and the run table but suppress the trend chart (a one-point line is noise) with a "trend appears after your second run" note. Cold-API behavior is the §6 retry card.

## 8. Component inventory

New components Team D owns (all client components live under `frontend/src/components/`, route shells under `frontend/src/app/`):

- `app/scans/[scanId]/report/page.tsx` — report route shell (server: fetch JSON + gate on status), `loading.tsx` skeleton.
- `components/report/kpi-tile.tsx` — the shared headline tile (report §3.2 **and** benchmark §7.1).
- `components/report/top-attacks.tsx` — the worst-first triage list (§3.3).
- `components/report/finding-card.tsx` — per-finding detail with attack/response/remediation disclosures (§3.4); reuses `CopyButton`/`PayloadImage` from `matrix-drawer.tsx`.
- `components/report/recommendations.tsx` — markdown panel (§3.5), wraps `BriefMarkdown`.
- `components/report/report-exports.tsx` — the HTML/PDF/JSON cluster (§5), modeled on `BriefDownloads`.
- `app/benchmark/page.tsx` + `components/benchmark/{headline,trend-chart,run-table}.tsx` — benchmark views (§7); `trend-chart` is hand-rolled SVG.

Everything keys off the shapes in `src/rogue/report.py` and the `score`/trend math owned by Teams F and E — this layer adds presentation, never a second source of truth for any number.
