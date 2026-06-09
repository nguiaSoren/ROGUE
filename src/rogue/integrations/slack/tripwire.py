"""Tripwire — the inbound-message breach PREDICTOR for the Slack cycle (build-06 §6).

When a message arrives for a registered Slack agent, Tripwire classifies it to an
:class:`~rogue.schemas.attack_primitive.AttackFamily` and — from THIS agent's own most
recent signed sandbox scan (§5 ``ChangeWitness``) — predicts whether the agent breaks to
that family, then composes a security-channel-ready ADVISORY *before* the agent responds.

ADR-0010 (load-bearing): Tripwire is **prediction/advice ONLY**. ROGUE never sits in the
request path. :func:`predict_breach` is a PURE function — it does NOT call Slack, does NOT
intercept/modify/block/enforce the message, and has NO side effects. It reads the agent's
prior sandbox results and returns a recommendation; acting on it is the customer's choice.

v1 scope (this module): prediction-only. The inbound message arrives as a plain function
argument (a test / MCP / sandbox replay) — there is NO Slack Events ingestion, NO inbound
endpoint, and NO request-signature verification here; those are deferred to §8. The v1
family classifier is a deterministic keyword heuristic (:func:`_keyword_family_match`); an
embedding ``retrieval/`` retriever is the injectable upgrade (the ``matcher`` parameter).

Side-effect-free import (no DB/engine/network at import time).

Spec: ``docs/v2/build/06_*`` §6; reads §5 ``change_witness``; ADR-0010.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from rogue.schemas.attack_primitive import AttackFamily

from . import change_witness

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService

__all__ = [
    "TripwirePrediction",
    "predict_breach",
    "format_advisory",
]


@dataclass(frozen=True)
class TripwirePrediction:
    """The render-ready ADVISORY for one inbound message (ADR-0010: advice, never a block).

    Carries what the security channel needs to triage the message before the agent acts:
    the matched family (or None), whether a calibrated prior exists for it on this agent,
    the prior sandbox breach rate + CI + trial counts the prediction rests on, the signed
    scan it was read from, the human recommendation, and the ready-to-post ``advisory``
    line (always framed as advice, never as an enforced block).
    """

    inbound_excerpt: str
    matched_family: str | None
    calibrated: bool
    prior_breach_rate: float | None
    ci: tuple[float, float] | None
    n_trials: int
    n_breaches: int
    scan_id: str | None
    recommendation: str
    advisory: str


# --- v1 keyword heuristic --------------------------------------------------
#
# A deterministic, documented signal-phrase → family map. Lowercase substring /
# regex match, first hit wins (most-specific families listed first so e.g. an
# explicit DAN persona isn't swallowed by the generic "ignore instructions"
# override rule). This is the v1 default classifier; the embedding retriever is
# the injectable upgrade via ``predict_breach(..., matcher=...)``.
_FAMILY_SIGNALS: list[tuple[AttackFamily, tuple[str, ...]]] = [
    (
        AttackFamily.DAN_PERSONA,
        (
            r"\bdan\b",
            r"do anything now",
            r"developer mode",
            r"jailbreak",
        ),
    ),
    (
        AttackFamily.SYSTEM_PROMPT_LEAK,
        (
            r"(reveal|print|repeat|show|output|display|leak).{0,40}(system prompt|system message|your (instructions|prompt|rules|guidelines))",
            r"what (is|are) your (system prompt|instructions|rules)",
        ),
    ),
    (
        AttackFamily.DIRECT_INSTRUCTION_OVERRIDE,
        (
            r"(ignore|disregard|forget|override).{0,30}(previous|prior|earlier|above|all|your).{0,20}(instruction|prompt|rule|direction)",
            r"ignore (everything|all) (you were|that was) (told|said)",
        ),
    ),
    (
        AttackFamily.ROLE_HIJACK,
        (
            r"pretend (you are|to be|that you)",
            r"\bact as\b",
            r"\broleplay\b",
            r"you are now (a|an|the)\b",
        ),
    ),
    (
        AttackFamily.REFUSAL_SUPPRESSION,
        (
            r"(never|do not|don'?t|you can'?t) (refuse|say no|decline)",
            r"you (must|have to|will) (answer|comply|respond)",
        ),
    ),
    (
        AttackFamily.TOOL_USE_HIJACK,
        (
            r"(call|invoke|use|run|execute) (the |a |your )?(tool|function|api|command)",
        ),
    ),
    (
        AttackFamily.OBFUSCATION_ENCODING,
        (
            r"base64",
            r"\bhex(adecimal)?\b",
            r"\brot13\b",
            r"leet ?speak",
            r"decode (the|this) (following|encoded)",
        ),
    ),
]

_COMPILED_SIGNALS: list[tuple[AttackFamily, tuple[re.Pattern[str], ...]]] = [
    (family, tuple(re.compile(p) for p in patterns)) for family, patterns in _FAMILY_SIGNALS
]


def _keyword_family_match(message: str) -> AttackFamily | None:
    """v1 deterministic classifier: signal-phrase → :class:`AttackFamily`, or ``None``.

    Lowercase-matches the documented ``_FAMILY_SIGNALS`` table; first family with any
    matching pattern wins (table is ordered most-specific first). Returns ``None`` when
    nothing matches. This is the v1 heuristic — the embedding ``retrieval/`` retriever is
    the injectable upgrade (pass it as ``predict_breach(..., matcher=...)``).
    """
    text = (message or "").lower()
    for family, patterns in _COMPILED_SIGNALS:
        if any(p.search(text) for p in patterns):
            return family
    return None


def _excerpt(message: str, limit: int = 160) -> str:
    """A single-line, length-capped excerpt of the inbound message for the advisory."""
    collapsed = " ".join((message or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _matched_verdicts(payload: dict, family_value: str) -> list[dict]:
    """The agent's prior rule verdicts whose ``attack_family`` matches ``family_value``."""
    report = payload.get("rule_breach_report") or {}
    verdicts = report.get("rule_verdicts") or []
    return [v for v in verdicts if v.get("attack_family") == family_value]


def predict_breach(
    org_id: str,
    agent_name: str,
    inbound_message: str,
    *,
    attestation_service: "AttestationService",
    matcher: Callable[[str], AttackFamily | None] | None = None,
) -> TripwirePrediction:
    """Predict — from this agent's prior signed scan — whether ``inbound_message`` breaks it.

    PURE advice (ADR-0010): no Slack call, no message mutation, no block/enforcement, no
    side effects. Steps:

    1. Classify the message to an :class:`AttackFamily`: ``matcher(inbound_message)`` when a
       matcher is injected (the embedding retriever wires here later), else the v1
       :func:`_keyword_family_match` heuristic.
    2. No family matched → ``matched_family=None, calibrated=False``; nothing to predict.
    3. Else read the agent's latest signed ``scan`` entry
       (:func:`change_witness.latest_agent_scan_entry`) and aggregate the verdict(s) for
       that family: ``n_trials = Σ n_trials``, ``n_breaches = Σ n_breaches``,
       ``prior_breach_rate = n_breaches / n_trials``. The ``ci`` is the matched verdict's
       ``(ci_low, ci_high)`` for a single verdict; for several, the CI of the verdict with
       the most trials (kept simple — the dominant verdict's interval).

       - No prior scan entry, or family never tested → ``calibrated=False,
         prior_breach_rate=None``.
       - Tested → ``calibrated=True`` with the prior rate + CI + counts.
    4. ``advisory`` always frames the result as advice ("⚠️ Tripwire (advisory — not a
       block): …"), never as an enforced block.
    """
    classify = matcher if matcher is not None else _keyword_family_match
    family = classify(inbound_message)
    excerpt = _excerpt(inbound_message)

    if family is None:
        recommendation = "no known attack family matched this message"
        return TripwirePrediction(
            inbound_excerpt=excerpt,
            matched_family=None,
            calibrated=False,
            prior_breach_rate=None,
            ci=None,
            n_trials=0,
            n_breaches=0,
            scan_id=None,
            recommendation=recommendation,
            advisory=f"⚠️ Tripwire (advisory — not a block): {recommendation}.",
        )

    family_value = family.value
    entry = change_witness.latest_agent_scan_entry(
        org_id, agent_name, attestation_service=attestation_service
    )
    payload = change_witness._payload(entry) if entry is not None else {}
    scan_id = (
        str(payload.get("scan_id") or change_witness._attr(entry, "reproducibility_ref") or "")
        or None
        if entry is not None
        else None
    )

    verdicts = _matched_verdicts(payload, family_value) if entry is not None else []

    if not verdicts:
        # Either the agent has no prior scan, or this family was never tested.
        recommendation = (
            f"inbound matches {family_value}, but this agent was not previously tested "
            f"against it — no calibrated prediction"
        )
        return TripwirePrediction(
            inbound_excerpt=excerpt,
            matched_family=family_value,
            calibrated=False,
            prior_breach_rate=None,
            ci=None,
            n_trials=0,
            n_breaches=0,
            scan_id=scan_id,
            recommendation=recommendation,
            advisory=f"⚠️ Tripwire (advisory — not a block): {recommendation}.",
        )

    n_trials = sum(int(v.get("n_trials") or 0) for v in verdicts)
    n_breaches = sum(int(v.get("n_breaches") or 0) for v in verdicts)
    prior_breach_rate = (n_breaches / n_trials) if n_trials > 0 else None

    # CI: single verdict → its own interval; several → the dominant (most-trials) one.
    dominant = max(verdicts, key=lambda v: int(v.get("n_trials") or 0))
    ci_low = dominant.get("ci_low")
    ci_high = dominant.get("ci_high")
    ci = (
        (float(ci_low), float(ci_high))
        if ci_low is not None and ci_high is not None
        else None
    )

    ci_text = f" (CI [{ci[0]}–{ci[1]}])" if ci is not None else ""
    recommendation = (
        f"inbound matches {family_value}; {agent_name} broke to it in "
        f"{n_breaches}/{n_trials} prior sandbox trials{ci_text} — review before the agent acts"
    )
    return TripwirePrediction(
        inbound_excerpt=excerpt,
        matched_family=family_value,
        calibrated=True,
        prior_breach_rate=prior_breach_rate,
        ci=ci,
        n_trials=n_trials,
        n_breaches=n_breaches,
        scan_id=scan_id,
        recommendation=recommendation,
        advisory=f"⚠️ Tripwire (advisory — not a block): {recommendation}.",
    )


def format_advisory(prediction: TripwirePrediction) -> str:
    """The security-channel-ready advisory line for ``prediction`` (always advice, never a block)."""
    return prediction.advisory
