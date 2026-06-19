# ROGUE CI gate — GitHub Action

Red-team your LLM deployment on every pull request and **fail the merge on any HIGH/CRITICAL breach**. ROGUE installs from PyPI (`rogue-live-redteam`), scans your target with the Python SDK, and gates the PR on findings by severity. No account, no hosted service — it runs in your own CI runner against your own endpoint.

## Quickstart

Add `.github/workflows/rogue-scan.yml` to your repo (full copy-paste version: [`examples/github-action/rogue-scan.yml`](../examples/github-action/rogue-scan.yml)):

```yaml
name: ROGUE red-team gate
on:
  pull_request:
    branches: [main]
permissions:
  contents: read
jobs:
  redteam:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: nguiaSoren/ROGUE@v1
        with:
          endpoint: https://gateway.your-company.com/v1
          model: your-deployed-model
          system-prompt-file: prompts/production-system-prompt.txt
          pack: aggressive
          fail-on: high
          api-key: ${{ secrets.ROGUE_TARGET_KEY }}
```

Store `ROGUE_TARGET_KEY` (and, for the calibrated judge, `ROGUE_JUDGE_KEY`) under **Settings → Secrets and variables → Actions**.

## Fail policy

The gate fails the job (exit 1) when **either** condition holds:

1. **Severity** — any finding that *actually breached* at or above the `fail-on` severity floor (default `high`, i.e. any HIGH or CRITICAL breach). Non-breaching probes never fail the gate, regardless of their nominal severity.
2. **Rate** — when `max-breach-rate` is set, the overall breach rate strictly exceeds it.

Set `fail-on: critical` to gate only on the worst, `fail-on: none` to disable the severity gate (e.g. when you only want the rate gate). The job otherwise exits 0.

A setup/operational problem (package not installed, target unreachable, bad input, or `calibrated` judge without a key) exits with a non-zero code and a one-line `::error::` annotation — never a stack trace that could echo a key.

## Inputs

| Input | Default | Description |
|---|---|---|
| `endpoint` | — | OpenAI-compatible base URL of your deployment. Use this **or** `provider`+`model`. |
| `provider` | — | Known provider when not using an endpoint: `openai` / `anthropic` / `openrouter` / `gemini` / `groq`. |
| `model` | — | Target model id. Required in provider mode; optional for an endpoint. |
| `system-prompt` | `""` | Inline system prompt of your deployment — red-team your **real** config. |
| `system-prompt-file` | `""` | Path in your repo to a file holding the system prompt (alternative to `system-prompt`). |
| `pack` | `aggressive` | Attack pack: `aggressive` / `default` / `compliance`. |
| `max-tests` | `50` | Cap on attacks run. |
| `judge` | `keyless` | `keyless` (heuristic, no key) or `calibrated` (LLM judge — requires `judge-key`). |
| `budget` | `""` | Optional USD cap on target-call spend. |
| `api-key` | `""` | Credential for the target endpoint/provider. Pass via a repo secret. |
| `judge-key` | `""` | Credential for the calibrated judge (only used with `judge: calibrated`). Pass via a repo secret. |
| `fail-on` | `high` | Minimum breached-finding severity that fails the PR: `high` / `critical` / `medium` / `low` / `none`. |
| `max-breach-rate` | `""` | Optional float 0-1; also fail when the overall breach rate exceeds it. |
| `python-version` | `3.11` | Python used to install and run the gate. |
| `card-dir` | `rogue-scan` | Directory the breach-card artifact is written to. |

## Outputs

| Output | Description |
|---|---|
| `breaches` | Number of breached findings. |
| `breach-rate` | Overall breach rate (0-1). |
| `failed` | `'true'` if the gate failed, else `'false'`. |
| `card` | Path to the breach-card artifact (PNG, SVG fallback). |

The gate also writes a markdown summary (target, tests, breaches, top attack, cost, a severity-grouped table of breached findings) to the GitHub step summary, and uploads the breach card as a build artifact. Both run even when the gate fails (`if: always()`).

## Security

- **Keys come from repo secrets and the environment only.** The action exports them under fixed env-var names (`ROGUE_TARGET_KEY`, `ROGUE_JUDGE_KEY`); the gate reads them by name and **never** passes them on the command line, logs them, or includes them in error output. Scan errors are reported as `TypeName: <first line>`, never a full traceback.
- **Least privilege.** The example sets `permissions: contents: read` — the gate only needs to install the package and run the scan. Add more scopes only if you extend it to post PR comments yourself.
- **Your traffic, your runner.** The scan calls your endpoint directly from the runner; nothing is sent to a ROGUE-hosted service.

## Version pinning

Pin to a released major tag for stability:

```yaml
- uses: nguiaSoren/ROGUE@v1
```

For a fully reproducible build, pin to a full commit SHA instead:

```yaml
- uses: nguiaSoren/ROGUE@<40-char-sha>
```

`@v1` tracks the latest backward-compatible release of the v1 action; a SHA never moves.
