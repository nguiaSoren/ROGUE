# ROGUE Python SDK

ROGUE is a continuous open-web LLM red-team: it harvests real jailbreaks and prompt-injection attacks from across the open web, reproduces them against your deployed model configuration, and grades the results with an independent judge. This package is the customer-facing client for the ROGUE Hosted API — you register a deployment, run a scan, and get back a risk report. You never see ROGUE's internal complexity (the breach matrix, attack taxonomy, judge panel, harvest pipeline); the entire surface is four objects: `Deployment`, `Scan`, `Report`, and `Finding`.

## Install

```sh
pip install rogue
```

The SDK is deliberately lean — its only runtime dependencies are `httpx` (transport) and `pydantic` v2 (models), and the CLI uses the standard-library `argparse` — so installs are small and offline-/cache-friendly. PDF export is an optional extra:

```sh
pip install 'rogue[pdf]'
```

## Quickstart

```python
from rogue import Rogue

rogue = Rogue(api_key="...")
deployment = rogue.register(
    name="Customer Support Agent",
    model="gpt-5",
    system_prompt="You are a helpful support agent.",
)
report = rogue.scan(deployment)          # starts the job, polls, returns the Report

print(report.summary())
print("risk:", report.risk_score, report.risk_level.value)
for f in report.top_findings(5):
    print(f.severity.value, f.title, f.success_pct)

report.export_markdown("report.md")
```

`rogue.scan(deployment)` is blocking: it starts a server-side scan job, polls it to completion, and returns the finished `Report`. For long scans, start one and poll yourself with `scan_async` (see [Async scans](#async-scans)).

## Try it offline right now (no server, no key)

Every part of the `v1` wire contract is implemented in-memory by `MockTransport`, so you can run the entire flow with zero setup — no API key, no network:

```python
from rogue import Rogue, MockTransport

rogue = Rogue(api_key="demo", transport=MockTransport())
deployment = rogue.register(
    name="Customer Support Agent",
    model="gpt-5",
    system_prompt="You are a helpful support agent.",
)
report = rogue.scan(deployment)
print(report.summary())
for f in report.top_findings(5):
    print(f.severity.value, f.title, f.success_pct)
```

When you pass `transport=MockTransport()`, `base_url` is ignored and the `api_key` can be any string. This is exactly what `examples/quickstart.py` runs — see the [`examples/`](examples/) directory for runnable scripts.

## Core objects

| Object | What it is | Key fields / methods |
|---|---|---|
| `Deployment` | Your deployed LLM config under test `(model × system_prompt × tools)`. | `name`, `model`, `system_prompt`, `tools`, `forbidden_topics`, `provider`, `id` (server-assigned, `None` until registered), `is_registered` |
| `Scan` | A server-side red-team job against one deployment. | `status` (`ScanStatus`), `progress` (0.0–1.0), `done`, `succeeded`; `.refresh()`, `.wait(timeout=, poll_interval=)`, `.report()`, `.cancel()` |
| `Report` | The customer-facing result of a completed scan. | `risk_score` (0–100), `risk_level` (`Severity`), `stats` (`ReportSummary`), `findings`; `.summary()`, `.top_findings(n)`, `.findings_by_severity(s)`, `.export_json()`, `.export_markdown()`, `.export_pdf()` |
| `Finding` | One reproduced vulnerability — risk, not a payload dump. | `severity` (`Severity`), `family`, `technique`, `vector`, `title`, `description`, `success_rate` (0–1), `success_pct` (e.g. `"81%"`), `n_trials`, `confidence`, `explanation` (plain-language "what this is + why it matters"), `remediation` ("how to fix"), `source_url`, `first_seen` |

`report.summary()` is a method that returns a human-readable paragraph; the structured counts live on `report.stats` (`n_findings`, `n_critical`, `n_high`, `n_medium`, `n_low`). Findings come pre-sorted by severity descending, then success rate descending, so `report.top_findings(5)` is the five highest-priority issues. The `risk_score` is synthesized by the SDK as a saturating product over findings weighted by severity, then banded into a `risk_level` (≥75 critical, ≥50 high, ≥25 medium, else low).

## Async scans

A scan is a server-side job that can take minutes to tens of minutes (it spends real LLM budget reproducing attacks), so for anything but a quick demo you start it and poll. `scan_async` returns a `Scan` job handle immediately:

```python
job = rogue.scan_async(deployment)
job.wait()                # blocks until terminal; raises ScanFailedError / ScanTimeoutError
report = job.report()
print(report.summary())
```

Or poll it yourself:

```python
job = rogue.scan_async(deployment)
while not job.done:
    job.refresh()
    print(job.status.value, round(job.progress * 100), "%")
    time.sleep(5)
report = job.report()
```

`job.wait(timeout=600, poll_interval=5)` raises `ScanTimeoutError` if the job is still running after `timeout` seconds, and `ScanFailedError` if it ends in the `failed` state. `job.cancel()` requests cancellation of a running scan.

## Providers

Before ROGUE can scan a deployment it needs credentials to reach your model provider. Register them with the typed helpers — secrets are write-only and never echoed back (the response carries only `id` / `provider` / `label` / `created_at`):

```python
rogue.register_openai(api_key="sk-...")
rogue.register_anthropic(api_key="sk-ant-...")
rogue.register_vertex(project="my-gcp-project", location="us-central1")
rogue.register_custom(base_url="https://llm.internal.example.com/v1")

rogue.providers()        # -> list of registered provider records (no secrets)
```

Each helper takes an optional `label=` to distinguish multiple credentials for the same provider. See `examples/providers.py` for a runnable demo.

## Authentication

Provide your API key one of three ways. The resolution order is **explicit argument > `ROGUE_API_KEY` env var > stored credentials**:

```python
rogue = Rogue(api_key="rk_live_...")     # explicit
# or set ROGUE_API_KEY in the environment, then:
rogue = Rogue()
```

Or log in once with the CLI, which persists a credential to `~/.config/rogue/credentials.json`:

```sh
rogue login
```

After that, `Rogue()` with no arguments picks up the stored credential. Authentication is lazy — the first API call exchanges your key for a short-lived access token (the SDK refreshes it transparently on expiry) — or call `rogue.login()` to authenticate eagerly.

## CLI

The package installs a `rogue` command (stdlib `argparse`, no extra deps):

```sh
rogue login                                              # authenticate, store credentials
rogue status                                             # SDK / API version + auth state
rogue deployment create --name "Support Agent" --model gpt-5
rogue deployment list
rogue scan start --deployment <deployment_id> --wait     # start a scan and block for the report
rogue report open <report_id> --format md --output report.md
rogue report open <id> --format json --output report.json
rogue report open <id> --format pdf --output report.pdf  # requires rogue[pdf]
```

Two global flags are useful everywhere: `--mock` runs against the in-memory backend for an offline trial (no key, no network), and `--json` emits machine-readable output instead of formatted text.

## Exporters

A `Report` knows how to serialize itself for routing into Slack / Jira / Notion / email:

```python
report.export_json("report.json")        # JSON; also returns the string
report.export_markdown("report.md")       # CISO-readable Markdown; also returns the string
report.export_pdf("report.pdf")           # PDF — requires the rogue[pdf] extra
```

`export_json` and `export_markdown` return the rendered text and write to the path only if one is given. `export_pdf` requires `reportlab` (`pip install 'rogue[pdf]'`) and raises a clear, actionable error if it is missing.

## Errors

Every error the SDK raises subclasses `rogue.exceptions.RogueError`, so a single `except RogueError` is exhaustive. The transport maps HTTP status and the server's `error.code` onto these typed exceptions, so application code branches on a type rather than a status integer:

| Exception | When |
|---|---|
| `ValidationError` | A local check failed before any request was sent (carries the offending `field` / `fields`). |
| `AuthenticationError` | 401 — API key / token missing, invalid, or expired. |
| `AuthorizationError` | 403 — authenticated but not permitted. |
| `NotFoundError` | 404 — resource does not exist. |
| `ConflictError` | 409 — conflicts with current state. |
| `RateLimitError` | 429 — too many requests (carries `retry_after`). |
| `APIError` | 5xx / unmapped server errors (carries `status_code`, `code`, `details`). |
| `APIConnectionError` | Could not reach the API at all: DNS, refused connection, timeout, dropped socket. |
| `ScanFailedError` | A scan finished in the `failed` state (carries the final `scan`). |
| `ScanTimeoutError` | `scan()` / `wait()` exceeded the caller's timeout while still running (carries the `scan`). |

```python
from rogue import Rogue
from rogue.exceptions import RogueError, ScanFailedError, ScanTimeoutError

try:
    report = rogue.scan(deployment, timeout=600)
except ScanTimeoutError as e:
    print("still running:", e.scan)
except ScanFailedError as e:
    print("scan failed:", e.scan)
except RogueError as e:
    print("ROGUE error:", e)
```

## Telemetry

Usage telemetry is **anonymous, opt-in, and off by default**. It never sends prompts, API keys, deployment configs, findings, or any customer data — only coarse, anonymous event names (e.g. that a scan started). Enable it explicitly:

```python
rogue.enable_telemetry()        # in code
```

```sh
export ROGUE_TELEMETRY=1         # via environment
```

Disable it any time with `rogue.disable_telemetry()`, or set `DO_NOT_TRACK=1` to keep it off regardless.

## Versioning

```python
import rogue

rogue.__version__                # the SDK package version, e.g. "0.1.0"

client = Rogue(api_key="...")
client.api_version               # the wire-contract version, "v1"
client.sdk_version               # the SDK package version
```

The client sends `X-Rogue-Api-Version: v1` and a `rogue-python/<version>` user agent on every request. The wire contract is frozen and documented in [`CONTRACT.md`](CONTRACT.md) — the SDK codes to it and the Hosted API is built to match it exactly.

## Status

This SDK is a client for the ROGUE Hosted API. The full `v1` wire contract — auth, deployments, scans, reports, providers — is specified in [`CONTRACT.md`](CONTRACT.md). Today the write/scan/auth endpoints are served in-memory by `MockTransport` (the test backbone and offline demo backend) while the Hosted API catches up to the contract, which is why the offline example above runs immediately. See [`DESIGN.md`](DESIGN.md) for the architecture.
