# ROGUE Python SDK — design doc

> The customer-facing translation layer. Turns ROGUE (a research system built around *our* DB,
> *our* configs) into something a company self-onboards onto in 15 minutes:
> `pip install rogue` → `register` → `scan` → `report`.

## Why this exists / first principles

1. **Customers never see internal ROGUE.** No `DeploymentConfig`, `AttackPrimitive`, `BreachResult`,
   `breach_matrix`, taxonomy internals. The whole surface is four objects: `Deployment`, `Scan`,
   `Report`, `Finding`.
2. **The SDK is a client for a hosted API.** It owns no business logic that belongs server-side.
   It owns: ergonomics, typed models, validation-before-network, transport/retry, exporters, CLI.
3. **The wire contract is frozen and explicit** (`CONTRACT.md`). The server is built to match it;
   today most write endpoints don't exist server-side, so a faithful `MockTransport` implements the
   whole contract in-memory — it is both the test backbone and an offline demo backend.
4. **Sell risk, not attacks.** A `Finding` leads with `severity`, `success_rate`, a plain-language
   `explanation` ("what this is + why it matters") and `remediation` ("how to fix") — a business risk,
   not a payload dump. `explanation` and `remediation` are synthesized per attack family.

## Packaging decisions

- **Separate uv project at `sdk/`**, distribution name **`rogue`**, import root `rogue` (`src/` layout).
  It has **zero dependency on the internal `src/rogue`** research codebase — that's why it can reuse
  the import name without colliding (customers install only this; we test it in its own venv).
- Runtime deps: **`httpx`** (transport, lazy-imported) + **`pydantic` v2** (models). CLI uses stdlib
  `argparse` (no `typer`) to keep installs cache-only/offline-friendly. PDF export is an optional
  extra `rogue[pdf]` (reportlab) that degrades gracefully.
- **Synchronous client.** "Async" scans are *server-side* async jobs polled over HTTP, not Python
  asyncio. (`AsyncRogue` can come later without changing the contract.)

## Architecture

```
Rogue (facade)                       rogue.client.rogue.Rogue
 ├─ .auth         AuthClient         token exchange / refresh / login / logout
 ├─ .deployments  DeploymentsClient  register / get / update / list / delete
 ├─ .scans        ScansClient        scan (blocking) / scan_async / get / list / cancel
 ├─ .reports      ReportsClient      get / fetch-for-scan
 ├─ .register(...)        -> Deployment   (sugar over .deployments.register)
 ├─ .scan(...)            -> Report       (blocking: start job, poll, return report)
 ├─ .scan_async(...)      -> Scan         (job handle; .refresh()/.wait()/.report())
 └─ .register_openai/anthropic/vertex(...)   provider credential registration

Transport (Protocol)                 rogue.transport.base.Transport
 ├─ HTTPTransport   httpx + retry (Render cold-start aware: 502/503/504/network)
 └─ MockTransport   in-memory faithful CONTRACT.md impl (tests + offline demo)

Models (pydantic v2)                  Deployment · Scan · Report · Finding · enums
Exceptions                            RogueError hierarchy (see exceptions/)
utils                                 validation (pre-network) · telemetry (opt-in) · config/creds
cli                                   `rogue login|deployment|scan|report` (argparse)
adapters                              openai · anthropic · vertex · custom (provider cred shapes)
```

## Object-model ergonomics (matches the headline example)

```python
from rogue import Rogue
rogue = Rogue(api_key="...")
deployment = rogue.register(name="Support Agent", model="gpt-5", system_prompt="...")
report = rogue.scan(deployment)          # blocks, polls, returns a Report
print(report.summary())                  # human-readable str
report.risk_score                        # float 0..100
report.top_findings(5)                   # list[Finding]
report.export_markdown("report.md")
```
- `report.summary()` is a **method** (returns prose) so the headline example is literal; structured
  counts live on `report.stats` (`ReportSummary`).
- `Scan` is a data model with bound `.refresh()` / `.wait(timeout=)` / `.report()` (client injected
  via a private attr) so `job` reads naturally.

## Risk-score synthesis (no internal equivalent — owned by SDK)

`risk_score ∈ [0,100]` = `100 * (1 - Π(1 - wᵢ·sᵢ))` over findings, where `sᵢ` = `success_rate` and
`wᵢ` = severity weight (`critical 1.0, high 0.7, medium 0.4, low 0.15`). Monotonic, saturating,
dominated by the worst findings. Banded → `risk_level` (≥75 critical, ≥50 high, ≥25 medium, else low).
Defined once in `models/report.py`; mirrored in `MockTransport` so mock reports are self-consistent.

## Build plan (waves) — ✅ complete

- **Wave 1 — core (orchestrator):** pyproject, DESIGN, CONTRACT, exceptions, models, transport
  (base/http/mock), validation, config, adapters, clients + facade, `__init__`. Verified end-to-end.
- **Wave 2 — fan-out (4 parallel agents, disjoint files, against the frozen core):** CLI · opt-in
  telemetry · comprehensive core test suite · README + examples.
- **Wave 3 — assemble + verify:** wired `utils/__init__` exports + telemetry env-enable, isolated
  `uv` venv, full suite + ruff, headline example + installed `rogue` CLI through the real package.

**Verification:** `uv run pytest` → **324 passed, 1 skipped**; `uv run ruff check src tests` → clean;
`examples/*.py` and the installed `rogue` console script run offline against `MockTransport`.

## Deliverable → location map

| # | Deliverable | Where |
|---|---|---|
| 1 | Package structure | this layout |
| 2 | Customer object model | `models/` |
| 3 | Auth | `client/auth.py`, `cli` `login/logout`, `utils/config.py` |
| 4 | Deployment registration | `client/deployments.py`, `models/deployment.py` |
| 5 | Scan API (sync + async job) | `client/scans.py`, `models/scan.py` |
| 6 | Report object (+ exporters) | `client/reports.py`, `models/report.py` |
| 7 | Findings model | `models/finding.py` |
| 8 | Provider registration | `adapters/`, `Rogue.register_*` |
| 9 | CLI | `cli/` |
| 10 | Local validation | `utils/validation.py` |
| 11 | Versioning | `_version.py`, `client.api_version`, version headers |
| 12 | Telemetry (opt-in, anonymous) | `utils/telemetry.py` |

## Out of scope for the SDK team (other teams)

- The **Hosted API** server (auth issuance, deployment store, scan job queue/worker, per-tenant
  scoping) — built to `CONTRACT.md`. Today: `reproduce_once.py` offline + read-only public API.
- Server-side multi-tenancy / billing.
