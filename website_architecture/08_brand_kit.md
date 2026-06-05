# 08 — ROGUE Brand Kit

A designer-facing one-pager for matching the ROGUE brand exactly in video, motion graphics, decks, and social assets — without reading source code. Every value below is pulled verbatim from the live frontend (`frontend/src/app/globals.css`, `frontend/src/app/layout.tsx`, `frontend/src/components/cinematic-hero.tsx`, `frontend/src/components/nav.tsx`) and cross-checked against `website_architecture/04_technical_architecture.md`. Where a number is the source of truth in code, it is reproduced here literally — nothing is invented.

The one-line read: ROGUE is a terminal-native, dark-only, "alive" aesthetic. Near-black blue-tinted backdrop, a signature electric green that means *alive / healthy / harvested*, a hot red that means *breach / critical*, monospace numerals everywhere, and motion that is purposeful and compositor-cheap (never decorative for its own sake). Think "a security operations terminal that is quietly breathing."

## 1. Logo / wordmark

There is no dedicated logo image file. ROGUE has no SVG/PNG logomark, no wordmark lockup file, and no `og-image`. The only brand raster that ships is the browser favicon at `frontend/src/app/favicon.ico` (a multi-size `.ico`: 16×16 and 32×32 only — far too small to use as a logo in video or print). The SVGs under `frontend/public/logos/` are *third-party* source/provider marks (OpenAI, Anthropic, Reddit, GitHub, arXiv, Hugging Face, X, etc.), not ROGUE's own logo. So: **the ROGUE logo is a text wordmark, set in code, not an image.** A designer recreating it should typeset it rather than look for a file.

How the wordmark is set (from `nav.tsx`, the canonical usage): the word `ROGUE` in **all-caps**, in the **monospace** font (Geist Mono), **bold** (`font-bold`), with **tight tracking** (`tracking-tight`), colored **terminal green** (`--rogue-green`, `#00ff88`). Immediately to its **left** sits the signature motif: a small **green dot** — a `2px × 2px` (`w-2 h-2`) filled circle in `#00ff88`, fully rounded, that **pulses** (the `rogue-pulse-green` heartbeat, opacity 1 → 0.55 → 1 over 2.5s). The dot reads as a "live / armed" indicator and is the closest thing ROGUE has to a logomark. In the nav it is followed by a muted-gray descriptor `· open-web threat intel`. On hover the wordmark briefly runs the `rogue-glitch` chromatic-offset effect (red/green text-shadow shudder).

The pulsing-green-dot + green caps "ROGUE" pairing is the de-facto lockup. Reproduce it as: `[green pulsing dot] ROGUE` in bold monospace caps.

Clear-space & usage (inferred from how it is used in-product — there is no written spec):
- Keep the green dot's diameter ≈ the cap-height of the wordmark's letters, set tight to the left of the word (a single small gap, ~half a dot-width).
- Give the lockup clear space of at least one cap-height on all sides.
- The wordmark lives on the dark backdrop only (see §6). Green-on-dark is the default; never set ROGUE in green on a light field (fails contrast and breaks the terminal feel).
- For a "title card" treatment, the terminal caret motif (`▮`, a blinking green block cursor — `rogue-caret`) can trail the wordmark to reinforce the terminal identity. This is used on hero text in-product.
- Casing is always `ROGUE` (all caps). Do not title-case ("Rogue") or lowercase it.

## 2. Color palette

Two color systems coexist. **Layer 1** is the neutral chrome (shadcn semantic tokens, defined in OKLCH, dark-mode values overridden by ROGUE). **Layer 2** is the ROGUE signature brand accents (defined as raw hex). For brand work, the Layer-2 hex accents are what you match; the Layer-1 OKLCH values are the surfaces/backgrounds the accents sit on. OKLCH hex equivalents below are approximate conversions for convenience — the OKLCH string is the source of truth in code.

### Signature accents (the brand — source of truth, raw hex)

| Name | Hex | Dim companion (≈33% alpha) | Used for |
|---|---|---|---|
| ROGUE green | `#00ff88` | `#00ff8855` (`--rogue-green-dim`) | The signature color. Means **alive / healthy / OK / harvested / live**. Wordmark, the pulsing live dot, primary CTA fill, nav active state, grid + spotlight + mesh glow, scrollbar, "live" pills, healthy stats. |
| ROGUE red | `#ff003c` | `#ff003c55` (`--rogue-red-dim`) | Means **critical breach / dangerous / alert**. Critical card borders, breach indicators, "db down" pill, the rotating threat-verb word in the hero, glitch offset. |
| ROGUE orange | `#ff6b00` | `#ff6b0055` (`--rogue-orange-dim`) | Means **warning / HIGH severity tier** (the step between green-OK and red-critical). |

### Background / surface (deep tones)

| Name | Hex / OKLCH | Used for |
|---|---|---|
| Deep background | `#050508` (`--rogue-bg-deep`) | The deepest backdrop layer — base of the grid and mesh backgrounds. Near-black with a faint blue cast. |
| Mid background | `#0a0a12` (`--rogue-bg-mid`) | Secondary deep tone, slightly lifted from deep. |
| App background (`--background`, dark) | `oklch(0.06 0.005 270)` ≈ `#08080c` | The page background. Deliberately a **deep blue-black, not pure black**, so cards read as floating panels. |
| Foreground / text (`--foreground`, dark) | `oklch(0.96 0 0)` ≈ `#f4f4f4` | Primary text — near-white. |
| Card surface (`--card`, dark) | `oklch(0.10 0.008 270)` ≈ `#101016` | Card / panel fill — a hair lighter than the page. |
| Border (`--border`, dark) | `oklch(1 0 0 / 8%)` | Hairline borders — white at 8% opacity. |
| Muted text (`--muted-foreground`, dark) | `oklch(0.62 0 0)` ≈ `#8f8f8f` | Secondary / label / descriptor text (e.g. the `· open-web threat intel` tagline, stat labels). |
| Destructive (`--destructive`, dark) | `oklch(0.704 0.191 22.216)` | shadcn's semantic "destructive" red (component-level; distinct from the brand `--rogue-red`). |

### Augmentation-tile accents (secondary hue set)

Five per-widget accents so the stacked "augmentation" sidebar tiles read as distinct subsystems at a glance. Picked for dark-mode legibility and maximum hue separation. Border color and the lighter text color are listed per tile.

| Subsystem | Border accent | Text accent | Meaning |
|---|---|---|---|
| Bandit | `#00ff88` (ROGUE green) | `#00ff88` | Signature / "always live" |
| Persona | `#a78bfa` (violet) | `#c4b5fd` | — |
| Escalation | `#fbbf24` (amber) | `#fcd34d` | — |
| Mutation | `#22d3ee` (cyan) | `#67e8f9` | — |
| Stubbornness | `#f87171` (red) | `#fca5a5` | The "this one is the killer" tile |

A third accent — cyan `rgba(34, 211, 238, …)` (`#22d3ee`) — also appears as one of the three mesh-gradient blobs in the home hero (see §5).

## 3. Typography

Two families only, both from the Geist superfamily (loaded via `next/font/google` in `layout.tsx`, exposed as CSS variables). No third font.

| Role | Family | CSS variable | Where it's used |
|---|---|---|---|
| UI / body / headings | **Geist** (sans) | `--font-geist-sans` / `--font-sans` / `--font-heading` | Body copy, the giant hero headline, subheads, prose. The hero `<h1>` is `font-bold`, very tight tracking (`tracking-tight`), tight leading (`leading-[0.95]`), scaling up to `5.5rem`. |
| Monospace — numerals, labels, terminal chrome | **Geist Mono** | `--font-geist-mono` / `--font-mono` | The wordmark, all stat **numbers** (with `tabular-nums` / `tabular` numerals for non-jittering counts), nav links, pills, uppercase micro-labels, button text, code/terminal surfaces, the blinking caret. |

Typographic signatures to reproduce:
- **Numbers are always monospace** with tabular figures. Big stats are `font-bold`; the big hero numbers sit at `3xl–4xl`.
- **Micro-labels are uppercase monospace with wide letter-spacing.** The recurring pattern is roughly `10px`, uppercase, `letter-spacing ~0.18em–0.22em` (e.g. `tracking-[0.22em]`), in muted gray or green. This is the "terminal HUD label" look — use it for captions, kickers, and tags.
- **Buttons / CTAs are uppercase monospace, bold, wide-tracked** (`tracking-[0.15em]`). The primary CTA is green fill with **black text**.
- **Headlines are sans (Geist), heavy, tight.** Sans for big statements; mono for everything machine-flavored.

## 4. Motion principles

Motion is purposeful, restrained, and compositor-cheap. The governing rule encoded in the CSS: animate **`opacity` and `transform` only** (never `box-shadow` or `background-position` on loops) so motion stays on the GPU compositor and never triggers per-frame repaint. Pulses are opacity, not glow. Two backgrounds were deliberately *de-animated* (grid drift, mesh drift) because moving backdrops forced expensive re-blurs — so the brand's backdrops are **static**, and the "alive" feeling comes from small foreground accents instead.

Catalog of the real animations (all prefixed `rogue-`):

| Animation | Feel | Timing | When to use |
|---|---|---|---|
| `rogue-fade-up` | Subtle rise + fade-in (8px up) | 0.5s ease-out | Staggered list/item entrances. |
| `rogue-reveal` | Bigger entrance — rise 28px + fade + de-blur | 0.9s cubic-bezier(0.16,1,0.3,1) | Hero / section "moments"; the headline, pills, CTAs reveal with staggered `animationDelay`. |
| `rogue-pulse-green` | Slow green heartbeat (opacity 1→0.55→1) | 2.5s ease-in-out, infinite | The "live / alive" signal — the wordmark dot, live pills. Signature motion. |
| `rogue-pulse-critical` | Same heartbeat, on critical elements | 2.5s ease-in-out, infinite | CRITICAL / breached elements only. Use sparingly. |
| `rogue-cell-pulse-red` (`rogue-cell-critical`) | Red cell heartbeat (opacity 1→0.6→1) | 3s ease-in-out, infinite | High-severity heatmap cells in the breach matrix. |
| `rogue-count-up` | Numbers tick up from 0 to target (CSS `@property` counter) | 1.2s cubic-bezier(0.16,1,0.3,1) | Big stat reveals — the "this is alive" proof numbers. |
| `rogue-word-cycle` (`rogue-word-rotator`) | A single word swaps vertically through a list | 10s cubic-bezier(0.7,0,0.3,1), infinite | Hero subhead's rotating threat-verb: "jailbroken / prompt-injected / role-played / escalated" (set in red). |
| `rogue-cell-pop` | Pop-in from 0.9 scale + fade | 0.4s ease-out | Heatmap cell entrance — a wave cascade across the grid. |
| `rogue-scan` (`rogue-scan-line`) | A faint green band sweeps left→right across an element | 3s linear, infinite | Hero text / high-attention cards — the "scanner" sweep. |
| `rogue-marquee` | Continuous horizontal scroll (translateX 0 → -50%) | 38s linear, infinite | The open-web sources logo strip. Pauses on hover. |
| `.rogue-card` hover | Magnetic lift: rises 2px, green border + soft green glow ring | 0.4s cubic-bezier(0.16,1,0.3,1) | Card hover. Critical variant (`.rogue-card-critical`) lifts to a red border + red glow instead. |
| `rogue-glitch` | Quick chromatic shudder (red/green text-shadow offset) | 0.4s ease-in-out, on hover | Wordmark hover; rare accent only. |
| `rogue-caret-blink` (`rogue-caret`) | Blinking terminal block cursor `▮` (green) | 1s steps(1), infinite | Trailing the hero/terminal text — terminal identity. |
| `rogue-bar-fill` | A bar grows to its target width | 0.7s cubic-bezier(0.16,1,0.3,1) | Lab "augmentation toggle" stat bars. |
| `rogue-glow-soft` | Gentle opacity breathing (1→0.7→1) | 2.4s ease-in-out, infinite | "Active" augmentation toggles. |
| `rogue-scroll-cue` | Gentle 8px down-bounce + fade | 2.2s ease-in-out, infinite | The scroll cue (↓) at the bottom of the hero. |
| `rogue-slide-in-right` | Slides in from the right (translateX 100%→0) + fade | — | The matrix cell-detail drawer panel. |

The shared easing curve `cubic-bezier(0.16, 1, 0.3, 1)` (a fast-out, smooth-settle "ease-out-expo" feel) is the brand's signature timing — reuse it for any new motion to match the house feel.

Two non-negotiable behaviors a designer should mirror in any motion work:
- **Reduced motion:** when the OS "reduce motion" setting is on (`prefers-reduced-motion: reduce`), all *infinite loops* stop — mesh, pulses, cell pulse, soft glow, scroll cue, marquee. Static frames read identically; one-shot entrances are left alone. (For video, this means: the brand is fully legible as a still frame — never depend on motion to convey meaning.)
- **Pause off-screen:** animations on a subtree pause (`animation-play-state: paused`) when it scrolls out of view (driven by an IntersectionObserver). Motion only runs where the eye is.

## 5. Background system

Three layered background recipes. All sit on the deep near-black base. Reproduce them literally:

**Grid** (`.bg-rogue-grid`) — a static green grid. Base color `--rogue-bg-deep` (`#050508`), overlaid with two 1px green lines on a 60px cell:

```css
background-color: #050508;
background-image:
  linear-gradient(rgba(0, 255, 136, 0.04) 1px, transparent 1px),
  linear-gradient(90deg, rgba(0, 255, 136, 0.04) 1px, transparent 1px);
background-size: 60px 60px;
```

(In the hero the grid is lightened: same green lines at `0.05` alpha on an `80px` cell, set to `opacity: 0.40`.) The grid is **static** — it used to drift but the motion was removed; do not animate it.

**Spotlight** (`.bg-rogue-spotlight`) — a soft green radial glow anchored at the top-center, painted via a `::before` behind content:

```css
background: radial-gradient(
  1200px 600px at 50% -10%,
  rgba(0, 255, 136, 0.12),
  transparent 60%
);
```

**Mesh** (`.bg-rogue-mesh`) — home-hero only. Three drifting-feel (but **static**) radial gradient blobs over the deep base — green, red, and cyan — giving an "alive without distraction" backdrop:

```css
background-color: #050508;
background-image:
  radial-gradient(900px 500px at 15% 20%, rgba(0, 255, 136, 0.14), transparent 60%),
  radial-gradient(700px 400px at 85% 30%, rgba(255, 0,  60, 0.10), transparent 60%),
  radial-gradient(600px 400px at 50% 90%, rgba(34, 211, 238, 0.10), transparent 60%);
```

The mesh's three blobs are the brand's signature trio: **green (top-left), red (top-right), cyan (bottom-center)** — a useful palette for any abstract ROGUE backdrop. The terminal scrollbar completes the look: an `8px` track, thumb in green at 15% alpha (`rgba(0,255,136,0.15)`), brightening to 40% on hover.

## 6. Do / Don't

**Do**
- **Dark theme only.** The app is hardcoded to dark (`<html class="dark">`, theme provider locked to dark, system theme disabled). Every asset lives on the deep blue-black backdrop. There is no light-mode brand.
- **Use green for good, red for breach.** Green (`#00ff88`) = alive / healthy / harvested / live. Red (`#ff003c`) = breach / critical / danger. Orange (`#ff6b00`) = HIGH-severity warning, the middle tier. Keep this semantic — never use green to flag a problem or red to flag health.
- **Set all numbers in monospace** (Geist Mono) with tabular figures. Stats, counts, percentages, timestamps — all mono.
- **Use uppercase wide-tracked monospace micro-labels** for kickers/captions/tags (~10px, ~0.2em tracking), in muted gray or green.
- **Keep "ROGUE" in green bold monospace caps**, paired with the pulsing green dot, on dark.
- **Keep motion purposeful and cheap** — small foreground accents (pulses, sweeps, count-ups), the signature `cubic-bezier(0.16, 1, 0.3, 1)` easing. Backdrops stay static. Ensure everything reads as a still frame.

**Don't**
- Don't put the brand on white or light backgrounds; don't invent a light theme.
- Don't use pure black (`#000`) for backgrounds — it's a deep *blue-black* (`#050508` / `oklch(0.06 0.005 270)`).
- Don't title-case or lowercase the wordmark — it's always `ROGUE`.
- Don't set body numbers in a proportional/sans font, and don't set big statement headlines in mono — sans (Geist) is for headlines/prose, mono (Geist Mono) is for machine-flavored chrome and numerals.
- Don't animate the backgrounds (grid/mesh drift was deliberately removed) and don't add glow/`box-shadow` pulses — pulse with opacity only.
- Don't overuse the heartbeat pulse, glitch, or red-critical motion — they're reserved for genuinely live / critical states. Reserve red for actual breach/danger.
- Don't go looking for a logo file — there isn't one. Typeset the wordmark.

## Asset inventory (what exists, with paths)

| Asset | Path | Notes |
|---|---|---|
| Favicon | `frontend/src/app/favicon.ico` | Multi-size `.ico`, 16×16 + 32×32 only. Browser tab use; too small for a logo. |
| Cover image | `assets/cover.png` | 1920×1080 PNG (demo-packet cover). |
| Video opening frame | `assets/rogue-opening-frame.png` | 1920×1080 PNG. |
| Video close frame | `assets/rogue-close-frame.png` | 1920×1080 PNG. |
| Demo / trailer videos | `assets/rogue-*.mp4`, `assets/demo*.mp4`, `assets/presentation.mp4`, `assets/0531.mp4` | Existing motion assets — reference these for the established on-brand look. |
| Third-party source logos | `frontend/public/logos/*.svg` | OpenAI, Anthropic, Google Gemini, Meta, Mistral, Hugging Face, Reddit, GitHub, arXiv, Discord, X. NOT ROGUE's own mark — these are the open-web sources/providers. |
| Next.js boilerplate SVGs | `frontend/public/{file,globe,next,vercel,window}.svg` | Framework defaults, unused for brand. |

**No ROGUE logomark / wordmark image, and no social `og-image`, exist in the repo.** If the brand needs a reusable logo file or OG card, one must be created from the text-wordmark spec in §1.
