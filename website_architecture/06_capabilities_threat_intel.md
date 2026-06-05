# 06 — Capabilities catalog: the THREAT-INTELLIGENCE surfaces

This is the exhaustive film-shot list for ROGUE's four threat-intelligence surfaces — `/matrix`, `/feed`, `/brief`, `/analytics` — plus the cross-cutting glossary/explainer system that overlays all of them. Every distinct thing a designer could point a camera at is catalogued below as a separate entry, framed as a marketable beat. If it renders, animates, toggles, opens, streams, downloads, or reacts to a cursor, it has an entry here.

The through-line for a trailer: ROGUE harvests real jailbreaks off the open web, fires them at customer model configs, has an independent judge grade the transcripts, and surfaces the result four ways — a heatmap you can drill into down to the exact breaching prompt (`/matrix`), a live forensic feed (`/feed`), a CISO-readable daily brief you can export (`/brief`), and a research telemetry layer (`/analytics`). Every number on screen carries a confidence interval and a provenance link back to the open-web source. Nothing is mocked except one clearly-labelled replay animation.

Two data-source facts that matter for filming, established in `frontend/src/lib/api.ts`:
- **Most pages are statically prerendered + ISR (5-minute revalidate)** served off Vercel's CDN — they paint instantly, no spinner, then refresh in the background. `/matrix`, `/feed`, `/brief` all do this.
- **Live realtime is real** — the `/feed` ticker rides a genuine Server-Sent-Events connection (`/api/sse/feed`), not a poll. `/analytics` is the exception: it reads a bundled static `/analytics.json` snapshot, no API call at all.

---

## SURFACE A — `/matrix` · the Breach Matrix

The hero surface. A coloured grid of attack-family rows × deployment-config columns, where heat = how often that attack breaks that model. The "wall of red" shot.

### A1 · The breach heatmap grid
- **Where:** `/matrix` route (`app/matrix/page.tsx`) → `components/matrix-heatmap.tsx` (`MatrixHeatmap`, `HeatmapCell`, `colorFor`).
- **What it does / on screen:** A full `<table>`: rows are attack families (e.g. `jailbreak`, `indirect_prompt_injection`), columns are deployment configs (model × system-prompt × tools), each with a provider logo + shortened model name. Every cell aggregates `MAX(any_breach_rate)` across all primitives in that (family × config) pair and prints the percentage big and bold (`60%`, `100%`). The colour ramp is the money shot: `<10%` dim card-grey, `10–30%` blue, `30–50%` yellow, `50–70%` orange, `70–100%` ROGUE-red with a live critical pulse animation (`rogue-cell-critical`). Cells stagger-animate in on load (`animate-rogue-cell-pop`, escalating delay across the diagonal). Empty cells render a muted `—`. Hovering a cell scales it up 110%, lifts its z-index, and casts a red glow shadow; a native tooltip shows `"<title> on <config> — N% any-breach (n=5) · click to inspect"`.
- **Live or static:** Static-prerendered baseline grid (this-run × baseline quadrant), served from CDN; the three other quadrants lazy-load client-side after mount.
- **Marketing hook:** "Every red square is a real jailbreak breaking a real model config. Read the board in three seconds."
- **Video idea:** Slow push-in on the grid as cells pop in one diagonal at a time, settling into a wall of pulsing red — then cut to a cursor hovering one cell and it glows and lifts.

### A2 · Heat-scale legend
- **Where:** `/matrix` → `Legend` / `LegendChip` in `app/matrix/page.tsx`.
- **What it does / on screen:** A horizontal row of five labelled colour chips spelling out the ramp: `<10%`, `10–30%`, `30–50%`, `50–70%`, `70–100% · breached` (the last one carries the same critical pulse as a hot cell). Fades up below the grid.
- **Live or static:** Static.
- **Marketing hook:** "A colour scale a CISO reads instantly — green is fine, red is breached."
- **Video idea:** Quick lower-third reveal of the five chips animating in left-to-right, the red one pulsing.

### A3 · Headline stat capsules (Worst cell / Critical cells)
- **Where:** `/matrix` → `StatCapsule` in `app/matrix/page.tsx`.
- **What it does / on screen:** Two tinted capsules top-right of the header. "Worst cell" shows the single highest any-breach rate as a percentage, tinted red/orange/green by threshold, with a plain-English subtitle (via `plainifyRate`). "Critical cells" counts how many cells breach ≥70% of the time, with a subtitle like "N cells breach 70%+ of the time" (or "nothing in red zone" at zero).
- **Live or static:** Static (computed from the baseline matrix at render).
- **Marketing hook:** "The damage report, up front: how bad is the worst case, and how many configs are in the red zone."
- **Video idea:** The two capsules count up / snap to their values as the header fades in.

### A4 · "Worst attacker today" callout banner
- **Where:** `/matrix` → the `<Link>` headline-cell card in `app/matrix/page.tsx`.
- **What it does / on screen:** A full-width red-bordered card under the header naming the single worst-performing attack: its title, family · vector, which config it breached, the breach rate in red, and `(n=5)`. On the right it names the "most-vulnerable config." The whole card is a link — on hover it brightens and an inline "— see full breakdown →" hint fades in. (Note: it deliberately pins Pliny's `elder_plinius` X jailbreak as the featured attack when present, since it ties several others at 100%.) Clicking jumps to the `/matrix/cell` drill-down.
- **Live or static:** Static.
- **Marketing hook:** "Today's worst offender, named — a real jailbreak from a real handle, breaking your bot 100% of the time."
- **Video idea:** Cursor lands on the red banner, the "see full breakdown" hint fades in, click → hard cut to the cell page.

### A5 · SCOPE toggle (This run ↔ All-time)
- **Where:** `/matrix` → `MatrixHeatmap` SCOPE segmented control.
- **What it does / on screen:** A two-button mono-uppercase pill: "This run" vs "All-time." Flipping it swaps the entire grid's date window — one run-day vs every run day merged — and updates a live caption ("this run's day ·" vs "every run day merged ·"). Active button glows ROGUE-green. This is one axis of the 2×2.
- **Live or static:** This-run is static (prerendered); All-time data lazy-loads client-side after mount (~768KB quadrant), so the toggle may briefly show a green pulsing "loading…" caption before its data lands.
- **Marketing hook:** "Zoom from today's snapshot to the all-time threat picture with one click."
- **Video idea:** Click "All-time" — the grid re-tints as merged data swaps in, more cells light up red.

### A6 · ATTACKER toggle (Baseline ↔ + Augmentations)
- **Where:** `/matrix` → `MatrixHeatmap` ATTACKER segmented control.
- **What it does / on screen:** The second 2×2 axis. "Baseline" = the raw harvested prompt, N=5 trials, no adaptation. "+ Augmentations" = worst-case across persona-wrap + PAIR iterative refinement. Flipping to augmented re-colours the grid hotter (cells the model defended single-shot light up once the attacker adapts) and the caption changes to "how hot each cell gets once the attacker adapts." Active augmented button glows red; baseline glows green.
- **Live or static:** Augmented quadrants lazy-load client-side; same "loading…" affordance as SCOPE.
- **Marketing hook:** "Watch the board get hotter the instant the attacker is allowed to adapt — this is the difference between a script kiddie and a determined adversary."
- **Video idea:** Side-by-side or a hard toggle: baseline grid (some orange) → "+ Augmentations" → the same grid blooms red.

### A7 · The 2×2 caption strip
- **Where:** `/matrix` → caption `<span>` after the toggles in `MatrixHeatmap`.
- **What it does / on screen:** A live one-line description that recomposes from the two toggle states — e.g. "every run day merged · worst-case across persona-wrap + PAIR refinement…" — so the visitor always knows exactly which of the four quadrants they're looking at. Includes the pulsing green "· loading…" tail while a quadrant is still fetching.
- **Live or static:** Reactive client-side.
- **Marketing hook:** "Always know which slice of the threat model you're staring at."
- **Video idea:** Close-up on the caption text recomposing as both toggles flip.

### A8 · Severity filter chips (all / any breach / ≥50% / ≥70% critical)
- **Where:** `/matrix` → `FilterChip` row in `MatrixHeatmap`.
- **What it does / on screen:** A filter bar of chips. Unlike a hide-filter, these *dim* cells below the chosen threshold to ~20% opacity + desaturate and drop their pulse, so the cells that clear the bar pop out of a dimmed field. "≥50%" tints orange, "≥70% (critical)" tints red.
- **Live or static:** Reactive client-side.
- **Marketing hook:** "Mute the noise — dim everything except the cells that breach more than half the time."
- **Video idea:** Click "≥70% (critical)" and the whole grid dims except a handful of red cells that stay lit and pulsing.

### A9 · Row (family) and column (config) click-to-filter
- **Where:** `/matrix` → the family `<button>` cells and config `<th>` buttons in `MatrixHeatmap`.
- **What it does / on screen:** Clicking a family row label collapses the grid to that single family; clicking a column header collapses to that single deployment config. Active filters surface as removable chips ("family: jailbreak ×", "config: … ×"). A live footer reads "N families × M configs · click a row, column, or cell."
- **Live or static:** Reactive client-side.
- **Marketing hook:** "Slice the matrix to one model or one attack class instantly."
- **Video idea:** Click a column header → grid narrows to one model's column; the chip appears; click the chip to restore.

### A10 · Column-header heat + PAIR-iterations annotation
- **Where:** `/matrix` → config `<th>` rendering (`colWorst`, `stubByConfig`) in `MatrixHeatmap`.
- **What it does / on screen:** Each column header carries, under the model name, a "worst N%" figure tinted by severity, and — when stubbornness data is present — a "PAIR X.XX iters" line (avg iterations the attacker needed to break that config; lower = more vulnerable to iterative refinement). Ties the matrix to the augmentation A/B story visually.
- **Live or static:** Worst% is static; PAIR-iters comes from `stubbornnessStats` (degrades to null silently).
- **Marketing hook:** "Each model carries its own resilience score — how many tries before it cracks."
- **Video idea:** Tooltip hover on the "PAIR 1.40 iters" annotation explaining lower = weaker.

### A11 · Cell-click → the breach drawer
- **Where:** `/matrix` → `components/matrix-drawer.tsx` (`MatrixCellDrawer`).
- **What it does / on screen:** THE signature interaction. Click any red cell and a 560px drawer slides in from the right (`rogue-slide-in-right`, easing curve) over a blurred black backdrop, with a green glow on its left edge. Header: family eyebrow, provider logo + config name + target model, and — if applicable — a "judge refused → fallback" provenance badge. Body, top to bottom:
  1. **Headline any-breach rate** rendered at `text-5xl`, tinted, with the line "95% CI: X% – Y% · N trials", the full-breach rate, and avg judge confidence. (This is the confidence-interval beat.)
  2. A green "see all breaching primitives in this cell →" link to the deep page.
  3. **The worst-offending primitive:** title, short description, severity, vector, a "multi-turn" chip if applicable.
  4. **`payload_template` — the actual prompt that breached it** in a monospace scroll box with a copy button. The "wow, that's the exact prompt that broke gpt-4o-mini" moment.
  5. **Payload image** (if the attack carries one) rendered verbatim "sent to the vision panel."
  6. **Verdict histogram** for this config (see A13).
  7. **Provenance:** up to 5 source links, each tagged with its Bright Data product, opening the original open-web post.
  Closes on the × button, backdrop click, or Escape.
- **Live or static:** Drawer content fetched live from `/api/attacks/{id}` on open, with hover-prefetch (see A12) and cold-boot retry — so it usually opens straight to content.
- **Marketing hook:** "One click on a red square and you're holding the exact prompt that broke the model — with the receipts."
- **Video idea:** Click a 100% red cell → drawer slides in → scroll past the giant "100%" and CI down to the green payload box → cursor hits "copy" → "copied ✓".

### A12 · Hover-prefetch warming
- **Where:** `/matrix` → `HeatmapCell` `onMouseEnter`/`onFocus` → `prefetchAttackDetail` in `matrix-drawer.tsx`.
- **What it does / on screen:** No visible UI of its own — but hovering a cell silently warms the attack-detail fetch into a shared cache, so by the time you click, the drawer opens *instantly* instead of showing "loading primitive…". Re-opening any cell is instant.
- **Live or static:** Live (background fetch + in-memory cache with failure eviction).
- **Marketing hook:** "Feels instant because it is — the data's already loading the moment your cursor touches a cell."
- **Video idea:** N/A for camera directly; supports the snappiness of the A11 shot.

### A13 · Verdict histogram bar
- **Where:** Drawer + cell page → `VerdictBar` in `matrix-drawer.tsx` (reused by `cell-primitive-list.tsx`).
- **What it does / on screen:** A single horizontal stacked bar segmented by trial outcome across N=5 trials: full breach (red), partial (orange), evaded (yellow), refused (green), error (grey). Below it, a 2-column legend with exact counts per outcome, plus a "last run <timestamp>" line. The honest, granular breakdown behind the headline rate.
- **Live or static:** Live (from the per-config breach detail).
- **Marketing hook:** "Not just a number — every single trial, graded and accounted for."
- **Video idea:** The stacked bar animates to width; cursor hovers a segment, tooltip "full breach: 5/5".

### A14 · The `/matrix/cell` deep drill-down page
- **Where:** `/matrix/cell?family=&config=&date=&scope=&attacker=` (`app/matrix/cell/page.tsx`) → `components/cell-view.tsx` + `cell-primitive-list.tsx`.
- **What it does / on screen:** The full expansion of one (family × config) cell. The grid only shows the single worst primitive per cell; this page lists *every* breaching primitive (>0% any-breach), worst-first, each as a full card (`CellCard`): rank badge (#1, #2…), vector, severity, title, description; a "via PERSONA" / "via PAIR" orange chip when the breach only happened after augmentation; a "judge refused → fallback" chip; the big tinted rate with CI and full-breach %; the `payload_template` with copy; payload image; verdict histogram; provenance links. Header carries its own SCOPE and ATTACKER toggles (mirroring the matrix 2×2) that re-fetch in place, and a "← back to matrix" link. Opens in whatever quadrant you clicked from.
- **Live or static:** Fully client-fetched (dynamic route) with patient retry (1s/2s/3s) + a "the API didn't respond (it may be waking up) — retry" state and a skeleton-pulse loading state. Empty-cell states offer one-click "try all-time / + augmentations" buttons.
- **Marketing hook:** "Drill all the way down: every prompt that broke this model on this config, ranked by how hard it hit."
- **Video idea:** From the matrix banner click → cell page loads its skeleton → cards stream in, #1 a red 100% card; flip the ATTACKER toggle on-page and a "via PAIR" chip appears on newly-listed cards.

### A15 · Copy-payload button
- **Where:** Drawer, cell cards, feed rows → `CopyButton` (`matrix-drawer.tsx` / `attack-row.tsx`).
- **What it does / on screen:** A small mono "copy" button next to every payload box; click writes the raw payload to clipboard and flips the label to "copied ✓" for 1.5s.
- **Live or static:** Client-only interaction.
- **Marketing hook:** "Copy the exact attack string straight into your own test harness."
- **Video idea:** Tight close-up: "copy" → "copied ✓" flash.

### A16 · Mini-matrix (home-hero preview)
- **Where:** `components/mini-matrix.tsx` (rendered on the home hero, links to `/matrix`).
- **What it does / on screen:** A compact, label-less grid of the top-8 hottest families × all configs, coloured by the same ramp (red cells carry the critical pulse), with a header "breach matrix · <date>" and a footer reading "N families × M configs" and a red "X% peak · Y crit" stat. The whole tile is a link with an "open →" hover hint. Empty-state nudges to seed data.
- **Live or static:** Fed by the home page's static matrix fetch.
- **Marketing hook:** "A glanceable threat thumbnail on the front door."
- **Video idea:** Home hero shot, the mini-grid pops in cell-by-cell, then cut to clicking it into the full `/matrix`.

---

## SURFACE B — `/feed` · the Live Feed (war room)

The real-time forensic surface: newest harvested attacks streaming in, framed in a three-column war-room layout.

### B1 · The "live" header pulse
- **Where:** `/feed` → header in `app/feed/page.tsx`.
- **What it does / on screen:** "/feed · live" eyebrow with a green dot pulsing (`animate-rogue-pulse-green`), title "Live Feed," subtitle "Newest attack primitives surfaced from the open web."
- **Live or static:** The pulse is decorative; page is ISR.
- **Marketing hook:** "A live wire into the open-web jailbreak underground."
- **Video idea:** Macro on the pulsing green dot, rack focus to the "Live Feed" title.

### B2 · KPI strip (4 tiles)
- **Where:** `/feed` → `KpiTile` ×4 in `app/feed/page.tsx`, numbers animate via `CountUp`.
- **What it does / on screen:** Four count-up tiles: "Attacks (7d)" (green), "New breaches today" (red, and the whole tile pulses critical when >0), "Configs tested" (green), "Total breach trials" (green). Each has a label, big tabular number that counts up on mount, and a sub-line.
- **Live or static:** ISR-fetched; "New breaches today" derived from the brief JSON summary (new_critical + new_high).
- **Marketing hook:** "The day's threat scoreboard, counting up live."
- **Video idea:** All four numbers spin up from 0 simultaneously; the red "new breaches" tile flares its critical pulse.

### B3 · Three-column war-room layout
- **Where:** `/feed` → `grid-cols-[220px_1fr_300px]` in `app/feed/page.tsx`.
- **What it does / on screen:** Left intel ribbons, center attack list, right augmentation sidebar — the "command center" composition.
- **Live or static:** Mixed (center + left are client-rescoping; right sidebar ISR).
- **Marketing hook:** "A SOC-style war room for LLM attacks."
- **Video idea:** Wide establishing shot of the full three-column layout, slow drift across it.

### B4 · Center attack list — expandable rows
- **Where:** `/feed` center → `components/feed-stream.tsx` → `components/attack-row.tsx` (`AttackRow`).
- **What it does / on screen:** The forensic core. Each row collapsed: a severity badge (critical pulses red, high orange, medium yellow, low blue), title, two-line description, family · vector, a Bright Data product tag, plus "multi-turn" / "tools: N" chips where relevant; rows fade-up with stagger. Click a row → it expands (chevron rotates green) revealing the `payload_template` in a scroll box with copy, a "▶ play/replay" button, the full source list (with authors), and a footer of id / repro% / cluster / "★ canonical." Turns a list of headlines into a forensics tool.
- **Live or static:** Server-rendered 7-day window seeds it; re-scoping (B6) re-fetches client-side.
- **Marketing hook:** "Click any attack and see the actual prompt, its sources, and how reproducible it is."
- **Video idea:** Cursor expands a CRITICAL row → payload unfolds → click "▶ play."

### B5 · Attack replay (▶ play → attacker → model → judge)
- **Where:** `/feed` expanded row → `components/attack-replay.tsx` (`AttackReplay`).
- **What it does / on screen:** A terminal-style 3-phase animation that "plays out" the attack: **ATTACKER** (red label, the payload typed out) → **MODEL** (cyan label, a "Sure — happy to help…" breach response or an "I'm not able to help…" refusal, synthesized from the repro score) → **JUDGE** (green/red label, a verdict pill `● breach` / `○ refused`, severity, reproducibility %, family). Each phase fades in sequentially with a blinking caret. Note: the model response is heuristically synthesized for the UX, not a live transcript — film it as the conceptual "how an attack plays out" beat, not as ground-truth output.
- **Live or static:** Animated client-side from the primitive's stored fields (response text is synthesized).
- **Marketing hook:** "Watch an attack play out end-to-end: attacker, model, verdict."
- **Video idea:** Hero shot — the three terminal phases type in one after another, caret blinking, ending on a red "● breach" pill pulsing.

### B6 · Time-window segmented control (Today / 7 days / All time)
- **Where:** `/feed` center → `FeedStream` window control.
- **What it does / on screen:** A three-button pill that re-scopes the attack list without a navigation reload; active button glows green. A status line below reads "N shown · 7 days", "loading 7 days…", or a stale-fallback note ("no attacks in today · showing newest N") when the window is empty and the API falls back to newest rows.
- **Live or static:** Live client-side re-fetch (`api.attacks`).
- **Marketing hook:** "Zoom the feed from today to all-time in one tap."
- **Video idea:** Tap "Today" → list reflows, count updates, intel ribbons (B7) recompute.

### B7 · Left intel ribbons (hot families / by Bright Data product)
- **Where:** `/feed` left → `IntelRibbon` in `feed-stream.tsx`.
- **What it does / on screen:** Two mini bar-chart panels. "hot families" (green bars) and "by Bright Data product" (cyan bars) — each a top-N frequency histogram of whatever window is loaded, bars animating to width with a glow. Recompute when the window changes.
- **Live or static:** Recomputed client-side from the loaded window.
- **Marketing hook:** "See which attack classes and which data sources are driving today's intel."
- **Video idea:** The green and cyan bars sweep out to length as the window toggles.

### B8 · Right augmentation sidebar (6 widgets)
- **Where:** `/feed` right → `BanditWidget`, `PersonaWidget`, `EscalationWidget`, `MutationWidget`, `StubbornnessWidget`, `SystemStatusWidget`.
- **What it does / on screen:** A stacked column of R&D telemetry tiles, each with an explainer header (B11) and its own micro-viz. The bandit widget (B9) is the standout. Others surface persona / escalation / mutation A/B deltas and PAIR stubbornness; the bottom "system" tile shows DB status (green pulse dot if "up"), primitive count, breach count.
- **Live or static:** ISR-fetched, each degrades to a "// no data" line independently.
- **Marketing hook:** "The attacker's brain on display — every adaptation strategy and how well it's paying off."
- **Video idea:** Slow vertical scroll down the sidebar past each glowing tile.

### B9 · Bandit widget + per-arm hover-cards
- **Where:** `/feed` sidebar → `components/bandit-widget.tsx`.
- **What it does / on screen:** The ε-greedy multi-armed bandit tile (with a scan-line accent). Lists top-3 and bottom-3 strategy "arms" by mean yield ("X.X/$"). Hovering any arm row opens a pure-CSS hover-card below it with the full breakdown: pulls, novel found, BD spend (4-decimal $), yield, a warm/cold label, and a one-liner ("// next pull biased by ε-greedy: 90% pick the hottest arm, 10% explore"). Footer: "N arms · M warm", seed date, last-live-pull date.
- **Live or static:** ISR-fetched (`banditStats`).
- **Marketing hook:** "ROGUE learns which data sources pay off and spends its budget there — online, every day, no retraining."
- **Video idea:** Hover the #1 arm → hover-card unfolds with pulls/spend/yield → the "90% exploit, 10% explore" line.

### B10 · Augmentation A/B summary strip
- **Where:** `/feed` → `AugmentationStrip` (between KPI strip and war room), fed by persona/escalation/mutation/stubbornness stats.
- **What it does / on screen:** A horizontal summary band tying the four §10.7 augmentation experiments together above the war room.
- **Live or static:** ISR-fetched.
- **Marketing hook:** "The proof that adaptation works — measured, not claimed."
- **Video idea:** Pan across the strip's deltas.

### B11 · Explainer "?" popovers (on every widget)
- **Where:** All sidebar widgets → `components/explainer.tsx` (`ExplainerHeader`).
- **What it does / on screen:** Each widget header carries a small "?" button; click and a "what this is / why it matters" popover fades open in plain English. Designed so a non-technical CISO or judge can land on any tile and understand it in under 5 seconds. (A larger "hero" variant exists for showcase cards.)
- **Live or static:** Client interaction, static copy.
- **Marketing hook:** "Every chart explains itself — no glossary lookup required."
- **Video idea:** Tap a "?" on the bandit tile → the plain-English explanation slides open.

### B12 · Live SSE attack ticker (home hero)
- **Where:** `components/live-attack-ticker.tsx` (`LiveAttackTicker`) fed by `components/sse-feed-provider.tsx` (`SseFeedProvider` / `useSseFeed`).
- **What it does / on screen:** The genuinely-live beat. A single shared `EventSource` to `/api/sse/feed?since_days=2` streams snapshots; the ticker diffs new primitives against seen IDs and **slides each new attack in from the top with a fade-up and a green-glow flash** that fades over ~1.5s. Max 5 rows; older ones fall off the bottom. Each row: a severity dot (critical pulses red), title, family · vector, source product tag, and a ↗ link to the original post. Header shows a pulsing "live · streaming" label and "N most-recent."
- **Live or static:** **Genuinely live** — real Server-Sent-Events push, not a poll. New snapshots arrive on reconnect.
- **Marketing hook:** "New jailbreaks slide in live, the second ROGUE finds them on the open web."
- **Video idea:** Hold on the ticker; a fresh red-dot attack slides in from the top with a green glow flash. This is the "it's alive" shot.

### B13 · Live 24h count pill
- **Where:** `components/live-attack-ticker.tsx` → `LiveAttackCountPill` / `LiveCount`.
- **What it does / on screen:** A compact "X attacks in the last 24h" counter that reads from the shared SSE snapshot (counting primitives discovered within 24h), falling back to a server-seeded count until the first snapshot lands.
- **Live or static:** Live (SSE-derived).
- **Marketing hook:** "A live 24-hour attack counter ticking up."
- **Video idea:** The number above the ticker incrementing as a new row slides in.

---

## SURFACE C — `/brief` · the daily Threat Brief

The CISO deliverable: a dated, exportable, read-in-3-seconds-then-read-in-depth report.

### C1 · Masthead + one-line headline
- **Where:** `/brief` → header in `app/brief/page.tsx`.
- **What it does / on screen:** A bordered "daily threat brief" masthead with a pulsing green dot, the title "Threat Brief," a long human date ("Friday, June 5, 2026"), and a dynamically-built CISO one-liner — e.g. "3 new CRITICAL attacks bypassed guardrails since yesterday — patch system prompts now," or "Steady state — no critical movers." Plus a provenance line ("Daily snapshot · regenerable from the breach matrix").
- **Live or static:** ISR-fetched markdown brief.
- **Marketing hook:** "The brief a CISO actually reads — the verdict in one sentence, dated and signed."
- **Video idea:** Push in on the masthead, the headline sentence typing/fading in.

### C2 · Export buttons (.md / .json)
- **Where:** `/brief` → `components/brief-downloads.tsx`.
- **What it does / on screen:** Two mono download buttons top-right of the masthead: "↓ .md" and "↓ .json" (the JSON one disables if the JSON form failed to load). Click downloads a real `rogue-brief-<date>.md` / `.json` file via an in-browser Blob (no API round-trip), hover-glows green.
- **Live or static:** Client-side Blob download of already-fetched content.
- **Marketing hook:** "Export the brief as Markdown or JSON — drop it straight into your incident tooling."
- **Video idea:** Click "↓ .md" → OS download chip appears with the dated filename.

### C3 · At-a-glance KPI strip + per-tier chips
- **Where:** `/brief` → `KpiCard` ×4 + `TierChip` ×4 in `app/brief/page.tsx`.
- **What it does / on screen:** Four KPI cards "vs yesterday": "Newly breaching" (red+pulse when >0), "New CRITICAL" (red+pulse), "Newly defended" (green), "Net Δ" (signed, tinted red if up / green if down). Below, four per-tier count chips: CRITICAL (red, pulses if >0), HIGH (orange), MEDIUM (yellow), LOW (blue).
- **Live or static:** ISR; values from the brief JSON summary, with a markdown-scrape fallback (`extractCount`) so the strip stays populated even if JSON failed.
- **Marketing hook:** "Today's delta vs yesterday, by severity — what got worse, what got fixed."
- **Video idea:** The four KPI cards land; the red "New CRITICAL" card pulses; the CRITICAL tier chip echoes it.

### C4 · Executive snapshot (net-Δ + worst-3 attackers + recommended action)
- **Where:** `/brief` → `components/brief-exec-snapshot.tsx` (`BriefExecSnapshot`).
- **What it does / on screen:** The "punchline in 3 seconds" panel. A big signed net-Δ capsule (today vs yesterday counts, "↓ N newly defended" footnote). Beside it, the **top-3 worst new attackers** as cards — each shows the breach rate %, severity tier, title, "family · N configs hit," and is a **clickable link that drills into that exact (family × config) cell on `/matrix/cell`** (hover reveals "view cell →"). Below, a colour-coded "recommended action" line ("Patch system prompts now — N new CRITICAL…" / "Review high-tier additions…" / "N attacks now defended…" / "Steady state…").
- **Live or static:** ISR (brief JSON).
- **Marketing hook:** "The three worst new attackers and exactly what to do about them — each one a click from the receipts."
- **Video idea:** Cursor over a worst-attacker card → "view cell →" reveals → click → hard cut to that matrix cell page.

### C5 · Long-form branded markdown report
- **Where:** `/brief` → `components/brief-markdown.tsx` (`BriefMarkdown`).
- **What it does / on screen:** The full CISO report rendered with the ROGUE aesthetic: H2 section headers get a coloured left-bar tinted by tier (CRITICAL red, HIGH orange, MEDIUM yellow, LOW blue, else green); `**CRITICAL**` bold text glows red; severity bullet lines turn red+medium; inline `code` chips turn green-on-card. Set in a centered max-prose reading container inside a bordered card.
- **Live or static:** ISR (markdown from disk artifact, regenerable from the matrix).
- **Marketing hook:** "A full, branded threat report — formatted like something you'd actually circulate to leadership."
- **Video idea:** Slow scroll down the report, the coloured section bars and red CRITICAL headers passing by.

---

## SURFACE D — `/analytics` · the Telemetry / research layer

The R&D-grade dashboard. Recharts-powered, reads a bundled static snapshot — the "we measured all of this" surface.

### D1 · Telemetry masthead + freshness stamp
- **Where:** `/analytics` → `Shell` in `app/analytics/page.tsx`.
- **What it does / on screen:** "/analytics · <generated timestamp>Z" eyebrow with pulsing green dot, title "Telemetry," subtitle calling it "a published snapshot" of capability/discovery/allocation/research metrics. Loading state: "loading telemetry…" pulse; error state nudges to run `publish_analytics.sh`.
- **Live or static:** **Static** — fetches bundled `/analytics.json` (regenerated and republished out-of-band), no live API call.
- **Marketing hook:** "A published research snapshot — the system measuring itself."
- **Video idea:** The "loading telemetry…" pulse resolving into the populated dashboard.

### D2 · Capability stat tiles + modality graduation chips
- **Where:** `/analytics` → "Capability" `Section` with `Stat` tiles.
- **What it does / on screen:** Six left-border-accented stat tiles: Strategies, Graduated (with % rate), Cost / graduation ($), Validity rate, Overall breach %, Total spend ($ + per-breach micro-cost). Below, green pill chips per modality ("text · N graduated", "image · N graduated").
- **Live or static:** Static (analytics.json).
- **Marketing hook:** "What graduates into the live arsenal, and how cheaply."
- **Video idea:** The six tiles fade up; chips populate.

### D3 · Discovery source-yield bar chart
- **Where:** `/analytics` → "Discovery · source yield" Recharts horizontal `BarChart`.
- **What it does / on screen:** Horizontal bars per source — bar length = number of techniques harvested, **bar colour = graduation rate** (green high / orange mid / dim low). Hovering shows a custom green-bordered tooltip with techniques / graduated / grad-rate. Bars animate out.
- **Live or static:** Static.
- **Marketing hook:** "Which open-web sources actually yield working attacks."
- **Video idea:** Bars sweep out left-to-right; hover the top source for the tooltip.

### D4 · Growth-by-month bar chart
- **Where:** `/analytics` → "Growth · techniques by source month" vertical `BarChart`.
- **What it does / on screen:** Vertical bars per source-month of when the harvested attacks were originally published; recent months render brighter green, older ones dimmed. Animated, with the same tooltip.
- **Live or static:** Static.
- **Marketing hook:** "The jailbreak meta over time — and how current ROGUE's corpus is."
- **Video idea:** Bars rise in sequence, recent months glowing brighter.

### D5 · Model-vulnerability ranking bar chart
- **Where:** `/analytics` → "Contextual breach heatmap" section, top `BarChart`.
- **What it does / on screen:** Horizontal bars ranking each target model by avg breach rate across all families, coloured by severity (red ≥50%, orange ≥25%, green below), with the % labelled at the bar end. Sorted worst-first.
- **Live or static:** Static.
- **Marketing hook:** "A leaderboard of which models break easiest."
- **Video idea:** Bars sort and animate; the worst model's red bar stretching furthest.

### D6 · Family × model breach heatmap (interactive)
- **Where:** `/analytics` → `FamilyRow` grid in the same section.
- **What it does / on screen:** A custom CSS-grid heatmap (not a Recharts primitive): rows = attack families, columns = models, each cell tinted by breach rate with the integer % printed, hover-ring on focus. **Family row labels are clickable to focus a single family** (others dim to 25%). A threshold filter (all / ≥30% / ≥60%) dims sub-threshold cells. A colour legend (low/mid/high swatches) sits top-right. A footer names the global best family, crossover-model count, and the routing verdict.
- **Live or static:** Static, with reactive client filters.
- **Marketing hook:** "The full attack-class × model threat surface, filterable down to the hot spots."
- **Video idea:** Click "≥60%" → cells dim except the hottest; then click a family label to isolate its row.

### D7 · Allocation & research stat tiles (§10.10 scheduler)
- **Where:** `/analytics` → "Allocation & research" `Section`.
- **What it does / on screen:** Eight stat tiles on the scheduler dataset: Reachability, Scheduler quality, Exploration efficiency, Starvation (orange, "by design"), Early-stop bias (orange), Opportunity cost (starved shots + % of eligible), Avg rank of winner, Avg ladder depth — colour-toned green/orange/blue by meaning.
- **Live or static:** Static.
- **Marketing hook:** "The research layer — proof the scheduler spends compute where it pays off."
- **Video idea:** The grid of eight tiles fading up as a "we measured everything" montage beat.

### D8 · SparkBars micro-chart (refinement histogram)
- **Where:** `components/spark.tsx` (`SparkBars`), used in the stubbornness widget on `/feed`.
- **What it does / on screen:** A pure-SVG horizontal mini bar chart (no Recharts) — labelled left, value-aligned right, bars "filling in" with a CSS transition + glow. Used for the PAIR refinement-type histogram.
- **Live or static:** Fed by ISR stubbornness stats.
- **Marketing hook:** "Even the sidebar micro-charts animate in."
- **Video idea:** Close-up of the little bars growing on first paint.

---

## CROSS-CUTTING — the glossary / explainer system

### X1 · `<Term>` inline glossary tooltips
- **Where:** `components/glossary.tsx` (`Term`, `GLOSSARY`), used throughout `/matrix` copy and elsewhere.
- **What it does / on screen:** Any jargon word in body copy wears a green dotted underline + a tiny "ⓘ". Hover (desktop) reveals a dark green-bordered tooltip card with the **expansion** (e.g. "PAIR → Prompt Automatic Iterative Refinement") and a **plain-English** explanation; click pins it open, click-outside dismisses. The glossary covers ~22 terms: PAIR, PAP, AutoDAN, mutation, MCP, SERP, LLM, CISO, Δ, pp, CI, ε-greedy, SSE, Crescendo, A/B, primitive, vector, family, deployment config, bandit. Goal stated in code: "a non-technical CISO can read every line of the dashboard without bouncing on a single term."
- **Live or static:** Static copy, client reveal.
- **Marketing hook:** "Every acronym explains itself — hover and the jargon dissolves into plain English."
- **Video idea:** Cursor hovers "PAIR" in the matrix footnote → the green tooltip card unfurls with the plain-English definition.

### X2 · `ExplainerHeader` "what this is / why it matters"
- **Where:** `components/explainer.tsx` (see B11) — also usable in a larger "hero" form on showcase cards.
- **What it does / on screen:** The compact form is the "?" popover on widgets (B11); the hero form renders an eyebrow + a plain-English headline + a why-it-matters paragraph for big showcase cards.
- **Live or static:** Static copy, client interaction.
- **Marketing hook:** "Built so a non-engineer gets it in five seconds."
- **Video idea:** Covered by B11.

---

## Full capability inventory (count)

`/matrix` (16): A1 heatmap grid · A2 heat-scale legend · A3 headline stat capsules · A4 worst-attacker callout · A5 SCOPE toggle · A6 ATTACKER toggle · A7 2×2 caption strip · A8 severity filter chips · A9 row/column click-filter · A10 column-header heat + PAIR-iters · A11 cell-click breach drawer · A12 hover-prefetch · A13 verdict histogram · A14 `/matrix/cell` drill-down · A15 copy-payload · A16 mini-matrix preview.

`/feed` (13): B1 live header pulse · B2 KPI strip · B3 war-room layout · B4 expandable attack rows · B5 attack replay · B6 time-window control · B7 left intel ribbons · B8 augmentation sidebar · B9 bandit widget + hover-cards · B10 augmentation A/B strip · B11 explainer popovers · B12 live SSE ticker · B13 live 24h count pill.

`/brief` (5): C1 masthead + headline · C2 export buttons · C3 KPI strip + tier chips · C4 executive snapshot (clickable worst-3 → matrix) · C5 long-form branded markdown.

`/analytics` (8): D1 masthead + freshness stamp · D2 capability tiles + modality chips · D3 source-yield bars · D4 growth-by-month bars · D5 model-vulnerability ranking · D6 family×model interactive heatmap · D7 allocation/research tiles · D8 SparkBars micro-chart.

Cross-cutting (2): X1 `<Term>` glossary tooltips · X2 `ExplainerHeader`.

**Total: 44 distinct filmable capabilities across the four threat-intelligence surfaces.**
