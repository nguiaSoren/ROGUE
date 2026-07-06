"""PII card — the leakage-profile companion to the breach and sweep cards.

Where the breach card answers "this attack broke config Y" and the sweep card "config Y breaks at
Z tokens", the PII card answers **"does config Y leak PII, and where does it come from?"** — the
Axis-A/B measurement in one artifact: the exact-match **context-leak rate** (headline-grade), the
fuzzy **fabrication-emission rate** (carried with its detector precision, per the calibration gate),
and the **provenance split** (planted / retrieval / parametric→fabricated). Same brand as the other
cards: BG ``#050508``, green ``#00ff88`` (held), red ``#ff003c`` (leak), Geist-Mono, mesh + orb frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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

FOOTER_URL = "rogue-eosin.vercel.app"
_PROV_COLORS = {"planted": "#7aa2ff", "retrieval": "#ffb020", "parametric": RED, "ambiguous": _MUTE}


@dataclass
class PiiProfile:
    """One deployment's PII-leakage profile — the card's input."""

    config_name: str
    target_model: str
    context_leak_rate: float  # exact-match leak of PII planted in context (headline-grade)
    emission_rate: float  # fuzzy fabrication-emission rate (uncalibrated per-finding)
    detector_precision: float  # the calibration gate on the fuzzy half
    provenance: dict = field(default_factory=dict)  # {planted, retrieval, parametric, ambiguous}
    param_split: dict = field(default_factory=dict)  # {fabricated, uncertain}
    top_attributes: list = field(default_factory=list)  # [(attribute, severity), ...]
    n_probes: int = 0


def _t(x: float, y: float, s: str, *, size: float, fill: str, weight: int = 400,
       anchor: str = "start", spacing: float = 0.0) -> str:
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{_MONO}" '
            f'font-size="{size}" font-weight="{weight}" fill="{fill}"{ls}>{escape(s)}</text>')


def _sev_color(sev: str) -> str:
    return {"critical": RED, "high": "#ff6b3d", "medium": "#ffb020", "low": GREEN}.get(sev, _MUTE)


def _layout(square: bool) -> dict:
    if square:
        return dict(W=1080, H=1080, plate=(44, 44, 992, 992), hdr=(72, 104), chip=(806, 80, 206, 34, 909, 104),
                    title=(72, 216, 36), head=(72, 306, 84), headsub=(72, 350, 22),
                    stat_y=440, stat_x=(72, 400, 700), bar_y=540, bar=(72, 936, 28),
                    attr_y=636, qr=(440, 712, 200), foot=(72, 972), tag=(72, 1004), url=(1008, 1004, "end"))
    return dict(W=1200, H=630, plate=(44, 44, 1112, 542), hdr=(80, 94), chip=(918, 68, 202, 34, 1019, 90),
                title=(80, 146, 30), head=(80, 228, 72), headsub=(80, 266, 20),
                stat_y=338, stat_x=(80, 400, 680), bar_y=422, bar=(80, 1030, 24),
                attr_y=492, qr=(902, 236, 156), foot=(80, 556), tag=(80, 578), url=(1120, 578, "end"))


def render_pii_card(profile: PiiProfile, *, square: bool = False) -> str:
    """Return the PII-leakage card SVG for a :class:`PiiProfile`. Pure string build — no browser."""
    L = _layout(square)
    W, H = L["W"], L["H"]
    held = profile.context_leak_rate <= 0.0

    qr_b64 = _qr_png_b64(_QR_URL, 150)

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'role="img" aria-label="ROGUE PII leakage profile">',
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
    parts.append(_t(ctx, cty, "pii leakage scan", size=14.5, fill=_MUTE, anchor="middle", spacing=0.6))

    # title
    parts.append(_t(L["title"][0], L["title"][1], "PII LEAKAGE PROFILE", size=L["title"][2], fill=_INK, weight=700, spacing=2))

    # headline: context-leak (exact-match, headline-grade)
    hx, hy, hsz = L["head"]
    head_col = GREEN if held else RED
    head_txt = "0% CONTEXT LEAK" if held else f"{profile.context_leak_rate * 100:.0f}% CONTEXT LEAK"
    parts.append(_t(hx, hy, head_txt, size=hsz, fill=head_col, weight=700, spacing=1))
    sub = "PII planted in context — HELD" if held else "planted PII disclosed under probing"
    parts.append(_t(L["headsub"][0], L["headsub"][1], sub, size=L["headsub"][2], fill=_MUTE, spacing=0.5))

    # stat trio: fabrication emission · detector precision · probes
    sy = L["stat_y"]
    x1, x2, x3 = L["stat_x"]
    def stat(x, val, lab, col):
        parts.append(_t(x, sy, val, size=34, fill=col, weight=700))
        parts.append(_t(x, sy + 26, lab, size=13.5, fill=_MUTE, spacing=0.4))
    stat(x1, f"{profile.emission_rate * 100:.0f}%", "fabricates PII on request", "#ffb020")
    stat(x2, f"{profile.detector_precision:.2f}", "detector precision (gate)", _INK)
    stat(x3, str(profile.n_probes), "extraction probes", _INK)

    # provenance bar (stacked): where emitted PII came from
    prov = profile.provenance or {}
    total = sum(prov.values()) or 1
    bx, bx1, bh = L["bar"]
    by = L["bar_y"]
    parts.append(_t(bx, by - 12, "PROVENANCE OF EMITTED PII", size=12.5, fill=_MUTE, spacing=1))
    cursor = float(bx)
    width = bx1 - bx
    for key in ("planted", "retrieval", "parametric", "ambiguous"):
        n = prov.get(key, 0)
        if not n:
            continue
        w = width * (n / total)
        parts.append(f'<rect x="{cursor:.1f}" y="{by}" width="{max(2, w):.1f}" height="{bh}" fill="{_PROV_COLORS[key]}" fill-opacity="0.85"/>')
        if w > 70:
            parts.append(_t(cursor + 8, by + bh - 9, f"{key} {100*n/total:.0f}%", size=12.5, fill=BG, weight=700))
        cursor += w

    # attribute severity chips (top attributes at risk, PRI-colored)
    ax = L["stat_x"][0]
    ay = L["attr_y"]
    parts.append(_t(ax, ay - 10, "ATTRIBUTES AT RISK", size=12.5, fill=_MUTE, spacing=1))
    chip_x = float(ax)
    for attr, sev in profile.top_attributes[:5]:
        label = f"{attr} · {sev}"
        w = 20 + len(label) * 8.4
        col = _sev_color(sev)
        parts.append(f'<rect x="{chip_x:.1f}" y="{ay + 6}" width="{w:.1f}" height="30" rx="15" fill="{col}" fill-opacity="0.14" stroke="{col}" stroke-opacity="0.6" stroke-width="1"/>')
        parts.append(_t(chip_x + w / 2, ay + 26, label, size=13, fill=col, anchor="middle"))
        chip_x += w + 12

    # QR (landscape: right margin; square: centered, fills the lower band)
    if qr_b64:
        qx, qy, qt = L["qr"]
        parts.append(_qr_block_svg(qx, qy, qt, qr_b64))
        parts.append(_t(qx + qt / 2, qy + qt + 24, _QR_LABEL, size=13, fill=_MUTE, anchor="middle", spacing=1))

    # footer
    dsub = f"{profile.config_name}" + (f" · {profile.target_model}" if profile.target_model else "")
    parts.append(_t(L["foot"][0], L["foot"][1], f"{dsub}  ·  emission non-headline until certified", size=14, fill=_MUTE))
    parts.append(_t(L["tag"][0], L["tag"][1], TAGLINE, size=15, fill=GREEN, spacing=1))
    parts.append(_t(L["url"][0], L["url"][1], FOOTER_URL, size=14, fill=_MUTE, anchor=L["url"][2]))
    parts.append("</svg>")
    return "".join(parts)


__all__ = ["PiiProfile", "render_pii_card"]
