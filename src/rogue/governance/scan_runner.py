"""Per-rule policy scan orchestration (build-04 §6).

``run_policy_scan`` is a pure orchestrator over the existing pieces: for each rule it
builds the attack pack (§3), scores its coverage (§5), instantiates the per-rule judge
(§4, for the honest calibration status), runs the pack's primitives as trials, puts a
**trial-outcome bootstrap CI** on the breach rate, and rolls everything into a
:class:`RuleBreachReport` (§6).

Both side-effecting steps are injected so the exit gate runs fully offline:
  * ``respond(primitive, config) -> str`` — get a model response. Tests inject recorded
    transcripts; :func:`live_responder` provides the real one (the §6 live seam).
  * ``grade(rule, judge, primitive, response, config) -> bool`` — did this trial breach.
    Defaults to :func:`default_grade` (the real per-rule judge); tests inject a mock.

:func:`live_responder` wires ``respond`` to the live scan path (``TargetPanel`` + the
existing adapters); ``default_grade`` wires ``grade`` to area-02's per-rule judge. Both
render via ``reproduce.instantiator.render`` (which needs the config), so the offline
exit gate keeps ``run_policy_scan`` itself render-free and injects pure mocks.
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
Grader = Callable[[object, RuleJudge, AttackPrimitive, str, object], bool]


def default_grade(
    rule, judge: RuleJudge, primitive: AttackPrimitive, response: str, config
) -> bool:
    """The live grader: render the primitive against the config, judge the response, project to breach.

    LIVE path (one judge LLM call per trial) — exercised when ``run_policy_scan`` is wired
    to real targets, not in the offline exit gate (which injects a recorded grader).
    """
    from rogue.reproduce.instantiator import render
    from rogue.schemas import BREACH_VERDICTS

    rendered = render(primitive, config)
    result = judge.grade_sync(rendered, response, primitive)
    return getattr(result, "verdict", None) in BREACH_VERDICTS


def live_responder(panel=None, *, temperature: float = 0.7):
    """Wire ``respond`` to the live scan path (TargetPanel + adapters) — the §6 live seam.

    Returns ``(respond, stats)``. ``respond(primitive, config)`` renders the primitive
    against the config and dispatches ONE real target trial, returning the response text
    ("" on a modality-skip or empty result). ``stats`` is a mutable dict accumulating
    ``calls`` and the cumulative target ``cost_usd`` so a caller can report the spend.

    LIVE: each call costs a real model invocation; needs the target provider's API key.
    """
    import asyncio

    from rogue.reproduce.instantiator import render
    from rogue.reproduce.target_panel import TargetPanel

    panel = panel or TargetPanel.from_env()
    stats = {"calls": 0, "empty": 0, "target_cost_usd": 0.0}
    # One persistent loop across all trials: asyncio.run() per call closes the loop
    # between calls and the async HTTP client's deferred cleanup then errors noisily.
    loop = asyncio.new_event_loop()

    def respond(primitive: AttackPrimitive, config) -> str:
        rendered = render(primitive, config)
        responses = loop.run_until_complete(
            panel.run_attack(rendered, config, temperature=temperature, n_trials=1)
        )
        stats["calls"] += 1
        if not responses:
            stats["empty"] += 1
            return ""
        r = responses[0]
        stats["target_cost_usd"] += float(getattr(r, "cost_usd", 0.0) or 0.0)
        return r.content

    return respond, stats


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
                breached = bool(grade(rule, judge, prim, response, config))
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
