"""The shared instrument-spine data model (ROGUE v2 — spec §3).

ROGUE v2 is "measured assurance": the instrument is the loop
*fire → capture → judge → signed record*. This module defines the **shared
vocabulary** the three surfaces (Surface 1 agent-scan, Surface 2 human-gate,
Surface 3 skill-pool) import instead of forking, so their results compose into
one attestation and one queryable record (spec §3).

Design discipline (build/01_foundation.md §0.2):
  - Each spine type is **thin** and *references existing IDs* rather than
    re-defining vocabulary. The harvest/reproduce wire format lives in
    ``rogue.schemas`` and is frozen Day-0 (CLAUDE.md); the spine **wraps/points
    at** those types and **never duplicates their enums**. In particular the
    breach/clean mapping is derived from ``rogue.schemas.JudgeVerdict`` /
    ``BREACH_VERDICTS`` — never a forked copy.
  - Captures are stored as **pointers, not blobs** (spec §3 design note): a
    ``Capture`` carries small inline scalars (latency/tokens) and a
    *reproducibility pointer*, never the transcript itself.
  - Negative/rejected exemplars are *kept*, not discarded (spec §3): a clean /
    refused trial still produces a retained ``Capture`` with
    ``is_negative_exemplar=True`` — it is the regression baseline for Surface-1b
    re-verification. Retention is an internal-corpus concern; it does **not**
    change the customer-facing (breach-led) report.

The independence invariant (ADR-0011, spec §5) is enforced at the type level on
``GroundTruthRef``: ground truth is *never* the regulation, the operators'/voters'
own decisions, or the verifier's (judge's) own score. For Phase-0 harm scans the
source is ``"NONE"`` — honest: there is no per-rule independent label yet. The
field exists so Phase 1 can populate it.

This file is **pure new** Phase-0 code: it does not touch ``schemas/``, ``sdk/``,
``report.py``, or any shared platform file.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from rogue.schemas import BREACH_VERDICTS, JudgeVerdict

# Ground-truth sources that violate the independence invariant (ADR-0011 / spec
# §5). A label drawn from any of these is circular — the thing being measured
# (or its grader) cannot also be its own answer key — and is rejected at the
# type level. Matched case-insensitively as a substring so near-spellings
# ("verifier_score", "judge-output", "the regulation") are also caught.
FORBIDDEN_GROUND_TRUTH_TOKENS = frozenset(
    {
        "verifier",  # the verifier's own score
        "judge",  # the judge's own output
        "regulation",  # the rule cannot be its own answer key
        "policy",  # ditto
        "operator",  # the operators' own decisions
        "voter",  # the reviewers'/voters' own votes
        "votes",
        "self",  # any "graded against itself" framing
    }
)


class Target(BaseModel):
    """What was measured (spec §3).

    A *thin* handle to the unit under test — an agent endpoint, a human approval
    gate, or a shared skill pool — registered via the adapter layer. It stores a
    ``target_ref`` (the stable identifier of the underlying ``TargetSpec`` /
    ``DeploymentConfig``) plus a **redacted snapshot** dict, and **never** a raw
    secret. Callers pass the output of ``TargetSpec.redacted()`` (or an
    equivalent log-safe dict) as ``redacted_snapshot`` — the spine deliberately
    does not import the platform schema so it stays dependency-light, but the
    no-raw-secret contract is the same.
    """

    target_kind: Literal["agent_endpoint", "human_gate", "skill_pool"] = Field(
        ..., description="which surface's unit-under-test this is (extensible per surface)"
    )
    target_ref: str = Field(
        ...,
        min_length=1,
        description="stable id of the underlying TargetSpec/DeploymentConfig (not a secret)",
    )
    redacted_snapshot: dict = Field(
        default_factory=dict,
        description="log-safe snapshot (e.g. TargetSpec.redacted()); MUST NOT contain a raw secret",
    )

    model_config = {"frozen": True}


class Probe(BaseModel):
    """What was fired at the target (spec §3).

    For the harm case ``probe_ref`` points at an ``AttackPrimitive.primitive_id``.
    Re-aim metadata (which policy rule a probe targets) is a Phase-1 field — it is
    left as a documented extension point here, not built (build §0.2).
    """

    probe_kind: Literal["attack_primitive", "labeled_case", "extraction_attack"] = Field(
        ..., description="attack-family instance / labeled case / extraction attack"
    )
    probe_ref: str = Field(
        ...,
        min_length=1,
        description="harm case: AttackPrimitive.primitive_id; other surfaces: their case id",
    )
    # Phase-1 extension point (do NOT populate in Phase 0): the rule/policy id a
    # re-aimed probe targets. Left absent rather than typed so it can't be
    # mistaken for a built field.

    model_config = {"frozen": True}


class Capture(BaseModel):
    """The raw output captured, stored as a **pointer, not a blob** (spec §3).

    The transcript is *never* inlined here. ``reproducibility_pointer`` is the
    handle that resolves back to the exact bytes. In Phase 0 the dedicated
    content-addressed snapshot store (``snapshot_ref`` → build §0.3
    ``CaptureStore``) is **DEFERRED**, so the pointer is the existing
    ``breach_id`` / ``scan_id`` reproducibility handle on a harm ``BreachResult``.
    When the snapshot store lands, the same field carries the sha256 ``snapshot_ref``
    with no shape change to this type.

    ``is_negative_exemplar`` is ``True`` for a clean/refused trial: those captures
    are *retained* as the regression baseline (spec §3, build §0.4), not
    discarded — internal-corpus hygiene, never surfaced in the breach-led report.
    """

    reproducibility_pointer: str = Field(
        ...,
        min_length=1,
        description="handle resolving to the exact transcript bytes (Phase-0: breach_id/scan_id; "
        "later: sha256 snapshot_ref). NEVER the transcript itself.",
    )
    is_negative_exemplar: bool = Field(
        default=False,
        description="True for a clean/refused trial — a retained regression baseline, not a breach",
    )
    # Small inline scalars only — NEVER the transcript.
    latency_ms: int | None = Field(default=None, ge=0, description="target-call latency in ms")
    tokens_in: int | None = Field(default=None, ge=0)
    tokens_out: int | None = Field(default=None, ge=0)

    model_config = {"frozen": True}


class Verdict(BaseModel):
    """The calibrated judge's call (spec §3): ``{breach | clean}``.

    Mapped from the existing ``rogue.schemas.JudgeVerdict`` via ``BREACH_VERDICTS``
    (reuse, never fork): ``PARTIAL_BREACH``/``FULL_BREACH`` → ``breach``; everything
    else (``REFUSED``/``EVADED``/``ERROR``) → ``clean``. Build a ``Verdict`` from a
    raw judge verdict with :meth:`from_judge_verdict`.

    ``consummation_event`` is the event that *defined* the breach (spec §2.2 table).
    ``class_confidence`` is the judge's confidence in this {breach|clean} call.
    ``ci`` is the spec §3 confidence-interval slot — the field exists now; its
    *population* (a shared ``bootstrap_ci`` helper) is Phase-1 work, so it defaults
    to ``None`` here.
    """

    label: Literal["breach", "clean"]
    consummation_event: str = Field(
        ...,
        description="the event that defined the breach (spec §2.2); '' / 'none' for a clean verdict",
    )
    class_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="judge confidence in the {breach|clean} call"
    )
    ci: tuple[float, float] | None = Field(
        default=None,
        description="confidence interval on the rate (spec §3 slot); populated in Phase 1, None now",
    )

    model_config = {"frozen": True}

    @staticmethod
    def label_for(verdict: JudgeVerdict) -> Literal["breach", "clean"]:
        """Map a raw ``JudgeVerdict`` to the spine's binary label using the canonical
        ``BREACH_VERDICTS`` set — the single source of truth, never duplicated here."""
        return "breach" if verdict in BREACH_VERDICTS else "clean"

    @classmethod
    def from_judge_verdict(
        cls,
        verdict: JudgeVerdict,
        *,
        class_confidence: float,
        consummation_event: str = "",
        ci: tuple[float, float] | None = None,
    ) -> Verdict:
        """Build a spine ``Verdict`` from a reproduce-layer ``JudgeVerdict``."""
        return cls(
            label=cls.label_for(verdict),
            consummation_event=consummation_event,
            class_confidence=class_confidence,
            ci=ci,
        )

    @field_validator("ci")
    @classmethod
    def _ci_ordered(
        cls, v: tuple[float, float] | None
    ) -> tuple[float, float] | None:
        if v is not None and v[0] > v[1]:
            raise ValueError("ci lower bound must be <= upper bound")
        return v


class GroundTruthRef(BaseModel):
    """Pointer to the **independent** label this verdict is scored against (ADR-0011 / spec §5).

    The independence invariant — the foundation of every defensible number — is
    enforced at the type level: ground truth is **never** the regulation/policy,
    **never** the operators'/voters' own decisions, and **never** the verifier's
    (judge's) own score. A ``source`` that names any of those is circular and is
    rejected by the validator.

    Allowed sources: ``"synthetic"`` (authored designed-label corpus — what an
    early build uses), ``"expert"`` (adjudication by experts separate from the
    operators — production-grade), ``"historical"`` (resolved real outcomes —
    production), and ``"NONE"`` (no independent label yet). For Phase-0 harm scans
    the source is ``"NONE"``: honest, because there is no per-rule independent
    label yet; the field exists so Phase 1 can populate it.
    """

    source: Literal["synthetic", "expert", "historical", "NONE"] = Field(
        ..., description="independent-label provenance (ADR-0011); harm Phase-0 uses 'NONE'"
    )
    ref: str | None = Field(
        default=None,
        description="id of the independent labeled case/set; None when source='NONE'",
    )

    model_config = {"frozen": True}

    @field_validator("source", mode="before")
    @classmethod
    def _reject_circular_source(cls, v: object) -> object:
        """Reject any verifier-/regulation-/operator-as-key value (ADR-0011).

        Runs *before* the ``Literal`` check so a forbidden token (e.g.
        ``"verifier"``, ``"judge_score"``, ``"the regulation"``) raises the
        independence-invariant error with a clear message rather than a generic
        enum error. Legitimate values fall through to the ``Literal`` validation.
        """
        if isinstance(v, str):
            lowered = v.lower()
            for token in FORBIDDEN_GROUND_TRUTH_TOKENS:
                if token in lowered:
                    raise ValueError(
                        "GroundTruthRef violates the independence invariant (ADR-0011): "
                        f"source {v!r} names a forbidden grader ({token!r}). Ground truth is "
                        "never the regulation, the operators'/voters' decisions, or the "
                        "verifier's own score."
                    )
        return v


class Mitigation(BaseModel):
    """Surface-1b stub — the generated fix + its re-test result (spec §3).

    FORWARD-DECLARED / UNUSED in Phase 0. The type exists so the seam is named;
    Phase 2 fills it and ADR-0010 governs its semantics. Do **not** wire this in
    Phase 0.
    """

    fix_summary: str = Field(default="", description="Phase-2: description of the generated fix")
    retest_breach_rate: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Phase-2: breach rate after the fix was applied"
    )
    over_block_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Phase-2: false-block / over-block rate introduced by the fix",
    )

    model_config = {"frozen": True}


class AttestationEntry(BaseModel):
    """A typed **view** of one signed, hash-chained record line (spec §3 / §2.5).

    This is the read-side / wire view of an attestation entry: the typed shape a
    surface or verifier reads. The **storage ORM and the hash-chain producer**
    (canonicalization, ``entry_hash`` computation, signing, ``verify_chain``) are
    another engineer's (build §0.5 ``instrument/attestation.py``); this file only
    declares the typed shape so consumers have a stable contract.

    The record framing is *threat-informed assurance* — "tested against the known
    corpus as of date D" — explicitly **not** a safety guarantee (build §0.5).
    ``reproducibility_pointer`` mirrors ``Capture.reproducibility_pointer`` so an
    entry can be byte-replayed.
    """

    target: Target
    probe: Probe
    verdict: Verdict
    rationale: str = Field(..., description="the judge's decision rationale for this verdict")
    timestamp: datetime
    reproducibility_pointer: str = Field(
        ..., min_length=1, description="resolves to the exact transcript (mirrors Capture)"
    )
    prev_hash: str = Field(..., description="hash of the previous chain entry (genesis for the first)")
    entry_hash: str = Field(..., description="sha256(canonical(body) + prev_hash)")
    signature: str = Field(..., description="signature over entry_hash (key id recorded, key never)")

    model_config = {"frozen": True}
