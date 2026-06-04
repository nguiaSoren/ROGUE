# ROGUE company onboarding

This is the path from "I have one model endpoint and some credentials" to "I'm holding a threat report" — and it takes under ten minutes. ROGUE points a continuous open-web red-team at *your* model, fires real jailbreak and prompt-injection attacks harvested from the open web at it, grades every response with an independent LLM judge, and hands you back a report a security engineer can act on. You never touch raw payloads or internal data types; you get a `Client`, a `scan()`, and a report.

There are two ways to run it, and they differ in exactly one thing: **who runs the judge.** Read this section before anything else, because it determines how many credentials you need.

- **Mode 1 — self-serve SDK.** You install ROGUE and run it on your own machine. ROGUE calls your target endpoint *and* grades the responses, both from your process. Nothing leaves your machine except the calls to your own endpoint and the calls to whichever LLM provider you choose as the judge. This needs **two** credentials — your target key and a judge key. It **works today** and, because your target key never leaves your process, it is the path we recommend for regulated or pilot deployments (see "Security and privacy").
- **Mode 2 — hosted API.** You send ROGUE one `curl` with a single ROGUE-issued key; we run the scan and the judge on our infrastructure and you poll for the report. The hosted `/v1` API is **live and key-authenticating today** as a private beta (request an `rk_live_` key); the one caveat is that executing a queued scan still needs a deployed background worker, so end-to-end scan completion is not yet generally available. Before using Mode 2 against a sensitive deployment, read the secret-handling disclosure in "Security and privacy" — today the hosted path stores the raw target key, so regulated/pilot customers should stay on Mode 1.

If you want a graded report in the next ten minutes, use Mode 1. Mode 2 is the hosted convenience layer on top of the same scan engine.

## Prerequisites — you need TWO credentials

The single thing to get right up front: ROGUE grades every response with an LLM judge, so a scan calls **two** services and needs **two** keys.

1. **A target endpoint/model key** — the model you want scanned. A sanitized OpenAI-compatible chat-completions URL we can call (a company gateway `https://gateway.company.ai/v1`, a proxy, a self-hosted vLLM/TGI server, or a hosted provider), plus whatever key its `Authorization` header expects. "Sanitized" means: point it at a staging/eval deployment, scope the key to that deployment, and assume every prompt ROGUE sends is adversarial (that is the point). ROGUE talks the OpenAI chat-completions wire format; anything that speaks it works.
2. **A judge key** — ROGUE grades every response with an LLM judge; that is what turns "the model said some words" into "this attack broke through," and ROGUE will not produce a graded report without it. The default judge is `anthropic/claude-sonnet-4-6`, which reads **`ANTHROPIC_API_KEY` specifically**. If you don't hold Anthropic credits, repoint it with `JUDGE_MODEL` and set that provider's key instead (see "Step 2 — set the judge credential" below).

```bash
# (1) target key — the model you want scanned
export OPENAI_API_KEY="sk-..."            # or match whatever your target endpoint expects
# (2) judge key — default judge is anthropic/claude-sonnet-4-6, which reads ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY="sk-ant-..."
# …or repoint the judge if you lack Anthropic credits:
# export JUDGE_MODEL="openai/gpt-5.4-nano"
# export OPENAI_API_KEY="sk-..."
# (optional) the fallback judge used on refused grades — see "Security and privacy"
# export JUDGE_FALLBACK_MODEL="deepseek/deepseek-v4-flash"   # OpenRouter; needs OPENROUTER_API_KEY
```

(In Mode 2 the judge runs on our infrastructure, so a hosted scan needs only the single `rk_live_` key; the target key still has to reach us — see the secret-handling disclosure in "Security and privacy.")

You do not need Postgres, Docker, the dashboard, or any ROGUE backend for Mode 1. The attack packs ship inside the package.

---

## Mode 1 — self-serve SDK (works today)

### Step 1 — install (≈2 min)

ROGUE is not published to PyPI, so install it from the repository as an editable package:

```bash
git clone https://github.com/nguiaSoren/ROGUE.git
cd ROGUE
pip install -e .          # or: uv pip install -e .
```

That installs both the Python SDK (`from rogue import Client`) and the `rogue` command-line tool. (`pip install rogue` is a future convenience once the package is published — it does not work today.)

### Step 2 — set the judge credential (≈1 min)

ROGUE grades responses with an independent judge model. The default is `anthropic/claude-sonnet-4-6`; if you don't have Anthropic credits, repoint it at a provider you do have. The judge model is chosen via the `judge_model=` argument (SDK) or the `JUDGE_MODEL` environment variable, and it reads that provider's standard key from the environment. For example, to judge with OpenAI:

```bash
export JUDGE_MODEL="openai/gpt-5.4-nano"
export OPENAI_API_KEY="sk-..."
```

The CLI does not auto-load a `.env` file — export the vars (or pass them in code) in the shell you run from. This judge key is the second of the two credentials self-serve needs; it is separate from your target key, and ROGUE will not produce a graded report without it.

### Step 3 — pre-flight with `validate()` (free, ≈30 s)

`validate()` is a cheap one-call check before you spend anything on a full scan: it confirms the target is reachable, your credentials are accepted, the model actually responds, and which modalities (image, audio) it supports. A typo in the URL or a dead key fails here, fast and free:

```python
from rogue import Client

client = Client(
    endpoint="https://gateway.company.ai/v1",
    api_key="<your endpoint key>",
    judge_model="openai/gpt-5.4-nano",
)
result = client.validate()
print(result.summary())
if result.ok:
    report = client.scan()
```

```
Target:           https://gateway.company.ai/v1
Reachable:        ✓
Authenticated:    ✓
Model responds:   ✓
Supports image:   ✓
Supports audio:   ✗
Ready to scan:    ✓
```

`result.ok` is `True` only when the target is reachable, authenticated, and responding; when something is wrong, `result.error` carries the reason. (`validate()` exercises the target only — it does not call the judge — so it is genuinely free of judge cost.)

### Step 4 — scan (≈3–5 min)

```python
from rogue import Client

client = Client(
    endpoint="https://gateway.company.ai/v1",
    api_key="<your endpoint key>",
    judge_model="openai/gpt-5.4-nano",
)
report = client.scan()                 # loads the bundled `default` pack
print(report.summary())
report.to_html("report.html")          # the artifact to email or attach to a ticket
```

`scan()` loads the `default` attack pack, fires each attack at the target, judges every response, and returns a `ScanReport`. The summary leads with the numbers that matter:

```
Target:
  https://gateway.company.ai/v1
Tests:
  8
Breaches:
  2
Rate:
  25%
Top Attack:
  DAN / Persona Jailbreak
Cost:
  $0.0034
```

To run a bigger sweep, pass a pack, a test cap, and a hard dollar ceiling — the scan stops the moment accumulated target-call cost reaches `budget`:

```python
report = client.scan(pack="aggressive", max_tests=50, budget=5.0)
```

`scan()`'s real signature is `scan(attacks=None, max_tests=100, budget=None, *, pack="default", n_trials=1)`. `attacks=` narrows to specific families (e.g. `["dan", "crescendo", "leak"]`); `n_trials=` runs each attack more than once to measure how *reliably* it breaks through, not just whether it can once.

### Step 4 (CLI alternative)

Everything the SDK does is on the `rogue` command. With the judge env vars exported from Step 2:

```bash
rogue validate --endpoint https://gateway.company.ai/v1 --api-key <your endpoint key>
rogue scan     --endpoint https://gateway.company.ai/v1 --api-key <your endpoint key> --output report.html
```

`rogue scan` accepts `--attacks`, `--max-tests`, `--budget`, `--pack`, `--n-trials`, and `--output` (write `.json` or `.html`); add `--json` to any command for machine-readable output. The judge model is set the same way as in the SDK — via the `JUDGE_MODEL` env var (the CLI has no `--judge-model` flag), with that provider's key in the environment. Rather than repeat flags, drop a `rogue.yaml` (or `rogue.toml`) in the working directory and the CLI picks it up automatically; explicit flags always override it.

### Targeting a hosted provider instead of a gateway

If your target is a hosted provider rather than a custom URL, name the provider instead of an endpoint. The target key then falls back to that provider's standard env var, and a sensible default model is chosen for you:

```python
client = Client(provider="openai")                                   # uses $OPENAI_API_KEY, default model
client = Client(provider="anthropic", model="claude-haiku-4-5")      # pin the model
```

Known providers with built-in defaults are `openai`, `anthropic`, `openrouter`, `gemini`, and `groq`. You must pass either `endpoint=` or `provider=` — neither, or an unknown provider with no model, raises `ValueError`. You can also pass `system_prompt=` to scan the deployment *as configured* (the system prompt is part of the attack surface).

That's it. From a clean machine to `report.html` is well under ten minutes, with Step 4 dominated by the model's own latency.

---

## Mode 2 — hosted API (private beta)

In the hosted model, ROGUE runs the judge, so a company needs only **one** credential: a ROGUE-issued `rk_live_…` key (request one — it's a private beta). The live host today is **`https://rogue-private.onrender.com`** (`api.rogue.ai` is a future vanity domain that does not resolve yet — don't use it). You give us a sanitized endpoint and key in the request body, we enqueue the scan, you poll for status and pull the report. Three calls:

```bash
# 1. Create — returns immediately with a scan_id
curl -X POST https://rogue-private.onrender.com/v1/scans \
  -H "Authorization: Bearer rk_live_…" \
  -H "Content-Type: application/json" \
  -d '{"target":{"endpoint":"https://gateway.company.ai/v1","api_key":"<your endpoint key>","system_prompt":""},"pack":"default","max_tests":50,"n_trials":3,"budget":5.0}'
# → {"scan_id":"scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X","status":"queued"}

# 2. Poll — status / progress / running breach count
curl https://rogue-private.onrender.com/v1/scans/scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X \
  -H "Authorization: Bearer rk_live_…"
# → {... "status":"running","progress":62,"n_completed":31,"n_breaches":4 ...}

# 3. Report — once status == "completed"
curl "https://rogue-private.onrender.com/v1/scans/scan_01J9ZC4M0K8Q2R3S4T5U6V7W8X/report?format=json" \
  -H "Authorization: Bearer rk_live_…"
```

The request body is a `ScanSpec`: `target` is a `TargetSpec` (`endpoint` **or** `provider`+`model`, plus the target `api_key` and an optional `system_prompt`), then `mode` (`pack | repertoire | ladder`, default `pack` — see "Scan modes" above), `pack` (`default | aggressive | compliance`, default `default`; used only in `pack` mode), optional `attacks`, `max_tests` (default 50, the cap on a repertoire run), `n_trials` (default 1), and an optional `budget`. The report route takes `?format=json|html|pdf` (default `json`) and returns `404 report_not_ready` while the scan is still running, so keep polling step 2 until `status: "completed"` before fetching it.

A request with no key returns `{"error":{"code":"invalid_token","message":"missing bearer api key"}}` and an unrecognized key returns `{"error":{"code":"invalid_api_key",…}}` — i.e. the `/v1` API is live and authenticating today.

**Status note — what's live and what isn't.** The hosted `/v1` API is deployed and key-authenticating at `https://rogue-private.onrender.com` (private beta). What is *not* yet generally available is end-to-end scan *execution*: a queued scan needs a deployed background worker to pick the job off the queue and run it, and that worker isn't running in production yet, so a `POST /v1/scans` will queue but not complete. The scan *engine* itself is the same one Mode 1 uses (`rogue.scan.run_scan`). The remaining platform design (the secret store, worker, and full orchestration) lives under `docs/platform/` — `ARCHITECTURE.md` §7, `docs/platform/api/scans-endpoints.md`, and `docs/platform/orchestration/`. For a graded report today, and for any regulated/pilot deployment, **use Mode 1** — it produces the identical report from the identical engine, with your target key never leaving your process.

---

## Scan modes — a curated sample vs. the full arsenal

A hosted scan runs in one of three **modes**, set by the `mode` field in the request body (`"pack" | "repertoire" | "ladder"`, default `"pack"`). The mode decides *which* corpus of attacks ROGUE fires; everything downstream — the target calls, the judge, the report — is identical.

- **`pack`** (default) — a small curated JSON pack of 8–17 attacks (the `default` / `aggressive` / `compliance` packs described below). Fast, cheap, deterministic. It is a representative *sample* of ROGUE's threat library, not the whole thing — the right mode for a quick smoke test, a CI gate on every prompt or model change, or your very first run.
- **`repertoire`** — ROGUE's live harvested corpus: the hundreds of real attack primitives ROGUE continuously grows from the open web, ordered most-reproducible-first and capped at `max_tests`. This throws ROGUE's full continuously-harvested arsenal at your model, not a fixed sample — the mode for a real security assessment, an audit, or a pre-release sign-off where you want breadth and want to know what *actually* breaks through today.
- **`ladder`** — the deepest mode. Rather than replaying fixed primitives, `ladder` escalates *each goal* through ROGUE's full multi-tier arsenal — graduated techniques, chain-of-jailbreak, structured-data injections, and image/audio renderers — climbing tier by tier with an attacker LLM until the goal breaches or the ladder is exhausted. It is the mode for the most thorough assessment you can ask for: when you want to know not just which known payloads break through but how far an adaptive attacker can push your model. It is also the **most expensive** mode, since it spends an attacker LLM plus the target plus the judge across every tier; for that reason it is budget-capped — pass a `budget` to set the ceiling, and if you leave it unset ROGUE applies a safe default of about **$5**, split across the goals.

The trade-off is cost. Repertoire is judge-dominated at roughly **$0.02 per test**, so `max_tests=50` lands around **$1**, and running the full (~459-primitive) corpus lands around **$9** — versus cents for a pack. Start with a pack to shake out wiring and target reachability, then run repertoire when you want the thorough sweep. Use `max_tests` to dial the depth (and ceiling) of a repertoire run, and pair it with `budget` for a hard dollar stop.

**How to set it.** Mode is available on the **hosted API** and the **dashboard** today. In the hosted request body, set `mode` alongside `max_tests`:

```bash
curl -X POST https://rogue-private.onrender.com/v1/scans \
  -H "Authorization: Bearer rk_live_…" \
  -H "Content-Type: application/json" \
  -d '{"target":{"endpoint":"https://gateway.company.ai/v1","api_key":"<your endpoint key>"},"mode":"repertoire","max_tests":50,"n_trials":1,"budget":2.0}'
```

In the dashboard, the **New scan** form has a mode toggle — "Curated pack" (default), "Full repertoire", and "Full ladder" — next to the pack/`max_tests` controls. (The self-serve SDK `Client.scan()` does not take a `mode=` argument yet; it always runs a bundled pack. Repertoire is a hosted/dashboard capability for now — the live corpus lives server-side in the platform DB, which the local SDK does not carry.)

## The three attack packs

In `pack` mode, ROGUE ships three curated packs inside the package — no database needed at scan time. Each is a list of real harvested `AttackPrimitive`s (top reproducibility-score per family), replayed at your target — a fast, fixed *sample* of the threat library; for the full live corpus use `mode: "repertoire"` (above). Pick a pack with `pack=` (SDK) / `--pack` (CLI) / `"pack"` (hosted body).

- **`default`** (8 primitives, 8 families) — a balanced starter battery, one attack per common family (DAN persona, Crescendo multi-turn gradient, role hijack, indirect prompt injection, refusal suppression, obfuscation/encoding, direct instruction override, system-prompt leak). This is what `scan()` runs when you don't ask for anything else. Small, fast, cheap — the right pack for CI and for your first run.
- **`aggressive`** (17 primitives, all 15 families) — the hardest and broadest set, biased toward high/critical severity (12 critical / 3 high / 2 medium), including three multimodal-image injections that probe vision-capable targets. Text-only targets honestly skip the image attacks.
- **`compliance`** (10 primitives, 6 families) — the focused "is my deployment leaking its system prompt or refusing properly?" set, restricted to leak / refusal / roleplay / extraction / override / injection families on text vectors only.

---

## What the report shows

A `ScanReport` (and the hosted JSON/HTML/PDF report) leads with the KPIs you saw in the summary — tests run, breaches, breach rate, top attack, cost — over a severity-sorted findings table. Each **finding** carries its `family`, human-readable `technique`, `vector`, `severity`, `success_rate` (with `n_trials` / `n_breach`), a `title`, and a redacted `example_attack` / `example_response` pair so a security engineer can see exactly what got through and what the model said. That last pair is the remediation hook: it shows the attacker turn to defend against and the leaked/compliant response to stop producing.

You can render and consume it three ways:

```python
report.summary()                 # the terminal KPI block (also str(report))
report.to_json("scan.json")      # full machine-readable report (returns the JSON string too)
report.to_html("scan.html")      # a standalone ~2 KB HTML page — KPI header + findings table
```

For programmatic use the report exposes `report.findings`, `report.breached_findings()`, `report.top_findings(n)`, and the headline properties `report.breach_rate` / `report.breach_pct` / `report.top_attack`. For the full field-by-field shape of the report and findings, and the CLI's `rogue report scan.json --output report.html` re-render path, see [`../README_SDK.md`](../README_SDK.md).

---

## Rough cost

The headline scan cost (the `Cost:` line) is **target-call spend only** — what it costs to call your model. The `default` pack against a small model lands in the **cents** (sub-cent in the SDK example above): it is meant to be run often, in CI, on every prompt or model change. The judge's grading cost is tracked separately and scales with the same volume. Bigger packs, `max_tests`, and `n_trials > 1` cost proportionally more, which is exactly what `budget=` (SDK/CLI) / `"budget"` (hosted) is for — set a hard USD ceiling and the sweep stops cleanly when projected spend would exceed it. Run `validate()` first so you never spend a cent on an unreachable target.

---

Read this before pointing ROGUE at anything sensitive. We'd rather you know the current limits than be surprised by them in a security review.

- **Mode 1 (SDK) is the safe path, and the one we recommend for regulated or pilot deployments.** Your target key lives only in your own process's memory and goes only to (1) your own endpoint and (2) the judge provider you chose. ROGUE has no backend in this mode; the attack packs ship in the package; nothing else leaves your machine.
- **Mode 2 (hosted) encrypts your target key at rest (as of 2026-06-05).** The hosted path runs the `api_key_ref` indirection: the API encrypts your raw `api_key` into a `secrets` table (Fernet, AES128-CBC + HMAC) and the queue/record carry only an opaque `secref_…` handle; the worker resolves it just-in-time, holds it only in memory for the scan, and never writes it back — so the raw key is **not** persisted to `scan_jobs`/`scan_runs`. This is active when the hosted service has `SECRET_ENCRYPTION_KEY` set and migration 0023 applied; until a given deployment has both, it falls back to carrying the raw key (confirm the deployment status with your ROGUE contact). The v1 uses a single env-held encryption key; full KMS/Vault envelope encryption + rotation is a future hardening (`docs/platform/tenancy/secrets.md`). The most security-conscious customers can still prefer **Mode 1 (SDK)**, where no key ever leaves their machine at all.
- **The judge sees the target's response text, and the worst breaches may go to a second provider.** ROGUE's verdicts come from an LLM judge, so the target model's *response text* (not just the attack) is sent to the judge provider — `JUDGE_MODEL`, by default Anthropic. When the primary judge refuses to grade a cell (which happens precisely on the most harmful, fully-complied responses), ROGUE re-sends that response to a fallback judge — `JUDGE_FALLBACK_MODEL`, by default an OpenRouter-hosted open model (`deepseek/deepseek-v4-flash`). So a bank should expect those specific responses to transit a *second* provider (OpenRouter) as well. Both are repointable, and the fallback can be disabled, by setting `JUDGE_MODEL` / `JUDGE_FALLBACK_MODEL` to providers you've vetted.
- **Assume every prompt is adversarial.** That is the product — point ROGUE at a staging/eval deployment with a scoped key, not at anything where a successful jailbreak would have real-world consequences.

---

## Troubleshooting

- **No judge credits / judge auth fails (Mode 1).** This is the most common first-run snag. The judge defaults to `anthropic/claude-sonnet-4-6`; if you don't hold Anthropic credits, repoint it: `export JUDGE_MODEL="openai/gpt-5.4-nano"` (or `judge_model="openai/gpt-5.4-nano"` in code) and export that provider's key (`OPENAI_API_KEY`, etc.). Remember the two-credential rule — a working target key alone is not enough for self-serve.
- **Endpoint auth rejected / 404.** Run `validate()` first. If `Authenticated` is ✗, the target key is wrong or scoped to the wrong deployment. If `Reachable` is ✗ or you get a 404, the URL is wrong — for OpenAI-compatible gateways the base URL usually ends in `/v1` (ROGUE appends the chat-completions path), so pass the base, not the full `…/chat/completions`.
- **Image/audio attacks "skipped" on a text-only target.** Expected and honest. The `aggressive` pack includes multimodal-image injections; a target whose `validate()` shows `Supports image: ✗` simply won't have those probes counted against it. Use `validate()` to see a target's modalities up front, and `default`/`compliance` (text-only) if you don't want any multimodal probes at all.
- **`ValueError: Client needs either endpoint=... or provider=...`.** You constructed the client with neither a URL nor a known provider (or an unknown provider with no `model=`). Pass an `endpoint=` or one of `openai`/`anthropic`/`openrouter`/`gemini`/`groq`.
- **Hosted `curl` returns `report_not_ready`.** The scan hasn't finished — keep polling `GET /v1/scans/{id}` until `status: "completed"`, then fetch the report. (And see the Mode 2 status note: the `/v1` API is live, but scan *execution* needs a deployed worker that isn't running in production yet, so a hosted scan may sit `queued`. The live host is `https://rogue-private.onrender.com`, not `api.rogue.ai`.)

---

## The pitch, in one line

Give me a sanitized endpoint — a staging deployment, or any OpenAI-compatible gateway URL — plus the credentials to call it, and you get a threat report: every open-web jailbreak that breaks your model, graded by an independent judge, with the exact attack and response to remediate. Today that's a few lines of Python on your own machine (Mode 1, the recommended path); the hosted `curl` API (Mode 2) is in private beta, with end-to-end scan execution landing as the background worker and secret store ship.
