"""Sign one gated human-review decision into the per-org attestation chain (Surface 2 §5).

The Surface-2 analogue of ``attestation/remediation.append_mitigation`` — an ADAPTER
into the EXISTING area-03 attestation layer, NOT a new attestation impl (build 07 §5,
ADR-0011 / build-03 §B). It turns a captured :class:`GatedDecision` (scored against its
:class:`GatedCase`'s independent ``designed_label``) into a structured ``decision``
attestation record and hands it to ``AttestationService.append`` on the SAME per-org
hash chain. It does NOT build a second chain and duplicates no hashing/chaining/sequence
logic — the record is just another payload on the existing chain.

The record carries the five properties the spec names (build 07 §5, unified §2.5):

1. **tamper-evident** — it rides area-03's hash chain (``service.verify(org)`` re-walks
   it; mutate a stored entry and verification fails).
2. **complete** — :func:`append_gate_run` appends ONE ``decision`` entry per decision,
   every gated decision and not just the headline ones (unified §2.5 item 2).
3. **decision-rationale captured** — a structured record (not a flat timestamp line):
   what was decided, what the disposition-judge scored (the 2×2 cell + whether it is the
   headline breach=false-approve), the case's ``designed_label`` (the independent key)
   + ``designed_rationale``, the reviewer, and **any dissent** (other reviewers' differing
   decisions on the same case, if supplied).
4. **replayable** — ``reproducibility_ref`` defaults to a deterministic handle so the
   verdict reconstructs from the stored ``GatedCase`` + decision + key, idempotent like
   the scan/mitigation paths.
5. **framing** — every record carries the non-negotiable ``framing_line`` (threat-informed
   assurance, not a safety guarantee), and the measure-don't-claim discipline: the record
   states it was *measured against the constructed corpus as of date D*, NEVER that the
   gate *improves* accuracy.

Redaction is critical: an append-only entry can never be un-written, so every free-text
field is scrubbed via the SAME ``report_service._redact`` the scan/mitigation paths use,
before it enters the immutable record.

Spec: ``docs/v2/build/07_surface2_humangate.md`` §5; reuses ``docs/v2/build/03_attestation.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rogue.attestation.emit import canonical_as_of, framing_line
from rogue.oversight.case_corpus import GatedCase, GatedDecision
from rogue.oversight.disposition_judge import classify_decision, is_breach
from rogue.platform.report_service import _redact

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService
    from rogue.platform.models import AttestationEntry

__all__ = ["decision_record", "append_gate_decision", "append_gate_run"]


def _ground_truth_ref(case: GatedCase) -> str:
    """The independent-label pointer for a case (ADR-0011 ``GroundTruthRef``).

    The ``designed_label`` is the answer key the decision is scored against; this is a
    stable handle resolving back to it in the corpus, NOT the label value inlined.
    """
    return f"oversight-corpus:{case.case_id}"


def _redact_dissent(dissent: list[dict] | None) -> list[dict] | None:
    """Redact free-text in each dissent record before it enters the immutable entry.

    A dissent record names another reviewer's differing disposition on the same case;
    its ``reviewer`` / ``decision`` are structured, but any ``deliberation_notes`` (or
    other free text) is scrubbed via the same ``_redact`` the rest of the payload uses.
    """
    if not dissent:
        return None
    out: list[dict] = []
    for d in dissent:
        scrubbed = dict(d)
        for k, v in scrubbed.items():
            if isinstance(v, str):
                scrubbed[k] = _redact(v)
        out.append(scrubbed)
    return out


def decision_record(
    decision: GatedDecision,
    case: GatedCase,
    *,
    corpus_as_of: datetime,
    dissent: list[dict] | None = None,
) -> dict:
    """Build the ``decision`` attestation record for one scored :class:`GatedDecision`.

    Mirrors ``emit._finding_record`` / ``remediation.mitigation_record``: a ``kind``
    disposition, the verified comparison (the 2×2 cell + headline breach flag), the
    independent key + its rationale, the reviewer, any dissent, a replay pointer, and
    the framing line — never a free-text blob (all free text is redacted).

    Deterministic + self-contained: given the same ``decision`` + ``case`` +
    ``corpus_as_of`` (+ ``dissent``) it returns a byte-identical dict, so it round-trips
    through ``chain.canonical_payload`` stably and ``replay`` recomputes the exact
    ``entry_hash``.
    """
    cell = classify_decision(decision, case)
    breach = is_breach(cell)

    return {
        "kind": "gated_decision",
        # --- what was decided (the reviewer's disposition) ---------------------
        "case_id": case.case_id,
        "case_class": case.case_class,
        "reviewer": _redact(decision.reviewer),
        "decision": decision.decision,
        # --- what the disposition-judge scored (the 2×2 + headline breach mode) -
        # Direct comparison of decision vs the independent key — there is no LLM
        # grading the human's reasoning (disposition_judge is a thin comparator).
        "disposition_cell": cell.value,
        # The headline breach mode (false-approve): APPROVE against a DENY key.
        "breach": breach,
        "verdict": "breach" if breach else "clean",
        # --- the key the decision was scored against (the GroundTruthRef) -------
        "designed_label": case.designed_label,
        # Why the key is what it is — free text, redacted.
        "designed_rationale": _redact(case.designed_rationale),
        "label_provenance": case.label_provenance,
        # --- any dissent (other reviewers' differing decisions on this case) ----
        # Captured so the signed record reflects disagreement, not just the headline
        # disposition (spec §5). None when no dissent supplied; free text redacted.
        "dissent": _redact_dissent(dissent),
        # --- replay pointer (a handle, not a blob): resolves back to the stored ---
        # GatedCase + decision + key so the verdict reconstructs.
        "snapshot_ref": f"{case.case_id}::{decision.reviewer}",
        "ground_truth_ref": _ground_truth_ref(case),
        # --- framing (non-negotiable) + measure-don't-claim discipline ----------
        "corpus_as_of": canonical_as_of(corpus_as_of),
        "framing": framing_line(corpus_as_of),
        # We measured whether oversight added accuracy or only accountability — we do
        # NOT claim the gate improves accuracy (spec §3 / §5 framing discipline).
        "measurement_note": (
            "measured against the constructed designed-label corpus as of "
            f"{canonical_as_of(corpus_as_of)}; this records what the reviewer decided "
            "vs the independent key — it does not claim the gate improves accuracy"
        ),
    }


def append_gate_decision(
    service: "AttestationService",
    org_id: str,
    decision: GatedDecision,
    case: GatedCase,
    *,
    corpus_as_of: datetime,
    dissent: list[dict] | None = None,
    reproducibility_ref: str | None = None,
) -> "AttestationEntry":
    """Append one gated decision to ``org_id``'s chain via the EXISTING engine.

    Thin: it builds the record with :func:`decision_record` and hands it to
    ``service.append`` with ``entry_type="decision"`` — the SAME per-org hash chain,
    the same lazy-genesis / monotonic-seq / idempotency invariants. No chain logic is
    duplicated here.

    ``corpus_as_of`` is the chain's mandatory "as of date D" (a datetime, passed to
    ``append``); the record body stores its canonical iso form so the payload bytes are
    stable. ``reproducibility_ref`` defaults to ``f"gateddecision:{case_id}:{reviewer}"``
    so a worker retry is idempotent (the verdict reconstructs from the stored case +
    decision + key). The independent ``designed_label`` travels as ``append``'s
    ``ground_truth_ref`` (ADR-0011).
    """
    if decision.case_id != case.case_id:
        raise ValueError(
            f"decision case_id {decision.case_id!r} does not match case {case.case_id!r}"
        )
    record = decision_record(
        decision, case, corpus_as_of=corpus_as_of, dissent=dissent
    )
    ref = reproducibility_ref or f"gateddecision:{case.case_id}:{decision.reviewer}"
    return service.append(
        org_id,
        "decision",
        record,
        reproducibility_ref=ref,
        ground_truth_ref=_ground_truth_ref(case),
        corpus_as_of=corpus_as_of,
    )


def append_gate_run(
    service: "AttestationService",
    org_id: str,
    decisions: list[GatedDecision],
    cases: list[GatedCase],
    *,
    corpus_as_of: datetime,
) -> list["AttestationEntry"]:
    """Append ONE ``decision`` entry per decision — the COMPLETE run, not just headlines.

    Completeness is the spec's property 2 (unified §2.5 item 2): every gated decision is
    signed, not only the breaches. Cases are indexed by ``case_id`` so each decision is
    scored against its own case; a decision for an unknown case is a wiring bug and raised
    loudly rather than silently dropped.

    Dissent is derived within the run: for each decision, the OTHER reviewers' differing
    decisions on the SAME case become that entry's ``dissent`` list, so each signed record
    reflects the disagreement that was present.
    """
    by_id: dict[str, GatedCase] = {c.case_id: c for c in cases}
    # Group decisions by case so dissent (differing decisions on the same case) is local.
    by_case: dict[str, list[GatedDecision]] = {}
    for d in decisions:
        by_case.setdefault(d.case_id, []).append(d)

    entries: list[AttestationEntry] = []
    for d in decisions:
        case = by_id.get(d.case_id)
        if case is None:
            raise ValueError(
                f"decision for case_id {d.case_id!r} has no matching case in the run"
            )
        dissent = [
            {"reviewer": o.reviewer, "decision": o.decision, "notes": o.deliberation_notes}
            for o in by_case[d.case_id]
            if o.reviewer != d.reviewer and o.decision != d.decision
        ]
        entries.append(
            append_gate_decision(
                service,
                org_id,
                d,
                case,
                corpus_as_of=corpus_as_of,
                dissent=dissent or None,
            )
        )
    return entries
