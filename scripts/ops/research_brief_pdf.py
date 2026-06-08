"""Generate the ROGUE research-brief PDF served at /research and attachable to
outreach emails.

A designed, readable research brief: dark header band, metric chips, boxed
"why this is notable" callouts, clean bullets, a footer rule. White page so it
prints/reads well for an academic. All numbers are verbatim from the measured
work (mirror of `frontend/src/app/research/page.tsx`). Writes to
`frontend/public/rogue-research-brief.pdf` (Next serves it at
`/rogue-research-brief.pdf`).

    uv run python scripts/ops/research_brief_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_ROOT = Path(__file__).resolve().parents[2]
_OUT = _ROOT / "frontend" / "public" / "rogue-research-brief.pdf"

GREEN = colors.HexColor("#1f9d55")
INK = colors.HexColor("#14161b")
BODY = colors.HexColor("#23262d")
MUTED = colors.HexColor("#5b6views" if False else "#5b6068")
LIGHT = colors.HexColor("#f3f6f4")
CHIPBG = colors.HexColor("#eef3f0")
LINE = colors.HexColor("#d8ddd9")

MARGIN = 0.8 * inch
CONTENT_W = LETTER[0] - 2 * MARGIN


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "brand": ParagraphStyle("brand", parent=base["Normal"], fontName="Helvetica-Bold",
                                fontSize=17, leading=20, textColor=colors.white),
        "tagline": ParagraphStyle("tag", parent=base["Normal"], fontName="Helvetica",
                                  fontSize=9, leading=13, textColor=colors.HexColor("#aeb6b0")),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.5, leading=12, textColor=MUTED),
        "h": ParagraphStyle("h", parent=base["Normal"], fontName="Helvetica-Bold",
                            fontSize=12.5, leading=15.5, textColor=INK, spaceBefore=14, spaceAfter=5),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica",
                               fontSize=10, leading=14.5, textColor=BODY, alignment=TA_LEFT, spaceAfter=5),
        "chipval": ParagraphStyle("cv", parent=base["Normal"], fontName="Helvetica-Bold",
                                  fontSize=12.5, leading=15, textColor=GREEN),
        "chiplbl": ParagraphStyle("cl", parent=base["Normal"], fontName="Helvetica",
                                  fontSize=7, leading=9, textColor=MUTED),
        "notelbl": ParagraphStyle("nl", parent=base["Normal"], fontName="Helvetica-Bold",
                                  fontSize=7.5, leading=10, textColor=GREEN),
        "note": ParagraphStyle("note", parent=base["Normal"], fontName="Helvetica",
                               fontSize=9, leading=13, textColor=colors.HexColor("#41454c")),
        "li": ParagraphStyle("li", parent=base["Normal"], fontName="Helvetica",
                             fontSize=10, leading=14, textColor=BODY),
        "limit": ParagraphStyle("lim", parent=base["Normal"], fontName="Helvetica",
                                fontSize=9.5, leading=13.5, textColor=colors.HexColor("#41454c")),
        "barlbl": ParagraphStyle("barlbl", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=8, leading=10, textColor=INK),
        "barval": ParagraphStyle("barval", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=8, leading=10, textColor=INK),
        "cap": ParagraphStyle("cap", parent=base["Normal"], fontName="Helvetica-Oblique",
                              fontSize=7.5, leading=10.5, textColor=MUTED),
    }


S = _styles()
b = lambda x: f"<b>{x}</b>"  # noqa: E731


def _header() -> Table:
    cell = [
        Paragraph('<font color="#1f9d55">ROGUE</font>  ·  Research Brief', S["brand"]),
        Paragraph(
            "A solo research build of a continuous open-web LLM red-team. "
            "The methods and the measured results, including the negative ones.",
            S["tagline"],
        ),
    ]
    t = Table([[cell]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LINEBELOW", (0, 0), (-1, -1), 3, GREEN),
    ]))
    return t


def _chips(items: list[tuple[str, str]]) -> Table:
    cells = [[Paragraph(v, S["chipval"]), Spacer(1, 2), Paragraph(lbl.upper(), S["chiplbl"])]
             for v, lbl in items]
    w = CONTENT_W / len(items)
    t = Table([cells], colWidths=[w] * len(items))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CHIPBG),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEAFTER", (0, 0), (-2, -1), 1, colors.white),
        ("LINEBELOW", (0, 0), (-1, -1), 2, GREEN),
    ]))
    return t


def _note(text: str) -> Table:
    inner = [Paragraph("WHY THIS IS NOTABLE", S["notelbl"]), Spacer(1, 2), Paragraph(text, S["note"])]
    t = Table([[inner]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, GREEN),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _heading(num: str, title: str) -> Paragraph:
    return Paragraph(f'<font color="#1f9d55"><b>{num}</b></font>&nbsp;&nbsp;{b(title)}', S["h"])


def _judgefig() -> Table:
    """Horizontal bars: judge agreement vs the field (the last → tied-with-frontier story)."""
    rows = [
        ("ROGUE v1", 70.3, colors.HexColor("#c0392b")),
        ("HarmBench", 78.3, colors.HexColor("#b9c2bb")),
        ("LlamaGuard-2", 87.7, colors.HexColor("#b9c2bb")),
        ("ROGUE v3", 89.3, GREEN),
        ("GPT-4", 90.3, colors.HexColor("#b9c2bb")),
        ("Llama-3", 90.7, colors.HexColor("#b9c2bb")),
    ]
    barmax = 2.7 * inch
    data = []
    for label, val, color in rows:
        d = Drawing(barmax, 11)
        d.add(Rect(0, 1.5, barmax, 8, fillColor=CHIPBG, strokeColor=None))
        d.add(Rect(0, 1.5, barmax * val / 100.0, 8, fillColor=color, strokeColor=None))
        emph = "Helvetica-Bold" if label.startswith("ROGUE") else "Helvetica"
        data.append([
            Paragraph(f'<font name="{emph}">{label}</font>', S["barlbl"]),
            d,
            Paragraph(f'<font name="{emph}">{val:.1f}</font>', S["barval"]),
        ])
    t = Table(data, colWidths=[1.25 * inch, barmax, 0.55 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (1, 0), (1, -1), 6),
        ("LEFTPADDING", (2, 0), (2, -1), 4),
    ]))
    cap = Paragraph(
        "Judge agreement vs the field (JailbreakBench, % vs the human majority). "
        "Recalibration moved ROGUE from last of five to 3rd, tied with the frontier classifiers.",
        S["cap"])
    wrap = Table([[t], [cap]], colWidths=[CONTENT_W])
    wrap.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 1), (0, 1), 5), ("BOTTOMPADDING", (0, 0), (0, 0), 0),
    ]))
    return wrap


def _footer(canvas, doc) -> None:
    canvas.saveState()
    y = 0.55 * inch
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    canvas.line(MARGIN, y + 12, LETTER[0] - MARGIN, y + 12)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, y, "Soren Obounou Nguia  ·  rogue-eosin.vercel.app/research")
    canvas.setFillColor(GREEN)
    canvas.drawRightString(LETTER[0] - MARGIN, y, f"{doc.page}")
    canvas.restoreState()


def build() -> Path:
    doc = SimpleDocTemplate(
        str(_OUT), pagesize=LETTER,
        leftMargin=MARGIN, rightMargin=MARGIN, topMargin=0.6 * inch, bottomMargin=0.85 * inch,
        title="ROGUE Research Brief", author="Soren Obounou Nguia",
    )
    F: list = [
        _header(),
        Spacer(1, 7),
        Paragraph(
            "Soren Obounou Nguia &nbsp;·&nbsp; Seoul &nbsp;·&nbsp; nguiasoren@gmail.com "
            "&nbsp;·&nbsp; live evidence at /matrix, /analytics, /about",
            S["meta"],
        ),
        Spacer(1, 10),
    ]

    # 01
    F += [_heading("01", "Calibrating an LLM-as-judge against human labels, then recalibrating when a benchmark exposed it.")]
    F += [Paragraph(
        "Every breach verdict is an LLM judgment, so the judge is the load-bearing weakness. It was "
        "validated four ways, three against independent human-annotated benchmarks: blind stratified "
        "in-distribution hand-labels, WildGuardTest (Allen AI annotators), StrongREJECT, and "
        "JailbreakBench&rsquo;s <i>judge_comparison</i> (300 human-labeled rows against four field "
        "classifiers). JailbreakBench exposed over-flagging: the v1 judge agreed with the human majority "
        "only " + b("70.3%, last of five") + " (behind HarmBench, LlamaGuard-2, GPT-4, Llama-3), at recall "
        "98% and precision 55%.", S["body"])]
    F += [Paragraph(
        "A 20-row false-positive audit traced it to " + b("five recurring failure modes") + ". The root "
        "cause was a <i>rubric</i> problem: it rewarded engagement with the attack frame (persona "
        "acceptance, acknowledgment, format mimicry) over transfer of harmful content. A "
        + b("content-transfer-gate rubric (v3)") + " moved the same 300 rows to "
        + b("89.3% agreement, 79.5% precision, 95.5% recall") + " (a 19-point agreement gain, 24.5-point "
        "precision gain, 2.5-point recall cost), lifting it from last to 3rd of five and tied with the "
        "frontier classifiers, for about $8.4 via a tiered evaluation.", S["body"])]
    F += [Paragraph(
        "Then the honest part. Re-judging the stored breach matrix under v3 cut breach cells from "
        + b("2,429 to 1,371, a 43.6% reduction") + ", correcting prior over-reporting. All three external "
        "axes were re-measured under v3 (WildGuard harm 88.5%; StrongREJECT 26% more conservative).", S["body"])]
    F += [Spacer(1, 4), _chips([
        ("70.3 → 89.3%", "JBB human agreement"),
        ("55 → 79.5%", "precision"),
        ("2,429 → 1,371", "breach cells re-judged"),
        ("2.56%", "in-dist false-positive"),
    ]), Spacer(1, 8)]
    F += [_judgefig(), Spacer(1, 8)]
    F += [_note(
        "A named false-positive taxonomy for a safety judge, plus a measured finding that two respected "
        "benchmarks (WildGuardTest harm labels and StrongREJECT) themselves <i>over-count</i> relative to a "
        "strict content-transfer standard.")]
    F += [Spacer(1, 6), Paragraph(
        b("The gate is not harm-specific, it is a calibration discipline.") + " An established practice taken "
        "rigorously, not a new method. One consummation-gate template, "
        "re-instantiated per breach type, now calibrates " + b("four structurally different breach classes") +
        ": a <i>harm</i> breach (capability transfer, re-confirmed at " + b("91.0% agreement, 273 of 300") +
        ", top-of-field); a <i>content</i> breach (information-disclosure, did the protected datum appear), "
        "whose v2 rubric defines a materially-revealing threshold and reaches " + b("97.35% agreement") +
        ", 100% recall, 0% FP-mode (up from 94.74%); an <i>action</i> breach (unauthorized-action, did the "
        "agent execute), whose v3 tool-trace rubric reaches " + b("98.89% agreement") + ", 100% recall, "
        "with FP-mode driven 9.38% to 6.25% to 3.12%; and a new <i>fabrication</i> breach "
        "(fabricated-sensitive-value, a trust breach distinct from disclosure) at " + b("100% agreement") +
        ", 0% FP-mode on the first pass. The harness " + b("self-diagnoses") + ": on the harder types it "
        "returned <i>refine</i>, a targeted rubric fix was applied, and re-measurement shipped it, the same "
        "diagnose then fix then re-measure loop that produced v3, run again. The tool-trace turned a stated "
        "limitation into a measured resolution: the action type&rsquo;s earlier weakness was the text-only "
        "proxy, not the gate, so a tool-call trace makes &ldquo;executed&rdquo; a fact and dissolves the "
        "simulate-or-claim confusion. This pattern generalizes: provenance-dependent breach types need an "
        "evidence trace, not a better rubric, and the independence check names the missing evidence, shown "
        "twice, a tool-call trace that lifted second-labeler kappa from 0.746 to 0.917 for unauthorized-action "
        "and a retrieval trace that lifted kappa from 0.723 to 0.909 for fabricated-value. The contribution is "
        + b("a repeatable discipline for calibrating breach judges across breach classes") + ", "
        "not a single judge.", S["body"])]
    F += [Spacer(1, 4), _chips([
        ("91.0%", "harm (capability transfer)"),
        ("97.35%", "info-disclosure v2"),
        ("98.89%", "unauth-action v3 (tool-trace)"),
        ("100%", "fabricated-value (new)"),
    ]), Spacer(1, 6)]
    F += [_note(
        "Four breach classes, one gate template, every variant shipped. The methodology exposes "
        "type-dependent difficulty: action consummation (did the agent execute) was the hardest, and the "
        "tool-call trace resolved it by making execution a recorded fact rather than a text-only proxy. "
        "Caveats stated plainly: single-operator kappa (the tool-trace lifted unauthorized-action from 0.746 "
        "to 0.917; the fabricated-value retrieval-trace lifted its human kappa from 0.723 to 0.909); "
        "corpora are synthetic. The building blocks are established (trace-grounded agent eval, kappa-gated "
        "calibration, provenance attribution, cross-type judge generalization like CompliBench); the "
        "contribution is the rigor and the measured cross-type result, not a new mechanism. These are "
        "descriptive measurements, not validated generalizations.")]

    # 02
    F += [_heading("02", "Scheduling as a capability lever, not just an optimization.")]
    F += [Paragraph(
        "A within-tier greedy reorder was replaced with a " + b("target-conditioned cross-tier scheduler") +
        ": a static, explainable blend (0.5 global, 0.3 vendor, 0.2 family breach-rate; Laplace-smoothed; "
        "deliberately no ML and no bandit, so it stays reproducible). A single-variable controlled "
        "experiment (same ladder, attacks, corpus, judge, and target on Claude Haiku across AdvBench and "
        "JailbreakBench, with only the order changed) beat the production baseline on every axis: "
        + b("median winner-rank 22 → 11 to 13.5") + ", " + b("attack-success-rate 50% → 60%") +
        ", and " + b("cost-per-success $1.25 → $0.74 (41% cheaper)") + ".", S["body"])]
    F += [Spacer(1, 4), _chips([
        ("22 → 11", "median winner-rank"),
        ("50 → 60%", "attack-success-rate"),
        ("41% cheaper", "cost per success"),
    ]), Spacer(1, 6)]
    F += [_note(
        "The mechanism is the interesting part: a lower rank <i>caused</i> a higher success rate. The old "
        "order exhausted the per-scan budget cap before reaching the winning technique, so reordering "
        "improved coverage, cost, and latency at once with zero new attacks. The reproducibility invariant "
        "is &ldquo;reorder, never exclude&rdquo;: same ladder, different order, full reachability preserved.")]

    # 03
    F += [_heading("03", "A publication-grade null result: grammar-component predictive power.")]
    F += [Paragraph(
        "Before building a grammar/AST attack-composition engine, a " + b("$0 observational study over "
        "1,540 (primitive × target) cells") + " tested whether grammar-structure nodes predict breach "
        "<i>beyond</i> attack-family membership, with full confound controls: Benjamini-Hochberg FDR "
        "across hundreds of node and pair tests, Mantel-Haenszel stratification by target model, "
        "within-family lift, and Cram&eacute;r&rsquo;s-V collinearity flagging. The verdict was "
        + b("weak to none") + ": the family label carries the predictive weight, cross-family structural "
        "nodes show roughly 1.0 to 1.1× non-significant lift, and the striking pre-FDR pairwise "
        "synergies (odds ratios up to 16.8) survived " + b("none") + " of the four controls.", S["body"])]
    F += [Spacer(1, 4), _chips([
        ("1,540", "cells, $0 study"),
        ("~1.0 to 1.1×", "cross-family lift (n.s.)"),
        ("0 of 4", "synergies survived controls"),
    ]), Spacer(1, 6)]
    F += [_note(
        "A cheap, rigorous falsification that redirected engineering away from a months-long build: "
        "a successful negative result.")]

    # 04
    F += [_heading("04", "Measure-before-build discipline.")]
    F += [Paragraph(
        "$0 measurements from existing telemetry were used repeatedly to <i>invert</i> &ldquo;build "
        "it&rdquo; decisions, each parked with an explicit trigger to revisit:", S["body"])]
    F += [ListFlowable([
        ListItem(Paragraph(b("Per-model ladder routing.") + " The spread was a model main effect, not a "
                           "family×model interaction, so it was not worth the rewrite.", S["li"]),
                 leftIndent=14, value="circle"),
        ListItem(Paragraph(b("LLM renderer-synthesis.") + " The synthesis-grade backlog stayed flat at 7 "
                           "across two widening harvests, so it was parked.", S["li"]),
                 leftIndent=14, value="circle"),
        ListItem(Paragraph(b("HF jailbreak-dataset bulk-import.") + " It measured 0 new attack families, so "
                           "it was declined.", S["li"]), leftIndent=14, value="circle"),
    ], bulletType="bullet", bulletColor=GREEN, bulletFontSize=6, spaceAfter=6)]

    # limitations
    F += [Spacer(1, 8)]
    lim = [Paragraph("LIMITATIONS, STATED PLAINLY", S["notelbl"]), Spacer(1, 3), Paragraph(
        "Targets are black-box live-API models whose versions are not pinned. Some cells are small-n "
        "(95% bootstrap confidence intervals are persisted precisely because of this). The judge is "
        "single-operator-calibrated. These are descriptive measurements of a live system, not validated "
        "generalizations.", S["limit"])]
    box = Table([[lim]], colWidths=[CONTENT_W])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 11), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, GREEN),
    ]))
    F += [box]

    doc.build(F, onFirstPage=_footer, onLaterPages=_footer)
    return _OUT


if __name__ == "__main__":
    out = build()
    print(f"wrote {out} ({out.stat().st_size} bytes)")
