# ROGUE brand assets

A reimagined, premium pass on the ROGUE identity. Same DNA as `assets/brand/` (the breach matrix), evolved: **dimensional, glowing, cinematic.** The evolved breach-grid identity. Vector-first, self-contained (logos are real paths, no font dependency), 4K cards + key-art.

**The mark — evolved breach grid.** Still a 3×3 cut of the breach matrix (defended cells green, one cell breached red, red radar ping), but upgraded: vertical gradients for depth, a soft glow on the live cells, a brighter breach with a stronger ping. It *is* the product (the matrix is ROGUE's signature visual) and it still collapses to a clean flat/mono form at favicon size.

**Locked colors:** green `#00ff88` (defended/alive) · red `#ff003c` (breach, accent only) · background `#050508`. Green = defended/alive, red = breach — never invert. Wordmark is **Geist Mono Bold**, all-caps, tracked open. Display/editorial serif pairing is **Newsreader** (per the launch trailer).

---

## File manifest

### `brand-svg/` — scalable source logos
| File | What it is |
|---|---|
| `logomark.svg` | The evolved mark (gradients + glow + ping), transparent. The core glyph. |
| `logomark-plate.svg` | The mark on a rounded deep-dark plate. Avatars / app icon. |
| `wordmark.svg` / `wordmark-white.svg` | "ROGUE" in Geist Mono Bold, green / off-white. |
| `logo-horizontal.svg` / `-white.svg` | **Primary lockup** (mark + wordmark), green / white wordmark. |
| `logo-stacked.svg` | Mark above, wordmark below. Square-ish spaces. |
| `logomark-mono-green/white/black.svg` | Flat single-color mark, breach drawn as a hollow square so it reads in one color. Favicons, print, stamps. |

### `animated/` — SMIL motion logos
`logomark-animated.svg` (on plate) · `logomark-animated-transparent.svg` — live cells breathe, the breach pulses, the ping expands. For web headers / loaders.

### `app-router/` — drop into `src/app/`
`icon.svg` (16px-legible favicon mark) · `apple-icon.png` (180²) · `favicon.ico` (16/32/48/256 multi-res) · `opengraph-image.png` (1200×630, key-art-led).

### `png/` — raster exports (transparent unless noted)
`logomark-512.png` · `logomark-64.png` · `avatar-512.png` / `avatar-1024.png` (mark on plate).

### `light/` — light-background variants
`logomark-light.svg` · `logo-horizontal-light.svg` · `logomark-light-512.png` (darker greens/red for legibility on light).

### `social/` — share images (4K, 3840×2016, 1.905:1 OG ratio)
| File | What it is |
|---|---|
| `opengraph-image-LIVE-matrix-led.{png,svg}` | OG card — the **breach-wall key-art** behind the lockup + tagline + `model · human gate · agent memory — all signed`. PNG is canonical (uses key-art); SVG is a vector source (no photo). |
| `social-card-three-surfaces-DOCS-github.{png,svg}` | Explainer card — the three signed surfaces, labelled. |

### `key-art/` — cinematic brand imagery (new, 5504×3072 ultra-HD)
`keyart-breach-wall.png` — the breach matrix as a 3D wall, one tile breached red with rings (Higgsfield, Nano Banana, 4K). `keyart-scan-field.png` — a dark grid horizon with a green scan-line and a red flare. Wallpapers / hero backdrops / card backgrounds.

### Resolutions
Cards 3840×2016 (4K). Key-art 5504×3072. Avatars 512/1024. Marks are vector (SVG) — infinitely scalable; PNG exports at their named sizes. App-router `opengraph-image.png` is 4K (platforms downscale for meta).

---

*Generated 2026-06-15. Marks are hand-authored vector (faithful geometry, not AI-traced); cards are canvas-composited; key-art is Higgsfield-generated. Palette and breach-grid concept are identical to `assets/brand/` — this is the elevated twin, not a different brand.*
