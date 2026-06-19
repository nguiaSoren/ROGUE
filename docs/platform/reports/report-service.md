# ReportService — rendering a persisted scan into customer artifacts

> Team F owns the box at the bottom-right of the [spine diagram](../../ARCHITECTURE.md). `ScanService`/`ScanEngine` run the scan and persist its result; **`ReportService` turns that persisted result into the four things a customer consumes** — a JSON dict, a standalone HTML page, a PDF, and an executive-summary document. It runs *no* scanning logic and re-reads only persisted rows. This doc specifies the class, the headline `score` formula (which the spine explicitly delegates here), storage/caching, idempotency, and secret redaction. The exec-vs-engineering *content* split lives in [`./executive-and-engineering.md`](./executive-and-engineering.md); the route that calls this service is in [`../api/scans-endpoints.md`](../api/scans-endpoints.md); the dashboard surfaces these artifacts in [`../dashboard/report-views.md`](../dashboard/report-views.md); secret handles and redaction policy come from [`../tenancy/secrets.md`](../tenancy/secrets.md).

Status: **BUILT (local).** Shipped as `DefaultReportService` (`src/rogue/platform/report_service.py`) against the `ReportService` ABC. The score lives in a sibling **`src/rogue/platform/scoring.py`** module — `score_from_findings` / `score_for(report)` / `risk_level(score)` (the doc's `compute_score`/`risk_level_for` names; the formula + bands below match the shipped code exactly). **Key deviations from this doc:** (1) `build_executive_summary` returns **`str` (markdown)**, not `bytes`/PDF — see §1; (2) it builds the CISO narrative **inline** (verdict + "Top risks in business terms" + "What to do first" + posture), it does **not** reuse `ThreatBriefBuilder`/`render_markdown` (§6); (3) the per-`(scan_id, format)` artifact **cache** described in §5 was not built — one `reports` row stores the whole `ScanReport.to_dict()` payload and PDF/HTML are re-rendered on demand each call; (4) `build_json` also layers in a `coverage` block and a top-level `executive_summary`, and backfills a per-finding `explanation`.

## 1. Contract (verbatim from the spine — do not redefine)

`ReportService` implements exactly the four coroutines from [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md) §4:

```python
class ReportService(abc.ABC):
    async def build_json(self, scan_id: str) -> dict: ...
    async def build_html(self, scan_id: str) -> str: ...
    async def build_pdf(self, scan_id: str) -> bytes: ...
    async def build_executive_summary(self, scan_id: str) -> str: ...   # markdown, NOT bytes/PDF
```

Each takes a `scan_id` (`scan_<ulid>`, ARCHITECTURE §5) and nothing else — no `ScanReport` is passed in. The service *loads* the persisted scan result by id and *renders* it; it never re-runs the scan and never reaches into `ScanEngine`. The report route (`GET /v1/scans/{id}/report?format=…`, [`../api/scans-endpoints.md`](../api/scans-endpoints.md) §3) resolves the scan for tenancy + readiness via `scan_service.get_scan(...)`, returns `report_not_ready` (a `404`) if `status != "completed"` **without** touching this service, then delegates by format to `build_json` / `build_html` / `build_pdf`. **`build_executive_summary` returns `str` (a CISO-ready markdown narrative)** — the shipped contract; the original `bytes`/PDF framing did not ship. `build_json` also embeds that markdown summary as a top-level `executive_summary` field so the dashboard gets it without a second call.

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

**Shipped: render-on-demand, no per-format artifact cache.** The design below (a `reports` row per `(scan_id, format)`, blob-stored PDFs, memoized serve-from-store) was **not** built. What ships: the **worker** writes a single `reports` row at scan finalize holding the whole `ScanReport.to_dict()` payload (a JSON blob — see [./data-model.md](../tenancy/data-model.md)); `report_id` is stamped on `scan_runs`. Every `build_json`/`build_html`/`build_pdf` call then **reconstructs the `ScanReport` from that one payload and re-renders** (the PDF via reportlab) on each request — there is no cached HTML/PDF artifact and no object-store blob. Because the payload is immutable the result is still deterministic, but the reportlab path runs per PDF fetch (acceptable at current volume; the per-format cache remains the obvious optimization).

The original design follows:

> Cache the artifact, keyed by `(scan_id, format)`. The first render persists a `reports` row with the bytes/blob reference; subsequent fetches serve it. JSON/HTML inline, PDF by object-store reference. Immutable inputs ⇒ no invalidation.

## 6. The PDF and executive-summary paths (new)

**`build_pdf` is the one new renderer.** The SDK already prototyped the exact shape to follow: `Report.export_pdf` (`sdk/src/rogue/models/report.py:190`) imports `reportlab` lazily and, **if it's missing, raises a clear actionable error** — `"PDF export requires the optional dependency. Install with: pip install 'rogue[pdf]'"` (`:204`) — rather than failing at import time. `build_pdf` reuses that reportlab-or-clear-error pattern: lazy `from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer` inside the method, the same Title → risk-score Heading2 → summary BodyText → per-finding `[SEVERITY] title` + `technique · vector · success_pct over n_trials` story the SDK builds (`:208`–`:230`), rendered into an in-memory buffer and returned as `bytes`. On the server, reportlab is a *hard* dependency of the platform (it's installed), so the clear-error branch is the defensive fallback, not the expected path — but it stays so a misconfigured deploy yields a `500` with a legible message instead of an `ImportError` traceback. The report route serves those bytes exactly like the existing binary-response pattern at `src/rogue/api/main.py:476` (`Response(content=…, media_type="application/pdf")`) with the `Content-Disposition: attachment; filename="rogue-scan-<id>.pdf"` header the endpoint doc specifies.

**`build_executive_summary` — shipped: inline markdown, not generalized from the threat brief.** It returns a **markdown `str`** built directly in `report_service.py` (it does **not** reuse `ThreatBriefBuilder`/`render_markdown`). The narrative has four moves: (1) a one-line risk-posture **verdict** banded off the `score`/`risk_level`; (2) **"Top risks, in business terms"** — the breached critical/high findings, each with a plain-language `explain_family` explanation; (3) a prioritized **"What to do first"** list — `remediation_for(family)`, severity-ranked and deduped per family; (4) a closing **Posture** sentence. Techniques are humanized (`humanize_technique`) so no raw ladder code reaches an exec, and it degrades to a clean all-clear when nothing critical/high breached. The PDF (`build_pdf`) reuses this summary's prose (via `_summary_prose`) as its lead-in paragraph. The original "generalize `ThreatBriefBuilder` off `acme`, serialize to PDF" plan did not ship.

## 7. Secret redaction in rendered payloads

Reports are **the** egress point where raw model interactions leave ROGUE for a customer's inbox/Slack/Jira, so redaction is a first-class concern, not a finishing touch. The policy is owned by [`../tenancy/secrets.md`](../tenancy/secrets.md); `ReportService` is one of its enforcement points. Two specific surfaces matter:

- **`api_key_ref`, never the secret.** `TargetSpec.api_key_ref` (ARCHITECTURE §5) is a Vault/KMS *handle*, and the resolved key never enters a `scan_runs` row, so it cannot leak through the loader. The service asserts this rather than assuming it: a rendered report references the target by `endpoint`/`provider`/`model`, never by a credential, and `build_json` must not echo any `api_key_ref` resolution.
- **Finding excerpts.** `Finding.example_attack` / `example_response` are verbatim slices of the attack prompt and the model's reply. **Shipped:** `_load_report` passes both through a **local `_redact` helper** in `report_service.py` — a regex (`_SECRET_RE = \b(?:sk|rk)[-_][A-Za-z0-9_-]{6,}\b`) that masks provider/ROGUE-key-shaped tokens with `[REDACTED]` before the rebuilt `Finding` reaches any renderer. (This is a focused defensive scrub, not the full configurable secrets-policy filter the original design pointed at in [`../tenancy/secrets.md`](../tenancy/secrets.md); the system-prompt-fragment scrubbing described there is not implemented here.) `to_html()` separately `html.escape`s every cell — redaction is *content*, escaping is *safety*, both apply.

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
| `src/rogue/platform/report_service.py` | The `DefaultReportService` class + the local `_redact` / `_explanation_for` / `_summary_prose` helpers. Wraps the existing renderers; the only new renderer is `build_pdf`'s reportlab story, and `build_executive_summary`'s inline markdown. |
| `src/rogue/platform/scoring.py` | The score functions `score_from_findings` / `score_for` / `risk_level` (§3) — used by **both** the worker (finalize) and this service (render). |
| `src/rogue/report.py` | **Reused.** `ScanReport.to_dict`/`to_json`/`to_html`, `Finding`, `technique_label`, `humanize_technique`, `remediation_for`, `explain_family`, `SCORE_METHODOLOGY`. (`to_html` gained optional `score`/`risk_level` params.) |
| `sdk/src/rogue/models/report.py` | **Reference.** Source of the mirrored `score` formula + reportlab-or-clear-error PDF pattern. (`src/rogue/diff/threat_brief.py` is **not** used by the exec summary — that was the un-taken design.) |

The service is small by design: a loader, a redaction hook, a score helper, and four thin serialization methods over renderers that already exist. The whole value of Team F is that the hosted product's reports are *the same reports* the SDK and the demo already produce — plus a PDF and a generalized executive summary — never a parallel re-implementation.
