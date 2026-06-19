"""Render the COMPOSITE breach leaderboard card — one shareable image ranking every model ROGUE has
measured, in two HONESTLY-SEPARATED panels:

  * PRODUCTION endpoints (8) — measured with the deep escalation+PAIR pipeline (~2k trials each), and
  * OPEN-SOURCE models (16) — measured with the single-shot aggressive jailbreak pack.

The two panels are NEVER merged into one ranking: the methodologies differ, so a production model's
low rate is not directly comparable to an open-source model's rate. Each panel ranks within itself
(most-resistant at top → most-permissive at bottom) on its own 0–100% axis, and a footer states the
caveat in plain words. This mirrors the deliberate split on the public /leaderboard.

Brand: background #050508, a faint breach-grid, a 2×2 breach-grid wordmark + "ROGUE", Geist-Mono
(system-mono fallback), and the load-bearing metaphor — each bar is a GREEN "defended" track with a
RED "breach" fill proportional to the measured breach rate. No off-brand colors, no interpolated mud.

Emits THREE formats (mirroring `report_card.render_breach_card`):
  * breach-leaderboard.svg  — canonical brand-native vector (crisp at any size)
  * breach-leaderboard.png  — the universal share/social raster (Pillow; SVG layout mirrored)
  * breach-leaderboard.html — a self-contained page wrapping the SVG

Data: `src/rogue/data/demo_stats.json` (production) + `src/rogue/data/oss_leaderboard_stats.json`
(open-source) — the SAME sources /leaderboard renders from, so the card can never drift. Pillow only
for the raster (no cairosvg / headless browser, per report_card's dependency rule).

Run:  uv run python scripts/cards/generate_composite_card.py
Out:  assets/card/composite/breach-leaderboard.{svg,png,html}  (+ svg & png copied to public/cards/)
"""

from __future__ import annotations

import html as _html
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT / "src"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rogue.report_card import BG, GREEN, RED, _INK, _MONO, _MUTE, _load_mono_font  # noqa: E402


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


# brand RGB — derived from report_card's canonical brand tokens so this card can never drift
_GREEN = _hex(GREEN)
_RED = _hex(RED)
_BG = _hex(BG)
_INK_RGB = _hex(_INK)
_MUTE_RGB = _hex(_MUTE)
_GRID = (18, 22, 26)  # card-only chrome (no brand token)
_GRID_HEX = "#121619"
_TRACK = (22, 82, 58)  # muted-green "defended" track — visibly green so the metaphor reads
_TRACK_HEX = "#16523a"
_PANEL = (10, 12, 15)
_PANEL_HEX = "#0a0c0f"

# --- canvas geometry (shared by the SVG + PNG renderers, identical coordinates) -----------------
W, H = 1600, 1500
PAD = 64
HEADER_H = 232
FOOTER_H = 116
GUTTER = 40
COL_W = (W - 2 * PAD - GUTTER) // 2
LEFT_X = PAD
RIGHT_X = PAD + COL_W + GUTTER
PANEL_HEAD_H = 84
ROWS_TOP = HEADER_H + PANEL_HEAD_H + 18
ROWS_BOTTOM = H - FOOTER_H - 28
BAR_INSET = 30  # bar left offset from the panel edge (room for the rank index)
BAR_RIGHT_PAD = 96  # room for the right-aligned pct
BAR_H = 18
_MEASURED = "2026-06-19"
_URL = "rogue-eosin.vercel.app/leaderboard"
_CHAR_W = 0.6  # monospace advance ≈ 0.6em, for char-count clipping in the SVG path


def _load(name: str) -> list[dict]:
    return json.loads((_ROOT / "src" / "rogue" / "data" / name).read_text())["models"]


def _ranked(models: list[dict]) -> list[dict]:
    """Most-resistant first; carry the computed bar geometry each row shares across renderers."""
    rk = sorted(models, key=lambda m: m["mean_breach_rate"])
    row_h = (ROWS_BOTTOM - ROWS_TOP) / max(len(rk), 1)
    return [
        {"i": i, "rate": float(m["mean_breach_rate"]), "label": m["model_label"],
         "ry": ROWS_TOP + i * row_h}
        for i, m in enumerate(rk)
    ]


def _pct_color(rate: float, *, rgb: bool):
    if rate >= 0.33:
        return _RED if rgb else RED
    if rate <= 0.10:
        return _GREEN if rgb else GREEN
    return _INK_RGB if rgb else _INK


def _clip_chars(text: str, max_px: float, font_px: float) -> str:
    max_chars = max(1, int(max_px / (font_px * _CHAR_W)))
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


# 2×2 breach-grid wordmark mark: 3 defended (green) + 1 breached (red), bottom-left.
_MARK = [(0, 0, "g"), (1, 0, "g"), (0, 1, "r"), (1, 1, "g")]
_MARK_CELL = 18
_MARK_GAP = 5
_MARK_X = PAD
_MARK_Y = 46


# ================================================================================================
# SVG renderer — canonical, brand-native vector
# ================================================================================================
def _build_svg(prod: list[dict], oss: list[dict]) -> str:
    e = _html.escape
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="ROGUE breach leaderboard: 24 models ranked across two panels">',
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
    ]
    # faint breach-grid
    for x in range(0, W, 56):
        parts.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}" stroke="{_GRID_HEX}" stroke-width="1"/>')
    for y in range(0, H, 56):
        parts.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="{_GRID_HEX}" stroke-width="1"/>')

    # --- header: wordmark mark + ROGUE + title + subtitle ---
    for cx, cy, kind in _MARK:
        mx = _MARK_X + cx * (_MARK_CELL + _MARK_GAP)
        my = _MARK_Y + cy * (_MARK_CELL + _MARK_GAP)
        fill = RED if kind == "r" else GREEN
        op = "" if kind == "r" else ' opacity="0.92"'
        parts.append(
            f'<rect x="{mx}" y="{my}" width="{_MARK_CELL}" height="{_MARK_CELL}" rx="3" '
            f'fill="{fill}"{op}/>'
        )
    wx = _MARK_X + 2 * (_MARK_CELL + _MARK_GAP) + 22
    parts.append(
        f'<text x="{wx}" y="{_MARK_Y + 38}" font-family="{e(_MONO)}" font-size="46" '
        f'font-weight="700" letter-spacing="6" fill="{GREEN}">ROGUE</text>'
    )
    parts.append(
        f'<text x="{PAD}" y="{160}" font-family="{e(_MONO)}" font-size="58" font-weight="700" '
        f'letter-spacing="-1" fill="{_INK}">LLM BREACH LEADERBOARD</text>'
    )
    parts.append(
        f'<text x="{PAD}" y="{206}" font-family="{e(_MONO)}" font-size="24" fill="{_MUTE}">'
        f'24 models red-teamed on the live open-web corpus  ·  measured {_MEASURED}</text>'
    )

    # --- panels ---
    parts.append(_svg_panel(LEFT_X, oss, "OPEN-SOURCE  ·  16 models",
                            "single-shot jailbreak pack · primitive-level any-breach"))
    parts.append(_svg_panel(RIGHT_X, prod, "PRODUCTION  ·  8 endpoints",
                            "deep red-team · escalation + PAIR (~2k trials each)"))

    # --- footer ---
    fy = H - FOOTER_H + 12
    parts.append(f'<line x1="{PAD}" y1="{fy}" x2="{W - PAD}" y2="{fy}" stroke="{_GRID_HEX}" stroke-width="1"/>')
    parts.append(
        f'<text x="{PAD}" y="{fy + 32}" font-family="{e(_MONO)}" font-size="18" fill="{_MUTE}">'
        f'Two methodologies — not directly comparable. Each panel ranks within itself; '
        f'bar = breach rate (red) vs defended (green).</text>'
    )
    parts.append(
        f'<text x="{PAD}" y="{fy + 62}" font-family="{e(_MONO)}" font-size="18" fill="{_MUTE}">'
        f'continuous open-web LLM red-team</text>'
    )
    parts.append(
        f'<text x="{W - PAD}" y="{fy + 62}" text-anchor="end" font-family="{e(_MONO)}" '
        f'font-size="18" fill="{GREEN}">{_URL}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _svg_panel(x0: int, models: list[dict], kicker: str, method: str) -> str:
    e = _html.escape
    p: list[str] = []
    y = HEADER_H
    p.append(f'<rect x="{x0}" y="{y}" width="{COL_W}" height="{PANEL_HEAD_H}" fill="{_PANEL_HEX}"/>')
    p.append(f'<rect x="{x0}" y="{y}" width="6" height="{PANEL_HEAD_H}" fill="{GREEN}"/>')
    p.append(
        f'<text x="{x0 + 24}" y="{y + 38}" font-family="{e(_MONO)}" font-size="26" '
        f'font-weight="700" fill="{_INK}">{e(kicker)}</text>'
    )
    method_clipped = _clip_chars(method, COL_W - 48, 17)
    p.append(
        f'<text x="{x0 + 24}" y="{y + 66}" font-family="{e(_MONO)}" font-size="17" '
        f'fill="{_MUTE}">{e(method_clipped)}</text>'
    )
    bar_x = x0 + BAR_INSET
    bar_w = COL_W - BAR_INSET - BAR_RIGHT_PAD
    for r in _ranked(models):
        ry, rate = r["ry"], r["rate"]
        pct = f"{round(rate * 100):d}%"
        p.append(
            f'<text x="{x0}" y="{ry + 18}" font-family="{e(_MONO)}" font-size="18" '
            f'fill="{_MUTE}">{r["i"] + 1:>2}</text>'
        )
        p.append(
            f'<text x="{bar_x}" y="{ry + 16}" font-family="{e(_MONO)}" font-size="21" '
            f'fill="{_INK}">{e(_clip_chars(r["label"], bar_w, 21))}</text>'
        )
        by = ry + 30
        p.append(f'<rect x="{bar_x}" y="{by}" width="{bar_w}" height="{BAR_H}" rx="3" fill="{_TRACK_HEX}"/>')
        fill_w = max(3, int(bar_w * rate)) if rate > 0 else 0
        if fill_w:
            p.append(f'<rect x="{bar_x}" y="{by}" width="{fill_w}" height="{BAR_H}" rx="3" fill="{RED}"/>')
        p.append(
            f'<text x="{x0 + COL_W}" y="{ry + 22}" text-anchor="end" font-family="{e(_MONO)}" '
            f'font-size="26" fill="{_pct_color(rate, rgb=False)}">{pct}</text>'
        )
    return "".join(p)


# ================================================================================================
# HTML renderer — self-contained page wrapping the SVG
# ================================================================================================
def _build_html(svg: str) -> str:
    title = "ROGUE — LLM breach leaderboard · 24 models"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)}</title>
<meta property="og:title" content="{_html.escape(title)}">
<meta property="og:description" content="24 models red-teamed — production (deep pipeline) + open-source (single-shot), two honestly-separated panels.">
<style>html,body{{margin:0;background:{BG};color:{_INK};font-family:{_MONO}}}
.wrap{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px}}
svg{{width:100%;height:auto;max-width:{W}px}}</style>
</head><body><div class="wrap">{svg}</div></body></html>
"""


# ================================================================================================
# PNG renderer — Pillow, mirroring the SVG layout
# ================================================================================================
def _render_png(prod: list[dict], oss: list[dict]) -> Image.Image:
    img = Image.new("RGB", (W, H), _BG)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 56):
        d.line([(x, 0), (x, H)], fill=_GRID, width=1)
    for y in range(0, H, 56):
        d.line([(0, y), (W, y)], fill=_GRID, width=1)

    f_word = _load_mono_font(46)
    f_title = _load_mono_font(58)
    f_sub = _load_mono_font(24)
    f_kick = _load_mono_font(26)
    f_method = _load_mono_font(17)
    f_row = _load_mono_font(21)
    f_pct = _load_mono_font(26)
    f_rank = _load_mono_font(18)
    f_foot = _load_mono_font(18)

    # wordmark mark + ROGUE
    for cx, cy, kind in _MARK:
        mx = _MARK_X + cx * (_MARK_CELL + _MARK_GAP)
        my = _MARK_Y + cy * (_MARK_CELL + _MARK_GAP)
        d.rounded_rectangle([mx, my, mx + _MARK_CELL, my + _MARK_CELL], radius=3,
                            fill=_RED if kind == "r" else _GREEN)
    wx = _MARK_X + 2 * (_MARK_CELL + _MARK_GAP) + 22
    d.text((wx, _MARK_Y - 4), "ROGUE", font=f_word, fill=_GREEN)
    d.text((PAD, 116), "LLM BREACH LEADERBOARD", font=f_title, fill=_INK_RGB)
    d.text((PAD, 186), f"24 models red-teamed on the live open-web corpus  ·  measured {_MEASURED}",
           font=f_sub, fill=_MUTE_RGB)

    fonts = {"kick": f_kick, "method": f_method, "row": f_row, "pct": f_pct, "rank": f_rank}
    _png_panel(d, LEFT_X, oss, "OPEN-SOURCE  ·  16 models",
               "single-shot jailbreak pack · primitive-level any-breach", fonts)
    _png_panel(d, RIGHT_X, prod, "PRODUCTION  ·  8 endpoints",
               "deep red-team · escalation + PAIR (~2k trials each)", fonts)

    fy = H - FOOTER_H + 12
    d.line([(PAD, fy), (W - PAD, fy)], fill=_GRID, width=1)
    d.text((PAD, fy + 18),
           "Two methodologies — not directly comparable. Each panel ranks within itself; bar = breach rate (red) vs defended (green).",
           font=f_foot, fill=_MUTE_RGB)
    d.text((PAD, fy + 48), "continuous open-web LLM red-team", font=f_foot, fill=_MUTE_RGB)
    uw = d.textlength(_URL, font=f_foot)
    d.text((W - PAD - uw, fy + 48), _URL, font=f_foot, fill=_GREEN)
    return img


def _png_clip(d: ImageDraw.ImageDraw, text: str, font, max_w: float) -> str:
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text + "…"


def _png_panel(d: ImageDraw.ImageDraw, x0, models, kicker, method, fonts) -> None:
    y = HEADER_H
    d.rectangle([x0, y, x0 + COL_W, y + PANEL_HEAD_H], fill=_PANEL)
    d.rectangle([x0, y, x0 + 6, y + PANEL_HEAD_H], fill=_GREEN)
    d.text((x0 + 24, y + 16), kicker, font=fonts["kick"], fill=_INK_RGB)
    d.text((x0 + 24, y + 52), _png_clip(d, method, fonts["method"], COL_W - 48),
           font=fonts["method"], fill=_MUTE_RGB)
    bar_x = x0 + BAR_INSET
    bar_w = COL_W - BAR_INSET - BAR_RIGHT_PAD
    for r in _ranked(models):
        ry, rate = r["ry"], r["rate"]
        pct = f"{round(rate * 100):d}%"
        d.text((x0, ry + 4), f"{r['i'] + 1:>2}", font=fonts["rank"], fill=_MUTE_RGB)
        d.text((bar_x, ry), _png_clip(d, r["label"], fonts["row"], bar_w), font=fonts["row"], fill=_INK_RGB)
        by = ry + 30
        d.rounded_rectangle([bar_x, by, bar_x + bar_w, by + BAR_H], radius=3, fill=_TRACK)
        fill_w = max(3, int(bar_w * rate)) if rate > 0 else 0
        if fill_w:
            d.rounded_rectangle([bar_x, by, bar_x + fill_w, by + BAR_H], radius=3, fill=_RED)
        pw = d.textlength(pct, font=fonts["pct"])
        d.text((x0 + COL_W - pw, ry + 6), pct, font=fonts["pct"], fill=_pct_color(rate, rgb=True))


def main() -> int:
    prod = _load("demo_stats.json")
    oss = _load("oss_leaderboard_stats.json")

    svg = _build_svg(prod, oss)
    html = _build_html(svg)
    png = _render_png(prod, oss)

    out_dir = _ROOT / "assets" / "card" / "composite"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "breach-leaderboard.svg").write_text(svg, encoding="utf-8")
    (out_dir / "breach-leaderboard.html").write_text(html, encoding="utf-8")
    png.save(out_dir / "breach-leaderboard.png")

    served = _ROOT / "frontend" / "public" / "cards"
    served.mkdir(parents=True, exist_ok=True)
    png.save(served / "breach-leaderboard.png")
    (served / "breach-leaderboard.svg").write_text(svg, encoding="utf-8")

    print(f"wrote {out_dir}/breach-leaderboard.{{svg,png,html}}  ({W}×{H})")
    print(f"copied svg+png → {served}")
    print(f"  production: {len(prod)} · open-source: {len(oss)} · total {len(prod) + len(oss)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
