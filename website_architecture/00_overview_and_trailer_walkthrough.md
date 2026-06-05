# ROGUE — Overview & Trailer Walkthrough

A vivid, experiential map of the live ROGUE website — written so it can be used as the basis for a trailer or demo video. This is the "what is this site, and what does it feel like to move through it" document. Live at `https://rogue-eosin.vercel.app`.

---

## 1. What is this

ROGUE is a continuous open-web LLM red-team. It watches the open web — Reddit, X, GitHub, Hugging Face, arXiv, leak mirrors — for every new jailbreak and prompt-injection the moment it gets published, harvests it through all five Bright Data products, then reproduces each attack against real deployment configurations (a model × a system prompt × a tool set) and has an independent LLM judge grade every trial. The output is a daily, CISO-readable threat brief that says, in plain numbers, what is breaking right now. And it is also a product you point at your own model: give ROGUE an endpoint (or `pip install rogue`), and it throws its continuously-harvested arsenal of real attacks at your stack and hands you back a scored report — which jailbreaks break you, with what confidence, and how to fix them. On top of that, ROGUE exposes its own MCP server, so Claude Desktop, Cursor, or Windsurf can query the live threat database directly.

In one sentence: **ROGUE is the thing that knows your LLM is being jailbroken right now — and lets you prove it on your own model in five minutes.**

---

## 2. The visual language

The whole site speaks one consistent dialect. Match it and any trailer reads as "the same product."

- **Near-black, blue-tinted background.** Not pure black — a deep blue-black (`#050508` / `oklch(0.06 ...)`). Everything floats on this.
- **The grid.** A faint terminal-green grid (`60px` cells, 4%-opacity green lines) is laid over the entire page (`.bg-rogue-grid`). It is deliberately *static* (it used to drift; the drift was killed for performance and reads identically). It says "instrument panel / war room."
- **The spotlight.** A soft green radial glow bleeds down from the top-center of every page (`.bg-rogue-spotlight`), giving depth — the page looks lit from above.
- **Two signature accent colors, used with discipline:**
  - **Terminal green `#00ff88`** = alive, OK, harvested, signature. The "live" pulse dot, CTAs, headings' eyebrows, the scrollbar.
  - **Alert red `#ff003c`** = critical breach, danger. Worst-attacker callouts, breached cells, the "jailbroken" word.
  - Plus **orange `#ff6b00`** for the HIGH tier and a few accent hues (purple/amber/cyan/red) that color-code the five augmentation widgets so they read as distinct.
- **Monospace everywhere it matters.** Geist Mono for eyebrows, route labels (`/matrix`, `/feed`), stat capsules, terminal readouts, numbers (`tabular-nums` so digits don't jitter). The body is a clean sans; the *texture* is terminal.
- **Motion vocabulary** (all CSS keyframes, defined in `globals.css`):
  - `rogue-reveal` — big hero entrance: fade up + un-blur. Used on hero lines and intro panels.
  - `rogue-fade-up` — the workhorse: subtle 8px rise + fade, staggered via `animationDelay`. Every section lands this way.
  - `rogue-pulse-green` / `rogue-pulse-critical` — slow 2.5s heartbeat on "live" dots and CRITICAL elements.
  - `rogue-word-rotator` — the hero's vertical word-swap (jailbroken → prompt-injected → role-played → escalated → jailbroken).
  - `rogue-cell-pop` / `rogue-cell-pulse-red` — matrix cells cascade in, and red cells pulse.
  - `rogue-marquee` — the horizontal sources strip drifts left.
  - `rogue-count-up` — numbers tick up from 0 on entrance (`<CountUp />`).
  - `rogue-caret-blink` — terminal cursor `▮`.
  - `rogue-card` hover — cards lift 2px and gain a green border + glow (red variant for critical).
  - `rogue-scan-line` — a green sweep crossing high-attention elements.
- **Shape & finish.** Rounded cards on translucent `card/40` backgrounds, thin borders, accent-colored left-borders (3px) on the augmentation tiles, glowing nav underlines. Reduced-motion is honored (loops stop) and the terminal-green scrollbar is a nice detail for close-ups.

Brand summary for a colorist: **deep blue-black, faint green grid, top spotlight, terminal-green "alive" accents, blood-red "breach" accents, monospace numerals, everything breathing on a slow pulse.**

---

## 3. Screen-by-screen trailer walkthrough (shot list)

Filmed in order, this is the cinematic journey. Each scene gives the route, what's on screen, the on-screen copy/numbers that pop, and a suggested voiceover/caption beat.

### Scene 0 — The 16-second intro overlay (`/` on first visit)
**Route:** `/` (component `intro-overlay.tsx`; force-replay with `?intro`)
**On screen:** A full-screen takeover that auto-plays four panels, 4s each, over a drifting gradient-mesh + grid. A progress bar and `01 / 04 · 16s intro` tick along the bottom; a "skip intro →" button sits top-right.
- **Panel 01 · the problem** (red tint): *"Your AI is being **jailbroken** right now."* Beside it, a live-looking feed of fake-but-realistic attacks (DAN 2024.12, Crescendo 3-turn, L1B3RT4S system-prompt leak) each with a pulsing red dot and "1h ago."
- **Panel 02 · the harvest** (green tint): *"ROGUE watches the open web **continuously**."* Side visual: the 5 Bright Data product chips + the 19 source chips lighting up one by one.
- **Panel 03 · the test** (cyan tint): *"Every attack ran against **your exact stack**."* Side visual: a 5×5 grid of cells popping in — red/orange/green/empty (each cell = one attack × one config × one trial).
- **Panel 04 · the brief** (yellow tint): *"And ships a brief your **CISO can read**."* Side visual: a mock threat brief — "3 new CRITICAL," a PAIR-refined DAN with a 95% CI, and ↓.md / ↓.json / MCP → Claude Desktop chips.
**Money shot:** the word "jailbroken" landing in red on panel 1.
**VO/caption:** "Every day, someone publishes a new way to break your AI. ROGUE finds it first — and tells you what it means." *(This overlay IS a pre-built 16-second trailer; the panels are essentially storyboard frames already.)*

### Scene 1 — The cinematic hero (`/`)
**Route:** `/` (component `cinematic-hero.tsx`) — fills ~88vh, a drifting mesh-gradient (green/red/cyan radials) with a lighter grid on top.
**On screen:** Two pills top-left — a pulsing green `live · streaming the open web` and `powered by Bright Data · 5 / 5 products · cost-optimized`. Then the giant headline.
**On-screen copy that pops:**
> **Your LLM is being** *[jailbroken. / prompt-injected. / role-played. / escalated.]* — in red, the word vertically swapping —
> **ROGUE finds out before your users do.**

Below it: "Built on **all 5 Bright Data products**. Harvests every new jailbreak from **19 open-web sources**, reproduces each one against your stack, and ships a daily brief — on a budget the bandit auto-tunes for you." Then the product one-liner: "**Point ROGUE at your LLM endpoint.** Get a report of which jailbreaks break it — and how to fix them."
**Hero stat trio (the "this is alive" proof, live numbers from the API):** `N attacks tracked` · `N trials judged` · `N deployments tested` — green, counting in.
**Three CTAs:** a glowing green **`Run a scan →`**, a `See a sample report` (opens `/sample-report.html`), and `See what's breaching → /matrix`. A bouncing "scroll ↓" cue at the bottom.
**Money shot:** the red word cycling under "Your LLM is being…", with the green stat trio ticking up beneath.
**VO/caption:** "Your LLM is being jailbroken — right now. ROGUE finds out before your users do."

### Scene 2 — The product pitch (`/`, just below the hero)
**Route:** `/` (component `product-pitch.tsx`)
**On screen:** Eyebrow `the product`, then the offer in a big headline: *"Point ROGUE at your LLM endpoint. Get a report of which jailbreaks break it — and how to fix them."* A line offering an endpoint, a provider+model, or `pip install rogue`. Then a clean **3-step strip** (green top-borders): **01 · point it** ("Give us an endpoint."), **02 · we attack** ("ROGUE throws its arsenal." — PAIR, persona, escalation, mutation), **03 · you fix** ("Get a scored report." — every breach graded with 95% CIs + remediation). CTAs repeat: `Run a scan →`, `See a sample report`, `Dashboard / quickstart`.
**Money shot:** the `pip install rogue` snippet glowing green, then the 01 → 02 → 03 strip.
**VO/caption:** "No harness to write. No corpus to curate. Point it, we attack, you fix."

### Scene 3 — The proof that the arsenal is real (`/`, the "aha" row)
**Route:** `/` (sources marquee + the live ticker + mini-matrix)
**On screen:** First the **sources marquee** — a horizontally-drifting strip of the 19 sources × 5 Bright Data products. Then a two-column "aha moment": on the left a pulsing-green `freshest threats · last 48h` with the **live attack ticker** ("Every row below is an attack someone published on the open web in the last 2 days"); on the right a `your stack · at a glance` **mini-matrix** preview.
**Money shot:** the ticker scrolling real, recent, dated attacks.
**VO/caption:** "These aren't synthetic benchmarks. Every one of these landed on the open web in the last 48 hours."

### Scene 4 — Connect it to your IDE (`/`, MCP)
**Route:** `/` (component `mcp-connect.tsx`)
**On screen:** Eyebrow `query it yourself`, headline "Connect ROGUE to your IDE." — "ROGUE is also a live MCP server — ask Claude Desktop, Cursor, or Windsurf about the threat DB directly. One click connects it."
**VO/caption:** "It's also an MCP server — your coding assistant can ask it what's breaching today."

### Scene 5 — How ROGUE thinks (`/`)
**Route:** `/` (component `how-rogue-thinks.tsx`)
**On screen:** Headline "Three loops, one outcome: a threat brief that's true today." Three accent-bordered cards: **01 · harvest** (green, "Stream the latest jailbreaks," with Reddit/X/GitHub/HF/arXiv logos), **02 · reproduce** (cyan, "Run each one against your stack," PAIR + stress tests), **03 · defend** (red, "Ship a brief that ends an argument," 95% CIs + MCP). A floating `→ N primitives` annotation bridges steps 1 and 2.
**Money shot:** the harvest → reproduce → defend chain reading left to right in green → cyan → red.
**VO/caption:** "Harvest. Reproduce. Defend. Every dot traces back to a real attack, a real config, a real judge."

### Scene 6 — The augmentation showcase + lab (`/`)
**Route:** `/` (`augmentation-showcase.tsx` + interactive `augmentation-lab.tsx`)
**On screen:** Five hero-stat cards (the §10.7 results — persona / escalation / mutation / PAIR / stubbornness), then an **interactive lab**: pick a config, toggle augmentations on, and watch the estimated breach-rate bar stack and re-fill. This is the "research credibility" beat.
**Money shot:** toggling a stress test and watching the breach-rate bar jump.
**VO/caption:** "Layer on persona wraps, multi-turn escalation, mutation — and watch the breach rate climb."

### Scene 7 — The live threat matrix lighting up (`/matrix`)
**Route:** `/matrix` (page + `matrix-heatmap.tsx` + `matrix-drawer.tsx`)
**On screen:** Header `/matrix · {date}`, title **Breach Matrix**, subtitle "Max any-breach rate per attack family × deployment config. **N attacks** tested against **N configs** (N cells total). Click any red cell to see the prompt that breached it." Two stat capsules: **Worst cell** (e.g. `100%`) and **Critical cells** (count breaching 70%+). A pulsing **worst attacker today** callout card (red) — e.g. Pliny's X jailbreak — naming the family · vector · the config it breached and at what %. Then the **heatmap itself**: a grid of family × config cells cascading in (`cell-pop`), colored on a blue→yellow→orange→red heat scale, the red 70–100% cells pulsing. A SCOPE × ATTACKER 2×2 toggle (this-run/all-time × baseline/+augmentations). A legend chip row at the bottom.
**The interaction money shot:** hover a red cell (it warms a prefetch), **click it**, and a **drawer slides in from the right** showing the exact attack — title, family/vector, the payload template, source links, and the per-config breach breakdown (n_full / n_partial / n_refused / n_evaded) with 95% CIs.
**VO/caption:** "This is what's breaking, today. Click any red cell — and there's the exact prompt that cracked it."

### Scene 8 — The live feed / war room (`/feed`)
**Route:** `/feed` (page + `feed-stream.tsx` + the augmentation sidebar)
**On screen:** A pulsing `/feed · live` header, a 4-tile KPI strip (Attacks 7d / New breaches today / Configs tested / Total breach trials — the breach tile pulses red if non-zero), the §10.7 augmentation strip, then a 3-column war room: a left intel ribbon, a center expandable attack list (click a row → full payload + breach trail, with a ▶ play **replay**), and a right sidebar of five color-coded augmentation widgets (bandit/persona/escalation/mutation/stubbornness) + a system-status readout (db up, primitives, breaches).
**Money shot:** expanding an attack row to reveal its real payload, then hitting ▶ replay.
**VO/caption:** "The war room: newest attacks off the open web, each one you can open, read, and replay."

### Scene 9 — The threat brief (`/brief`)
**Route:** `/brief` (page + `brief-exec-snapshot.tsx` + `brief-markdown.tsx`)
**On screen:** `/brief · {date}`, title **Threat Brief**, "Daily snapshot · regenerable from the breach matrix on demand," with **Markdown / JSON download** buttons. An executive snapshot (net Δ vs yesterday, top-3 worst new attackers, a recommended-action line), four tier chips (**CRITICAL** / HIGH / MEDIUM / LOW, the red one pulsing), then the full CISO-readable markdown report.
**Money shot:** the CRITICAL chip with a non-zero count, then the download buttons — "the artifact you'd actually send."
**VO/caption:** "And every day, the one-page brief that ends the argument — the diff vs yesterday, ready to send."

### Scene 10 — The research telemetry (`/analytics`)
**Route:** `/analytics` (reads a published `/analytics.json` snapshot)
**On screen:** `/analytics`, title **Telemetry**. Recharts visualizations over the breach matrix: capability stats (strategies, graduated, cost/graduation, validity rate, overall breach, total spend), a discovery source-yield bar chart, a growth-by-month chart, an interactive **family × model breach heatmap** (filter ≥30%/≥60%, click rows to focus, model-vulnerability ranking bars), and the §10.10 allocation/research metrics.
**VO/caption:** "Under the hood: what graduates, how cheaply, which model is most exposed — the research layer." *(This is the deep-credibility scene; optional for a short trailer, strong for an investor cut.)*

### Scene 11 — Run it on your own model: sign in (`/sign-in`)
**Route:** `/sign-in` (the product gate)
**On screen:** A clean, minimal card: "Sign in to ROGUE," a single `rk_live_…` API-key field (stored only in a server-side httpOnly cookie), a "Request access" mailto. This is the pivot from "look at the intel" to "now do it to yours."
**VO/caption:** "Want it on your model? One key, and you're in."

### Scene 12 — Launch a scan (`/scans/new`)
**Route:** `/scans/new`
**On screen:** "New scan — Point ROGUE at a model and pick an attack pack." Toggle **Known provider** (openai / anthropic / openrouter / groq / gemini) vs **Custom endpoint** (an OpenAI-compatible base URL), an optional model + target API key, an **attack-corpus** choice — **Curated pack** / **Full repertoire** / **Full ladder** (the deepest, most expensive mode) — pack + max-tests, then a **`Launch scan`** button.
**Money shot:** the moment of choosing your provider and clicking Launch.
**VO/caption:** "Point it at your endpoint. Pick how hard to hit it. Launch."

### Scene 13 — Watch it run, live (`/scans/{scanId}`)
**Route:** `/scans/[scanId]` (live poller `scan-progress.tsx`, polls every ~2s)
**On screen:** A status badge + risk badge, then the live progress card:
> `████████ 67%   32/50 tests complete   Current attack: Crescendo`

A determinate green bar, a running readout — **"N breaches so far"** (turns red as breaches land), **"~$X spent (estimate)"**, **"~N min remaining"** — a Cancel button, and on completion a **`View report →`** link. The breach counter climbing in real time is the drama.
**Money shot:** the progress bar advancing while "breaches so far" ticks up from 0 to red, "Current attack: Crescendo" updating live.
**VO/caption:** "Watch it work — every test, every breach, live."

### Scene 14 — The report lands (`/scans/{scanId}/report`)
**Route:** `/scans/[scanId]/report`
**On screen:** **The RiskHeadline is the hero of this screen** — a giant `NN /100` risk score, color-banded, with a severity pill (critical/high/medium/low) and a `Top attack` callout; a methodology caption underneath. Then a KPI row (Tests / Breaches / Breach rate / Cost), a **worst-first findings table** — each card shows severity + vector, "breached 4/5 trials · 80%," the attack title, family·technique, and expandable **Example attack** / **Model response** / **Remediation** (the actual system-prompt patch). Top-right: **HTML / PDF / JSON export** buttons. A recommendations panel closes it.
**Money shot:** the big `NN/100` landing with its color band, then the worst finding expanding to reveal the real prompt → the real model response → the fix. Then the **PDF export** click.
**VO/caption:** "And here's your report. One score. Every breach, with the exact prompt, the model's own words, and how to close it. Export the PDF, send it up the chain."

### Scene 15 — The scans dashboard (`/scans`) [bookend / B-roll]
**Route:** `/scans`
**On screen:** "Scans — Every red-team scan your org has launched, newest first." A clean table: scan id, target, status badge, breaches (red if >0), score badge, created time. A `New scan` button. Good as an establishing or closing shot of "an ongoing security program."
**VO/caption:** "Every scan, every model, one place — your standing red-team."

---

## 4. The two arcs

The site deliberately tells two intertwined stories. Knowing which page serves which arc keeps a trailer's structure clean.

### Arc A — The threat-intelligence story ("your LLM is being jailbroken right now, here's proof")
This is the *credibility and urgency* arc: a live, continuously-updated breach matrix proving the threat is real, fresh, and measured.
- **Pages:** the intro overlay, the hero, the freshest-threats ticker, **`/matrix`** (the centerpiece — the breach matrix lighting up, click-through to the exact prompt), **`/feed`** (the war room), **`/brief`** (the daily diff), **`/analytics`** (the research telemetry), and the MCP connect block.
- **Emotional job:** "This is happening, it's measured, and we can show you the receipts."

### Arc B — The product story (the customer scans their own endpoint → gets a scored report)
This is the *self-serve value* arc: turn the intel engine on the viewer's own model.
- **Pages:** the product-pitch strip, **`/sign-in`**, **`/scans/new`** (point at your endpoint), **`/scans/{scanId}`** (watch it run live), **`/scans/{scanId}/report`** (the scored report with remediation + PDF), and **`/scans`** (the standing program). The `Run a scan →` and `See a sample report` CTAs are the bridges from Arc A into Arc B, repeated on the hero and the pitch.
- **Emotional job:** "And you can do this — to your model — in five minutes."

The public threat-intel pages (Arc A) are the proof; the authenticated scan flow (Arc B) is the purchase. The hero and product-pitch CTAs are the seam that stitches them together.

---

## 5. The emotional / sales throughline

The narrative payoff is a single move: **research credibility → personal exposure → instant action.**

1. **Alarm.** "Your LLM is being jailbroken — right now." The red rotating word, the live ticker of attacks posted hours ago. The viewer feels exposed.
2. **Proof.** The breach matrix lights up and you click a red cell to see the *exact prompt* that cracked a real config, with confidence intervals. This isn't fear-mongering — it's measured, judged, receipted. The viewer trusts it.
3. **Pivot.** "And you can run it on your own model." The hero's `Run a scan →` and the product-pitch strip reframe the whole intelligence engine as a tool the viewer can aim at themselves.
4. **Payoff.** Sign in, point at an endpoint, watch the breach counter climb live, and land on a single `NN/100` risk score with every breach, the model's own incriminating words, the remediation, and a PDF you can send to your CISO.

The throughline in one breath: **"Your LLM is being jailbroken right now — here's the proof, measured and dated — and you can run the exact same red-team on your own model, and have a scored report in your hands, in five minutes."** Research authority earns the trust; the five-minute scan converts it.

---

## Section list

1. What is this
2. The visual language
3. Screen-by-screen trailer walkthrough (shot list) — Scenes 0–15
4. The two arcs (A: threat-intelligence / B: product)
5. The emotional / sales throughline
