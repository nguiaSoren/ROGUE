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
        """The SDK report dict + the platform headline (`score` 0-100 and its `risk_level`)."""
        report = await self._load_report(scan_id)
        score = scoring.score_for(report)
        out = report.to_dict()
        out["score"] = score
        out["risk_level"] = scoring.risk_level(score)
        out["score_methodology"] = SCORE_METHODOLOGY
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
        """Reuse `ScanReport.to_html()`, injecting the platform score/risk_level into the header KPIs."""
        report = await self._load_report(scan_id)
        score = scoring.score_for(report)
        level = scoring.risk_level(score)
        page = report.to_html()

        # Splice a Risk-score KPI in front of the existing KPI row so the headline number a customer
        # acts on leads the page — without re-templating the whole report.
        kpi = (
            f'<div class="kpi">Risk score'
            f"<b>{score:g}/100 ({_html.escape(level)})</b></div>\n "
        )
        marker = '<div class="kpis">\n'
        if marker in page:
            page = page.replace(marker, marker + " " + kpi, 1)
        return page

    async def build_pdf(self, scan_id: str) -> bytes:
        """Render score + summary + a findings table to PDF bytes (lazy-imports reportlab)."""
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

        story = [
            Paragraph("ROGUE Threat Scan", styles["Title"]),
            Paragraph(f"Risk score {score:g}/100 ({level.upper()})", styles["Heading2"]),
            Paragraph(_html.escape(SCORE_METHODOLOGY), styles["BodyText"]),
            Paragraph(_html.escape(report.target), styles["BodyText"]),
            Paragraph(
                f"Tests {report.n_tests} &middot; Breaches {report.n_breaches} "
                f"&middot; Rate {report.breach_pct}",
                styles["BodyText"],
            ),
            Spacer(1, 12),
        ]

        # Findings table: header + the ranked findings (severity, success, technique, finding,
        # remediation). Free-text cells wrapped in Paragraphs so long finding/remediation text reflows
        # instead of overflowing. All cells escaped; the rebuilt Findings are already redacted by
        # `_load_report`. Remediation is render-time per-family (not stored on the Finding).
        cell = styles["BodyText"]
        data = [["Severity", "Success", "Technique", "Finding", "Remediation"]]
        for f in report.top_findings(50):
            data.append(
                [
                    _html.escape(f.severity),
                    f.success_pct,
                    Paragraph(_html.escape(technique_label(f.family)), cell),
                    Paragraph(_html.escape(f.title), cell),
                    Paragraph(_html.escape(remediation_for(f.family)), cell),
                ]
            )
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


__all__ = ["DefaultReportService", "_redact"]
