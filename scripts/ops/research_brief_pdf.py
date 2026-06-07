"""Generate the ROGUE research-brief PDF served at /research and attachable to
outreach emails.

A clean, academic 2-page brief (white background, not the dark site theme) of the
four measured findings + limitations. All numbers are verbatim from the measured
work (mirror of `frontend/src/app/research/page.tsx`). Writes to
`frontend/public/rogue-research-brief.pdf` (Next serves it at
`/rogue-research-brief.pdf`).

    uv run python scripts/ops/research_brief_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

_ROOT = Path(__file__).resolve().parents[2]
_OUT = _ROOT / "frontend" / "public" / "rogue-research-brief.pdf"

GREEN = HexColor("#1f9d55")
INK = HexColor("#16181d")
MUTED = HexColor("#52565e")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=20, leading=24, textColor=INK, spaceAfter=2,
        ),
        "sub": ParagraphStyle(
            "s", parent=base["Normal"], fontName="Helvetica",
            fontSize=10.5, leading=14, textColor=MUTED, spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "m", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, leading=12, textColor=MUTED,
        ),
        "eyebrow": ParagraphStyle(
            "e", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=11, textColor=GREEN, spaceBefore=10, spaceAfter=2,
        ),
        "h": ParagraphStyle(
            "h", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=15, textColor=INK, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=13.5, textColor=INK, alignment=TA_LEFT, spaceAfter=4,
        ),
        "note": ParagraphStyle(
            "n", parent=base["Normal"], fontName="Helvetica-Oblique",
            fontSize=9, leading=12.5, textColor=MUTED, leftIndent=10, spaceAfter=4,
        ),
        "li": ParagraphStyle(
            "li", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=13, textColor=INK,
        ),
    }


def build() -> Path:
    S = _styles()
    doc = SimpleDocTemplate(
        str(_OUT), pagesize=LETTER,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
        topMargin=0.7 * inch, bottomMargin=0.65 * inch,
        title="ROGUE — Research Brief", author="Soren Obounou Nguia",
    )
    F: list = []

    def eyebrow(t: str) -> None:
        F.append(Paragraph(t.upper(), S["eyebrow"]))

    def h(t: str) -> None:
        F.append(Paragraph(t, S["h"]))

    def p(t: str) -> None:
        F.append(Paragraph(t, S["body"]))

    def note(t: str) -> None:
        F.append(Paragraph("<b>Why this is notable.</b> " + t, S["note"]))

    bold = lambda x: f'<font color="#16181d"><b>{x}</b></font>'  # noqa: E731

    F.append(Paragraph("ROGUE — Research Brief", S["title"]))
    F.append(Paragraph(
        "A solo research build of a continuous open-web LLM red-team. "
        "The methods and the measured results — including the negative ones.",
        S["sub"],
    ))
    F.append(Spacer(1, 4))
    F.append(Paragraph(
        "Soren Obounou Nguia · Seoul · nguiasoren@gmail.com · "
        '<font color="#1f9d55">rogue-eosin.vercel.app/research</font> · '
        "live evidence: /matrix · /analytics · /about",
        S["meta"],
    ))
    F.append(Spacer(1, 6))
    F.append(HRFlowable(width="100%", thickness=0.8, color=GREEN, spaceAfter=8))

    eyebrow("Finding 01 — calibrating an LLM-as-judge against human labels, then recalibrating when a benchmark exposed it")
    p(
        "Every breach verdict is an LLM judgment, so the judge is the load-bearing weakness. It was "
        "validated four ways — three against independent human-annotated benchmarks: blind stratified "
        "in-distribution hand-labels, WildGuardTest (Allen AI annotators), StrongREJECT, and "
        "JailbreakBench&rsquo;s <i>judge_comparison</i> (300 human-labeled rows against four field "
        "classifiers). JBB exposed over-flagging: the v1 judge agreed with the human majority only "
        + bold("70.3% &mdash; last of five") + " (behind HarmBench / LlamaGuard-2 / GPT-4 / Llama-3), at "
        "recall 98% / precision 55%."
    )
    p(
        "A 20-row false-positive audit diagnosed " + bold("five recurring failure modes") + "; the root "
        "cause was a <i>rubric</i> problem &mdash; it rewarded engagement with the attack frame "
        "(persona acceptance, acknowledgment, format mimicry) over transfer of harmful content. A "
        + bold("content-transfer-gate rubric (v3)") + " moved the same 300 rows to "
        + bold("89.3% agreement / 79.5% precision / 95.5% recall") + " (+19 / +24.5 / &minus;2.5 pp) &mdash; "
        "dead-last to 3rd of five, tied with the frontier classifiers &mdash; for ~$8.4 via a tiered "
        "evaluation. Then the honest part: re-judging the stored breach matrix under v3 "
        + bold("dropped breach cells 2,429 to 1,371 (&minus;43.6%)") + ", correcting prior over-reporting "
        "(all three external axes re-measured under v3: WildGuard harm 88.5%, StrongREJECT inflation &minus;26%)."
    )
    note(
        "A named false-positive taxonomy for a safety judge, plus a measured finding that two respected "
        "benchmarks (WildGuardTest harm labels, StrongREJECT) themselves <i>over-count</i> relative to a "
        "strict content-transfer standard."
    )

    eyebrow("Finding 02 — scheduling as a capability lever, not just an optimization")
    p(
        "A within-tier greedy reorder was replaced with a " + bold("target-conditioned cross-tier scheduler")
        + " &mdash; a static, explainable blend (0.5&middot;global + 0.3&middot;vendor + 0.2&middot;family "
        "breach-rate, Laplace-smoothed, deliberately no ML / no bandit so it stays reproducible). A "
        "single-variable controlled experiment (same ladder, attacks, corpus, judge, and target &mdash; "
        "Claude Haiku, AdvBench + JailbreakBench; only the order changed) beat the production baseline on "
        "every axis: " + bold("median winner-rank 22 to 11&ndash;13.5") + ", "
        + bold("attack-success-rate 50% to 60%") + ", and " + bold("cost-per-success $1.25 to $0.74 (&minus;41%)") + "."
    )
    note(
        "The mechanism: rank&darr; <i>caused</i> ASR&uarr; &mdash; the old order exhausted the per-scan "
        "budget cap before reaching the winning technique &mdash; so reordering improved coverage, cost, "
        "and latency at once with zero new attacks. The reproducibility invariant is "
        "&ldquo;reorder, never exclude&rdquo;: same ladder, different order, full reachability preserved."
    )

    eyebrow("Finding 03 — a publication-grade null result: grammar-component predictive power")
    p(
        "Before building a grammar/AST attack-composition engine, a " + bold("$0 observational study over "
        "1,540 (primitive &times; target) cells") + " tested whether grammar-structure nodes predict breach "
        "<i>beyond</i> attack-family membership, with full confound controls: Benjamini&ndash;Hochberg FDR "
        "across hundreds of node/pair tests, Mantel&ndash;Haenszel stratification by target model, "
        "within-family lift, and Cram&eacute;r&rsquo;s-V collinearity flagging. Verdict "
        + bold("weak/none") + " &mdash; the family label carries the predictive weight; cross-family "
        "structural nodes show ~1.0&ndash;1.1&times; non-significant lift, and the striking pre-FDR pairwise "
        "synergies (odds ratios up to 16.8) survived " + bold("none") + " of the four controls."
    )
    note(
        "A cheap, rigorous falsification that redirected engineering away from a months-long build "
        "&mdash; a successful negative result."
    )

    eyebrow("Finding 04 — measure-before-build discipline")
    p(
        "$0 measurements from existing telemetry were used repeatedly to <i>invert</i> &ldquo;build it&rdquo; "
        "decisions, each parked with an explicit trigger-to-revisit:"
    )
    F.append(ListFlowable(
        [
            ListItem(Paragraph(
                bold("Per-model ladder routing") + " &mdash; the spread was a model main effect, not a "
                "family&times;model interaction, so it was not worth the rewrite.", S["li"]), value="–"),
            ListItem(Paragraph(
                bold("LLM renderer-synthesis") + " &mdash; synthesis-grade backlog flat at 7 across two "
                "widening harvests, so it was parked.", S["li"]), value="–"),
            ListItem(Paragraph(
                bold("HF jailbreak-dataset bulk-import") + " &mdash; measured 0 new attack families, so it "
                "was declined.", S["li"]), value="–"),
        ],
        bulletType="bullet", start="–", leftIndent=14, spaceAfter=4,
    ))

    F.append(Spacer(1, 4))
    F.append(HRFlowable(width="100%", thickness=0.6, color=MUTED, spaceAfter=6))
    eyebrow("Limitations (stated plainly)")
    p(
        "Targets are black-box live-API models whose versions are not pinned; some cells are small-n "
        "(95% bootstrap CIs are persisted precisely because of this); the judge is "
        "single-operator-calibrated. These are descriptive measurements of a live system, not validated "
        "generalizations."
    )

    doc.build(F)
    return _OUT


if __name__ == "__main__":
    out = build()
    print(f"wrote {out} ({out.stat().st_size} bytes)")
