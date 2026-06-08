"""Per-rule policy scan orchestration (build-04 §6).

``run_policy_scan`` is a pure orchestrator over the existing pieces: for each rule it
builds the attack pack (§3), scores its coverage (§5), instantiates the per-rule judge
(§4, for the honest calibration status), runs the pack's primitives as trials, puts a
**trial-outcome bootstrap CI** on the breach rate, and rolls everything into a
:class:`RuleBreachReport` (§6).

Both side-effecting steps are injected so the exit gate runs fully offline:
  * ``respond(primitive, config) -> str`` — get a model response. In production this is
    the scan engine / target adapter; in tests it is recorded transcripts.
  * ``grade(rule, judge, primitive, response) -> bool`` — did this trial breach. Defaults
    to :func:`default_grade` (the real per-rule judge); tests inject a recorded mock.

Wiring the *default* ``respond`` to the live scan engine is the one remaining §6 seam
(inject the per-rule ``RuleJudge`` in place of the engine's default ``JudgeAgent``); the
orchestration, CIs, calibration honesty, coverage gating, and report shape are all
proven here on fixtures.
"""

from __future__ import annotations

from collections.abc import Callable

from rogue.diff.bootstrap import bootstrap_ci
from rogue.schemas import AttackPrimitive
from rogue.schemas.governance import ClientPolicy, RuleBreachReport, RuleVerdict

from .coverage import score_pack_coverage
from .reaim import build_attack_pack
from .report import build_rule_breach_report
from .rule_judge import RuleJudge, instantiate_rule_judge

Responder = Callable[[AttackPrimitive, object], str]
Grader = Callable[["object", RuleJudge, AttackPrimitive, str], bool]


def default_grade(rule, judge: RuleJudge, primitive: AttackPrimitive, response: str) -> bool:
    """The live grader: render the primitive, judge the response against the rule, project to breach.

    LIVE path (one LLM call per trial) — exercised when ``run_policy_scan`` is wired to
    the scan engine, not in the offline exit gate (which injects a recorded grader).
    """
    from rogue.reproduce.instantiator import render
    from rogue.schemas import BREACH_VERDICTS

    rendered = render(primitive)
    result = judge.grade_sync(rendered, response, primitive)
    return getattr(result, "verdict", None) in BREACH_VERDICTS


def _config_id(config: object) -> str:
    return (
        getattr(config, "config_id", None)
        or getattr(config, "id", None)
        or getattr(config, "name", None)
        or str(config)
    )


def run_policy_scan(
    policy: ClientPolicy,
    config: object,
    corpus: list[AttackPrimitive],
    *,
    respond: Responder,
    grade: Grader = default_grade,
    n_trials: int = 5,
) -> RuleBreachReport:
    """Run ``policy`` against ``config`` over ``corpus`` and return a per-rule breach report."""
    config_id = _config_id(config)
    verdicts: list[RuleVerdict] = []

    for rule in policy.rules:
        pack = build_attack_pack(rule, corpus)
        cov = score_pack_coverage(pack, rule)
        judge = instantiate_rule_judge(rule)

        outcomes: list[bool] = []
        transcript_refs: list[str] = []
        for prim in pack.primitives:
            for t in range(n_trials):
                response = respond(prim, config)
                breached = bool(grade(rule, judge, prim, response))
                outcomes.append(breached)
                if breached:
                    transcript_refs.append(f"{rule.rule_id}::{prim.primitive_id}::t{t}")

        n = len(outcomes)
        n_breaches = sum(outcomes)
        lo, hi = bootstrap_ci(outcomes)
        verdicts.append(
            RuleVerdict(
                rule_id=rule.rule_id,
                breach_type=rule.breach_type,
                attack_family=(pack.primitives[0].family if pack.primitives else None),
                n_trials=n,
                n_breaches=n_breaches,
                breach_rate=(n_breaches / n if n else 0.0),
                ci_low=lo,
                ci_high=hi,
                calibration_status=judge.calibration_status,
                judge_precision=judge.judge_precision,
                coverage_status=cov.status,
                transcript_refs=transcript_refs,
            )
        )

    return build_rule_breach_report(policy.policy_id, config_id, verdicts)
