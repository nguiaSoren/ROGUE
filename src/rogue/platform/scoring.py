"""The platform `score` (0-100) — the single headline risk number.

Pinned in the spine because both the worker (when finalizing a scan record) and the ReportService
(when rendering) need the identical formula. Mirrors the SDK's `compute_risk_score`: a saturating
product over findings, dominated by the worst ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rogue.report import Finding, ScanReport

_SEVERITY_WEIGHT = {"critical": 1.0, "high": 0.7, "medium": 0.4, "low": 0.15}


def score_from_findings(findings: list[Finding]) -> float:
    """0-100 risk. ``100 * (1 - Π(1 - wᵢ·sᵢ))`` over findings (wᵢ=severity weight, sᵢ=success_rate)."""
    prod = 1.0
    for f in findings:
        w = _SEVERITY_WEIGHT.get(getattr(f.severity, "value", f.severity), 0.15)
        prod *= 1.0 - min(1.0, w * f.success_rate)
    return round(100.0 * (1.0 - prod), 1)


def score_for(report: ScanReport) -> float:
    return score_from_findings(report.findings)


def risk_level(score: float) -> str:
    if score >= 75:
        return "critical"
    if score >= 50:
        return "high"
    if score >= 25:
        return "medium"
    return "low"


__all__ = ["score_from_findings", "score_for", "risk_level"]
