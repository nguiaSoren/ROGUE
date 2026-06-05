"""`ReportService` impl — render a persisted scan into customer artifacts (JSON / HTML / PDF).

The worker (`worker.py`) finalizes a scan by saving `ScanReport.to_dict()` under a fresh `report_id`
and stamping that id + the platform `score` onto the `ScanRecord`. This service is the read side: it
reconstructs a `rogue.report.ScanReport` from the persisted payload and re-renders it, layering in the
platform `score`/`risk_level` (which the bare SDK `ScanReport` doesn't carry). It owns no scan logic —
just persistence read + presentation.
"""

from __future__ import annotations

import html as _html
import re

from rogue.report import (
    SCORE_METHODOLOGY,
    Finding,
    ScanReport,
    humanize_technique,
    remediation_for,
    technique_label,
)

from . import scoring
from .interfaces import ReportService, ScanStore

# Credential shapes that must never appear in a rendered artifact. The persisted payload should already
# be secret-free (`TargetSpec.api_key` is excluded from the record), but example strings are harvested
# free-text, so we scrub provider key prefixes defensively before they reach a customer-facing page.
_SECRET_RE = re.compile(r"\b(?:sk|rk)[-_][A-Za-z0-9_-]{6,}\b")


def _redact(s: str | None) -> str | None:
    """Mask any leaked provider-key-shaped token in a free-text excerpt; pass `None` through."""
    if s is None:
        return None
    return _SECRET_RE.sub("[REDACTED]", s)


class DefaultReportService(ReportService):
    """Reconstructs the persisted `ScanReport` and renders JSON / HTML / PDF with the platform score."""

    def __init__(self, store: ScanStore):
        self.store = store

    # --- internals ------------------------------------------------------------------------------

    async def _load_report(self, scan_id: str) -> ScanReport:
        """Resolve `scan_id` → its persisted payload → a rebuilt `ScanReport`.

        Raises a clear `ValueError` if the scan is unknown, not completed, or has no stored report.
        """
        record = await self.store.get(scan_id)
        if record is None:
            raise ValueError(f"scan {scan_id!r} not found")
        if record.report_id is None:
            raise ValueError(f"scan {scan_id!r} has no report (status={record.status.value})")

        stored = await self.store.get_report(record.report_id)
        if stored is None:
            raise ValueError(f"report {record.report_id!r} for scan {scan_id!r} is missing")
        # `get_report` returns the report payload dict directly (== ScanReport.to_dict()), per the
        # ScanStore contract — NOT a {"payload": ...} wrapper. (The wrapper assumption silently emptied
        # every Postgres-backed report while the in-memory test passed.)
        payload = stored or {}

        # Rebuild Findings from the persisted dicts, redacting example excerpts on the way in. Only the
        # known Finding fields are carried over, so a forward-compatible payload (extra keys) is tolerated.
        findings: list[Finding] = []
        for raw in payload.get("findings") or []:
            findings.append(
                Finding(
                    family=raw["family"],
                    technique=raw["technique"],
                    vector=raw["vector"],
                    severity=raw["severity"],
                    title=raw["title"],
                    success_rate=raw["success_rate"],
                    n_trials=raw["n_trials"],
                    n_breach=raw["n_breach"],
                    example_attack=_redact(raw.get("example_attack")),
                    example_response=_redact(raw.get("example_response")),
                )
            )

        return ScanReport(
            target=payload.get("target", ""),
            n_tests=payload.get("n_tests", 0),
            n_breaches=payload.get("n_breaches", 0),
            cost_usd=payload.get("cost_usd", 0.0),
            findings=findings,
        )

    # --- renderers ------------------------------------------------------------------------------

    async def build_json(self, scan_id: str) -> dict:
        """The SDK report dict + the platform headline (`score` 0-100, its `risk_level`) + a coverage block.

        Additive over `ScanReport.to_dict()` (which already carries per-finding `remediation`): we layer the platform `score`/`risk_level`/`score_methodology` headline and a `coverage` block (n_tests, n_breaches, breach_rate, and the distinct human attack-families exercised) so a programmatic consumer gets the same scan-coverage framing the PDF/HTML surfaces show, without parsing prose. The underlying SDK shape is untouched.
        """
        report = await self._load_report(scan_id)
        score = scoring.score_for(report)
        out = report.to_dict()
        out["score"] = score
        out["risk_level"] = scoring.risk_level(score)
        out["score_methodology"] = SCORE_METHODOLOGY
        out["coverage"] = {
            "n_tests": report.n_tests,
            "n_breaches": report.n_breaches,
            "breach_rate": round(report.breach_rate, 4),
            "families_tested": report.families_covered(),
        }
        return out

    async def build_executive_summary(self, scan_id: str) -> str:
        """A CISO-ready MARKDOWN exec summary — the artifact an agent hands a security exec verbatim.

        Headline risk score + level, the breach ratio, a "Critical & high findings" list (each with humanized technique, severity, and the per-family remediation), and a one-line business framing. Reuses the same `_load_report` + `scoring` spine as the JSON/HTML/PDF renderers, so the headline number matches every other surface. Defensive about an empty report (no breached criticals → a clean all-clear), and the per-finding technique is run through `humanize_technique` so a raw ladder code / internal ULID never leaks into an exec-facing doc.
        """
        report = await self._load_report(scan_id)
        score = scoring.score_for(report)
        level = scoring.risk_level(score)

        # The findings that warrant exec attention: breached AND critical/high, severity-ranked as `top_findings` already orders them. A breached-but-medium/low finding is a detail for the full report, not the exec summary.
        notable = [
            f
            for f in report.top_findings(50)
            if f.breached and f.severity in ("critical", "high")
        ]

        lines = [
            "# ROGUE security scan — executive summary",
            "",
            f"**Risk {score:g}/100 ({level})** — {report.n_breaches}/{report.n_tests} attacks breached the target.",
            "",
        ]

        if notable:
            lines.append("## Critical & high findings")
            lines.append("")
            for f in notable:
                # Humanize the technique defensively — a graduated candidate persists a raw ULID, which must never reach an exec.
                technique = humanize_technique(f.technique)
                lines.append(
                    f"- **{technique}** ({f.severity}, {f.success_pct} success) — {remediation_for(f.family)}"
                )
            lines.append("")

        # One-line business framing — the "so what" a CISO acts on. Phrased by risk band so the
        # summary reads as a recommendation, not just a number.
        if level == "critical":
            framing = (
                "Exploitable critical weaknesses are present today; treat as an active risk to "
                "brand, compliance, and customer trust and remediate before further exposure."
            )
        elif level == "high":
            framing = (
                "Material weaknesses were reproduced; prioritize the findings above this sprint to "
                "reduce the likelihood of a public incident."
            )
        elif level == "medium":
            framing = (
                "Moderate weaknesses were found; schedule remediation and re-scan to confirm the "
                "risk has been driven down."
            )
        else:
            framing = (
                "No material weaknesses were reproduced in this run; maintain the current controls "
                "and continue periodic scanning."
            )
        lines.append(f"**Business impact:** {framing}")

        return "\n".join(lines)

    async def build_html(self, scan_id: str) -> str:
        """Reuse `ScanReport.to_html()`, surfacing the platform score/risk_level in the header KPIs.

        Per the R1 contract `ScanReport.to_html()` grows optional `score`/`risk_level` params that render the Risk-score KPI natively; we pass them through. While that change is in flight we fall back to the prior string-splice so the headline number still leads the page either way — the fallback is removed once `to_html` accepts the params everywhere.
        """
        report = await self._load_report(scan_id)
        score = scoring.score_for(report)
        level = scoring.risk_level(score)

        try:
            return report.to_html(score=score, risk_level=level)
        except TypeError:
            # `to_html` doesn't accept the params yet (R1 contract in flight). Splice a Risk-score KPI
            # in front of the existing KPI row so the headline number a customer acts on still leads
            # the page — without re-templating the whole report.
            page = report.to_html()
            kpi = (
                f'<div class="kpi">Risk score'
                f"<b>{score:g}/100 ({_html.escape(level)})</b></div>\n "
            )
            marker = '<div class="kpis">\n'
            if marker in page:
                page = page.replace(marker, marker + " " + kpi, 1)
            return page

    async def build_pdf(self, scan_id: str) -> bytes:
        """Render a CISO-ready PDF document (lazy-imports reportlab; raises if it's absent).

        Structure, top to bottom: a cover title, the headline Risk score + risk_level with the
        `SCORE_METHODOLOGY` caption, a one-paragraph executive summary (reusing `build_executive_summary`
        so the prose matches every other surface), a scan-coverage / methodology section (how many tests
        across which families, and one honest sentence on what "breach" means — ROGUE grades
        goal-achievement via an independent LLM judge), then the findings table, severity-grouped
        (critical → high → medium → low) with the wrapped Remediation column.
        """
        try:
            from reportlab.lib import colors  # noqa: PLC0415
            from reportlab.lib.pagesizes import letter  # noqa: PLC0415
            from reportlab.lib.styles import getSampleStyleSheet  # noqa: PLC0415
            from reportlab.platypus import (  # noqa: PLC0415
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as e:  # pragma: no cover - exercised only without reportlab installed
            raise RuntimeError(
                "PDF export requires reportlab. Install with: pip install reportlab"
            ) from e

        import io  # noqa: PLC0415

        report = await self._load_report(scan_id)
        score = scoring.score_for(report)
        level = scoring.risk_level(score)
        styles = getSampleStyleSheet()
        body = styles["BodyText"]

        # The exec summary is markdown (one short paragraph + a findings list); for the PDF we want a
        # single prose paragraph as the lead-in, so take the markdown's headline/business-framing prose
        # rather than re-rendering its bullet list (the table below already enumerates the findings).
        summary_md = await self.build_executive_summary(scan_id)
        summary_prose = self._summary_prose(summary_md)

        # --- Cover + headline -------------------------------------------------------------------
        story = [
            Paragraph("ROGUE Threat Scan — Security Assessment", styles["Title"]),
            Paragraph(f"Target: {_html.escape(report.target)}", styles["Heading3"]),
            Spacer(1, 10),
            Paragraph(f"Risk score {score:g}/100 ({level.upper()})", styles["Heading2"]),
            Paragraph(_html.escape(SCORE_METHODOLOGY), styles["BodyText"]),
            Spacer(1, 12),
        ]

        # --- Executive summary ------------------------------------------------------------------
        story.append(Paragraph("Executive summary", styles["Heading2"]))
        story.append(Paragraph(_html.escape(summary_prose), body))
        story.append(Spacer(1, 12))

        # --- Scan coverage / methodology --------------------------------------------------------
        families = report.families_covered()
        families_str = ", ".join(_html.escape(fam) for fam in families) or "none"
        story.append(Paragraph("Scan coverage &amp; methodology", styles["Heading2"]))
        story.append(
            Paragraph(
                f"This scan ran {report.n_tests} attack tests against the target across "
                f"{len(families)} attack famil{'y' if len(families) == 1 else 'ies'} "
                f"({families_str}); {report.n_breaches} breached "
                f"({_html.escape(report.breach_pct)} breach rate).",
                body,
            )
        )
        story.append(
            Paragraph(
                "A test counts as a breach when ROGUE judges the target to have achieved the attack's "
                "harmful goal — graded by an independent LLM judge on the model's actual response, not "
                "by keyword matching — with the rate taken as the worst (any-breach) result over the "
                "repeated trials per attack.",
                body,
            )
        )
        story.append(Spacer(1, 14))

        # --- Findings table (severity-grouped) --------------------------------------------------
        story.append(Paragraph("Findings", styles["Heading2"]))
        # Header + findings grouped by severity (critical → high → medium → low), breached-first within
        # each group. Free-text cells wrapped in Paragraphs so long finding/remediation text reflows
        # instead of overflowing. All cells escaped; the rebuilt Findings are already redacted by
        # `_load_report`. Remediation is render-time per-family (not stored on the Finding).
        data = [["Severity", "Success", "Technique", "Finding", "Remediation"]]
        for _sev, members in report.findings_by_severity():
            for f in members:
                data.append(
                    [
                        _html.escape(f.severity),
                        f.success_pct,
                        Paragraph(_html.escape(technique_label(f.family)), body),
                        Paragraph(_html.escape(f.title), body),
                        Paragraph(_html.escape(remediation_for(f.family)), body),
                    ]
                )
        if len(data) == 1:
            data.append([Paragraph("No findings.", body), "", "", "", ""])
        table = Table(data, repeatRows=1, colWidths=[55, 50, 90, 130, 195])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(table)

        buf = io.BytesIO()
        SimpleDocTemplate(buf, pagesize=letter).build(story)
        return buf.getvalue()

    @staticmethod
    def _summary_prose(summary_md: str) -> str:
        """Distill the markdown exec summary into one prose paragraph for the PDF lead-in.

        `build_executive_summary` emits a headline line, an optional bullet list of critical/high
        findings (enumerated again by the PDF's findings table, so dropped here), and a bold
        "Business impact:" framing line. We keep the headline + the business framing, stripped of
        markdown emphasis, joined into a single sentence-flowing paragraph.
        """
        keep: list[str] = []
        for line in summary_md.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("- "):
                continue
            # Drop markdown bold/emphasis markers and the "Business impact:" label so the prose reads
            # as plain narrative.
            text = stripped.replace("**", "").replace("Business impact:", "").strip()
            if text:
                keep.append(text)
        return " ".join(keep)


__all__ = ["DefaultReportService", "_redact"]
