# Sources (15 primary; expanded post-hackathon — no longer frozen)

Extracted from ROGUE_PLAN.md §5. The list is built so that 5+ can break completely and the harvest pipeline still works.

## The 15 sources

| # | Source | URL pattern | Fetch strategy | Why on the list |
|---|---|---|---|---|
| 1 | r/ChatGPTJailbreak | reddit.com/r/ChatGPTJailbreak/new | **Web Scraper API (Reddit pre-built)** | Fastest-moving public jailbreak community |
| 2 | r/LocalLLaMA | reddit.com/r/LocalLLaMA (jailbreak/inject flair) | **Web Scraper API (Reddit pre-built)** | Open-source model attack discussion |
| 3 | r/PromptEngineering | reddit.com/r/PromptEngineering | **Web Scraper API (Reddit pre-built)** | Adjacent, sometimes surfaces attacks |
| 4 | arXiv cs.CR + cs.CL (+ cs.AI, cs.LG, cs.CV, cs.MM) | arxiv.org/list/{cs.CR,cs.CL,cs.AI,cs.LG,cs.CV,cs.MM}/new | Web Unlocker (HTML listing + abstract pages) | Where real research lands first (cs.CV/cs.MM added 2026-06-03 for multimodal attack coverage — §1b finding) |
| 5 | GitHub trending (last 7d) | github.com/search?q=prompt-injection&s=updated | SERP API → Web Unlocker for READMEs | Public PoC repos |
| 6 | HuggingFace community discussions | huggingface.co (model card discussions) | **Web Scraper API (HF pre-built)** + Web Unlocker fallback | Model-specific exploits |
| 7 | Simon Willison's blog | simonwillison.net (prompt-injection tag) | Web Unlocker | High-signal curated commentary |
| 8 | Embrace The Red blog | embracethered.com | Web Unlocker | Practitioner-grade attack write-ups |
| 9 | Lakera blog | lakera.ai/blog | Web Unlocker | Industry intel; occasional novel attacks |
| 10 | Promptfoo Discord public archives | discord-archived sites (e.g. discordapp.io) | Scraping Browser | OSS community attack discussion |
| 11 | X/Twitter — 12 curated accounts | x.com/<account>/posts | **Web Scraper API (X pre-built — posts-by-profile-URL)** | Where novel attacks break first, before write-up |
| 12 | MITRE ATLAS updates | atlas.mitre.org | Web Unlocker | Taxonomy + new technique IDs |
| 13 | OWASP LLM Top 10 | genai.owasp.org/llm-top-10 | Web Unlocker | Reference taxonomy; tracks new entries |
| 14 | Vendor safety blogs | anthropic.com/news, openai.com/blog, deepmind.google/discover/blog | Web Unlocker | Defensive announcements often reveal attack categories |
| 15 | Jailbreakchat archive | jailbreakchat.com or wayback equivalent | Scraping Browser | Historical archive for backfill seeding |

**X account list** (locked at 12, Day 0): simonw, plinz, embracethered, llm_sec, garak_ml, lakera, pliny, hardmaru, AnthropicAI, OpenAIDevs, GoogleDeepMind, doomslide.

## Per-source SERP discovery queries

Every source has at least one targeted query. `{date}` is `today - 14 days` for backfill, `today - 1 day` for daily delta. Total designed query pool 52 (39 original + 6 multimodal arms 2026-06-03 §1b + 7 source-expansion arms 2026-06-04); the live bandit state (`data/discovery_bandit.json`) currently holds 45 arms. DiscoveryAgent picks ~10 per daily run based on recent yield.

**Source expansion (2026-06-04, startup-track / post-deadline)** — new sources complementing arXiv at different pipeline stages; Web Unlocker fetches all as HTML, the yield-per-dollar bandit cold-starts them. (Discord/BASI deferred — needs Scraping-Browser + auth.)
- `site:openreview.net "jailbreak" OR "prompt injection" after:{date}` *(OpenReview — ICLR/NeurIPS/ACL submissions + review threads, often months pre-arXiv; reviewer threads carry attack constructions the camera-ready strips)*
- `site:openreview.net "adversarial" ("language model" OR "LLM") after:{date}`
- `site:aclanthology.org (jailbreak OR "prompt injection" OR "adversarial attack") ("LLM" OR "language model")` *(ACL Anthology — peer-reviewed NLP-security; un-dated backfill, bandit deprioritizes once deduped)*
- `site:github.com/NVIDIA/garak probes (jailbreak OR injection OR encoding OR dan)` *(garak — NVIDIA red-team framework; probe files = structured attack primitives)*
- `site:huggingface.co/datasets (jailbreak OR "red team" OR adversarial OR "prompt injection")` *(HF datasets — published attack corpora, AdvBench / JailbreakBench style)*
- `site:github.com/advisories ("prompt injection" OR "LLM" OR "AI agent" OR "model context protocol") after:{date}` *(GitHub Advisory DB — OWASP/MITRE-aligned deployment-config / tool-surface CVEs)*
- `site:huntr.com ("prompt injection" OR "LLM" OR jailbreak OR "AI agent")` *(Protect AI huntr — disclosed prompt-injection / agent-exfiltration issues against real LLM products)*

**Scoped re-test verdicts (2026-06-04, `--only-arms` / `--source-expansion-only`):** OpenReview + ACL = live, 7 reusable techniques. Advisory + huntr = live but yield *primitives* (tool-surface CVEs, e.g. Copilot Cowork file-exfil), not techniques — KEEP. **garak = 0** (SERP can't reach repo file pages — needs a probes-dir fetcher). **HF datasets = intentionally not harvested as primitives:** `analyze_hf_datasets.py` (in-the-wild / wildjailbreak / JBB / AdvBench) found 0 new families — they're known-technique instances + bare harmful goals. The right integration is a **benchmark layer** (JBB + AdvBench as eval denominators / judge-calibration), not a harvest arm. The HF-datasets SERP arm's 0-yield is therefore the correct outcome, not a bug.

**#1 r/ChatGPTJailbreak**
- `site:reddit.com/r/ChatGPTJailbreak after:{date}`
- `site:reddit.com/r/ChatGPTJailbreak "new method" after:{date}`
- `site:reddit.com/r/ChatGPTJailbreak "GPT-4o" OR "Claude" OR "Gemini" after:{date}`

**#2 r/LocalLLaMA**
- `site:reddit.com/r/LocalLLaMA "jailbreak" OR "uncensor" after:{date}`
- `site:reddit.com/r/LocalLLaMA "system prompt" "leak" after:{date}`

**#3 r/PromptEngineering**
- `site:reddit.com/r/PromptEngineering "injection" OR "jailbreak" after:{date}`

**#4 arXiv**
- `site:arxiv.org "prompt injection" after:{date}`
- `site:arxiv.org "jailbreak" "LLM" after:{date}`
- `site:arxiv.org "adversarial" "language model" after:{date}`
- `site:arxiv.org "red team" "LLM" after:{date}`
- `site:arxiv.org "vision-language" jailbreak after:{date}` *(multimodal, 2026-06-03)*
- `site:arxiv.org multimodal jailbreak (LLM OR VLM) after:{date}` *(multimodal, 2026-06-03)*
- `site:arxiv.org "cross-modal" jailbreak OR attack after:{date}` *(multimodal, 2026-06-03)*
- `site:arxiv.org typographic attack (VLM OR "vision language") after:{date}` *(multimodal, 2026-06-03)*
- `site:arxiv.org audio jailbreak "language model" after:{date}` *(multimodal, 2026-06-03)*

**#5 GitHub**
- `site:github.com prompt-injection updated:>{date}`
- `site:github.com jailbreak GPT OR Claude updated:>{date}`
- `site:github.com "llm-attacks" OR "llm-security" updated:>{date}`

**#6 HuggingFace**
- `site:huggingface.co "jailbreak" OR "system prompt" discussion after:{date}`
- `site:huggingface.co/<model>/discussions "exploit" OR "bypass" after:{date}`

**#7 Simon Willison**
- `site:simonwillison.net "prompt injection" after:{date}`
- `site:simonwillison.net "indirect injection" after:{date}`

**#8 Embrace The Red**
- `site:embracethered.com after:{date}`
- `site:embracethered.com "MCP" OR "tool" OR "exfiltration"`

**#9 Lakera**
- `site:lakera.ai "attack" OR "jailbreak" after:{date}`

**#10 Promptfoo Discord**
- `"discord" "promptfoo" jailbreak after:{date}` (catches archive mirrors)

**#11 X/Twitter (12 accounts)**
- For each `{account}`: `site:x.com/{account} after:{date}` (SERP discovery)
- Then fetch via Web Scraper API X (posts-by-profile-URL) for structured JSON.

**#12 MITRE ATLAS**
- `site:atlas.mitre.org after:{date}`
- `"MITRE ATLAS" "new technique" OR "T1" after:{date}`

**#13 OWASP LLM Top 10**
- `site:genai.owasp.org after:{date}`
- `"OWASP" "LLM Top 10" "2026" OR "update"`

**#14 Vendor safety blogs**
- `site:anthropic.com/news "safety" OR "red team" after:{date}`
- `site:openai.com/blog "safety" OR "red team" after:{date}`
- `site:deepmind.google "safety" OR "red team" after:{date}`

**#15 Jailbreakchat archive** (one-off backfill, not daily)
- `"jailbreakchat" OR "jailbreakchat.com" "DAN" OR "Sigma" OR "AIM"`

## Fetch cadence

- **Daily delta** (production behavior, demo): every source once daily for last 24h. ~150–250 documents/day.
- **Backfill** (Day 3): every source, last 14 days. ~1500–2500 documents, run once.

## Source-level failure handling

Every source has a hard timeout (15s SERP, 30s Web Unlocker, 60s Scraping Browser, 60s Web Scraper API sync mode / async for the long tail). On failure: source marked stale with last-successful timestamp. Dashboard surfaces freshness. Harvest agent skips stale sources for 1h then retries. **No source blocks the pipeline.**

## Why this list is enough

1. **High overlap.** Reddit + X catch the same attack within hours. arXiv preprints get tweeted before they're indexed.
2. **Multiplicative coverage.** Each Reddit subreddit has 100+ posts/week; each tracked X account has 20+ posts/week. ~2000 candidate documents per daily run.
3. **Quality > quantity.** 15-family taxonomy means 5–10 *novel* attacks per week keeps the threat brief interesting.

If Day 3 backfill yields <50 unique primitives across 14 days, expand the X account list (cheapest addition). Don't add subreddits — every additional sub means understanding its norms.

## Demo-seed fixture corpus (locked 2026-05-21)

Three fixtures, three roles, three Bright Data fetch paths. Full table in ROGUE_PLAN.md §5.6; fixtures live in `tests/fixtures/`:

- `multilingual_paper.html` + `multilingual_paper.pdf` — primary, arXiv 2605.18239 (Marx & Dunaiski 2026-05-18), `LANGUAGE_SWITCHING` + `MULTI_TURN_GRADIENT`, Web Unlocker path. **Live-demo centerpiece.**
- `copirate_365.html` — secondary, Embrace The Red 2026-05-04, `INDIRECT_PROMPT_INJECTION` + `TOOL_USE_HIJACK`, references **CVE-2026-24299**. Threat-brief featured example.
- `etr_index.html` — tertiary, Embrace The Red feed. Live Feed scrolling backdrop.

Matching golden `AttackPrimitive` JSONs: `01_multilingual_african_languages.json`, `02_copirate_365_cve_2026_24299.json`, `03_hacking_claude_memory.json`.
