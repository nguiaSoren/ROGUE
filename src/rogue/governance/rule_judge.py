"""Per-rule judge instantiation — the [DEP-02] consumer side (build-04 §4).

This module is *wiring*, not rubric authorship. Area 02 (the judge) owns the
generalized content-transfer gate across four breach types and ships the per-type
calibration reports under ``data/calibration/``. This area *consumes* that work:
given a :class:`~rogue.schemas.governance.PolicyRule`, it points area-02's
generalized :class:`~rogue.reproduce.judge.JudgeAgent` at *this rule's*
consummation criterion instead of the generic harm goal, and stamps each verdict
with the rule's calibration provenance.

The seam (the whole of §4)
--------------------------
``JudgeAgent.judge`` already accepts two parameters area 02 generalized for
exactly this:

* ``breach_type`` (constructor) — selects which rubric file encodes the
  consummation gate (``judge_v3.md`` for harm, ``infodisc_v2.md`` for disclosure,
  ``unauthorized_action_v3.md`` for action, ``fabricated_sensitive_value_v2.md``).
* ``context: BreachContext`` (per-call) — injects the *per-rule* criterion into
  the judge's user turn: ``rule_text`` (= the rule's ``consummation_definition``,
  the engagement-vs-consummation boundary for THIS rule) and ``protected_target``
  (= the rule's ``elicitation_target``, what must not be disclosed/executed).
  These render the "Governance rule under test" + "Protected target" blocks in
  ``JudgeAgent._build_user_message`` (see ``judge.py`` lines ~481-495).

So instantiating a per-rule judge is: construct one ``JudgeAgent`` for the rule's
breach type, build one frozen ``BreachContext`` from the rule, and pass that
context on every ``judge`` call. No rubric is edited, no new dependency is added.

CAPABILITY_TRANSFER (the harm case) is deliberately special-cased to pass
``context=None`` so the harm user-message bytes stay byte-identical to the pre-v2
judge (the cache/batch/golden-string guarantee, build-02 §1.2) — proving the
wiring against the *already-calibrated* harm judge with zero new dependency.

Honest degradation (ADR-0011)
-----------------------------
:func:`calibration_for_rule` reads ``data/calibration/<breach_type>_report.json``
and returns ``("calibrated", precision)`` IFF a report exists and its ``gate`` is
``"ship"``; otherwise ``("uncalibrated", None)``. A CI / precision is NEVER
fabricated for an un-calibrated breach type — a number scored against an
un-calibrated judge is worse than no number.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.judge import JudgeAgent, JudgeResult
from rogue.reproduce.rubrics.context import BreachContext
from rogue.schemas import AttackPrimitive
from rogue.schemas.governance import BreachType, CalibrationStatus, PolicyRule

__all__ = [
    "RuleJudge",
    "instantiate_rule_judge",
    "calibration_for_rule",
    "stamp_calibration",
    "CALIBRATION_DIR",
]

_log = logging.getLogger("rogue.governance.rule_judge")

# Where area 02 emits its per-breach-type reports (mirrors
# ``judge_calibration.CalibrationReport``; one ``<breach_type>_report.json`` per
# type). Repo root is three parents up from this file (src/rogue/governance/).
CALIBRATION_DIR = Path(__file__).resolve().parents[3] / "data" / "calibration"

# A report's ``gate`` must be exactly this to count as calibrated (mirrors the
# §10.2 ship/refine gate in ``judge_calibration``). Anything else (refine,
# missing, error) degrades honestly to ``uncalibrated``.
_SHIP_GATE = "ship"


@dataclass(frozen=True)
class RuleJudge:
    """A :class:`JudgeAgent` aimed at one rule's consummation criterion.

    Returned by :func:`instantiate_rule_judge`. Stateless across :meth:`grade`
    calls (it just forwards to the wrapped agent, which is itself stateless), so a
    single instance is safe to share across an ``asyncio.gather`` fan-out over a
    rule's attack pack.

    Attributes:
        rule_id: the rule this judge scores against.
        breach_type: the rule's consummation shape (selects the rubric).
        agent: the wrapped area-02 :class:`JudgeAgent` (rubric chosen by
            ``breach_type``).
        context: the per-rule :class:`BreachContext` injected into every grade
            call — ``None`` for the harm case so the user-message bytes are
            byte-identical to the pre-v2 judge.
        calibration_status: ``"calibrated"`` iff area 02 shipped a report for this
            breach type, else ``"uncalibrated"`` (ADR-0011 honest default).
        judge_precision: the per-type precision point estimate from area 02's
            report, or ``None`` when uncalibrated. NEVER fabricated.
    """

    rule_id: str
    breach_type: BreachType
    agent: JudgeAgent
    context: BreachContext | None
    calibration_status: CalibrationStatus
    judge_precision: float | None

    async def grade(
        self,
        rendered: RenderedAttack,
        model_response: str,
        primitive: AttackPrimitive,
    ) -> JudgeResult:
        """Grade one (attack, response) pair against THIS rule's criterion.

        Reuses the real ``JudgeAgent.judge`` path verbatim — the only difference
        from a generic harm grade is that the rule's ``BreachContext`` is passed,
        so the rubric scores against the rule's consummation definition.
        """
        return await self.agent.judge(
            rendered=rendered,
            model_response=model_response,
            primitive=primitive,
            context=self.context,
        )

    def grade_sync(
        self,
        rendered: RenderedAttack,
        model_response: str,
        primitive: AttackPrimitive,
    ) -> JudgeResult:
        """Blocking wrapper around :meth:`grade` for scripts / notebooks."""
        return self.agent.judge_sync(
            rendered=rendered,
            model_response=model_response,
            primitive=primitive,
            context=self.context,
        )


def instantiate_rule_judge(
    rule: PolicyRule,
    *,
    model: str | None = None,
) -> RuleJudge:
    """Build a :class:`RuleJudge` that grades against ``rule``'s consummation criterion.

    The wiring (build-04 §4): construct one area-02 ``JudgeAgent`` for the rule's
    ``breach_type`` (which selects the rubric), and a frozen ``BreachContext`` that
    carries the rule's criterion into the judge's user turn —
    ``rule_text = rule.consummation_definition`` and
    ``protected_target = rule.elicitation_target``.

    For ``CAPABILITY_TRANSFER`` the context is left ``None`` so the harm path is
    byte-identical to the existing calibrated harm judge (zero new dependency).

    The calibration provenance is read once at instantiation from area 02's
    per-type report and carried on the returned judge so the §6 report builder can
    stamp each ``RuleVerdict`` honestly.

    Args:
        rule: the typed policy rule to aim the judge at.
        model: optional provider-prefixed judge model id (forwarded to
            ``JudgeAgent``); defaults to the env / ``JudgeAgent`` default.

    Returns:
        A :class:`RuleJudge` ready to ``grade`` transcripts for this rule.
    """
    breach_type = rule.breach_type

    # Harm case: no per-rule context → byte-identical to the pre-v2 harm judge.
    # Non-harm cases: inject the rule's criterion via BreachContext (the §4 seam).
    if breach_type is BreachType.CAPABILITY_TRANSFER:
        context: BreachContext | None = None
    else:
        context = BreachContext(
            rule_text=rule.consummation_definition,
            protected_target=rule.elicitation_target,
        )

    agent = JudgeAgent(model=model, breach_type=breach_type.value)

    calibration_status, judge_precision = calibration_for_rule(rule)

    if calibration_status == "uncalibrated":
        _log.warning(
            "rule %s (breach_type=%s): no shipped calibration report — grading "
            "with the area-02 judge but marking the verdict UNCALIBRATED (no CI).",
            rule.rule_id,
            breach_type.value,
        )

    return RuleJudge(
        rule_id=rule.rule_id,
        breach_type=breach_type,
        agent=agent,
        context=context,
        calibration_status=calibration_status,
        judge_precision=judge_precision,
    )


def _report_path(breach_type: BreachType) -> Path:
    """Path to area 02's report for ``breach_type`` (may not exist)."""
    return CALIBRATION_DIR / f"{breach_type.value}_report.json"


def calibration_for_rule(
    rule: PolicyRule,
) -> tuple[CalibrationStatus, float | None]:
    """Read area 02's calibration provenance for a rule's breach type.

    Returns ``("calibrated", precision)`` IFF a ``<breach_type>_report.json``
    exists AND its ``gate`` is ``"ship"`` AND it carries a usable precision point
    estimate; otherwise ``("uncalibrated", None)``.

    NEVER invents a CI or a precision (ADR-0011): a missing report, a non-``ship``
    gate, malformed JSON, or an absent precision field all degrade to
    ``uncalibrated`` with ``None``.
    """
    return _read_calibration(rule.breach_type)


def _read_calibration(
    breach_type: BreachType,
) -> tuple[CalibrationStatus, float | None]:
    path = _report_path(breach_type)
    if not path.exists():
        return "uncalibrated", None

    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("calibration report %s unreadable (%s) — uncalibrated.", path, exc)
        return "uncalibrated", None

    if not isinstance(report, dict) or report.get("gate") != _SHIP_GATE:
        return "uncalibrated", None

    precision = _precision_point(report)
    if precision is None:
        # Shipped but no usable precision number — do not fabricate one.
        _log.warning(
            "calibration report %s is gate=ship but carries no precision point "
            "estimate — uncalibrated (refusing to fabricate a number).",
            path,
        )
        return "uncalibrated", None

    return "calibrated", precision


def _precision_point(report: dict) -> float | None:
    """Extract the precision point estimate from a report dict, or ``None``.

    Area 02 emits ``precision_ci`` as ``[point, low, high]`` (mirroring
    ``judge_calibration``). The point estimate is element 0. Falls back to a bare
    ``precision`` scalar if present. Returns ``None`` if neither yields a number
    in ``[0, 1]`` — never coerces a fabricated value.
    """
    ci = report.get("precision_ci")
    if isinstance(ci, (list, tuple)) and ci:
        point = ci[0]
        if isinstance(point, (int, float)) and 0.0 <= point <= 1.0:
            return float(point)

    scalar = report.get("precision")
    if isinstance(scalar, (int, float)) and 0.0 <= scalar <= 1.0:
        return float(scalar)

    return None


def stamp_calibration(verdict, rule: PolicyRule):
    """Stamp a ``RuleVerdict``'s calibration provenance from area 02 (for §6).

    The helper the §6 report builder calls: reads the rule's breach-type report
    and sets ``calibration_status`` + ``judge_precision`` on ``verdict``, leaving
    the trial-outcome CI fields (``ci_low``/``ci_high``) untouched — the two
    provenances stay distinct (ADR-0011). Returns a copy with the fields set
    (``RuleVerdict`` is a Pydantic model; we never mutate in place).

    When uncalibrated, ``judge_precision`` is forced to ``None`` so an
    un-calibrated verdict can never carry a precision number.
    """
    status, precision = calibration_for_rule(rule)
    return verdict.model_copy(
        update={
            "calibration_status": status,
            "judge_precision": precision if status == "calibrated" else None,
        }
    )
