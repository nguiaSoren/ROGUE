# ReportService — rendering a persisted scan into customer artifacts

> Team F owns the box at the bottom-right of the [spine diagram](../../ARCHITECTURE.md). `ScanService`/`ScanEngine` run the scan and persist its result; **`ReportService` turns that persisted result into the four things a customer consumes** — a JSON dict, a standalone HTML page, a PDF, and an executive-summary document. It runs *no* scanning logic and re-reads only persisted rows. This doc specifies the class, the headline `score` formula (which the spine explicitly delegates here), storage/caching, idempotency, and secret redaction. The exec-vs-engineering *content* split lives in [`./executive-and-engineering.md`](./executive-and-engineering.md); the route that calls this service is in [`../api/scans-endpoints.md`](../api/scans-endpoints.md); the dashboard surfaces these artifacts in [`../dashboard/report-views.md`](../dashboard/report-views.md); secret handles and redaction policy come from [`../tenancy/secrets.md`](../tenancy/secrets.md).

Status: **design spec, not yet built.** The renderers it reuses ship today (`src/rogue/report.py`, `src/rogue/diff/threat_brief.py`); the PDF path and the service wrapper are new. Lives at `src/rogue/platform/report_service.py`.

## 1. Contract (verbatim from the spine — do not redefine)

`ReportService` implements exactly the four coroutines from [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) §4:

```python
class ReportService:
    async def build_json(self, scan_id: str) -> dict: ...
    async def build_html(self, scan_id: str) -> str: ...
    async def build_pdf(self, scan_id: str) -> bytes: ...
    async def build_executive_summary(self, scan_id: str) -> bytes: ...
```

Each takes a `scan_id` (`scan_<ulid>`, ARCHITECTURE §5) and nothing else — no `ScanReport` is passed in. The service is responsible for *loading* the persisted scan result by id and *rendering* it; it never re-runs the scan and never reaches into `ScanEngine`. The report route (`GET /v1/scans/{id}/report?format=…`, [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §3) is a thin caller: it resolves the scan for tenancy + readiness via `scan_service.get_scan(...)`, returns `report_not_ready` if `status != "completed"` **without** touching this service, and only then delegates by format to `build_json` / `build_html` / `build_pdf`. `build_executive_summary` returns `bytes` because its default serialization is PDF (the CISO hands a PDF up the chain); see §6 and [`./executive-and-engineering.md`](./executive-and-engineering.md) for the format negotiation.

## 2. What it reuses — the renderers already exist

The single most important design constraint: ROGUE already has two battle-tested renderers, and `ReportService` is a **wrapper + generalization of them**, not a third renderer. If the service ever diverges from `ScanReport.to_html()` for the same data, the demo and the hosted product disagree — the same failure mode §2 of the architecture warns about for the scan engine.

- **`ScanReport.to_dict()` / `to_json()`** (`src/rogue/report.py:130` / `:141`) — the canonical engineering JSON: `target`, `n_tests`, `n_breaches`, `breach_rate`, `top_attack`, `cost_usd`, and `findings[]` (each `Finding` from `src/rogue/report.py:54`: `family`, `technique`, `vector`, `severity`, `success_rate`, `n_trials`, `n_breach`, `example_attack`, `example_response`). `build_json` produces **this dict plus the platform `score`/`risk_level`** (§3); the scans-endpoints worked example (`../api/scans-endpoints.md` §3) shows exactly that body.
- **`ScanReport.to_html()`** (`src/rogue/report.py:147`) — a standalone, inline-CSS HTML page (no external assets, safe as an email attachment): KPI strip + a severity-sorted findings table, every cell `html.escape`d. `build_html` reuses this verbatim for the engineering report and is the source of the `format=html` response.
- **`ThreatBriefBuilder`** (`src/rogue/diff/threat_brief.py`) — the existing CISO-grade narrative renderer. `render_markdown` (`:213`), `render_json` (`:364`), and `write_outputs` (`:429`) already produce a tiered, prose threat brief (Summary → CRITICAL → HIGH → MEDIUM → LOW → Newly defended). **This is the precedent `build_executive_summary` generalizes.** Today it is hard-wired to a single customer — `build_diff(customer_id, target_date)` is called with the literal `acme` and reads the `breach_matrix` view across *all* of that customer's configs over a *day*. The executive summary for a hosted scan is the same shape scoped to *one scan* instead of one customer-day; §6 and [`./executive-and-engineering.md`](./executive-and-engineering.md) cover lifting the `acme`/day assumption.

The reuse rule, stated once: **`build_json` = `to_dict()` + `score`; `build_html` = `to_html()`; `build_executive_summary` = the threat-brief renderer generalized off `acme`; `build_pdf` = the one genuinely new renderer.** Nothing here re-derives breach rates, re-sorts findings differently, or re-labels techniques — `technique_label` (`src/rogue/report.py:47`) stays the single display map.

## 3. The `score` formula (owned here — the spine delegates it)

ARCHITECTURE §5 defines `score` as "the platform's single headline risk number, `0–100`, synthesized from findings (severity × success-rate, saturating)" and states the formula is **owned by Team F** and **mirrors the SDK's `compute_risk_score`**. This section is that definition; everywhere else (`ScanRecord.score`, the dashboard risk badge, the report header) reads it from here.

**Definition.** For a scan's findings, with per-finding success rate `sᵢ` (the `Finding.success_rate` already on the dataclass) and severity weight `wᵢ`:

```
score = 100 · (1 − Πᵢ (1 − wᵢ · sᵢ))
```

clamping each `wᵢ · sᵢ` to `≤ 1.0` before the product, rounding the result to one decimal. **Severity weights:** `critical 1.0`, `high 0.7`, `medium 0.4`, `low 0.15`. No findings → `0.0`. This is byte-for-byte the SDK's `compute_risk_score` (`sdk/src/rogue/models/report.py:20`, with weights from `Severity.weight`, `sdk/src/rogue/models/common.py:29` — identical values) — the platform deliberately does **not** invent a second formula, so an SDK user and a hosted-API user see the same number for the same findings.

The score is **monotonic** (adding a finding never lowers it), **saturating** (it asymptotes to 100 rather than summing past it, so ten weak findings can't outscore one critical breach), and **dominated by the worst findings** (a single `critical × 100%` finding alone yields `100·(1−(1−1.0)) = 100`). It is intentionally *not* `breach_rate`: `breach_rate = n_breaches / n_tests` (`src/rogue/report.py:86`) is the raw fraction; `score` is the risk-weighted exposure. ARCHITECTURE §5 keeps them distinct on `ScanRecord` for exactly this reason.

**Banding into a risk level** (mirrors `risk_level_for`, `sdk/src/rogue/models/report.py:32`): `score ≥ 75 → CRITICAL`, `≥ 50 → HIGH`, `≥ 25 → MEDIUM`, else `LOW`. `build_json` emits both `score` (float) and `risk_level` (the band) so the dashboard badge ([`../dashboard/report-views.md`](../dashboard/report-views.md)) and the PDF header don't each re-band. The same band is what `ScanService` writes onto `ScanRecord.score` when it finalizes a run, so the value the API returns in the status row and the value the report header prints are computed by one function in one place — `report_service.compute_score(findings)`, which the service exposes as a module-level helper for the worker to call at finalize time. (The worker, not the report route, populates `ScanRecord.score`; the report route only renders.)

## 4. Where the data comes from — load, don't recompute

`ReportService` reads the **persisted scan result**, not live engine output. Per the roadmap (ARCHITECTURE §7, Week 1) the worker writes `scan_jobs` / `scan_runs` rows; the report route's contract (`../api/scans-endpoints.md` §3) states plainly that "`ReportService` reads the persisted `scan_runs` rows by `scan_id`; it does not re-run the scan." The data model — the `scan_runs` columns, the `reports` table, and blob references — is owned by [`../tenancy/data-model.md`](../tenancy/data-model.md); this service depends on that schema but does not define it.

The load step reconstructs an in-memory `ScanReport` (`src/rogue/report.py:75`) from the persisted rows: `target`, `n_tests`, `n_breaches`, `cost_usd`, and the list of `Finding`s. Reconstructing the *object* rather than rendering straight from SQL is deliberate — it means `build_html` can call the existing `ScanReport.to_html()` unchanged, and `build_json` can call `to_dict()` unchanged, so the reuse rule in §2 holds with zero divergence risk. Every render method therefore shares one private `await self._load_report(scan_id) -> ScanReport` step, then diverges only in serialization. Tenancy scoping (the `org_id` filter) is applied by `ScanService.get_scan` before the route ever calls this service, so `_load_report` trusts that the `scan_id` it was handed is already authorized; it does not re-implement the RBAC check ([`../tenancy/secrets.md`](../tenancy/secrets.md) and the isolation doc own that boundary).

## 5. Storage, caching, and idempotency

**Idempotent by construction.** A completed scan's `scan_runs` rows are immutable — the scan ran once, the findings are fixed. Therefore `build_json(scan_id)` called twice returns byte-identical dicts, and `build_html` / `build_pdf` likewise. The renderers must be **deterministic**: findings are sorted by the existing total order (`top_findings`, `src/rogue/report.py:96` — severity rank then success rate), so two renders never shuffle rows; the PDF builder must avoid embedding a wall-clock timestamp or a random doc-id in the body (or pin them from the scan's `completed_at`), or the bytes drift and caching breaks.

**Cache the artifact, keyed by `(scan_id, format)`.** The first successful render of a format persists a `reports` row (`rep_<ulid>`, ARCHITECTURE §5) with the rendered bytes/blob reference; subsequent fetches return the stored artifact instead of re-rendering. JSON and HTML are small enough to store inline in the `reports` table; the **PDF is a blob** — stored by reference (object-store key / blob handle) in the `reports` row, not inline — per the data-model doc ([`../tenancy/data-model.md`](../tenancy/data-model.md)). The `report_id` that `ScanService` stamps onto `ScanRecord.report_id` when a scan completes (`../api/scans-endpoints.md` §1, §2) names this row. Because the inputs are immutable, the cache **never needs invalidation** — there is no "stale report" state; a `reports` row, once written, is the permanent answer for that `(scan_id, format)`. This makes `build_*` effectively memoized: render-on-first-request, serve-from-store thereafter, which keeps the report route's p99 off the reportlab path for any artifact a customer fetches twice.

## 6. The PDF and executive-summary paths (new)

**`build_pdf` is the one new renderer.** The SDK already prototyped the exact shape to follow: `Report.export_pdf` (`sdk/src/rogue/models/report.py:190`) imports `reportlab` lazily and, **if it's missing, raises a clear actionable error** — `"PDF export requires the optional dependency. Install with: pip install 'rogue[pdf]'"` (`:204`) — rather than failing at import time. `build_pdf` reuses that reportlab-or-clear-error pattern: lazy `from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer` inside the method, the same Title → risk-score Heading2 → summary BodyText → per-finding `[SEVERITY] title` + `technique · vector · success_pct over n_trials` story the SDK builds (`:208`–`:230`), rendered into an in-memory buffer and returned as `bytes`. On the server, reportlab is a *hard* dependency of the platform (it's installed), so the clear-error branch is the defensive fallback, not the expected path — but it stays so a misconfigured deploy yields a `500` with a legible message instead of an `ImportError` traceback. The report route serves those bytes exactly like the existing binary-response pattern at `src/rogue/api/main.py:476` (`Response(content=…, media_type="application/pdf")`) with the `Content-Disposition: attachment; filename="rogue-scan-<id>.pdf"` header the endpoint doc specifies.

**`build_executive_summary` generalizes the threat brief.** It produces the CISO-facing narrative — risk score + level, the headline "what's exposed and how bad," tiered findings in prose — by reusing `ThreatBriefBuilder`'s renderers (`render_markdown` `:213` / `render_json` `:364`) rather than writing new prose templates. The generalization is lifting the two hard-coded assumptions: (1) the builder's `build_diff(customer_id, …)` is scoped to a customer-day reading the `breach_matrix` view; the executive summary is scoped to **one scan's findings**, so the diff/matrix query is replaced by the persisted `scan_runs` findings for `scan_id` — the same `BreachedPrimitive`/tier-grouping rendering, fed from the scan instead of the day's matrix. (2) The literal `acme` customer goes away: the scan already carries its `org_id`/`project_id`, so the summary names the actual tenant. The default serialization is PDF (hence the `bytes` return), built through the same reportlab path as `build_pdf` but with the threat-brief layout; whether a Markdown variant is also offered, and the precise exec-vs-engineering content boundary, is specified in [`./executive-and-engineering.md`](./executive-and-engineering.md) — this doc owns the *mechanism*, that doc owns the *content*.

## 7. Secret redaction in rendered payloads

Reports are **the** egress point where raw model interactions leave ROGUE for a customer's inbox/Slack/Jira, so redaction is a first-class concern, not a finishing touch. The policy is owned by [`../tenancy/secrets.md`](../tenancy/secrets.md); `ReportService` is one of its enforcement points. Two specific surfaces matter:

- **`api_key_ref`, never the secret.** `TargetSpec.api_key_ref` (ARCHITECTURE §5) is a Vault/KMS *handle*, and the resolved key never enters a `scan_runs` row, so it cannot leak through the loader. The service asserts this rather than assuming it: a rendered report references the target by `endpoint`/`provider`/`model`, never by a credential, and `build_json` must not echo any `api_key_ref` resolution.
- **Finding excerpts.** `Finding.example_attack` / `example_response` (`src/rogue/report.py:63`–`64`) are verbatim slices of the attack prompt and the model's reply — exactly where a customer's own system-prompt text, internal URLs, or PII embedded in a response could surface. Before these strings reach any renderer, `_load_report` passes them through the redaction filter defined in [`../tenancy/secrets.md`](../tenancy/secrets.md) (e.g. scrubbing the customer's configured system-prompt fragments and known secret patterns). Because the existing `to_html()` already `html.escape`s every cell (`src/rogue/report.py:155`–`158`), redaction is about *content* (removing secrets), escaping is about *safety* (no HTML injection) — both apply, in that order, and the cached `reports` artifact stores the **already-redacted** bytes so a stored report can never be a redaction bypass.

Redaction happens once, at load, upstream of all four `build_*` methods — never per-format — so the JSON, HTML, PDF, and executive forms are guaranteed to carry the same redacted text.

## 8. Boundaries — what this service does NOT do

- It does **not** run, re-run, or partially re-execute a scan (that's `ScanEngine`, ARCHITECTURE §3–§4). It reads persisted rows only.
- It does **not** compute or write `ScanRecord.score` onto the status row — the worker does that at finalize time using the §3 helper; this service only *renders* the score it reads.
- It does **not** own the `reports` / `scan_runs` schema, tenancy filtering, or the redaction *policy* — those are [`../tenancy/data-model.md`](../tenancy/data-model.md) and [`../tenancy/secrets.md`](../tenancy/secrets.md). It is a *consumer* of all three.
- It does **not** define the exec-vs-engineering content split, nor the HTTP route, nor the dashboard rendering — those are [`./executive-and-engineering.md`](./executive-and-engineering.md), [`../api/scans-endpoints.md`](../api/scans-endpoints.md), and [`../dashboard/report-views.md`](../dashboard/report-views.md) respectively.
- It does **not** introduce a second risk number, a second technique-label map, or a second findings sort order — `score` (§3), `technique_label`, and `top_findings` are each defined once and reused.

## 9. File layout

| Path | Role |
|---|---|
| `src/rogue/platform/report_service.py` | **New.** The `ReportService` class + module-level `compute_score(findings)` / `risk_level_for(score)` helpers (§3). Wraps the existing renderers; the only new renderer is `build_pdf`'s reportlab story. |
| `src/rogue/report.py` | **Reused, unchanged.** `ScanReport.to_dict`/`to_json`/`to_html`, `Finding`, `technique_label`. |
| `src/rogue/diff/threat_brief.py` | **Reused, generalized in-place off `acme`** for `build_executive_summary` (§6). |
| `sdk/src/rogue/models/report.py` | **Reference, not imported.** Source of the `score` formula (`compute_risk_score`, `risk_level_for`) and the reportlab-or-clear-error PDF pattern the server mirrors. |

The service is small by design: a loader, a redaction hook, a score helper, and four thin serialization methods over renderers that already exist. The whole value of Team F is that the hosted product's reports are *the same reports* the SDK and the demo already produce — plus a PDF and a generalized executive summary — never a parallel re-implementation.
