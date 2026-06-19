"""Offline tests for the ``mode="policy"`` per-rule scan path of :class:`DefaultScanEngine`.

The §4 build-area added a strictly-additive policy-mode branch to the shared engine: a decomposed
:class:`ClientPolicy` is scanned rule-by-rule via ``run_policy_scan`` and the resulting
:class:`RuleBreachReport` is rolled into a :class:`ScanReport` (carried verbatim under
``rule_breach_report`` for §4's diff_post). These tests inject a fake ``policy_runner`` so the path
runs fully offline (no panel, no judge, no DB, no network), mirroring the convention in
``tests/test_platform_engine.py`` (pytest-asyncio STRICT mode → every async test is marked).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.platform.engine import DefaultScanEngine
from rogue.platform.schemas import ScanSpec, TargetSpec
from rogue.report import Finding, ScanReport
from rogue.schemas import AttackFamily, AttackPrimitive
from rogue.schemas.governance import (
    BreachType,
    ClientPolicy,
    CoverageStatus,
    PolicyRule,
    RuleBreachReport,
    RuleVerdict,
)


# --- fixtures / fakes ---------------------------------------------------------------------------


def _rule(rule_id: str, breach_type: BreachType = BreachType.CAPABILITY_TRANSFER) -> PolicyRule:
    return PolicyRule(
        rule_id=rule_id,
        text=f"rule {rule_id} verbatim text",
        breach_type=breach_type,
        elicitation_target="make the agent produce the forbidden artifact",
        consummation_definition="the agent actually produced the artifact",
    )


def _policy(*rule_ids: str) -> ClientPolicy:
    ids = rule_ids or ("R1", "R2")
    return ClientPolicy(
        policy_id="pol-001",
        customer_id="cust-acme",
        rules=[_rule(rid) for rid in ids],
        source_text="the raw policy text",
    )


def _verdict(
    rule_id: str,
    *,
    n_trials: int,
    n_breaches: int,
    family: AttackFamily | None = AttackFamily.POLICY_ROLEPLAY,
    ci_low: float | None = 0.1,
    ci_high: float | None = 0.6,
) -> RuleVerdict:
    return RuleVerdict(
        rule_id=rule_id,
        breach_type=BreachType.CAPABILITY_TRANSFER,
        attack_family=family,
        n_trials=n_trials,
        n_breaches=n_breaches,
        breach_rate=(n_breaches / n_trials if n_trials else 0.0),
        ci_low=ci_low,
        ci_high=ci_high,
        calibration_status="calibrated" if n_breaches else "uncalibrated",
        judge_precision=0.95 if n_breaches else None,
        coverage_status=CoverageStatus.ADEQUATE,
        transcript_refs=[f"{rule_id}::p1::t0"] if n_breaches else [],
    )


def _report(verdicts: list[RuleVerdict]) -> RuleBreachReport:
    holds = sum(1 for v in verdicts if v.holds)
    return RuleBreachReport(
        policy_id="pol-001",
        config_id="plat-scan-0001",
        rule_verdicts=verdicts,
        holds_count=holds,
        total_count=len(verdicts),
    )


class FakePolicyRunner:
    """Stand-in for ``run_policy_scan``: records its args and returns a hand-built report.

    Signature matches the engine's call site exactly:
    ``policy_runner(policy, config, corpus, *, n_trials) -> RuleBreachReport``.
    """

    def __init__(self, report: RuleBreachReport) -> None:
        self._report = report
        self.policy = None
        self.config = None
        self.corpus = None
        self.n_trials = None
        self.calls = 0

    def __call__(self, policy, config, corpus, *, n_trials):
        self.calls += 1
        self.policy = policy
        self.config = config
        self.corpus = list(corpus)
        self.n_trials = n_trials
        return self._report


_GOLDEN = json.loads(
    (Path(__file__).parent / "fixtures" / "02_copirate_365_cve_2026_24299.json").read_text()
)


def _prim(pid: str) -> AttackPrimitive:
    """A valid AttackPrimitive (from the golden fixture) with a known primitive_id, so the
    corpus-filter assertions can address primitives by id without hand-rolling the schema."""
    return AttackPrimitive.model_validate(_GOLDEN).model_copy(update={"primitive_id": pid})


def _spec(**kw) -> ScanSpec:
    target = kw.pop("target", TargetSpec(endpoint="https://x/v1", api_key="k"))
    return ScanSpec(target=target, **kw)


# --- validation ---------------------------------------------------------------------------------


def test_scanspec_policy_mode_validates_with_policy():
    spec = _spec(mode="policy", policy=_policy())
    assert spec.mode == "policy"
    assert spec.policy is not None
    assert [r.rule_id for r in spec.policy.rules] == ["R1", "R2"]


@pytest.mark.asyncio
async def test_policy_mode_without_policy_raises_clear_valueerror():
    # mode="policy" is valid on the spec (policy defaults None) but the engine must refuse it.
    spec = _spec(mode="policy", policy=None)
    engine = DefaultScanEngine(policy_runner=FakePolicyRunner(_report([])))
    with pytest.raises(ValueError, match="requires spec.policy"):
        await engine.run(spec)


# --- the policy scan rollup ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_policy_rolls_verdicts_into_scanreport():
    verdicts = [
        _verdict("R1", n_trials=5, n_breaches=2),  # breaching
        _verdict("R2", n_trials=3, n_breaches=0),  # holds
    ]
    runner = FakePolicyRunner(_report(verdicts))
    engine = DefaultScanEngine(
        policy_runner=runner,
        repertoire_loader=lambda spec: [],  # no DB; corpus empty (runner ignores it anyway)
    )

    report = await engine.run(_spec(mode="policy", policy=_policy(), n_trials=5))

    assert isinstance(report, ScanReport)
    # n_tests / n_breaches are the Σ over rule verdicts.
    assert report.n_tests == 5 + 3
    assert report.n_breaches == 2 + 0
    # One Finding per rule verdict, severity tracking the breach.
    assert len(report.findings) == 2
    sev = {f.title: f.severity for f in report.findings}
    assert sev["Policy rule R1"] == "high"
    assert sev["Policy rule R2"] == "low"
    # n_trials was threaded through to the runner.
    assert runner.n_trials == 5
    assert runner.calls == 1
    # The injected policy object is the one off the spec.
    assert runner.policy.policy_id == "pol-001"


@pytest.mark.asyncio
async def test_rule_breach_report_round_trips_in_to_dict():
    verdicts = [
        _verdict("R1", n_trials=5, n_breaches=2, ci_low=0.12, ci_high=0.71),
        _verdict("R2", n_trials=4, n_breaches=1, ci_low=0.05, ci_high=0.55),
    ]
    runner = FakePolicyRunner(_report(verdicts))
    engine = DefaultScanEngine(policy_runner=runner, repertoire_loader=lambda spec: [])

    report = await engine.run(_spec(mode="policy", policy=_policy()))
    d = report.to_dict()

    assert "rule_breach_report" in d
    rbr = d["rule_breach_report"]
    assert rbr["policy_id"] == "pol-001"
    assert rbr["holds_count"] == 0  # both rules breached
    assert rbr["total_count"] == 2

    got = {v["rule_id"]: v for v in rbr["rule_verdicts"]}
    assert set(got) == {"R1", "R2"}
    # Per-rule detail diff_post needs: rule_id, breach_type, n_breaches, ci_low/ci_high.
    assert got["R1"]["breach_type"] == BreachType.CAPABILITY_TRANSFER.value
    assert got["R1"]["n_breaches"] == 2
    assert got["R1"]["ci_low"] == 0.12
    assert got["R1"]["ci_high"] == 0.71
    assert got["R2"]["n_breaches"] == 1
    assert got["R2"]["ci_low"] == 0.05
    assert got["R2"]["ci_high"] == 0.55
    # Flag #2 reconciliation: rule_breach_report carries everything diff_post needs.
    for v in got.values():
        for key in (
            "rule_id",
            "breach_type",
            "attack_family",
            "n_trials",
            "n_breaches",
            "breach_rate",
            "ci_low",
            "ci_high",
            "calibration_status",
        ):
            assert key in v, f"missing {key} in rule verdict payload"


# --- corpus filtering -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corpus_filtered_to_spec_attacks():
    full = [_prim("p1"), _prim("p2"), _prim("p3")]
    runner = FakePolicyRunner(_report([_verdict("R1", n_trials=1, n_breaches=0)]))
    engine = DefaultScanEngine(
        policy_runner=runner,
        repertoire_loader=lambda spec: list(full),  # full live corpus
    )

    # The trigger selected only p1 + p3.
    await engine.run(_spec(mode="policy", policy=_policy("R1"), attacks=["p1", "p3"]))

    seen_ids = [p.primitive_id for p in runner.corpus]
    assert seen_ids == ["p1", "p3"]  # filtered to the selection, order preserved


@pytest.mark.asyncio
async def test_corpus_unfiltered_when_attacks_none():
    full = [_prim("p1"), _prim("p2")]
    runner = FakePolicyRunner(_report([_verdict("R1", n_trials=1, n_breaches=0)]))
    engine = DefaultScanEngine(policy_runner=runner, repertoire_loader=lambda spec: list(full))

    await engine.run(_spec(mode="policy", policy=_policy("R1"), attacks=None))

    assert [p.primitive_id for p in runner.corpus] == ["p1", "p2"]  # whole corpus


# --- additivity guard: non-policy to_dict() byte-identity ---------------------------------------


def test_non_policy_to_dict_has_no_rule_breach_report_key():
    """A plain (non-policy) ScanReport's dict must be byte-identical to pre-change: NO
    ``rule_breach_report`` key. This is the additivity guard from the QA review."""
    plain = ScanReport(
        target="t",
        n_tests=3,
        n_breaches=1,
        cost_usd=0.001,
        findings=[
            Finding(
                family="roleplay",
                technique="x",
                vector="user_turn",
                severity="high",
                title="t",
                success_rate=0.5,
                n_trials=2,
                n_breach=1,
                example_attack="a",
                example_response="b",
            )
        ],
    )
    d = plain.to_dict()
    assert "rule_breach_report" not in d
    assert plain.rule_breach_report is None
    # The full key set is exactly the pre-change set.
    assert set(d) == {
        "target",
        "n_tests",
        "n_breaches",
        "breach_rate",
        "top_attack",
        "cost_usd",
        "findings",
    }
