"""The shareable ROGUE breach report card — the screenshot-worthy artifact `rogue try` /
`rogue scan` emits and the leaderboard displays.

This is a design centerpiece, not a generic chart. The hero is ROGUE's signature **breach grid**
(a 3×3 cut of the matrix) with cells lit red proportional to the measured breach rate, anchored by
one huge headline stat — "6/10 BREACHED". It is unmistakably ROGUE-branded: the locked palette
(green ``#00ff88`` defended, red ``#ff003c`` breach, background ``#050508``), Geist-Mono-style
all-caps tracked typography, the logomark + wordmark, the tagline, and a footer URL.

Three artifacts come out, in order of how brand-native they are:

* **SVG** — canonical. The breach grid is real vector geometry (gradients + glow + radar ping),
  crisp at any size, no font fetch. This is the share asset.
* **HTML** — a self-contained standalone page (inline CSS, embedded SVG, monospace fallback stack),
  the artifact you open in a browser / attach to an email.
* **PNG** — a real raster, drawn directly with Pillow (already a project dependency). We deliberately
  do **not** pull in ``cairosvg`` or a headless browser to rasterize the SVG — the spec forbids
  adding a heavy/browser dependency, so the PNG is a parallel Pillow render, and if Pillow is somehow
  unavailable we return ``png: None`` and the SVG/HTML stay canonical.

Pure: zero network, zero API keys, works from a plain ``dict``.
"""

from __future__ import annotations

import html as _html
from pathlib import Path

# --- locked brand tokens (see docs/launch/VIRAL_LAUNCH_SPEC.md — NO substitutes) -----------------
GREEN = "#00ff88"  # defended / alive
RED = "#ff003c"  # breach (accent only, never invert)
BG = "#050508"  # background

# Supporting greys (dashboard chrome) — derived, not new brand colors.
_INK = "#e8ecea"  # near-white body text
_MUTE = "#7d8a84"  # muted label grey
_DIM_CELL_TOP = "#15281f"  # dim/unlit grid cell gradient
_DIM_CELL_BOT = "#0a1611"
_PLATE = "#0a0c0f"  # inner card plate (one notch up from BG)
_HAIRLINE = "#1c2420"  # hairline divider / cell stroke

# A monospace stack that prefers Geist Mono, then common system monos, then generic.
_MONO = (
    "'Geist Mono', 'GeistMono', 'SF Mono', 'SFMono-Regular', ui-monospace, "
    "'JetBrains Mono', 'Roboto Mono', Menlo, Consolas, monospace"
)

# Display label per internal attack-family slug — mirrors `rogue.report._TECHNIQUE_DISPLAY` so the
# card speaks the exact customer vocabulary. Imported lazily to keep this module import-cheap and to
# avoid any chance of a cycle; falls back to a local copy if the import is unavailable.
try:  # pragma: no cover - trivial import guard
    from rogue.report import technique_label as _technique_label
except Exception:  # pragma: no cover

    def _technique_label(family: str) -> str:
        return family.replace("_", " ").title()


def _clamp01(x: float) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def _norm_card(card: dict) -> dict:
    """Normalize the loosely-typed input dict into the exact fields the renderers need, deriving
    anything missing (rate from trials/breaches, top-attack display label) and humanizing labels."""
    trials = int(card.get("trials") or 0)
    breaches = int(card.get("breaches") or 0)
    rate = card.get("breach_rate")
    if rate is None:
        rate = (breaches / trials) if trials else 0.0
    rate = _clamp01(rate)

    raw_top = card.get("top_attack")
    # `top_attack` may arrive as a raw family slug or an already-humane label; humanize a slug,
    # leave a humane label untouched (slugs are lowercase/underscore, labels carry caps/spaces).
    if raw_top and raw_top == str(raw_top).lower() and " " not in str(raw_top):
        top_attack = _technique_label(str(raw_top))
    else:
        top_attack = str(raw_top) if raw_top else None

    families = card.get("families") or []
    n_families = len({str(f) for f in families}) if families else 0

    tier = str(card.get("tier") or "quick").lower()
    if tier not in ("quick", "calibrated"):
        tier = "quick"

    return {
        "model_label": str(card.get("model_label") or "unknown model"),
        "breach_rate": rate,
        "trials": trials,
        "breaches": breaches,
        "top_attack": top_attack,
        "n_families": n_families,
        "tier": tier,
        "generated_at": str(card.get("generated_at") or ""),
    }


# --- breach-grid geometry -----------------------------------------------------------------------
# A 3×3 cut of the matrix. We light `breaches`-of-`trials` worth of cells red (rounded to the grid),
# the rest defended green, in a fixed visually-balanced order so the card reads the same every time
# for a given rate. The single most-breached cell gets the radar ping (the signature flourish).
#
# Lighting order chosen so low rates breach the visually-weighted corner first and the pattern grows
# coherently — never a random scatter.
_BREACH_ORDER = [8, 2, 6, 5, 7, 1, 3, 4, 0]  # cell indices 0..8, row-major (0=TL, 8=BR)


def _lit_cells(rate: float) -> set[int]:
    """Which of the 9 cells are breached (red) for a given rate. A non-zero rate always lights at
    least one cell (a breach happened); a full breach lights all nine."""
    if rate <= 0:
        return set()
    n = max(1, min(9, round(rate * 9)))
    return set(_BREACH_ORDER[:n])


def _ping_cell(lit: set[int]) -> int:
    """The cell carrying the radar ping — the first breached cell in lighting order (the flourish
    anchors on the 'first' breach), or the canonical breach cell when nothing is lit."""
    for idx in _BREACH_ORDER:
        if idx in lit:
            return idx
    return 5  # canonical breach cell (mirrors the brand logomark) when fully defended


# --- shared content prep ------------------------------------------------------------------------
def _headline_parts(c: dict) -> tuple[str, str]:
    """The two halves of the hero stat: the big "N/M" count and the "BREACHED" word."""
    return f"{c['breaches']}/{c['trials']}", "BREACHED"


def _tier_chip_text(tier: str) -> str:
    return (
        "calibrated judge ✓"
        if tier == "calibrated"
        else "quick scan — upgrade for calibrated judge"
    )


TAGLINE = "The red-team that never sleeps."
FOOTER_URL = "rogue-eosin.vercel.app"
_FOOTER_FULL = "https://rogue-eosin.vercel.app"


# ================================================================================================
# SVG renderer (canonical) — one function parameterized by canvas, used for both OG and square.
# ================================================================================================
def _grid_svg(x: float, y: float, size: float, rate: float, *, cell_id: str) -> str:
    """The breach grid as an embedded SVG group: 3×3 rounded cells, defended green (glowing), the
    breached fraction red (strong glow), a radar ping on the lead breach cell. Self-contained — its
    own gradient/filter defs are namespaced by ``cell_id`` so two grids can coexist in one document."""
    lit = _lit_cells(rate)
    ping = _ping_cell(lit)
    gap = size * 0.075
    cell = (size - 2 * gap) / 3
    radius = cell * 0.2
    g = f"g_{cell_id}"
    gd = f"gd_{cell_id}"
    r = f"r_{cell_id}"
    glow = f"glow_{cell_id}"
    rglow = f"rglow_{cell_id}"

    defs = (
        f'<defs>'
        f'<linearGradient id="{g}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#3dffab"/><stop offset="1" stop-color="#00d472"/></linearGradient>'
        f'<linearGradient id="{gd}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{_DIM_CELL_TOP}"/><stop offset="1" stop-color="{_DIM_CELL_BOT}"/></linearGradient>'
        f'<linearGradient id="{r}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#ff4f6c"/><stop offset="1" stop-color="{RED}"/></linearGradient>'
        f'<filter id="{glow}" x="-60%" y="-60%" width="220%" height="220%">'
        f'<feGaussianBlur stdDev="{cell * 0.07:.1f}" result="b"/>'
        f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        f'<filter id="{rglow}" x="-90%" y="-90%" width="280%" height="280%">'
        f'<feGaussianBlur stdDev="{cell * 0.12:.1f}" result="b"/>'
        f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        f'</defs>'
    )

    dim_rects: list[str] = []
    green_rects: list[str] = []
    red_rects: list[str] = []
    for idx in range(9):
        row, col = divmod(idx, 3)
        cx = x + gap * 0 + col * (cell + gap)
        cy = y + row * (cell + gap)
        rect = (
            f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cell:.1f}" height="{cell:.1f}" '
            f'rx="{radius:.1f}" '
        )
        if idx in lit:
            red_rects.append(rect + f'fill="url(#{r})"/>')
        else:
            # A handful of defended cells stay "dim" (unlit substrate) for depth; the rest glow green.
            if idx in (0, 4, 8) and idx not in lit:
                dim_rects.append(rect + f'fill="url(#{gd})"/>')
            else:
                green_rects.append(rect + f'fill="url(#{g})" opacity="0.94"/>')

    # Radar ping rings, centered on the lead breach (or canonical) cell.
    prow, pcol = divmod(ping, 3)
    pcx = x + pcol * (cell + gap) + cell / 2
    pcy = y + prow * (cell + gap) + cell / 2
    ping_color = RED if lit else GREEN
    rings = (
        f'<circle cx="{pcx:.1f}" cy="{pcy:.1f}" r="{cell * 0.95:.1f}" fill="none" '
        f'stroke="{ping_color}" stroke-width="{cell * 0.03:.1f}" opacity="0.14"/>'
        f'<circle cx="{pcx:.1f}" cy="{pcy:.1f}" r="{cell * 0.66:.1f}" fill="none" '
        f'stroke="{ping_color}" stroke-width="{cell * 0.04:.1f}" opacity="0.3"/>'
    )

    return (
        f"{defs}{rings}"
        f"{''.join(dim_rects)}"
        f'<g filter="url(#{glow})">{"".join(green_rects)}</g>'
        f'<g filter="url(#{rglow})">{"".join(red_rects)}</g>'
    )


def _wordmark_svg(x: float, y: float, scale: float) -> str:
    """The ROGUE logomark (compact 3×3 glyph) + wordmark text, drawn as vector at (x, y).

    The wordmark text uses the monospace font stack (Geist-Mono-first) rather than embedding the
    hand-traced glyph paths, so it stays legible and tracks open like the brand wordmark while
    keeping this module self-contained (no font fetch). The mark beside it is the breach glyph."""
    mark = _logomark_glyph_svg(x, y, 36 * scale)
    tx = x + 36 * scale + 14 * scale
    ty = y + 27 * scale
    text = (
        f'<text x="{tx:.1f}" y="{ty:.1f}" font-family="{_html.escape(_MONO)}" '
        f'font-size="{30 * scale:.1f}" font-weight="700" letter-spacing="{6 * scale:.1f}" '
        f'fill="{_INK}">ROGUE</text>'
    )
    return mark + text


def _logomark_glyph_svg(x: float, y: float, size: float) -> str:
    """A compact ROGUE logomark: a small 3×3 with the canonical breach cell red. Used in the corner
    lockup (distinct from the hero grid). No filters — stays crisp at small size."""
    gap = size * 0.1
    cell = (size - 2 * gap) / 3
    rad = cell * 0.22
    parts: list[str] = []
    for idx in range(9):
        row, col = divmod(idx, 3)
        cx = x + col * (cell + gap)
        cy = y + row * (cell + gap)
        if idx == 5:  # canonical breach
            fill = RED
        elif idx in (1, 4, 6):
            fill = GREEN
        else:
            fill = "#16281e"
        parts.append(
            f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cell:.1f}" height="{cell:.1f}" '
            f'rx="{rad:.1f}" fill="{fill}"/>'
        )
    return "".join(parts)


def _build_svg(c: dict, *, w: int, h: int, square: bool) -> str:
    """Render the full card as one self-contained SVG string at the given canvas size."""
    rate = c["breach_rate"]
    count, breached_word = _headline_parts(c)
    pct = round(rate * 100)
    accent = RED if rate > 0 else GREEN
    e = _html.escape

    # Background: OLED black + two soft radial mesh orbs (green alive, red breach) + a faint grid.
    bg = (
        f'<defs>'
        f'<radialGradient id="orbG" cx="22%" cy="18%" r="55%">'
        f'<stop offset="0" stop-color="{GREEN}" stop-opacity="0.10"/>'
        f'<stop offset="1" stop-color="{GREEN}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="orbR" cx="88%" cy="92%" r="55%">'
        f'<stop offset="0" stop-color="{RED}" stop-opacity="0.12"/>'
        f'<stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient>'
        f'<pattern id="mesh" width="48" height="48" patternUnits="userSpaceOnUse">'
        f'<path d="M48 0H0V48" fill="none" stroke="{_HAIRLINE}" stroke-width="1" opacity="0.5"/>'
        f'</pattern>'
        f'</defs>'
        f'<rect width="{w}" height="{h}" fill="{BG}"/>'
        f'<rect width="{w}" height="{h}" fill="url(#mesh)"/>'
        f'<rect width="{w}" height="{h}" fill="url(#orbG)"/>'
        f'<rect width="{w}" height="{h}" fill="url(#orbR)"/>'
    )

    # Inner plate (double-bezel: card content sits on a plate inset from the canvas with a hairline).
    pad = 40 if square else 44
    plate_r = 28
    plate = (
        f'<rect x="{pad}" y="{pad}" width="{w - 2 * pad}" height="{h - 2 * pad}" '
        f'rx="{plate_r}" fill="{_PLATE}" fill-opacity="0.55" '
        f'stroke="{_HAIRLINE}" stroke-width="1.5"/>'
    )

    cx = pad + 36  # content left edge

    # --- corner lockup -------------------------------------------------------------------------
    lockup = _wordmark_svg(cx, pad + 30, 1.0)

    # --- tier chip (top-right) -----------------------------------------------------------------
    chip_text = _tier_chip_text(c["tier"])
    chip_fill = GREEN if c["tier"] == "calibrated" else _MUTE
    # Approximate chip width from text length (monospace ~ 0.6em advance at 17px).
    chip_w = max(150, int(len(chip_text) * 10.2) + 36)
    chip_x = w - pad - 36 - chip_w
    chip_y = pad + 34
    chip = (
        f'<rect x="{chip_x}" y="{chip_y}" width="{chip_w}" height="34" rx="17" '
        f'fill="{chip_fill}" fill-opacity="0.10" stroke="{chip_fill}" stroke-opacity="0.45" stroke-width="1"/>'
        f'<text x="{chip_x + chip_w / 2:.0f}" y="{chip_y + 23}" text-anchor="middle" '
        f'font-family="{e(_MONO)}" font-size="14.5" letter-spacing="0.6" '
        f'fill="{chip_fill}">{e(chip_text)}</text>'
    )

    # --- hero: grid + headline -----------------------------------------------------------------
    if square:
        grid_size = 360
        grid_x = (w - grid_size) / 2
        grid_y = pad + 110
        grid = _grid_svg(grid_x, grid_y, grid_size, rate, cell_id="hero")
        hy = grid_y + grid_size + 96
        headline = (
            f'<text x="{w / 2:.0f}" y="{hy:.0f}" text-anchor="middle" font-family="{e(_MONO)}" '
            f'font-size="118" font-weight="700" letter-spacing="-1" fill="{accent}" '
            f'font-variant-numeric="tabular-nums">{e(count)}</text>'
            f'<text x="{w / 2:.0f}" y="{hy + 76:.0f}" text-anchor="middle" font-family="{e(_MONO)}" '
            f'font-size="52" font-weight="700" letter-spacing="14" fill="{_INK}">{e(breached_word)}</text>'
            f'<text x="{w / 2:.0f}" y="{hy + 118:.0f}" text-anchor="middle" font-family="{e(_MONO)}" '
            f'font-size="22" letter-spacing="3" fill="{_MUTE}">{pct}% BREACH RATE</text>'
        )
        meta_y = hy + 168
        meta_anchor = w / 2
        meta_center = True
    else:
        grid_size = 300
        grid_x = cx
        grid_y = pad + 96
        grid = _grid_svg(grid_x, grid_y, grid_size, rate, cell_id="hero")
        hx = grid_x + grid_size + 56
        hy = grid_y + 120
        headline = (
            f'<text x="{hx:.0f}" y="{hy:.0f}" font-family="{e(_MONO)}" '
            f'font-size="150" font-weight="700" letter-spacing="-2" fill="{accent}" '
            f'font-variant-numeric="tabular-nums">{e(count)}</text>'
            f'<text x="{hx:.0f}" y="{hy + 72:.0f}" font-family="{e(_MONO)}" '
            f'font-size="58" font-weight="700" letter-spacing="16" fill="{_INK}">{e(breached_word)}</text>'
            f'<text x="{hx:.0f}" y="{hy + 116:.0f}" font-family="{e(_MONO)}" '
            f'font-size="23" letter-spacing="3" fill="{_MUTE}">{pct}% BREACH RATE</text>'
        )
        meta_y = grid_y + grid_size + 40
        meta_anchor = cx
        meta_center = False

    # --- metadata row: model · top attack · families ------------------------------------------
    top_attack = c["top_attack"] or "— none breached"
    fam_word = "family" if c["n_families"] == 1 else "families"
    metas = [
        ("MODEL", c["model_label"]),
        ("TOP ATTACK", top_attack),
        ("COVERAGE", f"{c['trials']} trials · {c['n_families']} {fam_word}"),
    ]
    meta_parts: list[str] = []
    if meta_center:
        # Stacked, centered for the square.
        for i, (label, val) in enumerate(metas):
            yy = meta_y + i * 52
            meta_parts.append(
                f'<text x="{meta_anchor:.0f}" y="{yy:.0f}" text-anchor="middle" '
                f'font-family="{e(_MONO)}" font-size="14" letter-spacing="3" fill="{_MUTE}">{label}</text>'
                f'<text x="{meta_anchor:.0f}" y="{yy + 24:.0f}" text-anchor="middle" '
                f'font-family="{e(_MONO)}" font-size="22" fill="{_INK}">{e(_clip(val, 34))}</text>'
            )
    else:
        # A row of three labelled columns for the OG card.
        col_w = (w - 2 * pad - 72) / 3
        for i, (label, val) in enumerate(metas):
            mx = cx + i * col_w
            meta_parts.append(
                f'<text x="{mx:.0f}" y="{meta_y:.0f}" font-family="{e(_MONO)}" '
                f'font-size="14" letter-spacing="3" fill="{_MUTE}">{label}</text>'
                f'<text x="{mx:.0f}" y="{meta_y + 30:.0f}" font-family="{e(_MONO)}" '
                f'font-size="23" fill="{_INK}">{e(_clip(val, 26))}</text>'
            )
        # Hairline above the metadata row.
        meta_parts.insert(
            0,
            f'<line x1="{cx}" y1="{meta_y - 36}" x2="{w - pad - 36}" y2="{meta_y - 36}" '
            f'stroke="{_HAIRLINE}" stroke-width="1.5"/>',
        )

    # --- footer: tagline + url -----------------------------------------------------------------
    fy = h - pad - 34
    footer = (
        f'<text x="{cx:.0f}" y="{fy:.0f}" font-family="{e(_MONO)}" font-size="20" '
        f'letter-spacing="1" fill="{GREEN}">{e(TAGLINE)}</text>'
        f'<text x="{w - pad - 36:.0f}" y="{fy:.0f}" text-anchor="end" font-family="{e(_MONO)}" '
        f'font-size="18" letter-spacing="1" fill="{_MUTE}">{e(FOOTER_URL)}</text>'
    )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="ROGUE breach report card: '
        f'{e(count)} breached, {c["model_label"]}">'
        f"{bg}{plate}{lockup}{chip}{grid}{headline}{''.join(meta_parts)}{footer}"
        f"</svg>"
    )


def _clip(text: str, n: int) -> str:
    text = str(text)
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ================================================================================================
# HTML renderer — self-contained standalone page wrapping the canonical SVG.
# ================================================================================================
def _build_html(c: dict, og_svg: str, square_svg: str) -> str:
    count, _ = _headline_parts(c)
    e = _html.escape
    title = f"ROGUE — {count} breached · {c['model_label']}"
    # The page is intentionally minimal: it presents the canonical SVG card (which already carries
    # the full design) centered on the brand background, plus a small caption. Self-contained.
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(TAGLINE)} — {_FOOTER_FULL}">
<meta name="twitter:card" content="summary_large_image">
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; height: 100%; }}
  body {{
    background: {BG};
    color: {_INK};
    font-family: {_MONO};
    -webkit-font-smoothing: antialiased;
    text-rendering: optimizeLegibility;
    display: flex; flex-direction: column; align-items: center;
    gap: 28px; padding: 48px 24px; min-height: 100dvh;
  }}
  .cards {{ display: flex; flex-wrap: wrap; gap: 28px; justify-content: center; align-items: flex-start; }}
  figure {{ margin: 0; }}
  .card {{
    border-radius: 22px; overflow: hidden; line-height: 0;
    box-shadow: 0 1px 0 rgba(255,255,255,0.04) inset,
                0 24px 60px -20px rgba(0,0,0,0.8),
                0 0 0 1px rgba(0,255,136,0.07);
    outline: 1px solid rgba(255,255,255,0.06); outline-offset: -1px;
  }}
  .card svg {{ display: block; width: 100%; height: auto; }}
  .og {{ width: min(760px, 92vw); }}
  .sq {{ width: min(520px, 92vw); }}
  figcaption {{
    margin-top: 12px; text-align: center; font-size: 12px; letter-spacing: 2px;
    text-transform: uppercase; color: {_MUTE}; line-height: 1.4;
  }}
  .tag {{ color: {GREEN}; }}
</style></head>
<body>
  <div class="cards">
    <figure><div class="card og">{og_svg}</div>
      <figcaption>1200 × 630 · link / OG card</figcaption></figure>
    <figure><div class="card sq">{square_svg}</div>
      <figcaption>1080 × 1080 · square</figcaption></figure>
  </div>
  <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{_MUTE}">
    <span class="tag">{e(TAGLINE)}</span> &nbsp;·&nbsp; {e(_FOOTER_FULL)}
  </div>
</body></html>"""


# ================================================================================================
# PNG renderer — direct Pillow raster (dependency-light; Pillow is already a project dep). We do NOT
# rasterize the SVG via cairosvg/a browser — the spec forbids adding a heavy/browser dependency.
# ================================================================================================
def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _load_mono_font(size: int):
    """Best-effort monospace truetype font at the given size. Tries Geist Mono if bundled, then
    common system monos; falls back to Pillow's default bitmap font (PNG still renders)."""
    from PIL import ImageFont

    candidates = [
        # A bundled Geist Mono, if a future asset drop adds one (kept first so it wins).
        str(Path(__file__).resolve().parent / "data" / "GeistMono-Bold.ttf"),
        str(Path(__file__).resolve().parent / "data" / "GeistMono-Regular.ttf"),
        # macOS system monos.
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        # Common Linux monos (CI).
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            continue
    try:  # pragma: no cover - environment-dependent fallback
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - very old Pillow
        return ImageFont.load_default()


def _build_png(c: dict, out_path: Path, *, w: int, h: int, square: bool) -> Path | None:
    """Draw the OG/square card directly with Pillow. Returns the path, or None if Pillow is absent."""
    try:
        from PIL import Image, ImageDraw
    except Exception:  # pragma: no cover - Pillow is a declared dep, but stay graceful
        return None

    rate = c["breach_rate"]
    count, breached_word = _headline_parts(c)
    pct = round(rate * 100)
    accent = RED if rate > 0 else GREEN
    green, red, ink, mute, hair = (
        _hex(GREEN),
        _hex(RED),
        _hex(_INK),
        _hex(_MUTE),
        _hex(_HAIRLINE),
    )

    img = Image.new("RGB", (w, h), _hex(BG))
    d = ImageDraw.Draw(img, "RGBA")

    # Background mesh grid + soft radial orbs (orbs approximated with translucent ellipses).
    for gx in range(0, w, 48):
        d.line([(gx, 0), (gx, h)], fill=(*hair, 110), width=1)
    for gy in range(0, h, 48):
        d.line([(0, gy), (w, gy)], fill=(*hair, 110), width=1)
    _radial_orb(img, int(w * 0.22), int(h * 0.18), int(min(w, h) * 0.55), green, 26)
    _radial_orb(img, int(w * 0.88), int(h * 0.92), int(min(w, h) * 0.55), red, 30)

    # Inner plate.
    pad = 40 if square else 44
    _rounded_rect(d, (pad, pad, w - pad, h - pad), 28, fill=(10, 12, 15, 140), outline=(*hair, 255), width=2)

    cx = pad + 36
    f_word = _load_mono_font

    # Corner lockup: logomark glyph + ROGUE.
    _png_logomark(d, cx, pad + 30, 36, green, red)
    d.text((cx + 36 + 14, pad + 34), "R O G U E", font=f_word(28), fill=ink)

    # Tier chip (top-right).
    chip_text = _tier_chip_text(c["tier"]).upper()
    chip_color = green if c["tier"] == "calibrated" else mute
    cf = f_word(15)
    tb = d.textbbox((0, 0), chip_text, font=cf)
    chip_w = (tb[2] - tb[0]) + 36
    chip_x = w - pad - 36 - chip_w
    chip_y = pad + 34
    _rounded_rect(
        d,
        (chip_x, chip_y, chip_x + chip_w, chip_y + 34),
        17,
        fill=(*chip_color, 26),
        outline=(*chip_color, 115),
        width=1,
    )
    d.text((chip_x + 18, chip_y + 9), chip_text, font=cf, fill=chip_color)

    # Hero grid + headline.
    if square:
        grid_size = 360
        gx = (w - grid_size) // 2
        gy = pad + 110
        _png_grid(img, d, gx, gy, grid_size, rate, green, red, hair)
        hy = gy + grid_size + 24
        _centered(d, w // 2, hy, count, f_word(112), accent)
        _centered(d, w // 2, hy + 130, breached_word, f_word(46), ink, track=2)
        _centered(d, w // 2, hy + 196, f"{pct}% BREACH RATE", f_word(20), mute, track=2)
        meta_y = hy + 250
        meta_center = True
    else:
        grid_size = 300
        gx = cx
        gy = pad + 96
        _png_grid(img, d, gx, gy, grid_size, rate, green, red, hair)
        hx = gx + grid_size + 56
        hy = gy + 8
        d.text((hx, hy), count, font=f_word(140), fill=accent)
        d.text((hx + 4, hy + 168), breached_word, font=f_word(50), fill=ink)
        d.text((hx + 4, hy + 236), f"{pct}% BREACH RATE", font=f_word(21), fill=mute)
        meta_y = gy + grid_size + 18
        meta_center = False

    # Metadata.
    top_attack = c["top_attack"] or "— none breached"
    fam_word = "family" if c["n_families"] == 1 else "families"
    metas = [
        ("MODEL", _clip(c["model_label"], 28)),
        ("TOP ATTACK", _clip(top_attack, 26)),
        ("COVERAGE", f"{c['trials']} trials · {c['n_families']} {fam_word}"),
    ]
    lf, vf = f_word(14), f_word(22)
    if meta_center:
        for i, (label, val) in enumerate(metas):
            yy = meta_y + i * 54
            _centered(d, w // 2, yy, label, lf, mute, track=3)
            _centered(d, w // 2, yy + 24, val, f_word(20), ink)
    else:
        d.line([(cx, meta_y - 28), (w - pad - 36, meta_y - 28)], fill=(*hair, 255), width=2)
        col_w = (w - 2 * pad - 72) / 3
        for i, (label, val) in enumerate(metas):
            mx = cx + int(i * col_w)
            d.text((mx, meta_y), label, font=lf, fill=mute)
            d.text((mx, meta_y + 26), val, font=vf, fill=ink)

    # Footer.
    fy = h - pad - 44
    d.text((cx, fy), TAGLINE, font=f_word(20), fill=green)
    uf = f_word(18)
    ub = d.textbbox((0, 0), FOOTER_URL, font=uf)
    d.text((w - pad - 36 - (ub[2] - ub[0]), fy + 2), FOOTER_URL, font=uf, fill=mute)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path


def _centered(d, cx: int, y: int, text: str, font, fill, *, track: int = 0) -> None:
    """Draw horizontally-centered text. ``track`` > 0 approximates open letter-spacing by inserting
    spaces between characters (Pillow has no native tracking) — used for the small tracked labels."""
    if track:
        text = " ".join(list(text))
    bb = d.textbbox((0, 0), text, font=font)
    d.text((cx - (bb[2] - bb[0]) // 2, y), text, font=font, fill=fill)


def _rounded_rect(d, box, radius, *, fill=None, outline=None, width=1) -> None:
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _radial_orb(img, cx: int, cy: int, r: int, color, max_alpha: int) -> None:
    """Composite a soft radial glow centered at (cx, cy) onto the base image (cheap multi-ring)."""
    from PIL import Image, ImageDraw

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    rings = 20
    for i in range(rings, 0, -1):
        rr = int(r * i / rings)
        a = int(max_alpha * (1 - i / rings) ** 2)
        if a <= 0:
            continue
        od.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=(*color, a))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _png_grid(img, d, x: int, y: int, size: int, rate: float, green, red, hair) -> None:
    """The breach grid in Pillow: 3×3 rounded cells, defended green / breached red, a radar ping."""
    from PIL import Image, ImageDraw, ImageFilter

    lit = _lit_cells(rate)
    ping = _ping_cell(lit)
    gap = size * 0.075
    cell = (size - 2 * gap) / 3
    radius = int(cell * 0.2)

    # Draw glowing cells onto an overlay we blur, then the crisp cells on top — gives the soft glow.
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for idx in range(9):
        row, col = divmod(idx, 3)
        cxx = int(x + col * (cell + gap))
        cyy = int(y + row * (cell + gap))
        box = (cxx, cyy, int(cxx + cell), int(cyy + cell))
        color = red if idx in lit else green
        gd.rounded_rectangle(box, radius=radius, fill=(*color, 150 if idx in lit else 90))
    glow = glow.filter(ImageFilter.GaussianBlur(int(cell * 0.12)))
    img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"), (0, 0))

    # Re-bind the draw context to the (now glow-composited) image.
    d2 = ImageDraw.Draw(img, "RGBA")
    for idx in range(9):
        row, col = divmod(idx, 3)
        cxx = int(x + col * (cell + gap))
        cyy = int(y + row * (cell + gap))
        box = (cxx, cyy, int(cxx + cell), int(cyy + cell))
        if idx in lit:
            d2.rounded_rectangle(box, radius=radius, fill=red)
        elif idx in (0, 4, 8) and idx not in lit:
            d2.rounded_rectangle(box, radius=radius, fill=_hex(_DIM_CELL_TOP))
        else:
            d2.rounded_rectangle(box, radius=radius, fill=green)

    prow, pcol = divmod(ping, 3)
    pcx = int(x + pcol * (cell + gap) + cell / 2)
    pcy = int(y + prow * (cell + gap) + cell / 2)
    ping_color = red if lit else green
    for rr, a, wdt in ((cell * 0.95, 36, 3), (cell * 0.66, 76, 4)):
        d2.ellipse(
            (pcx - rr, pcy - rr, pcx + rr, pcy + rr),
            outline=(*ping_color, a),
            width=wdt,
        )


def _png_logomark(d, x: int, y: int, size: int, green, red) -> None:
    gap = size * 0.1
    cell = (size - 2 * gap) / 3
    rad = int(cell * 0.22)
    for idx in range(9):
        row, col = divmod(idx, 3)
        cxx = int(x + col * (cell + gap))
        cyy = int(y + row * (cell + gap))
        box = (cxx, cyy, int(cxx + cell), int(cyy + cell))
        if idx == 5:
            fill = red
        elif idx in (1, 4, 6):
            fill = green
        else:
            fill = _hex("#16281e")
        d.rounded_rectangle(box, radius=rad, fill=fill)


# ================================================================================================
# Public entry point
# ================================================================================================
def render_breach_card(card: dict, out_dir: Path) -> dict:
    """Render the shareable ROGUE breach report card into ``out_dir``.

    ``card`` keys (loosely typed; missing fields are derived/defaulted):
        ``model_label`` str, ``breach_rate`` float(0-1), ``trials`` int, ``breaches`` int,
        ``top_attack`` str (family slug or humane label), ``families`` list[str],
        ``verdict_counts`` dict[str,int] (accepted for forward-compat, not required for the visual),
        ``tier`` str ('quick'|'calibrated'), ``generated_at`` str.

    Writes (and returns absolute paths to):
        * ``breach-card.svg``        — the 1200×630 OG card (canonical, brand-native vector).
        * ``breach-card-square.svg`` — the 1080×1080 square variant.
        * ``breach-card.png``        — a 1200×630 raster (Pillow; ``None`` if Pillow is unavailable).
        * ``breach-card.html``       — a self-contained page showing both cards.

    Returns ``{"html": Path, "png": Path|None, "svg": Path}`` (the SVG is the canonical share asset;
    the square SVG is written alongside and referenced from the HTML). Pure: no network, no keys.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    c = _norm_card(card)

    og_svg = _build_svg(c, w=1200, h=630, square=False)
    square_svg = _build_svg(c, w=1080, h=1080, square=True)

    svg_path = out_dir / "breach-card.svg"
    square_path = out_dir / "breach-card-square.svg"
    html_path = out_dir / "breach-card.html"
    svg_path.write_text(og_svg, encoding="utf-8")
    square_path.write_text(square_svg, encoding="utf-8")
    html_path.write_text(_build_html(c, og_svg, square_svg), encoding="utf-8")

    png_path: Path | None = None
    try:
        png_path = _build_png(c, out_dir / "breach-card.png", w=1200, h=630, square=False)
        # Square PNG too (best-effort; not part of the return contract).
        _build_png(c, out_dir / "breach-card-square.png", w=1080, h=1080, square=True)
    except Exception:  # pragma: no cover - never let raster failure break the canonical SVG/HTML
        png_path = None

    return {"html": html_path.resolve(), "png": png_path.resolve() if png_path else None,
            "svg": svg_path.resolve()}


__all__ = ["render_breach_card", "TAGLINE", "FOOTER_URL", "GREEN", "RED", "BG"]
