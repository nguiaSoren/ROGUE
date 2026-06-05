# 05 — Capabilities: Landing Page & "How ROGUE Thinks" Intelligence Demos

An exhaustive catalog of every distinct capability, interaction, and visual on ROGUE's landing surface (`/`) and the intelligence demos that explain how ROGUE thinks. Each entry is framed as a marketable beat: a designer reading this should know every separate thing on these surfaces they could build a short clip around, with no detail summarized away.

Scope note on "landing" vs "intelligence demos": the landing route (`frontend/src/app/page.tsx`) renders nine sections in a fixed order. The five intelligence widgets (bandit / persona / escalation / mutation / stubbornness) do NOT live on the landing page — they render in the right-hand sidebar of `/feed` (`frontend/src/app/feed/page.tsx`). The landing page's equivalent "intelligence" surfaces are the Augmentation Showcase and the interactive Augmentation Lab, which are driven by the same five data sources. Because the task explicitly asks for all five widgets, they are cataloged here as the "intelligence demo" layer; their on-landing cousins (Showcase, Lab) are cataloged in their landing positions. Two components in the directory are currently orphaned (built, not rendered anywhere): `pipeline-flow.tsx` and `augmentation-headlines.tsx` — both are cataloged at the end as dormant assets, since they are real capabilities a designer could revive.

Data-source ground truth (`frontend/src/lib/api.ts`): the landing page is a server component that fetches eight endpoints in parallel via `Promise.allSettled`, so the page paints even if a backend call fails (each result degrades to `null`). Pages are cached and revalidated every 5 minutes (ISR) — visitors get instant loads, and fresh Neon data surfaces within that window. The one genuinely real-time element is the live attack ticker, which holds its own Server-Sent-Events connection separate from the cached page fetch. Throughout, "live" below means "pulls from the live threat DB" (subject to the 5-minute cache), and "static" means "hardcoded copy/visuals in the component."

---

## SECTION 1 — First-visit cinematic intro overlay (16-second auto-play)

**Name.** The 16-Second Origin Story (auto-play intro).

**Where.** Landing `/`, mounted at the very top of `app/page.tsx`; component `frontend/src/components/intro-overlay.tsx`.

**What it does / what's on screen.** A fullscreen modal (`z-[100]`, above everything) that plays automatically on a visitor's first arrival and tells ROGUE's whole story in four auto-advancing panels of 4 seconds each (16s total). Each panel is a two-column layout: a giant animated headline + body paragraph on the left, a bespoke pure-CSS "side visual" on the right, over an animated radial-gradient mesh whose tint color morphs per panel, plus a faint grid overlay. The four panels:
- **01 · the problem** (red tint): headline "Your AI is being *jailbroken* right now." The side visual (`ProblemVisual`) is a stack of six fake live attack rows — "DAN 2024.12 — roleplay bypass", "agent prompt-smuggle via Markdown", "L1B3RT4S system-prompt leak", "Crescendo 3-turn — Claude 3.5 Sonnet", "PAP authority-frame on GPT-4o", "tool-injection via memory recall" — each with a pulsing red dot and an "Nh ago" timestamp, fading up in sequence.
- **02 · the harvest** (green tint): headline "ROGUE watches the open web *continuously.*" The side visual (`HarvestVisual`) shows two chip rows: the 5 Bright Data products and 6 representative sources (Reddit, X, GitHub, HuggingFace, arXiv, leak mirrors), each chip with a source logo, animating in.
- **03 · the test** (cyan tint): headline "Every attack ran against *your exact stack.*" The side visual (`TestVisual`) is a 5×5 grid of 25 cells that pop in one-by-one, color-coded red/orange/green/empty — captioned "each cell = one attack × one config × one trial."
- **04 · the brief** (yellow tint): headline "And ships a brief your *CISO can read.*" The side visual (`BriefVisual`) is a mock threat-brief card: "3 new CRITICAL breaches", a PAIR finding with a 95% CI, and three export chips (↓ .md, ↓ .json, MCP → Claude Desktop).

Controls and behavior: a persistent "skip intro →" button top-right; a bottom progress bar that fills smoothly over each 4s panel; four clickable segment dots (current = wide green, past = dim green, future = grey) that let the viewer jump to any panel; a "01 / 04 · 16s intro" counter bottom-left. The overlay auto-dismisses with a 600ms fade after the last panel. It is gated by `localStorage` (`rogue:intro-seen-v1`) so it shows exactly once per browser; appending `?intro` to the URL force-replays it (the demo/recording hook). Audio is intentionally omitted (browser autoplay policy would mute it on first visit anyway) — the narrative is carried purely visually.

**Live or static.** Static. All copy, the fake attack list, and the visuals are hardcoded; nothing touches the API.

**Marketing hook.** The entire ROGUE pitch — problem, harvest, test, brief — lands in 16 seconds before the visitor scrolls a single pixel.

**Video idea.** Screen-record the full uninterrupted 16s auto-play with the tint shifting red→green→cyan→yellow and the progress bar racing; cut it as the cold-open of any longer film.

---

## SECTION 2 — Cinematic hero (rotating headline + live stat trio + CTAs)

**Name.** The Cinematic Hero — "Your LLM is being jailbroken. ROGUE finds out first."

**Where.** Landing `/`, section 1 after the overlay; component `frontend/src/components/cinematic-hero.tsx` (wrapped in `PausedOffscreen` so its CSS animations pause when scrolled out of view).

**What it does / what's on screen.** A near-full-viewport (`min-h-[88vh]`) hero over an animated gradient "mesh" background with a faint 80px grid. Contents, top to bottom, each fading/revealing in staggered sequence:
- **Two status pills**: a green "live · streaming the open web" pill with a pulsing dot, and a foreground "powered by Bright Data · 5 / 5 products · cost-optimized" pill.
- **The rotating-word headline**: huge type reading "Your LLM is being [word]." where the word vertically rotates through *jailbroken. → prompt-injected. → role-played. → escalated. → jailbroken.* (a pure-CSS keyframe rotator, red text, masked inside a fixed-height window), then a muted third line "ROGUE finds out before your users do."
- **Subhead**: "Built on all 5 Bright Data products. Harvests every new jailbreak from 19 open-web sources, reproduces each one against your stack, and ships a daily brief — on a budget the bandit auto-tunes for you."
- **Product value line**: "Point ROGUE at your LLM endpoint. Get a report of which jailbreaks break it — and how to fix them."
- **Hero stat trio** (the "this is alive" proof): three big tabular numbers — *attacks tracked* (`n_primitives`), *trials judged* (`n_breaches`), *deployments tested* (`n_configs`) — each with a plain-English subtitle generated by `plainifyAttackCount` / `plainifyTrials` (e.g. "every public jailbreak from the last 30 days", "every attack tested 5+ times across every config"). Falls back to "—" if health is null.
- **Three CTAs**: a glowing green "Run a scan →" (to `/scans/new`), "See a sample report" (opens `/sample-report.html` in a new tab), and "See what's breaching → /matrix".
- **Scroll cue**: a bottom-centered "scroll ↓" with a gentle bob animation.

**Live or static.** Hybrid. The three hero stats are live (from `api.health()`, with `attacks.count` as fallback). The headline, pills, subhead, CTAs, and all motion are static.

**Marketing hook.** One screen frames the threat ("being jailbroken") and the product ("ROGUE finds out first") with live proof numbers that prove it's a running system, not a mockup.

**Video idea.** Hold on the hero and let the red word rotate through all four threats while the stat trio ticks up — the single most "poster-frame" shot ROGUE has.

---

## SECTION 3 — Product pitch strip ("point it → we attack → you fix")

**Name.** The Offer — "Point ROGUE at your endpoint, get a report of what breaks it."

**Where.** Landing `/`, section 2; component `frontend/src/components/product-pitch.tsx`.

**What it does / what's on screen.** A "the product" section that reframes ROGUE from a threat-intel dashboard into a buyable product. A bold headline repeats the offer, then a body line that inlines the live corpus size ("throws its continuously-harvested arsenal of **N** real attacks at it") with a `pip install rogue` code chip. Below, a three-step card strip, each card with a green top-border, a number+label badge, a headline, and body copy:
- **01 · point it** — "Give us an endpoint." (API endpoint, provider + model, or `pip install rogue` in your own CI; no agent to deploy.)
- **02 · we attack** — "ROGUE throws its arsenal." (every harvested jailbreak/injection replayed against your stack, with PAIR, persona, escalation, mutation stress tests layered on.)
- **03 · you fix** — "Get a scored report." (every breach graded by an independent judge with 95% CIs, plus remediation: the system-prompt patch or guardrail that closes each hole.)
Three CTAs follow: "Run a scan →" (`/scans/new`), "See a sample report" (new tab), and "Dashboard / quickstart" (`/scans`).

**Live or static.** Mostly static. The only live element is `nAttacks` inlined into the body sentence (from health/attacks count); falls back to the phrase "real, open-web attacks" if null.

**Marketing hook.** Turns a scary capability into a three-word purchase decision: point it, we attack, you fix.

**Video idea.** Animate the three numbered cards sliding in left-to-right as a voiceover says "point it / we attack / you fix," ending on the green "Run a scan" button glow.

---

## SECTION 4 — Bright Data spotlight + self-tuning bandit hero + sources marquee

This is one section (`sources-marquee.tsx`) containing several distinct, individually-clippable beats.

**Name (4a).** The Bright Data Spotlight — "Five products. Nineteen sources. One self-tuning budget."

**Where.** Landing `/`, section 3; component `frontend/src/components/sources-marquee.tsx`, top block.

**What it does / what's on screen.** A "powered by Bright Data" eyebrow, a headline "Five products. Nineteen sources. **One self-tuning budget.**", and a paragraph contrasting ROGUE ("fans out across the entire Bright Data product line and lets a bandit decide where to spend the next dollar") with one-platform scrapers.

**Live or static.** Static copy.

**Marketing hook.** Positions ROGUE as the maximal, intelligent Bright Data customer — every product, automatically optimized.

**Video idea.** Title-card reveal of "5 products · 19 sources · 1 self-tuning budget" as three counters.

---

**Name (4b).** The Bandit Hero Callout — "Every Bright Data dollar gets routed to the queries finding the most novel attacks."

**Where.** Same component, the large `rogue-scan-line` card immediately below the spotlight.

**What it does / what's on screen.** The cost-optimization money-shot, given full hero treatment with an animated scan-line overlay. Left column: a giant 6–7xl number — the hot arm's **mean yield** ("novel attacks per $1 BD spend") — with the hot arm's id truncated beneath, and an "in plain English" line from `plainifyYield` (e.g. "~3 novel attacks for every $1 of BD spend"). Top-right: a "hot arm = N× cold arm" ratio badge (computed from `top_arms[0].mean_yield / bottom_arms[0].mean_yield`). Right column: a "The mechanism" paragraph (an ε-greedy bandit tracks 36 candidate SERP queries, picks the top 10 by yield each harvest, explores 1 random arm) and a "Why it matters to BD" paragraph (you stop paying for dead queries; hot arms get 90% of pulls; spend sharpens daily with no manual tuning). A footer line shows live counts: `n_arms` arms · `n_warm_arms` warm · seeded date · last-live-pull date. Key terms (ε-greedy, bandit, SERP) are wrapped in `<Term>` glossary triggers.

**Live or static.** Live (from `api.banditStats()`). Degrades gracefully: if no warm arm, the hero number shows "—" and the plain-English line reads "bandit warming up — first pulls in progress"; the ratio badge only renders when both hot and cold arms have yield.

**Marketing hook.** A literal, live dollar-efficiency number — the answer to "why does ROGUE deserve a Bright Data budget?"

**Video idea.** Zoom into the giant "novel attacks per $1" number with the scan-line sweeping, then pan to the "hot arm = N× cold arm" badge — the cost-efficiency proof in one move.

---

**Name (4c).** The Three Reliability/Breadth Tiles.

**Where.** Same component, the 3-tile grid below the bandit card.

**What it does / what's on screen.** Three metric tiles: "**5 / 5** Bright Data products in use" (sub-listing MCP · SERP · Unlocker · Scraping Browser · Web Scraper, with glossary terms), "**19** open-web sources fanned out" (with inline Reddit/X/GitHub/HuggingFace/arXiv source logos), and "**2-tier** reliability with explicit fallbacks" (Scraping Browser → SERP · MCP → Unlocker · per-plugin error isolation).

**Live or static.** Static (the "5/5", "19", "2-tier" values are hardcoded copy).

**Marketing hook.** Proves breadth and resilience — ROGUE doesn't break when one product or source goes down.

**Video idea.** Three tiles snapping in with the fallback arrows animating (Scraping Browser → SERP).

---

**Name (4d).** The Live Source Roster Marquee.

**Where.** Same component, the bottom infinite-scroll strip.

**What it does / what's on screen.** A horizontally auto-scrolling marquee of all 19 sources (the list doubled so it loops seamlessly), each as a mono chip with a tint-colored glowing dot (color-coded by Bright Data product), a source logo, the source name (e.g. "Reddit · r/ChatGPTJailbreak", "X · @elder_plinius", "GitHub · L1B3RT4S"), and its "· via [product]" label. Gradient fade masks on both edges. **Pauses on hover** (and pauses when scrolled offscreen via `PausedOffscreen`) so demo viewers can read entries. A "hover to pause" hint sits above it.

**Live or static.** Static — the 19-source roster is a hardcoded constant in the component.

**Marketing hook.** The named, real sources (r/ChatGPTJailbreak, @elder_plinius, L1B3RT4S) signal ROGUE watches where attackers actually post.

**Video idea.** Let the color-coded marquee scroll, then a cursor hovers and it freezes on a recognizable source chip ("GitHub · L1B3RT4S · via SERP + Unlocker").

---

## SECTION 5 — "Aha moment": live attack ticker + mini breach-matrix (side by side)

**Name (5a).** The Live Attack Ticker — "What landed since yesterday."

**Where.** Landing `/`, section 4, left column; component `frontend/src/components/live-attack-ticker.tsx`.

**What it does / what's on screen.** A live-streaming feed of the most recent harvested attacks. Header label adapts to freshness: "freshest threats · last 48h" / "What landed since yesterday." when there's recent data, or "latest harvest · threat DB" / "The most recent attacks we've captured." when the harvest is stale (the API sets a `stale` flag when nothing new landed in the window). Renders up to 5 rows; each `TickerRow` is a tinted card with a severity dot (critical = pulsing red, high = orange, medium = yellow, low = blue), the attack title (truncated), a mono line of "family · vector · [BD PRODUCT]", and a ↗ link to the original source URL. A "live · streaming" pulsing label and an "N most-recent" count sit above. The real magic: it subscribes to the shared SSE feed (`useSseFeed`) and, on each new snapshot, **diffs incoming primitives against already-seen ids and slides genuinely new attacks in from the top with a fade-up plus a 1.5s green-glow flash** on the newest row. Has a cold-start path (seeds from the SSE snapshot if the server passed empty initial attacks) and an empty state ("// waiting for live feed... run scripts/harvest_once.py to seed").

**Live or static.** Live and real-time — this is the one element with its own persistent SSE connection, not just the 5-minute ISR cache.

**Marketing hook.** Watch a brand-new real-world jailbreak literally slide in and flash green — undeniable proof the system is breathing right now.

**Video idea.** Hold on the ticker until a new attack row slides in from the top and pulses green; freeze on the severity dot + family + source link.

---

**Name (5b).** The Mini Breach-Matrix ("your stack · at a glance").

**Where.** Landing `/`, section 4, right column; component `frontend/src/components/mini-matrix.tsx`.

**What it does / what's on screen.** A compact, label-free heat-grid preview of the full breach matrix, wrapped as a clickable link to `/matrix`. It aggregates the matrix cells to (family × config), takes the MAX any-breach-rate per cell, ranks families by heat and shows the top 8 as rows × all configs as columns. Each cell is a small square color-graded by breach rate (≥70% = pulsing critical red, ≥50% orange, ≥30% yellow, ≥10% blue, >0% faint, 0% dim outline) that **pops in with a staggered diagonal animation**, with a hover title like "jailbreak × config_x: 73%". Header shows "breach matrix · [date]" and an "open →" affordance; footer shows "N families × M configs" and a red "X% peak · N crit" summary. Empty state links to `/matrix` with a "// no breach data yet — run scripts/reproduce_once.py" note.

**Live or static.** Live (from `api.breachMatrix()`).

**Marketing hook.** A glanceable threat heatmap of "your stack" — red squares scream "you're exposed here" in under a second.

**Video idea.** The grid pops in cell-by-cell diagonally, red cells flaring last, then a cursor clicks through to the full `/matrix`.

---

## SECTION 6 — Connect via MCP (one-click IDE install)

**Name.** Connect ROGUE to Your IDE — the live, hosted MCP server.

**Where.** Landing `/`, section 5; component `frontend/src/components/mcp-connect.tsx` (under an "query it yourself" header in `page.tsx`).

**What it does / what's on screen.** A card with three action buttons plus the raw URL. "**+ Add to Cursor**" fires a `cursor://` deeplink whose config is the base64-encoded MCP server URL; "**+ Add to VS Code**" fires a `vscode:mcp/install` deeplink with url-encoded `{name,type,url}`; "**Copy MCP URL**" copies the hosted endpoint (`<api-base>/mcp/`) to the clipboard and flips to "✓ copied" for 1.6s. Below, the live MCP URL is shown in green mono text, and instructions explain the Claude Desktop path (Settings → Connectors → Add custom connector → paste URL) and the Cursor/VS Code one-click path — "No clone, no Python, no JSON editing — it's a hosted, read-only MCP server with 5 query tools."

**Live or static.** The buttons/URL are static config (derived from the API base env var), but they connect to a genuinely live, hosted MCP server — clicking truly adds a working `rogue` server to the IDE.

**Marketing hook.** ROGUE's headline differentiator: it isn't just a dashboard, it's a tool your AI assistant can query — one click and Claude/Cursor/Windsurf knows what's breaching today.

**Video idea.** Click "+ Add to Cursor", show Cursor open and prompt to add the `rogue` server, then ask Claude "what's the worst attack against a model like you?" and show it answering from the live DB.

---

## SECTION 7 — How ROGUE thinks (3-loop narrative: harvest → reproduce → defend)

**Name.** How ROGUE Thinks — "Three loops, one outcome: a threat brief that's true today."

**Where.** Landing `/`, section 6; component `frontend/src/components/how-rogue-thinks.tsx`.

**What it does / what's on screen.** A three-card pipeline narrative, each card with a color-coded top border, a number+label badge, a live metric in the corner, a headline, and body copy with inline glossary terms:
- **01 · harvest** (green): metric = 19 open-web sources. "Stream the latest jailbreaks." Body inlines Reddit/X/GitHub/Hugging Face/arXiv source logos and "fanned out through 5 Bright Data products. New attacks land in the DB within minutes."
- **02 · reproduce** (cyan): metric = `n_configs` deployment configs. "Run each one against your stack." Body names the 5-config trial panel and PAIR/persona/escalation/mutation stress tests.
- **03 · defend** (red): metric = `n_breaches` trials judged. "Ship a brief that ends an argument." Body names Markdown/JSON/Slack/MCP outputs, 95% bootstrap CIs (glossary term), and "Today's diff vs yesterday's, automatically."
On desktop, a floating annotation "→ N primitives" hovers between steps 1 and 2 to suggest the chain. Intro paragraph: "Every dot on the dashboard traces back to a real attack that ran against a real config and got judged by a real LLM. No synthetic benchmarks."

**Live or static.** Hybrid — the three corner metrics (sources count is constant 19; configs and breaches are live from health) and the floating primitives count are live; the rest is static copy.

**Marketing hook.** The mental model in one glance: harvest → reproduce → defend, with real numbers proving each loop runs.

**Video idea.** Three cards light up green→cyan→red in sequence with their live metrics counting up and the "→ N primitives" annotation appearing between them.

---

## SECTION 8 — Augmentation Showcase (the five §10.7 stress-test hero cards)

**Name.** The Five Stress Tests — "ROGUE doesn't just collect attacks. It evolves them."

**Where.** Landing `/`, section 7; component `frontend/src/components/augmentation-showcase.tsx` (copy + accent colors from `augmentation-meta.tsx`, mini-charts from `spark.tsx`, plain-English from `plain-numbers.ts`).

**What it does / what's on screen.** A section header ("§10.7 · stress tests") then five large color-accented cards (bandit, persona, escalation, mutation, stubbornness — the last spanning full width). Every card has: a color-matched eyebrow + a plain-English "what it is" subhead (canonical copy from `AUGMENTATION_COPY`); a **● live / ○ no data** badge so viewers know if it's real numbers or just the explanation; one giant hero stat; a small `SparkBars` mini-chart; an "in plain English" translation line; and a "why it matters" footer. The five hero stats and their plain-English translators:
- **Bandit** — hero = hot arm's mean yield ("novel attacks / $"), chart = top-5 arms by yield, plain via `plainifyYield`.
- **Persona** — hero = worst config's max breach-rate Δ, shown as "+Npp" *or* honestly as "no lift" / "every config resisted the persona wrap" when Logical Appeal raised nothing; chart = per-config max Δ; plain via `plainifyPP`.
- **Escalation** — hero = worst config's Δ ("lift from turn 1 → turn 3"); chart = per-config Δ; plain via `plainifyPP`.
- **Mutation** — hero = worst config's pattern-matching score ("% of 'defended' attacks leaked on paraphrase"); chart = per-config score; plain via `plainifyPattern`.
- **Stubbornness** (full width) — hero = min avg-iters-to-breach ("iterations to crack the easiest config"); chart = refinement-type distribution; plain via `plainifyIters`.
Cards with no data show "—" and "// chart unlocks when the first batch lands".

**Live or static.** Live (all five from their respective `*Stats()` endpoints); the eyebrows/subheads/why-it-matters copy is static.

**Marketing hook.** ROGUE evolves a single harvested jailbreak into the attack a real adversary would mount — and each evolution gets a hard number against your stack.

**Video idea.** Scroll through the five cards letting each `SparkBars` chart fill left-to-right and the "in plain English" line type in beneath each hero number; end on the full-width stubbornness card.

---

## SECTION 9 — Augmentation Lab (the interactive "play with it" demo)

**Name.** The Stress-Test Lab — "Pick a config. Toggle attacks. Watch it bend."

**Where.** Landing `/`, section 8; component `frontend/src/components/augmentation-lab.tsx` (a client component — the one fully interactive surface on the landing page).

**What it does / what's on screen.** The lab the viewer actually plays with. The user:
1. **Picks a target deployment** from a row of config buttons (each shows a provider logo + the config name with the "Acme · " prefix stripped); the active one glows green.
2. **Toggles up to four stress tests** via switch tiles — **Persona wrap** (PAP persuasion), **Multi-turn** (Crescendo escalation), **Mutation** (AutoDAN paraphrase), **PAIR refine** (iterative attacker). Each tile has a hover/`title` micro-explainer of what that technique does, and lights up in its accent color with a soft glow when on.
3. **Watches the estimated breach rate animate.** A horizontal `BreachBar` stacks segments: a baseline segment (chosen in preference order from persona/escalation baseline rate, or `1 − never_breach_rate` from PAIR data) plus one accent-colored segment per enabled toggle equal to that config's observed Δ (mutation is half-weighted as "not directly comparable"; PAIR credits eventual-breach beyond baseline; total capped at 100% and turns red at ≥70%). A header reads "baseline X% → Y%". Below the bar: a plain-English translation of the resulting rate via `plainifyRate` (e.g. "2 out of 3 attacks breach (up from 1 in 3)"), and an ingredient legend listing each active toggle with its "+Npp" contribution and color swatch. The copy is explicit that this is a directionally-honest **upper-bound estimate**, not a perfect simulation, using "real numbers from your sweep". Empty state ("// the interactive lab unlocks once at least one stress-test A/B has data") when no config data exists.

**Live or static.** Live data, interactive math. Configs, baselines, and per-toggle deltas come from the four `*Stats()` endpoints; the stacking arithmetic runs client-side in real time as the user toggles.

**Marketing hook.** The viewer becomes the attacker — flip switches and physically watch a real deployment's breach rate climb from baseline into the red.

**Video idea.** Cursor selects a config, flips Persona → Escalation → PAIR one at a time, and the stacked bar grows segment by segment past 70% into red, with the "in plain English" line updating to "4 out of 5 attacks breach."

---

## SECTION 10 — Deep-dive links (three views on the same truth)

**Name.** Three Views On The Same Truth — /feed, /matrix, /brief.

**Where.** Landing `/`, section 9 (final); inline `PageLink` cards in `app/page.tsx`.

**What it does / what's on screen.** Three linked cards under "go deeper": **Live Feed** (`/feed` — newest attacks with the 5-stress-test sidebar; click a row for full payload + breach trail + ▶ play replay), **Breach Matrix** (`/matrix` — 14 families × 5 configs, click red cells for the exact cracking prompt with 95% CIs), and **Threat Brief** (`/brief` — today's CISO-readable diff vs yesterday, Markdown + JSON exports). Each card's path turns green and lifts on hover.

**Live or static.** Static copy/links (the destination pages are live; these cards are navigation).

**Marketing hook.** One dataset, three audiences — analyst (feed), engineer (matrix), executive (brief).

**Video idea.** Three cards fan in; cursor hovers each as its path glows green, teasing the three destination surfaces.

---

# THE FIVE INTELLIGENCE WIDGETS ("how ROGUE thinks" demos)

These render in the right sidebar of `/feed` (`frontend/src/app/feed/page.tsx`), not on the landing page. Each is the deep, per-config version of one Augmentation-Showcase card, sharing the same data source and the same canonical copy via `AUGMENTATION_COPY`. Every widget opens with an `ExplainerHeader` — a color-accented eyebrow, a one-line subhead, and a **(?) popover** that reveals "what this is" + "why it matters" so a non-technical CISO can decode the tile in under five seconds. All five render multi-state empty/seed messages (with the exact `uv run` seed command) when data is missing, so they're never blank.

---

## WIDGET 1 — Bandit (cost-efficiency intelligence)

**Name.** ε-Greedy Bandit — "which queries earn their Bright Data dollar."

**Where.** `/feed` sidebar; component `frontend/src/components/bandit-widget.tsx`.

**What it does / what's on screen.** A scan-line card listing the **top 3 arms** and **bottom 3 arms** (each row = a SERP query id + its "N/$" mean yield). **Each row has a pure-CSS hover-card** that opens below it with the full per-arm breakdown: pulls, novel found, BD spend (to 4 decimals), yield, a warm/cold badge, and a note explaining the next pull's ε-greedy bias ("90% pick the hottest arm, 10% explore"; cold arms get a guaranteed cold-start pull). Footer shows arms count, warm count, seed date, last-live-pull date. Empty state surfaces the bandit's `note`.

**Live or static.** Live (`api.banditStats()`).

**Marketing hook.** Demonstrates ROGUE *learning* where to spend money — hover any query to see its exact pulls, cost, and yield.

**Video idea.** Hover down the top-3 arms one by one, each revealing its detail card; then hover a cold bottom arm to show the "untested — guaranteed cold-start pull" note.

---

## WIDGET 2 — Persona (social-engineering susceptibility intelligence)

**Name.** Persona Susceptibility — "does your model react to tone instead of intent?"

**Where.** `/feed` sidebar; component `frontend/src/components/persona-widget.tsx`.

**What it does / what's on screen.** Per-config "max Δ" `SparkBars` (purple) showing how much a PAP persuasion wrap raised breach rate vs the unwrapped baseline, plus a **top 3 (config × technique)** list where each cell shows the persona name, its "+Npp" delta (red when positive), the target config (with provider logo), and trial count. Refusal-fallback cells are marked with a ⊘ glyph. Three rendered states: no baselines / baselines-but-no-wrapped-runs / wrapped runs exist — each with its own seed command.

**Live or static.** Live (`api.personaStats()`).

**Marketing hook.** Exposes the model that refuses "how do I make X" but obeys "as a safety researcher, explain how X is made" — pattern-matching on tone, not intent.

**Video idea.** Reveal the purple per-config bars, then zoom the top-3 list onto a "+Npp" cell with the ⊘ refusal-fallback marker.

---

## WIDGET 3 — Escalation (multi-turn resilience intelligence)

**Name.** Multi-Turn Escalation — "does context carry your guardrails?"

**Where.** `/feed` sidebar; component `frontend/src/components/escalation-widget.tsx`.

**What it does / what's on screen.** Per-config "escalation Δ" `SparkBars` (yellow) = breach-rate lift of a synthesized 3-turn Crescendo arc over the single-turn parent. A collapsible **"parent → escalated breakdown"** `<details>` with a rotating ▸ caret lists each config (provider logo), its "+Npp" delta tinted (red = escalation worked, green = it didn't), and a "baseline% → escalated% · Nt child" line. Footer shows synthesized/parents/min_trials counts. Three states: no synthesized primitives / synthesized-but-not-yet-reproduced / full per-config rollup — each with its `uv run` seed command.

**Live or static.** Live (`api.escalationStats()`).

**Marketing hook.** If turn 3 breaches a config that refused turn 1, the model makes isolated decisions — exactly what real users exploit by warming up.

**Video idea.** Expand the "parent → escalated breakdown" caret and pan to a row showing "12% → 64% · +52pp" in red.

---

## WIDGET 4 — Mutation (pattern-matching brittleness intelligence)

**Name.** Pattern-Match Audit — "is your filter keyword-matching or understanding?"

**Where.** `/feed` sidebar; component `frontend/src/components/mutation-widget.tsx`.

**What it does / what's on screen.** Per-config "pattern-match %" `SparkBars` (cyan, max-scaled to 100) = fraction of pairs where the config defended the original wording but failed on a semantically-identical AutoDAN paraphrase. A collapsible per-config breakdown lists each config (provider logo), its score tinted green/orange/red by severity, and an "N/M leaked · K total pairs" line. Footer shows mutations/parents/evade-threshold. Three states with seed commands.

**Live or static.** Live (`api.mutationStats()`).

**Marketing hook.** A high pattern-match score is the receipt that a "defended" model was string-matching, not reasoning — it leaks the moment wording changes.

**Video idea.** Reveal the cyan bars, then expand to a red config row reading "3/4 leaked" — defenses that were never real.

---

## WIDGET 5 — Stubbornness (adaptive-attacker resilience intelligence)

**Name.** PAIR Stubbornness — "how long does your weakest config hold against an adaptive attacker?"

**Where.** `/feed` sidebar; component `frontend/src/components/stubbornness-widget.tsx`.

**What it does / what's on screen.** A per-config "avg iters" list where each row shows the config, its average iterations-to-breach tinted green (≥2, robust) / orange (≥1) / red (<1, gives up fast), and an "N/M breached · $cost" attacker-spend line. Below, a "refinement strategies fired" `SparkBars` (red) histogram of which attacker tactics the PAIR LLM chose most across all steps. Footer shows cells/breached/steps totals. Three states (no PAIR runs / runs-but-none-breached / breaches recorded) with seed commands.

**Live or static.** Live (`api.stubbornnessStats()`).

**Marketing hook.** Most safety evals measure single-shot refusal; this measures resilience against an LLM that keeps refining until it breaks you — and shows what it cost the attacker.

**Video idea.** Pan the per-config avg-iters list (green robust → red "0.8 iters" easy crack), then reveal the red refinement-strategy histogram beneath.

---

# SUPPORTING / SHARED PRIMITIVES (used across the surfaces above)

These aren't standalone sections but are reusable interaction primitives a designer will see repeatedly and may want to feature.

**Glossary `<Term>` tooltips** (`frontend/src/components/glossary.tsx`). Any jargon word (PAIR, PAP, AutoDAN, MCP, SERP, ε-greedy, Crescendo, CI, pp, Δ, primitive, vector, family, deployment config, bandit, CISO, LLM, SSE, A/B, mutation) renders with a dotted green underline and a small ⓘ. **Hover reveals** a tooltip with the expansion + a plain-English definition; **click pins** it open; click-outside dismisses. Used throughout the Bright Data spotlight, How-ROGUE-Thinks, and the augmentation copy. Marketing hook: a non-technical CISO can read every line without bouncing on a single acronym. Video idea: hover "ε-greedy" and "PAIR" to pop their plain-English cards.

**`ExplainerHeader` (?) popover** (`frontend/src/components/explainer.tsx`). The shared "what this is / why it matters" header on every intelligence widget (compact mode = eyebrow + subhead + (?) toggle) and the showcase cards (hero mode = eyebrow + headline + body). Marketing hook: instant self-documentation on every tile.

**`SparkBars` mini-charts** (`frontend/src/components/spark.tsx`). The pure-SVG horizontal bar chart (no charting library) used in the showcase and four of the five widgets; bars grow with a 700ms fill transition on first paint. Video idea: any chart filling in is a clean micro-beat.

**`CountUp` animated counter** (`frontend/src/components/count-up.tsx`). An ease-out-cubic count-up from 0 used on `/feed` KPI numbers (not on the landing hero — the hero uses static `toLocaleString`). Video idea: a stat snapping up fast then easing into its final value.

**`PausedOffscreen` performance wrapper** (`frontend/src/components/paused-offscreen.tsx`). Pauses CSS animations (the hero, the sources marquee) when scrolled offscreen via an IntersectionObserver — not a visible feature, but why the page stays smooth during a long scroll-through recording.

---

# DORMANT ASSETS (built, currently not rendered anywhere)

These two components exist in the codebase but are imported by nothing — they're real, revivable capabilities, not live surfaces. Flagged for completeness.

**`PipelineFlow` — animated SVG pipeline** (`frontend/src/components/pipeline-flow.tsx`). A pure-SVG + SMIL four-stage flow diagram: [19 sources] → [harvest/primitives] → [reproduce/configs] → [judge/breaches], with traveling pulse dots animating along dashed connectors and pulsing glow rings on each node, each node showing its live count. Built to take the four health metrics as props. **Not currently mounted on any page** (the landing page uses the card-based `HowRogueThinks` narrative instead). Marketing hook / video idea: if revived, the pulse-dots flowing source→harvest→reproduce→judge is the most literal "this is a pipeline" animation ROGUE has.

**`AugmentationHeadlines` — 4-tile impact strip** (`frontend/src/components/augmentation-headlines.tsx`). A four-tile "augmentation impact · today" KPI strip (persona / escalation / mutation / stubbornness) that deliberately surfaces the *worst* config per technique so the numbers read alarming, with red "alarm" tone above thresholds. **Imported by nothing** (the similar `AugmentationStrip` is the one used on `/feed`). Revivable as a punchy "worst-case at a glance" banner.
