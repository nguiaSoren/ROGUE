# ROGUE SDK

ROGUE is a continuous open-web LLM red-team. The SDK points it at *your* model — a hosted provider, a company gateway, or a self-hosted vLLM/TGI endpoint — runs real jailbreak and prompt-injection attacks harvested from the open web against it, grades the responses with an independent judge, and hands you back a report a security engineer can act on. You never touch raw payloads or internal data types; you get `Client`, a `scan()`, and a `ScanReport`.

## Install

```bash
pip install rogue
```

That gives you both the Python SDK (`from rogue import Client`) and the `rogue` command-line tool.

## 5-minute quickstart

Point the client at any OpenAI-compatible endpoint, scan it, print the summary. Three lines:

```python
from rogue import Client

client = Client(endpoint="https://api.company.com/v1", api_key="sk-...")
report = client.scan()
print(report.summary())
```

`scan()` loads the bundled `default` attack pack, fires each attack at the target, judges every response, and returns a `ScanReport`. The summary leads with the numbers that matter — how many tests ran, how many broke through, the breach rate, the single worst attack, and what it cost:

```
Target:
  https://api.company.com/v1
Tests:
  8
Breaches:
  3
Rate:
  38%
Top Attack:
  DAN / Persona Jailbreak
Cost:
  $0.04
```

`Cost` is the target-call spend only (the judge's grading cost is tracked separately). A scan against the default pack is small and cheap — it is meant to be run often, in CI, on every prompt or model change.

## Provider mode

If your target is a hosted provider rather than a custom endpoint, name the provider instead of a URL. The API key falls back to that provider's standard environment variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and so on), and a sensible default model is chosen for you:

```python
from rogue import Client

client = Client(provider="openai")                 # uses $OPENAI_API_KEY, default model
client = Client(provider="anthropic")              # uses $ANTHROPIC_API_KEY
client = Client(provider="openai", model="gpt-x")  # pin the model
```

Known providers with built-in default models are `openai`, `anthropic`, `openrouter`, `gemini`, and `groq`. A `model` containing a slash (e.g. `"vendor/some-model"`) is used verbatim; a bare model name is prefixed with the provider. You must pass either an `endpoint` or a `provider` — passing neither, or an unknown provider with no model, raises `ValueError`.

You can also set a system prompt to scan the deployment *as configured* (the system prompt is part of the attack surface), and override the grading model:

```python
client = Client(provider="openai", system_prompt="You are Acme's support bot...", judge_model="openai/gpt-5.4")
```

## Validate before you scan

`validate()` is a cheap one-call pre-flight: it confirms the target is reachable, your credentials are accepted, the model actually responds, and which modalities (image, audio) it supports. Run it before spending on a full scan so a typo in the URL or a dead key fails fast and free:

```python
result = client.validate()
print(result.summary())
if result.ok:
    report = client.scan()
```

`result.ok` is `True` only when the target is reachable, authenticated, and responding. When something is wrong, `result.error` carries the reason and `result.summary()` shows a per-check breakdown.

## Attack packs

ROGUE ships three curated attack packs as part of the wheel — no database needed at scan time. Pick one with `pack=`:

- **`default`** — a balanced starter battery, one attack per common family. This is what `scan()` runs when you don't ask for anything else. Small, fast, cheap; the right pack for CI.
- **`aggressive`** — the hardest and broadest set, spanning every attack family and biased toward high/critical severity, including multimodal-image injections that probe vision-capable targets. Text-only targets honestly skip the image attacks.
- **`compliance`** — the focused "is my deployment leaking its system prompt or refusing properly?" set, restricted to leak/refusal/roleplay/extraction/override/injection families on text vectors only.

```python
report = client.scan(pack="aggressive")
```

You can narrow a scan to specific attack families with `attacks=`, accepting either internal family slugs or friendly aliases (`dan` → DAN persona jailbreak, `crescendo` → multi-turn gradient, `injection`/`ipi` → indirect prompt injection, `multimodal` → multimodal injection, `leak` → system-prompt leak, and so on). Cap the number of attacks with `max_tests=`, and put a hard dollar ceiling on the run with `budget=` — the sweep stops as soon as accumulated target-call cost reaches it:

```python
report = client.scan(attacks=["dan", "crescendo", "leak"], max_tests=50, budget=5.0)
```

Run each attack more than once with `n_trials=` to measure how *reliably* it breaks through, not just whether it can once.

## Benchmark

Beyond ad-hoc scanning, `benchmark()` measures attack-success-rate (ASR) against a standard research dataset (AdvBench / JailbreakBench), so you can compare a target to the published field:

```python
bench = client.benchmark(dataset="advbench_100", max_goals=25)
print(bench.summary())
print(bench.asr, bench.cost_per_success)
```

`BenchmarkReport` exposes `asr` (success / goals), `cost_per_success`, and `winner_rank` (where the target lands against the field, when available).

## Reading and exporting reports

A `ScanReport` knows how to render itself three ways:

```python
report.summary()                 # the terminal block shown above (also str(report))
report.to_json("scan.json")      # machine-readable; returns the JSON string, optionally writes a file
report.to_html("scan.html")      # a standalone HTML report — the artifact to email or attach to a ticket
```

It also carries the structured findings for programmatic use: `report.findings` (every `Finding`), `report.breached_findings()` (only the ones that broke through), `report.top_findings(n)` (worst first, by severity then success rate), and the headline properties `report.breach_rate`, `report.breach_pct`, and `report.top_attack`. Each `Finding` reports its `family`, `technique`, `vector`, `severity`, `title`, `success_rate` / `success_pct`, `n_trials`, `n_breach`, and a redacted `example_attack` / `example_response` pair. `ValidationResult` and `BenchmarkReport` offer the same `summary()` / `to_dict()` / `to_json()` exporters.

## Command-line tool

Everything the SDK does is available from the `rogue` command:

```bash
rogue validate --endpoint https://api.company.com/v1 --api-key sk-...
rogue scan     --provider openai --pack aggressive --budget 10 --output scan.html
rogue benchmark --provider anthropic --dataset advbench_100 --max-goals 25
rogue report   scan.json --output scan.html
```

`rogue scan` accepts `--attacks`, `--max-tests`, `--budget`, `--pack`, `--n-trials`, and `--output` (write `.json` or `.html`); add `--json` to any command for machine-readable output. `rogue report` re-renders a previously saved scan JSON without re-running anything.

Rather than repeat flags, drop a `rogue.yaml` (or `rogue.toml`) in the working directory and the CLI picks it up automatically (override the path with `--config`):

```yaml
target:
  endpoint: https://api.company.com/v1
  api_key: sk-...
  provider: openai
  model: gpt-x
scan:
  budget: 10
  max_tests: 50
  pack: default
```

Explicit CLI flags always override config-file values.

## A note on the SDK surface

The public SDK is exactly `Client` plus the report objects (`ScanReport`, `Finding`, `ValidationResult`, `BenchmarkReport`). ROGUE's internal types — `TargetPanel`, `DeploymentConfig`, `BreachResult`, `AttackPrimitive`, the harvest/extract/adapter machinery — are implementation details and are not part of the supported surface; don't import them. A bare `import rogue` stays deliberately light and only loads the adapter and scan machinery the moment you touch `rogue.Client`.
