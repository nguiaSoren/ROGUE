"""Generate the ROGUE research-brief PDF served at /research and attached to outreach emails.

Editorial-offprint design: a serif masthead + lead/abstract, each finding numbered
in a serif rail beside a serif title with a hairline rule above, the reading column
indented under the title while figures and metric chips span full width. White page,
print-clean, credible for an academic reader. All numbers are verbatim from the
measured work (mirror of `frontend/src/app/research/page.tsx`). Writes to
`frontend/public/rogue-research-brief.pdf`.

    uv run python scripts/ops/research_brief_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
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
MUTED = colors.HexColor("#525860")  # darker gray, readable on white
LIGHT = colors.HexColor("#f3f6f4")
CHIPBG = colors.HexColor("#eef3f0")
LINE = colors.HexColor("#d3d8d4")
HAIR = colors.HexColor("#c7ccc8")

MARGIN = 0.8 * inch
CONTENT_W = LETTER[0] - 2 * MARGIN
RAIL_W = 0.86 * inch  # the serif-number rail; body indents to match


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        # --- masthead / lead (serif display) ---
        "wordmark": ParagraphStyle("wordmark", parent=base["Normal"], fontName="Times-Bold",
                                   fontSize=23, leading=25, textColor=INK),
        "tag": ParagraphStyle("tag", parent=base["Normal"], fontName="Helvetica-Bold",
                              fontSize=8, leading=11, textColor=GREEN, spaceBefore=3),
        "metaR": ParagraphStyle("metaR", parent=base["Normal"], fontName="Helvetica",
                                fontSize=8.5, leading=12.5, textColor=MUTED, alignment=TA_RIGHT),
        "headline": ParagraphStyle("headline", parent=base["Normal"], fontName="Times-Bold",
                                   fontSize=20, leading=23, textColor=INK, spaceBefore=2),
        "abstract": ParagraphStyle("abstract", parent=base["Normal"], fontName="Times-Roman",
                                   fontSize=11.5, leading=16.5, textColor=BODY, alignment=TA_LEFT),
        "meta": ParagraphStyle("meta", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.5, leading=12, textColor=MUTED),
        # --- finding rail + title (serif) ---
        "fnum": ParagraphStyle("fnum", parent=base["Normal"], fontName="Times-Bold",
                               fontSize=27, leading=27, textColor=GREEN),
        "flabel": ParagraphStyle("flabel", parent=base["Normal"], fontName="Helvetica-Bold",
                                 fontSize=7, leading=9.5, textColor=MUTED, spaceBefore=3),
        "ftitle": ParagraphStyle("ftitle", parent=base["Normal"], fontName="Times-Bold",
                                 fontSize=14.5, leading=17.5, textColor=INK),
        # --- body (sans, indented under the title) ---
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica",
                               fontSize=10.5, leading=16, textColor=BODY, alignment=TA_LEFT,
                               spaceAfter=6, leftIndent=RAIL_W),
        # --- chips / notes / figures (full width) ---
        "chipval": ParagraphStyle("cv", parent=base["Normal"], fontName="Helvetica-Bold",
                                  fontSize=13, leading=16, textColor=GREEN),
        "chiplbl": ParagraphStyle("cl", parent=base["Normal"], fontName="Helvetica",
                                  fontSize=7.5, leading=10, textColor=MUTED),
        "notelbl": ParagraphStyle("nl", parent=base["Normal"], fontName="Helvetica-Bold",
                                  fontSize=7.5, leading=10, textColor=GREEN),
        "note": ParagraphStyle("note", parent=base["Normal"], fontName="Helvetica",
                               fontSize=9.5, leading=14, textColor=colors.HexColor("#3c4047")),
        "li": ParagraphStyle("li", parent=base["Normal"], fontName="Helvetica",
                             fontSize=10.5, leading=15.5, textColor=BODY),
        "limit": ParagraphStyle("lim", parent=base["Normal"], fontName="Helvetica",
                                fontSize=10, leading=15, textColor=colors.HexColor("#3c4047")),
        "barlbl": ParagraphStyle("barlbl", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=8, leading=10.5, textColor=INK),
        "barval": ParagraphStyle("barval", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=8, leading=10.5, textColor=INK),
        "cap": ParagraphStyle("cap", parent=base["Normal"], fontName="Helvetica-Oblique",
                              fontSize=8, leading=11, textColor=MUTED),
    }


S = _styles()
b = lambda x: f"<b>{x}</b>"  # noqa: E731


def _masthead() -> Table:
    """Editorial masthead: serif wordmark on the left, meta on the right, green rule below."""
    left = [Paragraph('<font color="#1f9d55">ROGUE</font>', S["wordmark"]),
            Paragraph("RESEARCH&nbsp;BRIEF", S["tag"])]
    right = Paragraph(
        "A continuous open-web LLM red-team.<br/>The methods and the measured results, "
        "including the negative ones.", S["metaR"])
    t = Table([[left, right]], colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.58])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -1), 1.6, GREEN),
    ]))
    return t


def _finding(num: str, label: str, title: str) -> Table:
    """A finding header: serif number + label in the rail, serif title beside it, hairline above."""
    rail = [Paragraph(num, S["fnum"]), Paragraph(label.upper(), S["flabel"])]
    t = Table([[rail, Paragraph(title, S["ftitle"])]], colWidths=[RAIL_W, CONTENT_W - RAIL_W])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 13), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LINEABOVE", (0, 0), (-1, 0), 0.75, HAIR),
    ]))
    return t


def _chips(items: list[tuple[str, str]]) -> Table:
    cells = [[Paragraph(v, S["chipval"]), Spacer(1, 2), Paragraph(lbl.upper(), S["chiplbl"])]
             for v, lbl in items]
    w = CONTENT_W / len(items)
    t = Table([cells], colWidths=[w] * len(items))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CHIPBG),
        ("LEFTPADDING", (0, 0), (-1, -1), 11),
        ("RIGHTPADDING", (0, 0), (-1, -1), 11),
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


def _judgefig() -> Table:
    """Horizontal bars: judge agreement vs the field (the last to tied-with-frontier story)."""
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
        "ROGUE v1 last; v3 tied with the frontier classifiers.", S["cap"])
    wrap = Table([[t], [cap]], colWidths=[CONTENT_W])
    wrap.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 1), (0, 1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
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
        _masthead(),
        Spacer(1, 16),
        Paragraph("Seven findings from a solo open-web LLM red-team, the negatives included.", S["headline"]),
        Spacer(1, 7),
        Paragraph(
            "Every result here is measured and reproducible. A grey-literature reproducibility audit showing "
            "a source&rsquo;s claimed jailbreak success doesn&rsquo;t predict what reproduces against your "
            "deployment; scheduling shown to be a capability lever, not just an optimization; an LLM-as-judge "
            "calibrated against human labels and then generalized into a four-breach-type discipline; a "
            "publication-grade null result that redirected engineering; measured remediation that refuses a "
            "fix it can&rsquo;t prove; shared agent-skill pools treated as an assurance surface to audit and "
            "sign before sharing; and the measure-before-build habit behind all of it.", S["abstract"]),
        Spacer(1, 4),
        Paragraph(
            "Soren Obounou Nguia &nbsp;·&nbsp; Seoul &nbsp;·&nbsp; nguiasoren@gmail.com "
            "&nbsp;·&nbsp; live evidence at /matrix, /analytics, /about", S["meta"]),
    ]

    # 01 — reproduction (lead)
    F += [_finding("01", "reproduction",
                   "Claimed potency doesn&rsquo;t predict what reproduces against your deployment.")]
    F += [Paragraph(
        "Of 17 harvested techniques whose source claimed " + b("~100% success") + ", only " + b("6") +
        " reproduce at all, and their mean measured breach rate is " + b("13%") + ". Across the 56 "
        "techniques that publish a number, claimed success and measured reproduction are "
        + b("uncorrelated (Spearman -0.07, 95% CI [-0.34, +0.19])") + ", a claimed rate is not portable "
        "signal, which is why ROGUE re-measures every technique against your model and system prompt, "
        "not the source&rsquo;s.", S["body"])]
    F += [Paragraph(
        "The same pattern is a reproduction funnel. Across " + b("301 techniques from 19 open-web sources") +
        " on a five-model panel, the &ldquo;works on at least one of five models&rdquo; rate (40%) is "
        "inflated by the weakest target: on a " + b("frozen open-weight model only ~9% reproduce") + ", "
        "and " + b("~4% on the most robust model") + ". Reproduction is whether the technique still "
        "produces a consummated breach toward its native objective (a mixed corpus, predominantly "
        "harmful), scored by the calibrated under-counting judge; paper-sourced techniques degrade "
        "more slowly than grey-literature ones.", S["body"])]
    F += [Paragraph(
        "A stronger-model re-extraction (Sonnet 4.6) of all 148 candidate sources confirmed the null is "
        "not an extraction artifact, it recovered a claimed rate for only 1 of 94 unquantified sources, "
        "so the small claimed-rate sample reflects that the open web rarely quantifies these claims, not "
        "a weak extractor. The claimed values carry ~17% extraction noise, so the -0.07 reads as "
        + b("no predictive signal") + ", not a precise estimate.", S["body"])]
    F += [Spacer(1, 4), _chips([
        ("-0.07", "claimed vs measured (n=56)"),
        ("100% → 13%", "claimed ~100%, mean measured"),
        ("40 → 4%", "reproduce: best-of-5 to robust"),
        ("judge-only", "v3 re-grade, collected data"),
    ]), Spacer(1, 6)]
    F += [_note(
        "The honest version of &ldquo;we test real attacks&rdquo;: a success rate claimed in a paper or "
        "forum is not portable to your deployment. The value is the re-measurement against your model, "
        "system prompt, and tools under a judge calibrated to under-count, with a frozen open-weight "
        "anchor so non-reproduction isn&rsquo;t confounded by silent vendor patching.")]

    # 02 — scheduling
    F += [_finding("02", "scheduling", "Scheduling as a capability lever, not just an optimization.")]
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

    # 03 — judge calibration
    F += [_finding("03", "judge",
                   "Calibrating an LLM-as-judge against human labels, then recalibrating when a benchmark exposed it.")]
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
        ": a <i>harm</i> breach (capability transfer) at " + b("89.3% agreement on JBB-300") +
        "; a <i>content</i> breach (information-disclosure, did the protected datum appear), "
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
        ("89.3%", "harm (capability transfer)"),
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

    # 04 — null result
    F += [_finding("04", "null result", "A publication-grade null result: grammar-component predictive power.")]
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

    # 05 — remediation
    F += [_finding("05", "remediation",
                   "Measured remediation: prove a fix closes the breach without over-blocking, or refuse to ship it.")]
    F += [Paragraph(
        "Finding a breach is half the job. ROGUE also " + b("generates a candidate fix") + ", then "
        "<i>measures</i>, by re-scanning a mutated test config with the same calibrated judge, whether it "
        "closes the breach " + b("without over-blocking") + " legitimate traffic, and " + b("refuses") + " any "
        "it cannot prove (it generates and verifies; the client deploys; it never sits in the request path). "
        "Across live runs it " + b("refused every offline patch") + ", each for a distinct measured reason: a "
        "medical/financial-directive patch " + b("did not reduce the breach") + " (" + b("20.8% → ~25%") + "), "
        "and a system-prompt-extraction patch " + b("over-blocked legitimate traffic") + ", the calibrated "
        "over-block judge flagged " + b("~20%") + " where a marker heuristic had scored " + b("0%") + ", so the "
        "loop refused it for an architecture change. The &ldquo;without over-blocking&rdquo; check is itself "
        "calibrated and earned its keep: an over-block judge scored against a 50-case independent set reaches "
        + b("98% agreement, 100% precision, 0% over-flag") + " (vs an 88% marker heuristic) and caught the "
        "over-block the heuristic missed.", S["body"])]
    F += [Spacer(1, 4), _chips([
        ('<font color="#c0392b">0% → ~20%</font>', "RD04 over-block: heuristic → judge"),
        ('<font color="#c0392b">20.8 → ~25%</font>', "RA06 patch: no reduction"),
        ("98% / 0%", "over-block judge: agree / over-flag"),
        ("88 → 98%", "over-block detector calibrated"),
    ]), Spacer(1, 6)]
    F += [_note(
        "The contribution is not a new mitigation but the discipline: a fix is accepted only when a re-scan "
        "proves it closes the breach without over-blocking, and refused otherwise, and the calibrated judge is "
        "what makes &ldquo;does not over-block&rdquo; trustworthy. It flipped a would-be accept (heuristic 0% "
        "over-block) into a correct refusal (judge ~20%). A runtime guardrail asserts it blocks; this measures "
        "it, and says no when a patch does not hold or over-blocks.")]

    # 06 — skill pools (new)
    F += [_finding("06", "skill pools",
                   "Shared skill pools are an assurance surface, not a free upgrade.")]
    F += [Paragraph(
        "Agents increasingly accumulate and " + b("share skills and memory") + " across a fleet. Pooling "
        "them is an unaudited surface: a skill distilled from private work can leak it, a popular skill can "
        "quietly make the agent worse, two benign skills can combine into something harmful. ROGUE treats a "
        "pool as a red-team target, measures each risk, and emits a " + b("signed, tamper-evident "
        "attestation") + " for the pool before it ships.", S["body"])]
    F += [Paragraph(
        "A first measurement. Against a " + b("deliberately weak agent") + " (Llama-3.1-8B) holding a planted "
        "secret, a standard extraction pack recovered it on " + b("17 of 20") + " skills, with "
        + b("zero false positives on the 12 controls") + ", despite an explicit &ldquo;never reveal&rdquo; "
        "instruction, instruction-following is not containment. And of four candidate skills with enough "
        "held-out tasks to measure, only " + b("one earned promotion") + " under a verified-net-effect gate; "
        "the rest were neutral or worse. Accumulated skills are not free upgrades.", S["body"])]
    F += [Paragraph(
        "The same canary pack across four targets shows the surprise: leakage does not fall with size or "
        "capability, it falls with " + b("alignment") + ". A 32B reasoning model leaks every canary (100%), a "
        "70B instruct model 65%, and the smallest, safety-tuned 20B model resists best (35%), so the size "
        "ordering and the leak ordering have nothing to do with each other, a skill-pool leakage audit cannot "
        "be waved off by pointing at how big or capable the model is.", S["body"])]
    F += [Spacer(1, 4), _chips([
        ("100%", "qwen3-32b · reasoning"),
        ("85%", "llama-3.1-8b · instruct"),
        ("65%", "llama-3.3-70b · instruct"),
        ("35%", "gpt-oss-20b · safety-tuned"),
    ]), Spacer(1, 6)]
    F += [Spacer(1, 4), _chips([
        ("17 / 20", "canary leak · weak target"),
        ("0 / 12", "control false positives"),
        ("1 of 4", "skills earn promotion"),
        ("signed", "tamper-evident attestation"),
    ]), Spacer(1, 6)]
    F += [_note(
        "The under-discussed part is the <i>surface</i>, not the number. That a weak model leaks a secret it "
        "was told to hold is expected, it is the known extraction / prompt-injection mechanism; the "
        "contribution is treating shared skill and memory pools as something to audit before sharing, "
        "leakage, verified promotion, dangerous combinations, signed. Honest caveats: this is a first "
        "measurement on a <i>weak</i> target with a small n and a standard pack, so the leak rate is "
        "illustrative of the surface, not a hardened &ldquo;agent pools leak 85%&rdquo; claim; the "
        "verified-promotion sample is n=4 (one promotion rests on a single decisive case); single trust "
        "domain, cross-team isolation is roadmap.")]

    # 07 — discipline
    F += [_finding("07", "discipline", "Measure-before-build discipline.")]
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
    F += [Spacer(1, 10)]
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
