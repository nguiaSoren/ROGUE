# ROGUE quickstart

Point ROGUE at any OpenAI-compatible LLM endpoint and get back a report of which open-web jailbreaks and prompt-injections break it — graded by an independent judge, with the exact attack, the model's response, and a remediation hook for each finding. This is the literal 5-minute path from a clean machine to `report.html`.

## 1. Install

ROGUE is on PyPI (Python 3.11+) — the `rogue` CLI + Python SDK:

```bash
pip install rogue-live-redteam
```

For development (tests, the full repo, the offline examples), install editable from a clone instead:

```bash
git clone https://github.com/nguiaSoren/ROGUE.git
cd ROGUE
pip install -e .          # or: uv pip install -e .
```

That gives you both the Python SDK (`from rogue import Client`) and the `rogue` command-line tool.

**Want the dashboard, not the SDK?** Self-host the full threat-intel UI (Postgres + API + Next.js) with one command — it migrates + seeds demo data on startup, no keys needed:

```bash
docker compose -f docker-compose.full.yml up      # then open http://localhost:3000
```

To fill it with **your** model's data, scan your endpoint with `--persist` and open the per-config view:

```bash
rogue scan https://api.company.com/v1 --model my-model --persist --config-name "my-bot"
# → http://localhost:3000/matrix?config=my-bot
```

For a board that's **only** your data (no demo rows), bring the stack up with `SEED_DEMO=0` so the DB starts empty — then `/feed`, `/matrix`, `/analytics`, and `/brief` all show nothing but your own scans:

```bash
SEED_DEMO=0 docker compose -f docker-compose.full.yml up
```

## 2. Two credentials

A scan calls **two** services, so you need **two** keys: your **target** model, and the **judge** that grades each response (this is what turns "the model said some words" into "this attack broke through" — there is no graded report without it). The default judge is `anthropic/claude-sonnet-4-6`, which reads `ANTHROPIC_API_KEY` specifically; if you don't hold Anthropic credits, repoint it with `JUDGE_MODEL` and set that provider's key instead. The CLI and SDK do **not** auto-load a `.env` file — export the vars in the shell you run from (or pass the target key as `api_key=` / `--api-key`):

```bash
# (1) target key — the model you want scanned
export OPENAI_API_KEY="sk-..."            # or match whatever your target endpoint expects
# (2) judge key — default judge is anthropic/claude-sonnet-4-6, which reads ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY="sk-ant-..."
# …or repoint the judge if you lack Anthropic credits:
# export JUDGE_MODEL="openai/gpt-5.4-nano"
# export OPENAI_API_KEY="sk-..."
```

## 3. Run

Three lines of Python — point the client at your endpoint, scan, print the summary, save the report:

```python
from rogue import Client

report = Client(endpoint="https://api.company.com/v1", api_key="sk-...").scan()
print(report.summary())
report.to_html("report.html")
```

Or the one-line CLI equivalent (with the judge env vars from step 2 exported):

```bash
rogue scan --endpoint https://api.company.com/v1 --api-key sk-... --output report.html
```

Targeting a hosted provider instead of a gateway? Swap `endpoint=`/`--endpoint` for `provider="openai"` / `--provider openai` (known: `openai`, `anthropic`, `openrouter`, `gemini`, `groq`) and the key falls back to that provider's standard env var.

Runnable companion: [`examples/company_quickstart.py`](examples/company_quickstart.py) is the same flow as a real script — and it ships an **offline demo that needs no keys** (`PYTHONPATH=src python3 examples/company_quickstart.py`) so you can see a full report before wiring up credentials.

## 4. What you get

A `ScanReport` — printable, exportable to JSON, and rendered to a standalone HTML page:

- A headline KPI block — tests run, breaches, breach rate, the single worst attack, and target-call cost.
- Every breach, severity-sorted.
- The top attacks, each with its technique name and severity.
- Per finding: the family/vector, success rate over N trials, and a redacted `example_attack` / `example_response` pair — the remediation hook that shows the exact attacker turn to defend against and the response to stop producing.

See a sample report: [`examples/sample_report.html`](examples/sample_report.html).

## 5. Next

- **Hosted API + dashboard** (private beta) — send one `curl` with a single ROGUE-issued key and let us run the scan and the judge: [`docs/company_onboarding.md`](docs/company_onboarding.md).
- **MCP server** — query ROGUE's live threat database directly from Claude Desktop / Cursor / Windsurf: [`docs/platform/integrations/mcp.md`](docs/platform/integrations/mcp.md).
