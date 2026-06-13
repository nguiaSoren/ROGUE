# Dashboard

A tour of ROGUE's Next.js dashboard — the cinematic home plus the `/feed`, `/matrix`, and `/brief` deep-dive surfaces.

## Dashboard

The dashboard is a Next.js 16 + React 19 + Tailwind v4 app under `../frontend/`.
Designed for a 5-second pitch and a 5-minute deep-dive: the cinematic home
page lands the value prop; `/feed`, `/matrix`, `/brief` provide the depth.

### `/` — cinematic home (7 sections, top-to-bottom)

1. **Cinematic hero** — full-viewport opener with rotating-word headline
   (*"jailbroken → prompt-injected → role-played → escalated"*), hero stat
   trio pulled live from `/api/health`, and a single high-contrast CTA.
2. **Aha moment** — freshest 48h attack ticker side-by-side with the
   `MiniMatrix` so visitors see real data within 2 scrolls.
3. **How ROGUE thinks** — 3-step narrative (HARVEST → REPRODUCE → DEFEND)
   with color-coded top borders and live counters per step.
4. **Augmentation showcase** — 5 large story cards (one per augmentation:
   bandit, persona, escalation, mutation, PAIR) each carrying a hero stat,
   mini chart, "what this is / why it matters" copy, and a `live`/`no data`
   badge.
5. **Augmentation Lab (interactive)** — pick a deployment config, toggle
   persona / escalation / mutation switches, watch the estimated breach
   rate animate as stacked colored segments. Uses real `max_delta` /
   `delta` / `pattern_matching_score` values from the API.
6. **Bright Data spotlight** — 4 hero metrics (5 BD products in use, 19
   sources fanned out, novel-attacks-per-BD-$, 2-tier reliability), the
   per-product role breakdown, and the hover-pause sources marquee.
7. **Deep-dive cards** — links to `/feed`, `/matrix`, `/brief`.

### `/feed` — live attack feed

Headline KPIs, the augmentation A/B strip, then a 3-column war room:
left ribbon (hot families + BD-product histogram), center attack list
(expandable rows with a **▶ play** button that streams the attack as a
3-phase ATTACKER → MODEL → JUDGE terminal replay), right sidebar with all
5 augmentation widgets. Every widget has a `?` icon that opens a "What
this is / Why it matters" panel — the canonical copy lives in one place
(`../src/components/explainer.tsx` → `AUGMENTATION_COPY`) so the explanation
never drifts.

The bandit widget's arm rows each carry a CSS-only hover-card with
`pulls / novel-found / BD-spend / yield` and an ε-greedy explanation.

### `/matrix` — breach heatmap

15 attack families × 8 deployment configs. Click any red cell to see the
exact primitive that cracked it, with 95% bootstrap CIs. Column headers
carry the PAIR avg-iters-to-breach so the matrix and the augmentation
story stay tied together visually.

### `/brief` — daily threat brief

Executive snapshot (net Δ vs yesterday, top-3 worst new attackers,
recommended action), tier-count chips, then the full markdown brief with
`.md` and `.json` download buttons.
