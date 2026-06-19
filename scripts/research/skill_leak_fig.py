"""Skill-pool leakage strength curve (2026-06-13, liveness-guarded run).

Horizontal bars = canary-leakage rate per target model, sorted by leakage, each
annotated with size + model type so the reader sees the message: leakage tracks
alignment, not size. Wilson 95% CIs as error bars. Serif to match the LaTeX body.
Writes PNG + PDF into the skill_leak package.

    uv run python scripts/research/skill_leak_fig.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix", "figure.dpi": 150, "font.size": 11,
    "axes.edgecolor": "#cfd3da",
})

PKG = Path(__file__).resolve().parents[2] / "docs/research/publishing/skill_leak"
INK, MUTED, STEEL, SAFE, WARN = "#16181d", "#8a9098", "#3a6ea5", "#1f9d55", "#c2354d"

# (label, size·type, leakage%, ci_low, ci_high, color)  — sorted leakiest-first
ROWS = [
    ("qwen3-32b",              "32B · reasoning (inline CoT)", 100, 100, 100, WARN),
    ("llama-3.1-8b-instant",   "8B · instruct",                 85,  70, 100, STEEL),
    ("llama-3.3-70b-versatile", "70B · instruct",               65,  45,  85, STEEL),
    ("openai/gpt-oss-20b",     "20B · safety-tuned",            35,  15,  55, SAFE),
]


def main() -> int:
    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    y = list(range(len(ROWS)))[::-1]  # top row at top
    for yi, (name, tag, rate, lo, hi, c) in zip(y, ROWS):
        ax.barh(yi, rate, height=0.55, color=c, alpha=0.88,
                xerr=[[rate - lo], [hi - rate]], capsize=4,
                error_kw={"ecolor": MUTED, "lw": 1.2})
        ax.text(rate + (hi - rate) + 3, yi, f"{rate}%", va="center", fontsize=11,
                weight="bold", color=c)
        ax.text(1.5, yi, tag, va="center", ha="left", fontsize=8.5, color="white"
                if rate >= 60 else INK)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in ROWS], fontsize=9.5)
    ax.set_xlim(0, 112); ax.set_xlabel("canary-leakage rate  (recovered $\\div$ 20)")
    ax.set_title("Skill-pool leakage tracks alignment, not size", fontweight="bold", pad=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.5, -0.04,
             "20 canary skills + 12 controls per model, extraction_pack_v1 (standard) + paraphrase judge; "
             "0 control false-positives and 128/128 live responses each (liveness-guarded). "
             "qwen emits chain-of-thought inline, so its rate counts leaks in visible reasoning.",
             ha="center", fontsize=6.8, color=MUTED, wrap=True)
    fig.tight_layout()
    for out in (PKG / "fig-curve.png", PKG / "fig-curve.pdf"):
        fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {PKG/'fig-curve.png'} + .pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
