# Budget — $250 Bright Data credit + ~$190 LLM out-of-pocket

Extracted from ROGUE_PLAN.md §7. Conservative order-of-magnitude estimates (real prices live on Day 1 dashboard).

## Bright Data spend ($250 credit)

| Bucket | Volume | Est. unit | Est. total |
|---|---|---|---|
| Web Scraper API — Reddit + X + HF (daily × 4d) | ~500 records | ~$1.50/1k | ~$0.75 |
| Web Scraper API — backfill | ~800 records | same | ~$1.20 |
| SERP API — daily discovery × 4d | ~1000 queries | $0.0015–$0.003/q | $1.50–$3.00 |
| SERP API — backfill (Day 3) | ~300 queries | same | $0.45–$0.90 |
| Web Unlocker — daily × 4d | ~400 pages | $0.001–$0.005/p | $0.40–$2.00 |
| Web Unlocker — backfill | ~600 pages | same | $0.60–$3.00 |
| Scraping Browser — daily (fallback only) | ~80 sessions | $0.005–$0.02/s | $0.40–$1.60 |
| Scraping Browser — backfill | ~150 sessions | same | $0.75–$3.00 |
| MCP Server — agent tool calls | ~2000 calls | free tier covers it | ~$0 |
| Demo dry-runs (Day 4) | ~500 mixed | mixed | $5–$15 |
| 30% buffer | | | ~$8 |
| **Total estimated** | | | **~$20–$40** |

Headroom: $210+. The $250 is generous. Web Scraper API's pay-per-success model is cheap because most pages succeed.

## LLM spend (out-of-pocket, separate from Bright Data)

| Item | Volume | Est. |
|---|---|---|
| Extraction LLM (Haiku/4o-mini) | ~1000 docs × $0.005 | $5 |
| Judge LLM (Sonnet/4o) | ~500 attacks × 5 configs × 5 trials × $0.01 | $125 |
| Target panel (OpenRouter / Together / Groq) | ~12.5k calls × $0.005 avg | $60 |
| Embeddings (3-small) | ~5k strings × $0.00002 | $0.10 |
| **Total non-Bright-Data LLM cost** | | **~$190** |

**Action:** top up OpenAI + Anthropic + OpenRouter + Groq accounts to ~$200 before May 26. Real money out of pocket.

If tight: cut N=5 trials to N=3, panel from 5 models to 3 (GPT-4o-mini, Claude Haiku, Llama-3-8B). Cost drops to ~$80.

## Escalation ladder — the "try harder" pass (§10.8, default OFF)

Reproduction above is the baseline pass. The **auto-escalation ladder** is an *optional second pass* over the attacks the panel refused (`synthesize_escalations.py --ladder`, or inline `reproduce_once.py --escalate`). It's the dominant variable cost when on, because it tries up to ~18 transformed variants × the panel × judge per refused attack.

| Item | Estimate |
|---|---|
| One fully-resisting primitive, exhausts all tiers (`n_trials=1`) | **~150–180 LLM calls ≈ ~$2** (judge-dominated; observed live 2026-05-29: 181 calls / ~13 min) |
| One primitive that breaches early (short-circuit) | a few calls ≈ $0.05–0.30 |
| Full-corpus escalation delta (~85 EVADE-band primitives) | **~$10 (most breach early) → ~$170 (all exhaust)** — roughly doubles a full run in the worst case |

**Bound it with `--escalate-max-spend $X`** (estimated-USD cap): once cumulative escalation spend hits it, remaining refused primitives are skipped and the baseline pass still completes. Keep escalation OFF for ordinary runs; turn it on deliberately, capped. (The planned §10.10 escalation bandit will cut this by front-loading the likely-winning strategy → earlier short-circuit → fewer calls.)

## If Bright Data credit runs out

Ask in Discord — the page explicitly says additional credits are available on request. If denied, cut from 15 sources to 8.

## If OpenAI / Anthropic budget runs out

Switch entire pipeline to GPT-4o-mini including judge. Quality drops ~10%; demo still works. OpenRouter as backstop.
