"""End-to-end exit gate for Surface 1 OFFENSE (build-04 §6 = build-seq Phase 1 exit gate).

Runs `run_policy_scan` on the canonical `sample_policy.json` over a fixture corpus with
an injected (offline) responder + grader, then asserts the five §6 conditions: every
verdict carries a trial-outcome CI; calibration_status is honest (never a fabricated
judge precision); every holds carries a coverage status and a low-coverage holds is
downgraded; the report renders "holds against N/M"; and attestation-ready rows are
emitted. No network, no DB, no LLM, no paid run.
"""

from __future__ import annotations

import json
from pathlib import Path

from rogue.governance import (
    attestation_rows,
    build_rule_breach_report,
    render_markdown,
    run_policy_scan,
)
from rogue.schemas import AttackPrimitive, demo_deployment_configs
from rogue.schemas.governance import (
    BreachType,
    ClientPolicy,
    CoverageStatus,
    RuleVerdict,
)

_FIX = Path(__file__).parent / "fixtures" / "governance"


def _policy() -> ClientPolicy:
    return ClientPolicy.model_validate_json((_FIX / "sample_policy.json").read_text())


def _corpus() -> list[AttackPrimitive]:
    raw = json.loads((_FIX / "mini_corpus.json").read_text())
    rows = raw["primitives"] if isinstance(raw, dict) and "primitives" in raw else raw
    return [AttackPrimitive.model_validate(r) for r in rows]


def _respond(primitive, config) -> str:  # offline: a canned model response
    return "Sure — here is exactly what you asked for."


def _grade_only_r2_breaches(rule, judge, primitive, response) -> bool:
    # Deterministic recorded outcome: rule R2 breaches every trial, the rest hold.
    return rule.rule_id == "R2"


def test_phase1_exit_gate_end_to_end():
    policy = _policy()
    corpus = _corpus()
    config = demo_deployment_configs()[0]

    report = run_policy_scan(
        policy, config, corpus, respond=_respond, grade=_grade_only_r2_breaches, n_trials=4
    )

    assert report.total_count == len(policy.rules)
    assert len(report.rule_verdicts) == len(policy.rules)

    for v in report.rule_verdicts:
        # (1) every verdict carries a trial-outcome bootstrap CI
        assert v.ci_low is not None and v.ci_high is not None
        # (2) calibration is HONEST — never a fabricated precision (ADR-0011).
        #     (calibrated locally where the gitignored report exists; uncalibrated in CI — both honest.)
        assert v.calibration_status in ("calibrated", "uncalibrated")
        if v.calibration_status == "calibrated":
            assert v.judge_precision is not None
        else:
            assert v.judge_precision is None
        # (3) every verdict has a coverage status
        assert v.coverage_status is not None

    # holds rollup: R2 breached, the rest hold
    assert report.holds_count == len(policy.rules) - 1
    r2 = next(v for v in report.rule_verdicts if v.rule_id == "R2")
    assert not r2.holds
    assert r2.breach_rate == 1.0 and r2.ci_low == 1.0 and r2.ci_high == 1.0
    assert r2.transcript_refs  # breached trials leave transcript pointers

    # (4) the §3 "holds against N/M" output renders
    md = render_markdown(report)
    assert f"Holds against {report.holds_count} / {report.total_count}" in md
    assert "BREACHED" in md

    # (5) attestation-ready rows for area 03
    rows = attestation_rows(report)
    assert len(rows) == len(policy.rules)
    needed = {"rule", "breach_type", "target", "verdict", "calibration_status",
              "coverage_status", "n_breach", "n_trials", "ground_truth_ref"}
    assert needed <= set(rows[0])
    assert rows[0]["ground_truth_ref"] is None  # no independent per-rule label yet


def test_low_coverage_holds_is_downgraded_in_render():
    rpt = build_rule_breach_report("P1", "dc-haiku", [
        RuleVerdict(rule_id="R9", breach_type=BreachType.INFORMATION_DISCLOSURE,
                    n_trials=4, n_breaches=0, ci_low=0.0, ci_high=0.0,
                    coverage_status=CoverageStatus.INADEQUATE),
    ])
    md = render_markdown(rpt).lower()
    assert "low coverage" in md and "not load-bearing" in md


def test_uncalibrated_renders_honestly():
    rpt = build_rule_breach_report("P1", "dc-haiku", [
        RuleVerdict(rule_id="R1", breach_type=BreachType.CAPABILITY_TRANSFER,
                    n_trials=2, n_breaches=0, ci_low=0.0, ci_high=0.0,
                    calibration_status="uncalibrated", coverage_status=CoverageStatus.ADEQUATE),
    ])
    assert "uncalibrated" in render_markdown(rpt).lower()
