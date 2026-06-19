"""The per-rule breach report — the Surface-1 deliverable (build-04 §6).

Rolls per-rule :class:`RuleVerdict`s into a :class:`RuleBreachReport` ("holds against
N/M"), renders the markdown output, and emits attestation-ready rows for area 03 to
hash-chain (this module only *emits* the structured rows; it never builds the chain).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Optional

from rogue.diff.bootstrap import format_ci
from rogue.schemas.governance import (
    CoverageStatus,
    RuleBreachReport,
    RuleVerdict,
)


def build_rule_breach_report(
    policy_id: str, config_id: str, rule_verdicts: Sequence[RuleVerdict]
) -> RuleBreachReport:
    """Assemble the report + the holds rollup from per-rule verdicts."""
    verdicts = list(rule_verdicts)
    holds = sum(1 for v in verdicts if v.holds)
    return RuleBreachReport(
        policy_id=policy_id,
        config_id=config_id,
        rule_verdicts=verdicts,
        holds_count=holds,
        total_count=len(verdicts),
    )


def _calib_str(v: RuleVerdict) -> str:
    if v.calibration_status == "calibrated":
        p = f", p={v.judge_precision:.2f}" if v.judge_precision is not None else ""
        return f"calibrated{p}"
    return "uncalibrated (no CI on the judge)"


def render_markdown(report: RuleBreachReport) -> str:
    """Render the ``surface1_agent_spec.md §3`` "holds against N/M" output."""
    out = [
        f"# Policy breach report — {report.policy_id} vs {report.config_id}",
        "",
        f"**Holds against {report.holds_count} / {report.total_count} rules.**",
        "",
    ]
    for v in report.rule_verdicts:
        if v.holds:
            disp = "HOLDS"
            # A 'holds' is only load-bearing when the pack actually exercised the rule (§5).
            if v.coverage_status is not None and v.coverage_status != CoverageStatus.ADEQUATE:
                disp = f"HOLDS (low coverage — not load-bearing, {v.coverage_status.value})"
        else:
            disp = f"BREACHED {v.n_breaches}/{v.n_trials}"
        ci = (
            format_ci(v.breach_rate, v.ci_low, v.ci_high)
            if v.ci_low is not None and v.ci_high is not None
            else f"{v.breach_rate:.0%} (no CI)"
        )
        cov = v.coverage_status.value if v.coverage_status is not None else "unscored"
        fam = v.attack_family.value if v.attack_family is not None else "—"
        refs = f" · {len(v.transcript_refs)} transcript(s)" if v.transcript_refs else ""
        out.append(
            f"- **{v.rule_id}** [{v.breach_type.value}] — {disp} · family {fam} · "
            f"breach-rate {ci} · coverage {cov} · judge {_calib_str(v)}{refs}"
        )
    return "\n".join(out)


def attestation_rows(
    report: RuleBreachReport, *, corpus_as_of: Optional[datetime] = None
) -> list[dict]:
    """Emit per-rule decision-rationale rows for area 03 (hash-chained attestation).

    Mirrors the shape of ``attestation/emit._finding_record`` so the existing chain
    can consume them. ``target`` = the DeploymentConfig under test; ``probe`` = the
    rule's attack pack; ``verdict`` = the RuleVerdict. Honest by construction: the
    trial-outcome CI and the judge ``calibration_status`` are distinct fields
    (ADR-0011), and ``ground_truth_ref`` is None (no independent per-rule label yet).
    """
    rows: list[dict] = []
    for i, v in enumerate(report.rule_verdicts):
        breached = not v.holds
        rows.append(
            {
                "rule": v.rule_id,
                "breach_type": v.breach_type.value,
                "target": report.config_id,
                "probe": f"attack pack for {v.rule_id}",
                "n_breach": v.n_breaches,
                "n_trials": v.n_trials,
                "success_rate": round(v.breach_rate, 6),
                "ci": [v.ci_low, v.ci_high] if v.ci_low is not None else None,
                "verdict": "breach" if breached else "clean",
                "calibration_status": v.calibration_status,
                "judge_precision": v.judge_precision,
                "coverage_status": (
                    v.coverage_status.value if v.coverage_status is not None else None
                ),
                "consummation_event": v.breach_type.value if breached else "",
                "snapshot_ref": f"{report.policy_id}::{v.rule_id}::{i}",
                "ground_truth_ref": None,
                "corpus_as_of": corpus_as_of.isoformat() if corpus_as_of else None,
            }
        )
    return rows
