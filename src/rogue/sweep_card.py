"""Sweep card — the robustness-threshold companion to the breach card.

Where the breach card answers "this attack broke config Y" (general, per-breach), the sweep card
answers "config Y is safe up to X, breaks at Z" — the ASR curve over a scaled dimension (context
length / shot count) with the breaking threshold marked. Rendered only for generator/sweep attacks
(``rogue.reproduce.generator_sweep.SweepResult``). Same brand as the breach card: BG ``#050508``,
green ``#00ff88`` (held), red ``#ff003c`` (breach), Geist-Mono, mesh + orb frame.
"""

from __future__ import annotations

import math
from html import escape

from .report_card import (
    BG,
    GREEN,
    RED,
    TAGLINE,
    _HAIRLINE,
    _INK,
    _MONO,
    _MUTE,
    _PLATE,
    _QR_LABEL,
    _QR_URL,
    _qr_block_svg,
    _qr_png_b64,
)

_W, _H = 1200, 630
_CX0, _CX1, _CY0, _CY1 = 150.0, 1055.0, 250.0, 500.0  # chart box (right edge shrinks when a QR is shown)
FOOTER_URL = "rogue-eosin.vercel.app"


def _fmt_val(v: int) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:g}M"
    if v >= 1_000:
        return f"{v / 1_000:g}K"
    return str(v)


def _t(x: float, y: float, s: str, *, size: float, fill: str, weight: int = 400,
       anchor: str = "start", spacing: float = 0.0) -> str:
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{_MONO}" '
            f'font-size="{size}" font-weight="{weight}" fill="{fill}"{ls}>{escape(s)}</text>')


def _layout(square: bool) -> dict:
    """All position/size coords for one aspect ratio. Landscape (1200×630, OG/link) puts the QR in the
    chart's right margin; square (1080×1080, feed post) uses a full-width chart with the QR below."""
    if square:
        return dict(W=1080, H=1080, plate=(44, 44, 992, 992), hdr=(72, 106), chip=(838, 82, 174, 34, 925, 106),
                    title=(72, 232, 36), thr=(72, 282, 24), cx0=120.0, cx1_full=960.0, cx1_qr=960.0,
                    cy0=370.0, cy1=744.0, tick_dy=32, qr=(812, 792, 196), qr_margin=False,
                    foot=(72, 902), tag=(72, 942), url=(72, 982, "start"))
    return dict(W=1200, H=630, plate=(44, 44, 1112, 542), hdr=(80, 101), chip=(946, 78, 174, 34, 1033, 101),
                title=(80, 175, 34), thr=(80, 214, 22), cx0=150.0, cx1_full=1055.0, cx1_qr=866.0,
                cy0=250.0, cy1=500.0, tick_dy=26, qr=(902, 300, 156), qr_margin=True,
                foot=(80, 558), tag=(80, 578), url=(1120, 578, "end"))


def render_sweep_card(result, *, config_name: str, target_model: str = "", square: bool = False) -> str:
    """Return the sweep card SVG for a ``SweepResult`` (log-x, ASR-y, CI band, threshold marked).
    ``square=True`` renders the 1080×1080 feed-post variant; default is the 1200×630 OG/link card.
    Pure string build — no browser."""
    pts = list(result.points)
    if not pts:
        raise ValueError("sweep card needs at least one point")
    L = _layout(square)
    W, H = L["W"], L["H"]
    cx0, cy0, cy1 = L["cx0"], L["cy0"], L["cy1"]

    qr_b64 = _qr_png_b64(_QR_URL, 150)
    cx1 = (L["cx1_qr"] if qr_b64 and L["qr_margin"] else L["cx1_full"])

    xs = [max(1, p.value) for p in pts]
    lx = [math.log10(v) for v in xs]
    lo, hi = min(lx), max(lx)
    span = (hi - lo) or 1.0

    def X(v: int) -> float:
        return cx0 + (math.log10(max(1, v)) - lo) / span * (cx1 - cx0)

    def Y(asr: float) -> float:
        return cy1 - max(0.0, min(1.0, asr)) * (cy1 - cy0)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="ROGUE robustness sweep">',
        '<defs>'
        f'<radialGradient id="og" cx="20%" cy="16%" r="55%"><stop offset="0" stop-color="{GREEN}" stop-opacity="0.10"/><stop offset="1" stop-color="{GREEN}" stop-opacity="0"/></radialGradient>'
        f'<radialGradient id="orr" cx="88%" cy="90%" r="55%"><stop offset="0" stop-color="{RED}" stop-opacity="0.12"/><stop offset="1" stop-color="{RED}" stop-opacity="0"/></radialGradient>'
        f'<pattern id="mesh" width="48" height="48" patternUnits="userSpaceOnUse"><path d="M48 0H0V48" fill="none" stroke="{_HAIRLINE}" stroke-width="1" opacity="0.5"/></pattern>'
        '</defs>',
        f'<rect width="{W}" height="{H}" fill="{BG}"/><rect width="{W}" height="{H}" fill="url(#mesh)"/>',
        f'<rect width="{W}" height="{H}" fill="url(#og)"/><rect width="{W}" height="{H}" fill="url(#orr)"/>',
        f'<rect x="{L["plate"][0]}" y="{L["plate"][1]}" width="{L["plate"][2]}" height="{L["plate"][3]}" rx="28" fill="{_PLATE}" fill-opacity="0.55" stroke="{_HAIRLINE}" stroke-width="1.5"/>',
    ]

    # header + chip
    parts.append(_t(L["hdr"][0], L["hdr"][1], "ROGUE", size=30, fill=_INK, weight=700, spacing=6))
    cx, cyy, cw, ch, ctx, cty = L["chip"]
    parts.append(f'<rect x="{cx}" y="{cyy}" width="{cw}" height="{ch}" rx="17" fill="{_MUTE}" fill-opacity="0.10" stroke="{_MUTE}" stroke-opacity="0.45" stroke-width="1"/>')
    parts.append(_t(ctx, cty, "robustness sweep", size=14.5, fill=_MUTE, anchor="middle", spacing=0.6))

    # title + threshold headline
    broke = result.threshold_value is not None
    parts.append(_t(L["title"][0], L["title"][1], f"{result.sweep_param.upper().replace('_', ' ')} THRESHOLD", size=L["title"][2], fill=_INK, weight=700, spacing=2))
    if broke:
        parts.append(_t(L["thr"][0], L["thr"][1], f"BREAKS AT {result.sweep_param} = {_fmt_val(result.threshold_value)}", size=L["thr"][2], fill=RED, weight=700, spacing=1))
    else:
        parts.append(_t(L["thr"][0], L["thr"][1], "HELD ACROSS THE SWEEP", size=L["thr"][2], fill=GREEN, weight=700, spacing=1))

    # y gridlines + labels
    for pct in (0, 25, 50, 75, 100):
        y = Y(pct / 100)
        parts.append(f'<line x1="{cx0}" y1="{y}" x2="{cx1}" y2="{y}" stroke="{_HAIRLINE}" stroke-width="1" opacity="0.6"/>')
        parts.append(_t(cx0 - 12, y + 5, f"{pct}%", size=14, fill=_MUTE, anchor="end"))

    # CI band + ASR curve
    if len(pts) >= 2:
        top = " ".join(f"{X(p.value):.1f},{Y(p.ci_high):.1f}" for p in pts)
        bot = " ".join(f"{X(p.value):.1f},{Y(p.ci_low):.1f}" for p in reversed(pts))
        parts.append(f'<polygon points="{top} {bot}" fill="{GREEN}" fill-opacity="0.08"/>')
        curve = " ".join(f"{X(p.value):.1f},{Y(p.asr):.1f}" for p in pts)
        parts.append(f'<polyline points="{curve}" fill="none" stroke="{GREEN}" stroke-width="2.5" opacity="0.85"/>')

    if broke:
        tx = X(result.threshold_value)
        parts.append(f'<line x1="{tx}" y1="{cy0 - 8}" x2="{tx}" y2="{cy1}" stroke="{RED}" stroke-width="2" stroke-dasharray="5 4" opacity="0.8"/>')

    for p in pts:
        col = RED if p.asr >= result.breach_threshold else GREEN
        parts.append(f'<circle cx="{X(p.value):.1f}" cy="{Y(p.asr):.1f}" r="6" fill="{col}"/>')
        parts.append(_t(X(p.value), cy1 + L["tick_dy"], _fmt_val(p.value), size=13, fill=_MUTE, anchor="middle"))

    # QR (scan → leaderboard)
    if qr_b64:
        qx, qy, qt = L["qr"]
        parts.append(_qr_block_svg(qx, qy, qt, qr_b64))
        parts.append(_t(qx + qt / 2, qy + qt + 24, _QR_LABEL, size=13, fill=_MUTE, anchor="middle", spacing=1))

    # footer
    sub = f"{config_name}" + (f" · {target_model}" if target_model else "")
    parts.append(_t(L["foot"][0], L["foot"][1], f"{result.kind}  ·  {sub}  ·  {pts[0].n_trials} trials/point", size=15, fill=_MUTE))
    parts.append(_t(L["tag"][0], L["tag"][1], TAGLINE, size=15, fill=GREEN, spacing=1))
    parts.append(_t(L["url"][0], L["url"][1], FOOTER_URL, size=14, fill=_MUTE, anchor=L["url"][2]))
    parts.append("</svg>")
    return "".join(parts)


__all__ = ["render_sweep_card"]
