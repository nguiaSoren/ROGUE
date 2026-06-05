# Logo & OG creative brief — ROGUE

The one real asset gap: ROGUE has **no logomark, wordmark, or social/OG image file** — only a 16/32px `favicon.ico` and third-party *source* logos in `public/logos/`. Today the "logo" is a text wordmark rendered in code (green `#00ff88` bold Geist Mono `ROGUE` + a pulsing green dot). This brief specs exactly what to create so a designer or an image tool can execute against the existing brand (`08_brand_kit.md` is the source of truth for color/type/motion).

## What ROGUE is (for the designer)

ROGUE is a continuous, open-web LLM red-team: it harvests real jailbreaks from the open web, fires them at AI models, and reports what breaks — with an independent judge so the verdicts are trustworthy. The feeling: **a calm, precise security instrument watching something dangerous.** Not loud "hacker" cliché — measured, technical, credible. Dark, terminal-adjacent, with one alive green signal and the threat of red. "Rogue" = the adversary's perspective, turned into a defensive tool.

## Deliverables to produce

| Asset | Format | Size | Notes |
|---|---|---|---|
| **Logomark** (the glyph alone) | SVG + PNG | scalable; export 512×512, 64×64 | Must read at 16px (favicon) and 1000px (title card) |
| **Wordmark** (ROGUE lettering) | SVG | scalable | The text lockup, refined from the in-code version |
| **Primary lockup** (mark + wordmark) | SVG | horizontal + stacked | The main logo |
| **Favicon** | ICO + SVG + PNG | 16/32/48 + 180 (Apple touch) | Replaces the current weak `.ico` |
| **App/social avatar** | PNG | 512×512, 1024×1024 | Square, the mark centered on dark |
| **OG / social share image** | PNG | **1200×630** | For link unfurls (Twitter/X, LinkedIn, Slack) |
| **Variants** | — | — | Full-color, mono-green, mono-white (for dark bg), mono-black (for the rare light context) |

## Locked brand constraints (do NOT deviate)

- **Green** `#00ff88` — the alive/healthy/ROGUE signal. The primary logo color.
- **Red** `#ff003c` — breach/critical. Use only as an accent (the threat), never the dominant color.
- **Orange** `#ff6b00` — high/warning accent (optional).
- **Background** deep blue-black, not pure black: `#050508` / `#0a0a12` (the app uses `oklch(0.06 0.005 270)`).
- **Type** Geist (UI) + **Geist Mono** (numerals, labels, the wordmark). The wordmark is monospace, all-caps, bold.
- **The pulsing green dot** is an existing brand motif (a small heartbeat dot) — strong candidate to carry into the mark.
- Dark theme only. Motion is restrained and purposeful (see brand kit). Green = good, red = breach — never mix that semantics up in the logo.

## The wordmark (exact)

`ROGUE`, all caps, **Geist Mono Bold**, tracked slightly open, in `#00ff88` on dark. Optionally precede it with the pulsing dot as a fixed bullet (`● ROGUE`) or integrate the dot into a letter (see concept C). Keep generous clear space = the cap-height on all sides. Provide a mono-white version for use over busy/colored frames.

## Logomark concept directions (pick one to develop; several are filmable as animations too)

1. **The signal dot / heartbeat.** The existing pulsing green dot, elevated into a deliberate mark — a single green dot with a faint concentric "ping" ring, like a radar/sonar return. Says: *something is being watched, and it just pinged.* Animatable as a slow pulse for video. Simplest, most ownable, scales to 16px.
2. **The breach cell.** A small grid of squares (echoing the breach matrix) with exactly one cell lit — green if "defended," or a single red cell among green for "breached." A literal nod to the product's signature visual (the matrix heatmap). Reads as "we map where you break."
3. **The rogue glyph "R".** A monospace `R` (or `>_` terminal prompt) where one stroke breaks/glitches or splits into a second offset copy — the "rogue/escaped" idea. Green primary with a red shadow-offset for the threat. Terminal-native.
4. **The shield, deconstructed.** A minimal shield outline drawn as a single green stroke that is *incomplete* (a gap) — security with an honest admission that gaps exist (that's what ROGUE finds). Subtle, mature, not the overused solid-shield cliché.
5. **The crosshair / reticle.** A precise green reticle/targeting bracket framing a small dot — "we point at your model and find the weak spot." Pairs naturally with the "point ROGUE at your endpoint" pitch.
6. **The escaping arrow.** A bracketed boundary `[ ]` with one element crossing the boundary line (an arrow or dot breaking out) — prompt-injection/jailbreak as "something crossing a boundary it shouldn't." Conceptual but distinctive.
7. **Monogram lockup.** Just a refined `●R` or `R●` where the green dot is the counter of the R or sits in the bowl — tightest possible mark for favicon/avatar.

**Recommended:** concept **1 (signal dot)** or **2 (breach cell)** — both are the most *ownable*, both tie directly to the live product (the SSE ticker pulse; the matrix), both animate beautifully for video, and both survive 16px. Concept 3 is the strong runner-up for terminal/dev-tool personality.

## OG / social share image (1200×630)

The dark blue-black grid background (the site's `bg-rogue-grid` + spotlight recipe — see brand kit §5), the logomark + wordmark left or center, and a one-line value prop in white/green: **"Continuous red-team for your LLM."** or **"Point ROGUE at your model. See what breaks."** Optional: a faint, blurred slice of the breach matrix heatmap (a few green cells, one red) in the lower third as texture — instantly signals the product without clutter. Keep ≥120px clear margins; text must read as a small thumbnail in a Slack/Twitter unfurl. Provide one neutral variant (logo + tagline) and one "product" variant (with the matrix texture).

## Do / Don't

- **Do** keep it dark, green-primary, red only as the threat accent, monospace lettering, lots of negative space.
- **Do** make the mark work as a single flat color (favicon, embroidery, stamp).
- **Don't** use gradients-as-crutch, drop shadows, glossy 3D, generic padlocks/hooded-figures, or matrix "falling code." Don't let red dominate. Don't render the wordmark in a non-mono or non-caps face.

## Ready-to-use generation prompts (for an image/vector tool)

Seed prompts a designer can paste into an AI image/vector tool, then refine to clean SVG:

- *(concept 1)* "Minimal vector logomark: a single bright green (#00ff88) dot emitting one faint concentric radar-ping ring, centered, on a deep blue-black (#050508) background. Flat, geometric, high-contrast, scalable, no gradient, no text. Security-instrument feel."
- *(concept 2)* "Minimal vector logo: a small 3×3 grid of rounded squares in muted green on deep blue-black, exactly one square lit bright green (#00ff88) and one square red (#ff003c). Flat, precise, tech-forensic, no text, no gradient."
- *(concept 3)* "Monospace capital letter R as a logomark, bright green (#00ff88), one stroke glitched/offset with a faint red (#ff003c) shadow copy, on deep blue-black, terminal/developer-tool aesthetic, flat vector, no gradient."
- *(wordmark)* "Wordmark 'ROGUE' in bold monospace, all caps, slightly tracked, bright green (#00ff88) on deep blue-black, a small pulsing green dot before the R, clean, flat, vector."
- *(OG image)* "1200x630 social share image, deep blue-black background with a faint technical grid and subtle top spotlight, a minimal green dot-ping logomark with 'ROGUE' wordmark in bold monospace, tagline 'Point ROGUE at your model. See what breaks.' in white, a faint blurred breach-matrix heatmap (green cells, one red) in the lower third, high contrast, readable as a small thumbnail."

When the mark is chosen, drop the files into `frontend/public/` (logomark.svg, wordmark.svg, logo.svg, favicon set, og.png) and wire them in `layout.tsx` (favicon/OG meta) + `nav.tsx`/`cinematic-hero.tsx` (replace the text wordmark with the SVG lockup).
