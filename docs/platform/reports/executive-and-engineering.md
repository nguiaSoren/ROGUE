# Executive & Engineering Reports (Team F)

> What the customer actually reads. The `ScanReport` and its `Finding[]` (`src/rogue/report.py:51`, `src/rogue/report.py:75`) are the raw material; this doc designs the two *human* artifacts rendered from them — the **Executive Summary** for the buyer who signs the contract, and the **Engineering Report** for the team that fixes the holes. Both are produced by `ReportService` (`ARCHITECTURE.md:88`, see [./report-service.md](./report-service.md)); the dashboard renders the same two personas in HTML (see [../dashboard/report-views.md](../dashboard/report-views.md)); the headline `score` and its trend come from [../benchmark/scoring-and-trends.md](../benchmark/scoring-and-trends.md). This is a content/template spec, not code.

Status: **design spec, not yet built.** The engine, `Finding`, `ScanReport`, and the SDK's `compute_risk_score` (`sdk/src/rogue/models/report.py:19`) ship today; the two-persona report rendering does not.

---

## 1. Why two personas, one scan

A scan produces exactly one `ScanReport` (`src/rogue/report.py:75`) with one `findings: list[Finding]`. We never re-run or re-score per persona — that would violate the one-engine principle (`ARCHITECTURE.md:28`). Instead, **both reports are two projections of the same persisted scan**, differing only in *what they include* and *how they frame it*:

- **Executive Summary** — 1–2 pages, no payloads, no per-trial detail. Answers "how exposed am I, against whom, and is it getting better?" Audience: CISO, security buyer, the person who approves spend. The headline is the `score` (`ARCHITECTURE.md:104`) and its risk band.
- **Engineering Report** — long-form, every `Finding` in full, redacted example payloads, reproduction context, and — the new value — **per-finding remediation advice**. Audience: the platform/ML team that closes the gaps.

The split is purely presentational. If a number in the executive summary disagrees with the engineering report, the architecture has failed exactly as a divergent scan engine would.

## 2. The descriptive precedent (and what's new)

ROGUE already ships a descriptive diff artifact: the daily threat brief, `ThreatBriefBuilder.render_markdown` / `render_json` (`src/rogue/diff/threat_brief.py:213`, `:364`). It is the structural precedent for both reports — section-per-severity layout, primitives sorted descending by severity within each tier (`src/rogue/diff/threat_brief.py:192`), a Summary block of per-tier counts (`:240`), and a "Newly defended" close (`:283`). We deliberately reuse that shape so a reader who has seen a brief recognizes a report.

What the threat brief does **not** carry is any mitigation text — it is descriptive only (`src/rogue/diff/threat_brief.py:75` comment: "the internal threat brief is descriptive only and carries no mitigation text"). **The remediation layer is the new customer value Team F adds.** A brief tells you *what broke*; a report tells you *what broke, why it matters to the business, and how to fix it.*

## 3. Remediation source — the per-family map

Every piece of "how to fix it" traces to a single source: a **per-`AttackFamily` remediation map**, keyed by the same internal family slug the `Finding` carries. The SDK already shipped one — `REMEDIATION_BY_FAMILY` in `sdk/src/rogue/models/common.py:77`, with a concrete one-to-three-sentence mitigation for each of the 15 family slugs and a generic fallback `remediation_for` (`sdk/src/rogue/models/common.py:152`). Team F **generalizes and hosts** that map server-side (so the API, dashboard, and PDF all draw the identical text) rather than re-authoring it. The contract:

- Key = the `Finding.family` slug (`src/rogue/report.py:55`) — never a display label, never a re-keyed taxonomy. The 15 keys are exactly the slugs in `TECHNIQUE_DISPLAY` (`src/rogue/report.py:16` / `sdk/src/rogue/models/common.py:57`).
- Value = remediation guidance: a concrete, vendor-neutral control the customer can implement (e.g. for `indirect_prompt_injection`: "Treat all retrieved/tool/RAG content as untrusted data, never instructions; sandbox tool outputs…", `sdk/src/rogue/models/common.py:114`).
- Lookup goes through one function (`remediation_for`, `sdk/src/rogue/models/common.py:152`) so an unknown/future slug degrades to the generic control text + a logged warning, never a `KeyError` — mirroring how `_compute_severity_score` clamps unknown families (`src/rogue/diff/threat_brief.py:640`).

Remediation is per-**family**, not per-finding, on purpose: two findings in the same family share a root cause and therefore a fix. The engineering report groups by family (§7) precisely so the remediation block appears once per family, with the findings that motivate it listed beneath.

Hosting note: when the family map moves server-side, the SDK's copy becomes a thin client of the hosted map (or stays as an offline fallback). The map is the one place remediation text is authored; the glossary, dashboard, and PDF all read from it. Editing remediation = editing this map, nowhere else (no stale duplicate strings).

## 4. The headline `score`

The executive summary leads with `score` — the platform's single 0–100 risk number (`ARCHITECTURE.md:104`), synthesized severity × success-rate, saturating, dominated by the worst findings. The formula is owned by Team F and mirrors the SDK's `compute_risk_score` (`sdk/src/rogue/models/report.py:19`): `100 · (1 − Π(1 − wᵢ·sᵢ))` over findings, with `wᵢ` the severity weight (`sdk/src/rogue/models/common.py:27`) and `sᵢ` the `Finding.success_rate`. The risk **band** comes from `risk_level_for` (`sdk/src/rogue/models/report.py:33`): ≥75 CRITICAL, ≥50 HIGH, ≥25 MEDIUM, else LOW. This `score` is distinct from the raw `breach_rate` (`src/rogue/report.py:86`); the executive report shows the `score` as the headline and may footnote `breach_rate` as the underlying raw signal. The trend arrow vs. the previous scan is the same `score` differenced across two `ScanRecord`s — definition lives in [../benchmark/scoring-and-trends.md](../benchmark/scoring-and-trends.md); this report only *renders* it.

## 5. Grouping, sorting, and the "Critical Findings" rule

Three shared rules, used by both report types so the ordering is identical wherever a finding appears:

- **Sort** — descending by `(severity_rank, success_rate)`, exactly the key in `ScanReport.top_findings` (`src/rogue/report.py:96`) with `_SEVERITY_RANK` (`src/rogue/report.py:34`). The most dangerous, most reliable finding is always first.
- **Group** (engineering report) — by `Finding.family`. Within a family, findings keep the sort above. Families themselves are ordered by their worst contained finding's `(severity_rank, success_rate)`.
- **Critical Findings selection** (executive report) — the set surfaced under "Critical Findings" is: every breached finding (`Finding.breached`, `src/rogue/report.py:71`) whose `severity` is `critical` **or** `high`, **and** whose `success_rate` clears the breach threshold of 0.4 (the plan-locked `BREACH_RATE_THRESHOLD`, `src/rogue/diff/threat_brief.py:71`). Cap the rendered set at the top 5 by the shared sort; if more qualify, note "+N more in the engineering report." If none qualify, the section reads "No critical findings — see Top-5 below" and the headline band will already be MEDIUM or LOW. This keeps the executive page honest: a green report is allowed to look green.

"Top-5 jailbreaks" (the executive summary's second table) is simply `ScanReport.top_findings(5)` (`src/rogue/report.py:96`) rendered by technique label (`technique_label`, `src/rogue/report.py:47`) + success% + severity — it includes the Critical Findings and the next-most-severe even if sub-threshold, so the buyer sees the leading edge regardless of the 0.4 cut.

## 6. Executive Summary — section-by-section template

Produced by `ReportService.build_executive_summary(scan_id) -> bytes` (`ARCHITECTURE.md:92`). PDF (1–2 pp) primary; the dashboard renders the same sections as HTML. No payloads, no per-trial rationale, no reproduction steps. Sections, in order:

1. **Header / cover** — target identity (the `ScanReport.target` string, `src/rogue/report.py:79`), scan date, scan id (`scan_<ulid>`, `ARCHITECTURE.md:99`), pack name. One line. No secrets — the target is rendered from `TargetSpec` display fields, never the `api_key_ref` (`ARCHITECTURE.md:102`).
2. **Risk headline** — the `score` (0–100, §4) as the dominant number, with its risk band word (CRITICAL/HIGH/MEDIUM/LOW) and band color. One supporting line: "N of M tests breached (`n_breaches`/`n_tests`, `src/rogue/report.py:82`) — raw breach rate `breach_pct`."
3. **Trend vs. last scan** — the `score` delta and arrow vs. the prior completed scan for this target (↑ worse / ↓ better / → flat), plus a one-clause reading ("exposure down 12 points since last week"). Sourced per [../benchmark/scoring-and-trends.md](../benchmark/scoring-and-trends.md). Omit gracefully ("first scan — no prior baseline") when there is no predecessor.
4. **Business framing** — two to three sentences translating the families present into business risk in plain language: e.g. `system_prompt_leak` / `training_data_extraction` → "confidential-data exposure"; `tool_use_hijack` / `indirect_prompt_injection` → "unauthorized actions via your agent's tools." This mapping is a small family→business-impact table owned by Team F alongside the remediation map; it never invents numbers, only frames the findings already present.
5. **Critical Findings** — the §5 selection, max 5, one row each: technique label, severity, success%, and a single plain-English consequence clause. No payload, no response excerpt.
6. **Top-5 jailbreaks** — `top_findings(5)` table (technique label · severity · success%). This is the "what's hitting you hardest" glance.
7. **Which models are vulnerable** — the breached `DeploymentConfig`/target view: each scanned target (or, in multi-target scans, each `target_model`) with its own `score` band and breach count, sorted worst-first. Mirrors the threat brief's per-config listing (`src/rogue/diff/threat_brief.py:327`) but at the report's aggregate level. Single-target scans collapse this to one row.
8. **Remediation overview** — the *families* present, each with its one-line remediation headline pulled from the per-family map (§3, `sdk/src/rogue/models/common.py:77`), ordered by family severity. This is the executive teaser; the full controls live in the engineering report. Three to six bullets, no implementation detail.
9. **Footer** — cost (`_fmt_usd(cost_usd)`, `src/rogue/report.py:37`), methodology one-liner ("N trials per attack, independent judge, breach threshold 40%"), and a pointer to the engineering report for reproduction + full remediation.

## 7. Engineering Report — section-by-section template

Produced by `ReportService.build_pdf(scan_id) -> bytes` (`ARCHITECTURE.md:91`) — the long-form artifact; the dashboard renders the same as an expandable HTML view. Every `Finding` appears in full. Sections:

1. **Header** — same identity block as the executive cover, plus the full scan parameters: pack, `n_trials`, breach threshold, judge model, total tests/breaches, cost. This is the reproducibility preamble.
2. **Score & methodology** — the same `score` (§4) with the formula stated explicitly (`compute_risk_score`, `sdk/src/rogue/models/report.py:19`) and `_SEVERITY_RANK` / severity weights (`sdk/src/rogue/models/common.py:27`) tabulated, so an engineer can audit how the headline number was reached.
3. **Findings by family** — the body. Grouped by `Finding.family` (§5), families ordered worst-first, findings within a family by the shared sort. For each **family** block:
   - Family heading: `technique_label(family)` (`src/rogue/report.py:47`) + count of findings + worst severity in the family.
   - **Remediation advice** for the family — the full control text from the per-family map (`remediation_for`, `sdk/src/rogue/models/common.py:152`). Rendered once, at family level, because all findings in the family share the root cause (§3).
   - Then, per `Finding` in the family, a detail block (§7.4).
4. **Per-`Finding` detail block** — every real field of `Finding` (`src/rogue/report.py:51`):
   - `title`, `technique` (display), `family` slug, `vector` slug, `severity`.
   - `success_rate` rendered as `success_pct` (`src/rogue/report.py:67`), with `n_breach` / `n_trials` (e.g. "60% — 3/5 trials breached") so the engineer sees the denominator, not just a percentage.
   - **Redacted example** — `example_attack` and `example_response` (`src/rogue/report.py:63`), shown only after redaction (Team F runs the redaction pass before persistence/render; the executive report never includes these). These are the proof-of-breach: the engineer needs the concrete payload shape to reproduce, but harmful specifics are masked.
   - **Reproduction context** — pack name, `n_trials`, breach threshold (0.4), judge model, and the scan id — everything needed to re-run *this* finding via `client.scan()` / the hosted API and confirm the fix. Where source provenance exists (the brief's `_source_map`, `src/rogue/diff/threat_brief.py:344`), cite the open-web origin of the technique.
5. **Newly defended** — findings that breached in the prior scan and no longer do, mirroring the brief's close (`src/rogue/diff/threat_brief.py:283`). Confirms regressions-fixed; gives the team a win to point at.
6. **Appendix** — full family→remediation map for reference, and the scoring formula. So the report is self-contained.

## 8. How `ReportService` produces both

Both methods read **one** persisted scan (`scan_id` → its `ScanReport` + `Finding[]`) — neither re-runs the engine, both call the same sort/group/score helpers (§4, §5) so the numbers are byte-for-byte consistent:

- `build_executive_summary(scan_id) -> bytes` (`ARCHITECTURE.md:92`) → §6 template → PDF (1–2 pp). Pulls the headline `score`, the trend delta, applies the Critical-Findings rule (§5), renders the family→business-impact framing and the remediation *overview* (one line/family).
- `build_pdf(scan_id) -> bytes` (`ARCHITECTURE.md:91`) → §7 template → the full engineering PDF, including redacted examples and per-family full remediation.
- `build_html` / `build_json` (`ARCHITECTURE.md:90`) return the same content as the dashboard's HTML view and the machine-readable form respectively — JSON keys mirror `ScanReport.to_dict` (`src/rogue/report.py:130`) plus a `remediation` field per family and the `score`/`risk_level`. The dashboard ([../dashboard/report-views.md](../dashboard/report-views.md)) consumes `build_html`/`build_json`; the existing `ScanReport.to_html` (`src/rogue/report.py:147`) is the throwaway-demo ancestor of the hosted HTML, not the persona renderer.

Shared helper surface Team F factors out (so executive, engineering, HTML, and JSON never diverge): the `score`/band computation (§4), the sort/group/Critical-Findings selection (§5), the redaction pass for example fields, the family→remediation lookup (§3), and the family→business-impact framing (§6.4). Each is one function, called by all renderers.

## 9. Invariants (review checklist)

- One scan → one `ScanReport` → both personas. Never re-score per persona; never re-run the engine to render (`ARCHITECTURE.md:28`).
- The executive summary contains **zero** payloads or response excerpts; only the engineering report carries `example_attack`/`example_response`, and only redacted.
- Family slugs flow through unchanged from `Finding.family` to the remediation lookup — no re-keying, no parallel taxonomy. Unknown slug → generic remediation + warning, never a crash.
- Sort and Critical-Findings rule are the *same* code in both reports and the dashboard.
- Remediation text is authored in exactly one place — the hosted per-family map generalized from `REMEDIATION_BY_FAMILY` (`sdk/src/rogue/models/common.py:77`). Changing a control = editing that map; no duplicated strings in templates.
- `score` is the headline everywhere; `breach_rate` is the raw footnote. They must never be presented as the same thing (`ARCHITECTURE.md:104`).
