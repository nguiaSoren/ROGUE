"""The :class:`Report` — the customer-facing result of a completed scan.

Leads with an overall risk score and ranked findings, and knows how to export itself (the formats
security teams route into Slack / Jira / Notion / email). The risk score is **synthesized by the
SDK** — ROGUE internally has no single risk number — via a saturating product over findings.
"""

from __future__ import annotations

import json as _json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, computed_field

from .common import Severity
from .finding import Finding


def compute_risk_score(findings: list[Finding]) -> float:
    """Overall exposure in [0, 100].

    ``100 * (1 - Π(1 - wᵢ·sᵢ))`` where ``sᵢ`` = success_rate and ``wᵢ`` = severity weight. Monotonic,
    saturating, dominated by the worst findings. No findings → 0.0.
    """
    prod = 1.0
    for f in findings:
        prod *= 1.0 - min(1.0, f.severity.weight * f.success_rate)
    return round(100.0 * (1.0 - prod), 1)


def risk_level_for(score: float) -> Severity:
    """Band a 0..100 risk score into a severity level."""
    if score >= 75:
        return Severity.CRITICAL
    if score >= 50:
        return Severity.HIGH
    if score >= 25:
        return Severity.MEDIUM
    return Severity.LOW


class ReportSummary(BaseModel):
    """Structured finding counts (the numeric companion to :meth:`Report.summary`)."""

    n_findings: int = 0
    n_critical: int = 0
    n_high: int = 0
    n_medium: int = 0
    n_low: int = 0

    @classmethod
    def from_findings(cls, findings: list[Finding]) -> ReportSummary:
        by = {s: 0 for s in Severity}
        for f in findings:
            by[f.severity] += 1
        return cls(
            n_findings=len(findings),
            n_critical=by[Severity.CRITICAL],
            n_high=by[Severity.HIGH],
            n_medium=by[Severity.MEDIUM],
            n_low=by[Severity.LOW],
        )


class Report(BaseModel):
    """The risk report for a completed scan."""

    id: str
    scan_id: str
    deployment_id: str
    generated_at: datetime | None = None
    findings: list[Finding] = Field(default_factory=list)

    # Server may send these; if absent we derive them so the object is always self-consistent.
    risk_score: float | None = None
    risk_level: Severity | None = None
    stats: ReportSummary | None = None

    def model_post_init(self, __context) -> None:
        # Always sort findings severity-desc then success-rate-desc, and backfill derived fields.
        ordered = sorted(
            self.findings, key=lambda f: (f.severity.rank, f.success_rate), reverse=True
        )
        object.__setattr__(self, "findings", ordered)
        if self.risk_score is None:
            object.__setattr__(self, "risk_score", compute_risk_score(ordered))
        if self.risk_level is None:
            object.__setattr__(self, "risk_level", risk_level_for(self.risk_score))
        if self.stats is None:
            object.__setattr__(self, "stats", ReportSummary.from_findings(ordered))

    # --- accessors ----------------------------------------------------------------------------

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)

    def top_findings(self, n: int = 5) -> list[Finding]:
        """The ``n`` highest-priority findings (already sorted severity- then success-desc)."""
        return self.findings[:n]

    def findings_by_severity(self, severity: Severity | str) -> list[Finding]:
        sev = Severity(severity) if not isinstance(severity, Severity) else severity
        return [f for f in self.findings if f.severity == sev]

    def summary(self) -> str:
        """Human-readable one-paragraph summary (this is what ``print(report.summary())`` shows)."""
        s = self.stats
        if not self.findings:
            return (
                f"Risk score {self.risk_score}/100 ({self.risk_level.value}). "
                "No vulnerabilities reproduced against this deployment."
            )
        worst = self.findings[0]
        parts = []
        if s.n_critical:
            parts.append(f"{s.n_critical} critical")
        if s.n_high:
            parts.append(f"{s.n_high} high")
        if s.n_medium:
            parts.append(f"{s.n_medium} medium")
        if s.n_low:
            parts.append(f"{s.n_low} low")
        breakdown = ", ".join(parts)
        # Lead with the headline numbers and the worst finding, then a plain-language "what this is"
        # line so a non-expert reader understands the top exposure before acting on it.
        head = (
            f"Risk score {self.risk_score}/100 ({self.risk_level.value}). "
            f"{s.n_findings} finding(s): {breakdown}. "
            f"Top exposure: {worst.title!r} via {worst.technique} "
            f"({worst.success_pct} success over {worst.n_trials} trials)."
        )
        if worst.explanation:
            head += f" What this is: {worst.explanation}"
        return head

    # --- exporters ----------------------------------------------------------------------------

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    def export_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        """Serialize to JSON. Writes to ``path`` if given; always returns the JSON string."""
        text = _json.dumps(self.to_dict(), indent=indent, default=str)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def export_markdown(self, path: str | Path | None = None) -> str:
        """Render a CISO-readable Markdown report. Writes to ``path`` if given; returns the text."""
        gen = (self.generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "# ROGUE Threat Report",
            "",
            f"- **Risk score:** {self.risk_score}/100 (**{self.risk_level.value.upper()}**)",
            f"- **Deployment:** `{self.deployment_id}`",
            f"- **Scan:** `{self.scan_id}`",
            f"- **Generated:** {gen}",
            "",
            f"**Findings:** {self.stats.n_findings} "
            f"({self.stats.n_critical} critical · {self.stats.n_high} high · "
            f"{self.stats.n_medium} medium · {self.stats.n_low} low)",
            "",
            self.summary(),
            "",
            "## Findings",
            "",
        ]
        if not self.findings:
            lines.append("_No vulnerabilities reproduced._")
        for i, f in enumerate(self.findings, 1):
            lines += [
                f"### {i}. [{f.severity.value.upper()}] {f.title}",
                "",
                f"- **Technique:** {f.technique} (`{f.family}`)",
                f"- **Vector:** `{f.vector}`",
                f"- **Success rate:** {f.success_pct} over {f.n_trials} trials",
            ]
            if f.confidence is not None:
                lines.append(f"- **Judge confidence:** {round(f.confidence * 100)}%")
            if f.source_url:
                lines.append(f"- **Source:** {f.source_url}")
            if f.description:
                lines += ["", f.description]
            if f.example_attack:
                lines += ["", "**Example attack:**", "", "```", f.example_attack.strip(), "```"]
            if f.explanation:
                lines += ["", f"**What this is:** {f.explanation}"]
            lines += ["", f"**Remediation:** {f.remediation}", ""]
        text = "\n".join(lines)
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def export_pdf(self, path: str | Path) -> str:
        """Render to PDF (requires the ``rogue[pdf]`` extra). Returns the written path as a string.

        Degrades with a clear, actionable error if reportlab is not installed.
        """
        try:
            from reportlab.lib.pagesizes import letter  # noqa: PLC0415
            from reportlab.lib.styles import getSampleStyleSheet  # noqa: PLC0415
            from reportlab.platypus import (  # noqa: PLC0415
                Paragraph,
                SimpleDocTemplate,
                Spacer,
            )
        except ImportError as e:  # pragma: no cover - exercised only without the extra
            raise RuntimeError(
                "PDF export requires the optional dependency. Install with: pip install 'rogue[pdf]'"
            ) from e

        styles = getSampleStyleSheet()
        story = [
            Paragraph("ROGUE Threat Report", styles["Title"]),
            Paragraph(
                f"Risk score {self.risk_score}/100 ({self.risk_level.value.upper()})",
                styles["Heading2"],
            ),
            Paragraph(self.summary(), styles["BodyText"]),
            Spacer(1, 12),
        ]
        for i, f in enumerate(self.findings, 1):
            story.append(
                Paragraph(f"{i}. [{f.severity.value.upper()}] {f.title}", styles["Heading3"])
            )
            story.append(
                Paragraph(
                    f"{f.technique} · vector {f.vector} · {f.success_pct} over {f.n_trials} trials",
                    styles["BodyText"],
                )
            )
            if f.description:
                story.append(Paragraph(f.description, styles["BodyText"]))
            if f.explanation:
                story.append(Paragraph(f"<b>What this is:</b> {f.explanation}", styles["BodyText"]))
            story.append(Paragraph(f"<b>Remediation:</b> {f.remediation}", styles["BodyText"]))
            story.append(Spacer(1, 8))
        out = str(path)
        SimpleDocTemplate(out, pagesize=letter).build(story)
        return out

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return f"Report {self.id} · risk {self.risk_score}/100 ({self.risk_level.value}) · {self.stats.n_findings} findings"


__all__ = ["Report", "ReportSummary", "compute_risk_score", "risk_level_for"]
