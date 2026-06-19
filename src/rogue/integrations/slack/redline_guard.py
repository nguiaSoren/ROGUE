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

from rogue.diff.bootstrap import bootstrap_ci
from rogue.governance.reaim import FAMILY_BREACH_TYPE
from rogue.governance.rule_judge import calibration_for_breach_type
from rogue.remediation import legit_corpus
from rogue.schemas.attack_primitive import AttackFamily
from rogue.schemas.remediation import MitigationCandidate, MitigationType, OverBlockCheck

from . import change_witness
from .tripwire import classify_inbound_family

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService

__all__ = [
    "RedlineScore",
    "measure_over_block",
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
        over_block: the MEASURED over-block — the gate rule's false-positive rate on an
            independent legitimate-traffic set (area-05 ``legit_corpus``): how often the
            classifier would wrongly flag a should-answer message as this family. An
            :class:`OverBlockCheck` when a family matched and the legit corpus is non-empty,
            else ``None`` (no family → nothing to gate; empty corpus → no honest measurement).
            See :func:`measure_over_block`.
        recommendation: the honest, render-ready recommendation line.
        rule: the deployable ``GUARDRAIL_RULE`` :class:`MitigationCandidate`, or ``None``.
    """

    matched_family: str | None
    breach_type: str | None
    risk: str
    confidence: float | None
    calibration_status: str
    over_block: OverBlockCheck | None
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


def measure_over_block(
    family: AttackFamily,
    *,
    classifier: Callable[[str], AttackFamily | None] | None = None,
    legit_sets: list[str] | None = None,
    legitimate_set_ref: str | None = None,
) -> OverBlockCheck | None:
    """MEASURE this gate rule's over-block — its false-positive rate on legitimate traffic.

    A RedlineGuard rule says "flag inbound classified as ``family``." Its over-block is how
    often that rule would WRONGLY flag *legitimate* traffic the agent SHOULD answer = the
    classifier's false-positive rate on an INDEPENDENT legitimate-traffic set (area-05
    ``legit_corpus``, ADR-0011 — authored should-answer messages, never derived from any
    agent's behavior). Purely OFFLINE: re-run the same classifier over the legit set and
    count how many it (wrongly) classifies as ``family``.

    NOTE (honesty): this is the filter RULE's classifier false-flag rate on legit traffic —
    distinct from area-05's agent-patch *judge* over-block (a judge FP on a patched config).
    Hence ``judge_rubric_handle=None``: no judge ran here, just the inbound classifier.

    Args:
        family: the attack family the gate rule flags.
        classifier: the family classifier to measure (defaults to the shared §6
            :func:`classify_inbound_family`); pass the SAME ``matcher`` the rule was scored
            with so the over-block reflects the rule being emitted.
        legit_sets: an explicit legitimate-traffic message list (test injection). When
            ``None``, the union of every authored ``legit_corpus`` set is loaded.
        legitimate_set_ref: an explicit provenance ref; defaults to one derived from the
            corpus rule ids (or ``"legit_traffic:injected"`` when ``legit_sets`` is given).

    Returns:
        An :class:`OverBlockCheck` with ``n_legit``, ``n_false_block``, ``over_block_rate``,
        and a bootstrap CI over the per-message false-block outcomes — or ``None`` when the
        legitimate-traffic set is empty (ADR-0011: no corpus, no fabricated rate).
    """
    if legit_sets is not None:
        messages = list(legit_sets)
        ref = legitimate_set_ref or "legit_traffic:injected"
    else:
        rule_ids = legit_corpus.available_rule_ids()
        messages = [m for rid in rule_ids for m in legit_corpus.load_legit_set(rid)]
        ref = legitimate_set_ref or ("legit_traffic:" + ",".join(rule_ids))

    if not messages:
        return None

    clf = classifier or classify_inbound_family
    # A false-block: a LEGITIMATE message the rule would (wrongly) flag as this attack family.
    outcomes = [1 if clf(msg) == family else 0 for msg in messages]
    n_legit = len(messages)
    n_false_block = sum(outcomes)
    ci_low, ci_high = bootstrap_ci(outcomes)

    return OverBlockCheck(
        legitimate_set_ref=ref,
        n_legit=n_legit,
        n_false_block=n_false_block,
        over_block_rate=n_false_block / n_legit,
        ci_low=ci_low,
        ci_high=ci_high,
        judge_rubric_handle=None,
    )


def score_inbound(
    org_id: str,
    agent_name: str,
    message: str,
    *,
    matcher: Callable[[str], AttackFamily | None] | None = None,
    attestation_service: "AttestationService | None" = None,
    legit_sets: list[str] | None = None,
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

    ``over_block`` is MEASURED when a family matched: the gate rule's false-positive rate on
    the INDEPENDENT area-05 ``legit_corpus`` legitimate-traffic set — how often the SAME
    classifier (the ``matcher`` the rule was scored with) would wrongly flag a should-answer
    message as this family (:func:`measure_over_block`). ``None`` when nothing classified
    (nothing to gate) or when the legit corpus is empty (ADR-0011: no corpus, no fabricated
    rate). This is the filter rule's classifier FP rate, distinct from area-05's agent-patch
    *judge* over-block.

    Args:
        org_id: the tenant whose agent this is (for the optional empirical-prior lookup).
        agent_name: the registered Slack agent (for the optional empirical-prior lookup).
        message: the inbound message text to classify + gate.
        matcher: optional injected family classifier (the embedding retriever wires here).
            Reused for the over-block measurement so it reflects the same rule being scored.
        attestation_service: optional area-03 service; when given, the agent's empirical
            breach rate for the family enriches the recommendation (supplementary only).
        legit_sets: optional explicit legitimate-traffic set for the over-block measurement
            (test injection). ``None`` → measure against the real ``legit_corpus``.

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

    # Measure the emitted rule's over-block with the SAME classifier the score used, so the
    # FP rate reflects the rule being deployed (None when the legit corpus is empty).
    over_block = measure_over_block(family, classifier=matcher, legit_sets=legit_sets)

    return RedlineScore(
        matched_family=family_value,
        breach_type=breach_value,
        risk=risk,
        confidence=confidence,
        calibration_status=calibration_status,
        over_block=over_block,
        recommendation=recommendation,
        rule=rule,
    )
