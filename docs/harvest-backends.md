# Harvest backends — run the open-web harvest on any scraper, any LLM

ROGUE's open-web harvest is **backend-agnostic**. Every network fetch goes through a single `Fetcher` interface (`src/rogue/harvest/fetchers/`), and Bright Data is just the default — and most robust — backend. You can run the entire harvest on free/keyless backends instead, with no Bright Data account.

## Capabilities

Each source plugin declares the capabilities it needs (`required_capabilities`); a registry resolves each capability to a backend that provides it. The capabilities are: `UNLOCK` (anti-bot single-page fetch → markdown/html), `SERP` (web search), `SERP_IMAGE` (image search), `BROWSER` (JS / heavy-anti-bot render), `REDDIT` / `X` / `HF` (structured per-platform), `IMAGE_BYTES` (raw media), `REDIRECT` (resolve a shortlink). A source whose capability no registered backend serves is skipped with a warning — never a crash.

## Backends

| Backend | Capabilities | What it needs | Free? |
|---|---|---|---|
| `searxng` | SERP, SERP_IMAGE | `SEARXNG_URL` (your self-hosted instance, JSON format enabled) | ✅ OSS, self-host, **unlimited** |
| `local_pdf` | UNLOCK (PDF only) | nothing (pypdf, core); `pip install "rogue[pdf]"` upgrades to pymupdf4llm | ✅ OSS, local, always-on |
| `brightdata` | all | Bright Data keys (`BRIGHTDATA_*`) | paid (the default) |
| `crawl4ai` | UNLOCK, BROWSER | one command: `rogue setup` (installs crawl4ai + its Chromium) | ✅ OSS, local |
| `firecrawl` | UNLOCK, BROWSER, SERP | `FIRECRAWL_BASE_URL` (self-host) **or** `FIRECRAWL_API_KEY` (cloud) **or** `FIRECRAWL_KEYLESS=1` (keyless free tier, no account) | ✅ self-host / keyless free / paid cloud |
| `direct` | UNLOCK, IMAGE_BYTES, REDIRECT | nothing (httpx) | ✅ keyless |
| `ddg` | SERP, SERP_IMAGE | nothing (DuckDuckGo HTML) | ✅ keyless, rate-limited |
| `hf_api` | HF | nothing (`HF_TOKEN` optional) | ✅ keyless |
| `reddit_oauth` | REDDIT | `REDDIT_CLIENT_ID` / `_SECRET` (free Reddit "script" app) | ✅ free credential |
| `x_besteffort` | X | nothing (experimental) | ✅ best-effort, fragile |
| `playwright` | BROWSER | a chromium binary (`playwright install chromium`) | ✅ local |

## Run without Bright Data

Leave the `BRIGHTDATA_*` keys unset and the registry resolves a free backend for every capability: `UNLOCK` → `crawl4ai`/`firecrawl` when installed else `direct` (PDF URLs → `local_pdf`, always on — pypdf core floor, `pip install "rogue[pdf]"` upgrades to pymupdf4llm), `SERP`/`SERP_IMAGE` → `searxng` when `SEARXNG_URL` set, else `firecrawl`-keyless / `ddg`, `BROWSER` → `crawl4ai`/`firecrawl`/`playwright`, `HF` → `hf_api`, `IMAGE_BYTES`/`REDIRECT` → `direct`. The best fully-free stack: **crawl4ai** (UNLOCK/BROWSER) + **SearXNG** (SERP/image) + **local_pdf** (PDF) — all OSS, local/self-hosted, unlimited. (arXiv and other dual-format sources are fetched as **HTML**, not PDF — easier to parse; `RoutingFetcher` rewrites arXiv `/pdf/` → `/abs/`.) For a robust *keyless* backend with zero setup, set `FIRECRAWL_KEYLESS=1` (Firecrawl's free tier — no account; rate-limited, so best for demo/low-volume). It serves `UNLOCK`/`BROWSER` (ahead of `direct`/`playwright`) **and `SERP`** (a real search API, ahead of the fragile DuckDuckGo-HTML `ddg` backend) in the default order, and parses PDF→markdown (which `direct`/BD can't — `RoutingFetcher` auto-routes PDF URLs to it). **Auto-enable:** when *no* robust scraper is configured at all (no Bright Data, no crawl4ai, no Firecrawl key), the harvest turns on keyless Firecrawl automatically (one-time notice) so a first run gets a real anti-bot backend instead of bare `direct`+`ddg`; set `FIRECRAWL_KEYLESS=0` to opt out. On that keyless path the harvest also **scopes to the highest-yield sources** (`arxiv`/`blog`/`reddit`/`github`, ~96% of breaching primitives) to fit the rate budget, and surfaces a notice when the rate limit is hit — install crawl4ai (free/local/unlimited) or add a key for the full source set. Two caveats: `REDDIT` needs a free Reddit-app credential (`reddit_oauth`), and `X` only has the experimental `x_besteffort` path (it degrades to an empty result when the keyless route breaks, which it does periodically). Set whatever you want in `.env` (see the "Scraper-agnostic harvest" block in `.env.example`) and run the harvest normally — no code changes.

## Universal proxy (residential scale, any provider)

Set `ROGUE_PROXY_URL=http://user:pass@host:port` to route **all origin-site scraping** through one external proxy pool — wired once at the `Fetcher` layer, applied to every backend that fetches arbitrary sites with our IP: `direct`, `ddg` (IP-rate-limited), `local_pdf`, and the browser backends `crawl4ai` / `playwright`. This makes a cheap residential pool (Webshare ~$1.4/GB, IPRoyal, or your own) a drop-in substitute for Bright Data's *bundled* residential network — **crawl4ai + a residential proxy ≈ BD's residential capability at a fraction of the cost.** Opt-in (unset = our own IP). Scoped to scraping only — it does **not** touch the LLM/judge or Bright Data calls (BD keeps its own superproxy), nor the authed-API (`hf_api`/`reddit_oauth`) or self-hosted `searxng` / proxy-service `firecrawl` backends. Use an `http(s)://` URL (Playwright/crawl4ai don't support SOCKS5-with-auth); a rotating-gateway endpoint needs no extra logic.

## Preference order

When more than one registered backend serves a capability, the registry picks the first one in `ROGUE_FETCHER_ORDER` (csv). The default is `searxng > local_pdf > brightdata > crawl4ai > firecrawl > direct > ddg > hf_api > reddit_oauth > playwright > x_besteffort`. The two OSS backends lead **for the capabilities they serve only** (both register just when available, and neither serves `UNLOCK`/`BROWSER` generally, so they never disturb those): `searxng` is the preferred `SERP`/`SERP_IMAGE` (free + unlimited self-hosted, ahead of BD's paid SERP and Firecrawl/`ddg`); `local_pdf` is the preferred PDF parser (always on: pypdf core floor + pymupdf4llm upgrade) (`pdf_only` → the PDF guard reaches it for PDF URLs ahead of Firecrawl, but it never serves HTML `UNLOCK`). Then Bright Data, then the robust scrapers (`crawl4ai`/`firecrawl`) ahead of `direct`/`playwright` for `UNLOCK`/`BROWSER`. Override to taste, e.g. `ROGUE_FETCHER_ORDER=crawl4ai,direct,ddg,hf_api,reddit_oauth,playwright,x_besteffort`.

## Add your own backend

A new scraper (a hosted API, a house proxy, another OSS crawler) is a single file and one line of config — no changes to sources, the harvest pipeline, or the scan:

```python
# src/rogue/harvest/fetchers/mybackend.py
from .base import Fetcher
from .capabilities import Capability

class MyFetcher(Fetcher):
    name = "mybackend"
    capabilities = frozenset({Capability.UNLOCK})

    @classmethod
    def is_available(cls) -> bool:
        return bool(os.environ.get("MYBACKEND_API_KEY"))

    async def unlock(self, url, format="markdown"):
        ...  # return an UnlockedPage (the same shape every UNLOCK backend returns)
```

Then register it in `build_default_registry` (gated by `is_available()`) and add its name to `DEFAULT_PREFERENCE_ORDER` in `registry.py`. Done.

## Choose your models — bring your own LLM (including local)

The harvest's *extraction* step and the scan's *judge* call an LLM, and both are configurable `provider/model` strings — you are not locked to one model or API:

- `EXTRACTION_MODEL` (default `anthropic/claude-haiku-4-5`) — classifies scraped pages into attack primitives.
- `JUDGE_MODEL` (default `anthropic/claude-sonnet-4-6`) — grades each response; wired independently of the attacker/target (ADR-0011). A permissive open-model fallback is configurable via `JUDGE_FALLBACK_MODEL`.

Both accept `anthropic/…`, `openai/…`, `openrouter/…`, `groq/…`, `gemini/…`, or an **OpenAI-compatible local endpoint**. To run the judge on a local model (Ollama):

```bash
JUDGE_MODEL=openai/llama3.1
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
```

**Calibration caveat (important).** ROGUE's judge credibility — the human-agreement, κ, and ship-gate numbers in [`judge-calibration.md`](judge-calibration.md) — is validated against the *default* judge. A local or open judge is **uncalibrated** and tends to *under-report* breaches until you re-run the calibration harness (`scripts/calibration/`) against it. A free judge is easy; a *trusted* judge needs re-calibration first.
