# ROGUE brand assets

Logo suite built to `10_logo_and_og_creative_brief.md`, grounded in the live product (`/matrix`, `/product`).

**The mark — breach grid + red ping.** A 3×3 cut of your signature breach matrix: defended cells dim/green, one cell breached red, with a faint red radar-ping emanating from it. It *is* the product (the matrix is ROGUE's signature visual), it carries the alive-signal pulse from the homepage ticker, and it survives at 16px.

**Locked colors:** green `#00ff88` (defended/alive) · red `#ff003c` (breach, accent only) · background `#050508`. Wordmark is real **Geist Mono Bold**, all-caps, tracked open, converted to vector paths — the SVGs are self-contained, no font dependency. Green = defended/alive, red = breach; never invert that.

---

## Complete file manifest (28 files)

### `brand-svg/` — scalable source logos
| File | What it is |
|---|---|
| `logomark.svg` | The mark alone (breach grid + red ping), transparent background. The core glyph. |
| `logomark-plate.svg` | The mark centered on a rounded deep-dark plate. Use for avatars / app icon. |
| `wordmark.svg` | "ROGUE" lettering, green, Geist Mono Bold, with clear space built in. |
| `wordmark-white.svg` | Same wordmark in off-white — for placing over busy/colored frames where green won't read. |
| `logo-horizontal.svg` | **Primary lockup** (mark left + wordmark right), green. The workhorse — use this by default. |
| `logo-horizontal-white.svg` | Horizontal lockup with a **white wordmark** (mark keeps its colors). For colored/photographic dark backgrounds where green text would clash. |
| `logo-stacked.svg` | Mark above, wordmark below. For square-ish spaces (cards, centered headers). |
| `logomark-mono-green.svg` | Single flat **green** mark, no ping; breach cell drawn as a hollow square so it stays distinct in one color. For favicons, embroidery, stamps, single-color print. |
| `logomark-mono-white.svg` | Same flat mono mark in **white** — one-color use on dark. |
| `logomark-mono-black.svg` | Same flat mono mark in **near-black** — one-color use on light. |

### `png/` — raster exports (transparent unless noted)
| File | What it is |
|---|---|
| `logomark-512.png` | The mark, 512×512, transparent. General-purpose raster. |
| `logomark-64.png` | The mark, 64×64, transparent. Small UI / inline use. |
| `avatar-512.png` | Mark on dark plate, 512×512. Social/app avatar (Twitter, GitHub org, Slack). |
| `avatar-1024.png` | Same avatar at 1024×1024 for higher-res avatar slots. |

### `app-router/` — drop straight into `src/app/`
| File | What it is |
|---|---|
| `icon.svg` | SVG favicon (3×3 grid + red breach cell, simplified). Verified legible at 16px. |
| `apple-icon.png` | 180×180 Apple touch icon (mark on dark plate). |
| `favicon.ico` | Refreshed multi-resolution ICO (16 / 32 / 48 / 256). |
| `opengraph-image.png` | **1200×630 LIVE share image** (matrix-led) — this is the one wired into the site meta tag. Identical to `social/opengraph-image-LIVE-matrix-led.png`. |

### `social/` — share images, two purposes
| File | What it is |
|---|---|
| `opengraph-image-LIVE-matrix-led.png` | The **live OG image** (1200×630). Leads with the breach matrix (number-free — no baked-in counts that would go stale); human-gate & memory as secondary lines. Survives thumbnailing — wired into the meta tag (also copied into `app-router/`). |
| `opengraph-image-LIVE-matrix-led.svg` | Editable vector source for the live OG image above. |
| `social-card-three-surfaces-DOCS-github.png` | The **explainer card** (1200×630). All three surfaces explicit and labelled (model / human gate / agent's memory). Use in the GitHub README, docs hero, and social posts viewed larger. |
| `social-card-three-surfaces-DOCS-github.svg` | Editable vector source for the explainer card above. |

### `animated/` — pulsing red ping (hero / loading state)
| File | What it is |
|---|---|
| `logomark-animated.svg` | The mark on its dark plate, with two red ping rings expanding from the breach cell and fading on a 2.4s loop (offset so one's always in flight) + a subtle breach-cell heartbeat. Pure SMIL — animates in an `<img>` or inline, no JS. |
| `logomark-animated-transparent.svg` | Same animation, **no plate** — for placing over the hero background. |

### `light/` — for white / light backgrounds
| File | What it is |
|---|---|
| `logo-horizontal-light.svg` | Horizontal lockup tuned for light contexts: darker green (`#00b863`), defended cells as light mint, darker red (`#e0003a`) breach. Use only when the logo can't go on dark. |
| `logomark-light.svg` | The mark alone, light-tuned, for white backgrounds. |
| `logomark-light-512.png` | 512×512 raster of the light mark, white background baked in. |

### Root
| File | What it is |
|---|---|
| `README.md` | This file. |

---

## Wiring into the site (App Router file convention)

Copy into `src/app/` — Next auto-wires them, same as the existing `favicon.ico`:

```
src/app/icon.svg
src/app/apple-icon.png
src/app/favicon.ico
src/app/opengraph-image.png
```

No hand-written `<link>` / meta tags needed. Only add `metadataBase` + an `openGraph` block to `layout.tsx` if you want per-route OG overrides.

For the **GitHub README**, reference `social/social-card-three-surfaces-DOCS-github.png`.

The one code change: swap the in-code text wordmark for the SVG lockup in `nav.tsx` / `cinematic-hero.tsx`. Put `logomark.svg`, `wordmark.svg`, and `logo-horizontal.svg` in `frontend/public/`.

**Reduced motion:** if you inline `logomark-animated.svg`, gate it with `@media (prefers-reduced-motion: reduce)` and fall back to the static `logomark.svg`.

---

## Pick-by-context cheat sheet

| Context | Use |
|---|---|
| Nav / dark UI (default) | `brand-svg/logo-horizontal.svg` |
| Colored / photo dark background | `brand-svg/logo-horizontal-white.svg` |
| Square avatar / app icon | `brand-svg/logomark-plate.svg` or `png/avatar-512.png` |
| One-color print / embroidery / stamp | `brand-svg/logomark-mono-green.svg` (or white/black) |
| White / light background | `light/logo-horizontal-light.svg` |
| Favicon | `app-router/icon.svg` + `app-router/favicon.ico` |
| Link unfurl (Slack / X / LinkedIn) | `app-router/opengraph-image.png` |
| GitHub README / docs hero / larger social | `social/social-card-three-surfaces-DOCS-github.png` |
| Hero animation / loading state | `animated/logomark-animated.svg` |
