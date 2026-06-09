"""RedlineGuard — the inbound-gate-RULE emitter for the Slack cycle (build-06 §7).

When a message arrives for a registered Slack agent, RedlineGuard classifies it to an
:class:`~rogue.schemas.attack_primitive.AttackFamily`, maps that to its breach class, and
emits a **deployable inbound gate RULE** whose confidence is the *area-02 calibrated judge's
measured precision* for that class — NOT a bespoke moderation classifier (the foil the §5
spec rejects). The confidence is a number ROGUE already earned and can attest, not a fresh
risk model.

ADR-0010 (load-bearing): RedlineGuard **generates + verifies** the rule and its precision;
the **CLIENT deploys + enforces** it in their own runtime. :func:`score_inbound` is a PURE
function — it does NOT call Slack, does NOT intercept/modify/block the message, and has NO
side effects. It returns a :class:`MitigationCandidate` (``GUARDRAIL_RULE``) the client may
deploy; ROGUE never sits in the request path and never auto-blocks.

ADR-0011 (honesty): the confidence is the judge's calibrated precision when area 02 shipped
a report for the message's breach type, else ``None`` with an honest ``"uncalibrated"`` status
— a precision number is NEVER fabricated for an un-calibrated class.

Contrast with §6 ``tripwire``: Tripwire predicts breakage from *this agent's empirical prior
breach-rate* (its own sandbox scans). §7 RedlineGuard is target-agnostic — its confidence is
*the judge's calibrated precision* for the class, and its output is a deploy-by-client rule.

v1 scope: rule-emission only. The inbound message arrives as a plain function argument; there
is NO Slack Events ingestion / inbound endpoint / signature verification here (deferred to §8).
The v1 family classifier is the shared §6 keyword heuristic (:func:`classify_inbound_family`);
an embedding ``retrieval/`` retriever is the injectable upgrade (the ``matcher`` parameter).

Side-effect-free import (no DB/engine/network at import time).

Spec: ``docs/v2/build/06_*`` §7; reuses §6 ``tripwire``, ``governance.reaim``,
``governance.rule_judge``, area-05 ``schemas.remediation``; ADR-0010 / ADR-0011.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from rogue.governance.reaim import FAMILY_BREACH_TYPE
from rogue.governance.rule_judge import calibration_for_breach_type
from rogue.schemas.attack_primitive import AttackFamily
from rogue.schemas.remediation import MitigationCandidate, MitigationType

from . import change_witness
from .tripwire import classify_inbound_family

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService

__all__ = [
    "RedlineScore",
    "score_inbound",
]

# Stamped on every emitted rule's ``generated_by`` so the artifact's provenance is
# reproducible: this is a deterministic composition (classifier + the area-02 report),
# not a model call.
_GENERATED_BY = "redline_guard/v1 (deterministic; confidence = area-02 calibrated judge precision)"


@dataclass(frozen=True)
class RedlineScore:
    """The render-ready result for one inbound message (ADR-0010: a deployable rule, never a block).

    Carries the classified family + its breach class, an honest risk label, the calibrated
    judge precision the rule's confidence rests on (``None`` when the class was not shipped),
    the calibration status that distinguishes those two cases, the deployable
    ``GUARDRAIL_RULE`` artifact (or ``None`` when nothing classified), and the human-readable
    recommendation — always framed as advice the client deploys, never an enforced block.

    Attributes:
        matched_family: the classified :class:`AttackFamily` value, or ``None``.
        breach_type: the family's breach class (``FAMILY_BREACH_TYPE``), or ``None``.
        risk: a short honest label — ``"calibrated-flag"`` (precision known),
            ``"uncalibrated-advisory"`` (class not shipped), ``"no-match"`` (nothing matched).
        confidence: the area-02 calibrated judge precision (float) when calibrated, else
            ``None`` — NEVER fabricated (ADR-0011).
        calibration_status: ``"calibrated"`` / ``"uncalibrated"`` from the area-02 accessor,
            or ``"n/a"`` when nothing classified.
        over_block: ``None`` in v1 — the measured over-block rate needs area-05's
            legit-corpus run (same judge, never a new model); see :func:`score_inbound`.
        recommendation: the honest, render-ready recommendation line.
        rule: the deployable ``GUARDRAIL_RULE`` :class:`MitigationCandidate`, or ``None``.
    """

    matched_family: str | None
    breach_type: str | None
    risk: str
    confidence: float | None
    calibration_status: str
    over_block: dict | None
    recommendation: str
    rule: MitigationCandidate | None


def _agent_family_breach_rate(
    org_id: str,
    agent_name: str,
    family_value: str,
    *,
    attestation_service: "AttestationService",
) -> float | None:
    """The agent's empirical breach rate for ``family_value`` from its latest signed scan, or ``None``.

    OPTIONAL supplementary context only (folded into the recommendation text). The rule's
    *confidence* is the judge's calibrated precision, NOT this number — this is the §6
    empirical prior, surfaced here just to enrich the advice when the caller supplies an
    attestation service. Reuses §5 ``latest_agent_scan_entry``; no new read path.
    """
    entry = change_witness.latest_agent_scan_entry(
        org_id, agent_name, attestation_service=attestation_service
    )
    if entry is None:
        return None
    report = change_witness._payload(entry).get("rule_breach_report") or {}
    verdicts = [
        v
        for v in (report.get("rule_verdicts") or [])
        if v.get("attack_family") == family_value
    ]
    if not verdicts:
        return None
    n_trials = sum(int(v.get("n_trials") or 0) for v in verdicts)
    n_breaches = sum(int(v.get("n_breaches") or 0) for v in verdicts)
    return (n_breaches / n_trials) if n_trials > 0 else None


def score_inbound(
    org_id: str,
    agent_name: str,
    message: str,
    *,
    matcher: Callable[[str], AttackFamily | None] | None = None,
    attestation_service: "AttestationService | None" = None,
) -> RedlineScore:
    """Emit a deployable inbound gate RULE for ``message`` (ADR-0010: rule, never a block).

    PURE (ADR-0010): no Slack/HTTP call, no enforcement, no message mutation. Steps:

    1. Classify the message to an :class:`AttackFamily` via the shared §6
       :func:`classify_inbound_family` (``matcher`` injects the retriever later). No family
       → ``risk="no-match"``, no rule.
    2. Map the family to its breach class via ``governance.reaim.FAMILY_BREACH_TYPE``.
    3. Read area-02's calibration provenance for that breach type
       (``rule_judge.calibration_for_breach_type``): ``(calibration_status, judge_precision)``.
       Calibrated (area 02 shipped a ``gate=ship`` report) → a precision float; otherwise
       ``("uncalibrated", None)`` — NEVER fabricated (ADR-0011).
    4. Build the deployable :class:`MitigationCandidate` (``GUARDRAIL_RULE``): a clear rule the
       *client* deploys in their own guardrail — flag/quarantine inbound of this class for human
       review, carrying the calibrated precision (or an honest "uncalibrated" note when unknown).
    5. ``confidence = judge_precision`` (``None`` when uncalibrated); ``risk`` is an honest
       label derived from calibration. When ``attestation_service`` is supplied, the agent's
       empirical breach rate for the family (§6 prior, via :func:`latest_agent_scan_entry`) is
       folded into the recommendation as supplementary context — it never becomes the confidence.

    ``over_block`` is ``None`` for v1: the measured over-block rate (does the gate block
    *legitimate* traffic the agent should answer?) needs area-05's independent legit-corpus run,
    scored by the SAME area-02 judge over-block FP mode — never a new model (ADR-0010/0011). That
    is the calibrated upgrade; v1 refuses to fabricate the number.

    Args:
        org_id: the tenant whose agent this is (for the optional empirical-prior lookup).
        agent_name: the registered Slack agent (for the optional empirical-prior lookup).
        message: the inbound message text to classify + gate.
        matcher: optional injected family classifier (the embedding retriever wires here).
        attestation_service: optional area-03 service; when given, the agent's empirical
            breach rate for the family enriches the recommendation (supplementary only).

    Returns:
        A :class:`RedlineScore` carrying the gate rule + its calibrated-precision confidence.
    """
    family = classify_inbound_family(message, matcher=matcher)

    if family is None:
        return RedlineScore(
            matched_family=None,
            breach_type=None,
            risk="no-match",
            confidence=None,
            calibration_status="n/a",
            over_block=None,
            recommendation="no known attack family matched this message",
            rule=None,
        )

    family_value = family.value
    breach_type = FAMILY_BREACH_TYPE.get(family)
    breach_value = breach_type.value if breach_type is not None else None

    # Confidence MUST trace to the area-02 judge (ADR-0011) — reuse the canonical
    # breach-type calibration accessor; never re-read the report JSON by hand, never
    # fabricate a number for an un-calibrated class.
    if breach_type is not None:
        calibration_status, judge_precision = calibration_for_breach_type(breach_type)
    else:
        calibration_status, judge_precision = "uncalibrated", None

    calibrated = calibration_status == "calibrated" and judge_precision is not None
    confidence = judge_precision if calibrated else None
    risk = "calibrated-flag" if calibrated else "uncalibrated-advisory"

    # Optional supplementary context: the agent's empirical breach rate for this family
    # (§6 prior). It NEVER becomes the confidence — that is the judge's calibrated precision.
    prior_rate = None
    if attestation_service is not None:
        prior_rate = _agent_family_breach_rate(
            org_id, agent_name, family_value, attestation_service=attestation_service
        )

    # The deployable gate-rule artifact (ADR-0010: the client deploys this, ROGUE never runs it).
    if calibrated:
        artifact = (
            f"Flag/quarantine for human review any inbound classified as {breach_value} "
            f"(attack family {family_value}); ROGUE's calibrated judge flags this class at "
            f"{confidence:.0%} measured precision. Deploy this gate in your own guardrail "
            f"runtime — do NOT auto-block; route flagged inbound to a human."
        )
        recommendation = (
            f"inbound matches {breach_value}; our judge flags this class at {confidence:.0%} "
            f"measured precision — deploy the gate rule below in your runtime (ROGUE does not block)"
        )
    else:
        artifact = (
            f"Flag/quarantine for human review any inbound classified as {breach_value} "
            f"(attack family {family_value}); ROGUE's judge is NOT yet calibrated for this class, "
            f"so this rule carries no measured precision. Deploy in your own guardrail runtime "
            f"as an advisory flag — do NOT auto-block; route flagged inbound to a human."
        )
        recommendation = (
            f"inbound matches {breach_value}, but our judge is not yet calibrated for this class "
            f"— rule emitted without a precision number"
        )

    if prior_rate is not None:
        recommendation += (
            f" (context: {agent_name} broke to this family in {prior_rate:.0%} of prior "
            f"sandbox trials — supplementary, not the rule's confidence)"
        )

    rule = MitigationCandidate(
        candidate_id=f"redline::{org_id}::{agent_name}::{family_value}",
        breach_ref=f"{breach_value or family_value} (inbound-gate, no scanned rule)",
        mitigation_type=MitigationType.GUARDRAIL_RULE,
        artifact=artifact,
        generated_by=_GENERATED_BY,
        rationale=recommendation,
    )

    return RedlineScore(
        matched_family=family_value,
        breach_type=breach_value,
        risk=risk,
        confidence=confidence,
        calibration_status=calibration_status,
        over_block=None,
        recommendation=recommendation,
        rule=rule,
    )
