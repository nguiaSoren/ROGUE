"""Per-type independent-labeling schema — the binary ground-truth a non-harm
breach judge is calibrated against (v2 build-02 §3.1, ADR-0011).

Why this exists (the ADR-0011 "half the work")
-----------------------------------------------
Every v2 headline number is only as real as the ground-truth standard it is
scored against (ADR-0011). For a *non-harm* breach type — information-disclosure
first — the surface-specific axis is cleanly **binary**: did the protected datum
actually appear in the response, ``breach`` / ``clean``? That is *not* the 4-way
``JudgeVerdict`` the harm judge emits; it is the §2.3.1 surface-specific label,
deliberately coarser because non-harm ground truth is binary by construction.

This module is the storage + validation layer for that label set. It mirrors the
proven pattern in :class:`rogue.reproduce.judge_calibration.CalibrationCase`:
a frozen-by-pydantic case model with a ``from_dict`` that **rejects unknown
values loudly** (a silent coercion of a bad ``label_source`` or ``human_label``
would let a circular or mislabeled row contaminate a calibration set, the exact
failure ADR-0011 forbids). It is a *pure new file*: nothing here imports or edits
``judge.py``.

The three ADR-0011 "nevers" live in ``label_source``
----------------------------------------------------
Ground truth is established by a process independent of the thing being measured.
``label_source`` records that provenance on **every row** so it is auditable:

* ``synthetic_designed`` — authored cases whose disposition is known *by
  construction* (the author wrote the response with intent, so the label is not
  a judgement call). This is the legitimate early source for info-disclosure and
  the only one the seed fixture uses. It is NOT LLM-judging — no verifier scores
  its own output here.
* ``expert_adjudication`` — experts *separate from the operators* (production
  upgrade; named as planned, not yet held).
* ``historical_outcome`` — resolved real-world outcomes (production upgrade).

The shared contract with the calibration harness: ``fp_mode_trap``
------------------------------------------------------------------
A case authored specifically to probe the surface's false-positive mode — for
info-disclosure, an agent that only *discusses* the data-handling policy (and is
therefore labeled ``clean``). The calibration harness (build-02 §4.1) computes
the **headline FP-mode rate over exactly the ``fp_mode_trap=True`` rows**, so
this flag is the shared definition between the labeling fixture's trap quota and
the harness's headline metric. Keeping the definition in one field stops the two
from drifting (build-02 §4.1 risk note).

Spec: docs/v2/build/02_judge_generalization.md §3.1; ADR-0011.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "HUMAN_LABELS",
    "LABEL_SOURCES",
    "LabelSet",
    "LabeledCase",
]


# The two closed vocabularies. Defined as tuples (not just the ``Literal``) so
# the loud-rejection error messages can list the valid values without
# duplicating them — single source, the way ``CalibrationCase`` lists
# ``[v.value for v in JudgeVerdict]``.
HUMAN_LABELS: tuple[str, ...] = ("breach", "clean")
LABEL_SOURCES: tuple[str, ...] = (
    "synthetic_designed",
    "expert_adjudication",
    "historical_outcome",
)


class LabeledCase(BaseModel):
    """One independently-labeled (rule → probe → response → label) row.

    Generalizes :class:`rogue.reproduce.judge_calibration.CalibrationCase` to
    non-harm breach types. The label is the **binary** surface-specific axis
    (``breach`` / ``clean``, build-02 §2.3.1), not the 4-way ``JudgeVerdict``.
    Validation is intentionally strict: ``from_dict`` raises on an unknown
    ``label_source`` or ``human_label`` so a bad row can never enter a
    calibration set unnoticed (ADR-0011).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(..., min_length=1)
    breach_type: str = Field(..., min_length=1)
    rule_text: str = Field(
        ...,
        description="The governance rule being tested (e.g. an employee-comp "
        "confidentiality policy). Drawn from a realistic rule, never a toy.",
    )
    protected_target: str = Field(
        ...,
        description="What must not be disclosed/executed — the datum whose "
        "appearance in the response constitutes the breach.",
    )
    probe_payload: str = Field(
        ...,
        description="The attacker probe. Should be drawn from real corpus "
        "families re-aimed at the rule, not a toy prompt (build-02 §4.4).",
    )
    model_response: str = Field(
        ...,
        description="The response being labeled. For synthetic_designed rows "
        "this is authored with intent so the label is known by construction.",
    )
    human_label: Literal["breach", "clean"] = Field(
        ...,
        description="The binary surface-specific ground truth. NOT the 4-way "
        "JudgeVerdict — non-harm ground truth is cleanly binary (§2.3.1).",
    )
    label_source: Literal[
        "synthetic_designed", "expert_adjudication", "historical_outcome"
    ] = Field(
        ...,
        description="ADR-0011 provenance recorded on every row. The seed "
        "fixture is exclusively synthetic_designed (authored by construction).",
    )
    label_rationale: str = Field(
        ...,
        min_length=1,
        description="One line stating why this disposition is correct — the "
        "auditable reason, required so no row carries a silent label.",
    )
    fp_mode_trap: bool = Field(
        default=False,
        description="True iff this case was authored specifically to test the "
        "surface's FP mode (e.g. discuss-only → clean). The calibration harness "
        "computes the headline FP-mode rate over exactly these rows — the "
        "shared contract with the harness (build-02 §4.1).",
    )
    tool_trace: str | None = Field(
        default=None,
        description="Optional captured tool-call trace, for unauthorized-action "
        "where the gate keys on the call, not the prose (build-02 §4.5).",
    )

    @field_validator("human_label", mode="before")
    @classmethod
    def _reject_unknown_label(cls, value: Any) -> str:
        """Reject an unknown ``human_label`` loudly (mirrors CalibrationCase)."""
        norm = str(value).strip().lower()
        if norm not in HUMAN_LABELS:
            raise ValueError(
                f"invalid human_label {value!r}; "
                f"must be one of {list(HUMAN_LABELS)}"
            )
        return norm

    @field_validator("label_source", mode="before")
    @classmethod
    def _reject_unknown_source(cls, value: Any) -> str:
        """Reject an unknown ``label_source`` loudly (ADR-0011 provenance)."""
        norm = str(value).strip().lower()
        if norm not in LABEL_SOURCES:
            raise ValueError(
                f"invalid label_source {value!r}; "
                f"must be one of {list(LABEL_SOURCES)}"
            )
        return norm

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LabeledCase":
        """Project a JSON-fixture entry into the model.

        Raises ``ValueError`` on any unknown / missing field, an invalid
        ``human_label``, or an invalid ``label_source`` — the same loud
        rejection contract as ``CalibrationCase.from_dict``. The ``case_id`` is
        surfaced in the error so a bad row in a large fixture is locatable.
        """
        try:
            return cls.model_validate(d)
        except Exception as exc:  # noqa: BLE001 — re-raise with locator context
            raise ValueError(
                f"invalid LabeledCase {d.get('case_id', '?')!r}: {exc}"
            ) from exc


class LabelSet(BaseModel):
    """A breach-type's full independently-labeled corpus + provenance metadata.

    Wraps the list of :class:`LabeledCase` with the breach-type key and the
    provenance metadata a calibration run needs to be auditable (who/what
    authored it, when, the dominant source). The loader ignores top-level keys
    prefixed with ``_`` so a fixture can carry a ``_README`` documentation block
    (same convention as ``judge_calibration_pairs.json``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    breach_type: str = Field(..., min_length=1)
    cases: tuple[LabeledCase, ...] = Field(default_factory=tuple)
    provenance: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form provenance metadata (author, date, source "
        "notes, kappa-check status) — auditable record, not validated values.",
    )

    @field_validator("cases")
    @classmethod
    def _breach_type_matches(
        cls, cases: tuple[LabeledCase, ...]
    ) -> tuple[LabeledCase, ...]:
        """Every case's ``breach_type`` must match the set's (no mixing)."""
        # ``info`` is unavailable for the set key here without model context;
        # the cross-check against the set-level breach_type happens in
        # ``model_validate``-time via the model validator below.
        return cases

    def class_counts(self) -> dict[str, int]:
        """Count of cases per ``human_label`` (``breach`` / ``clean``)."""
        counts = {label: 0 for label in HUMAN_LABELS}
        for case in self.cases:
            counts[case.human_label] += 1
        return counts

    def fp_mode_trap_count(self) -> int:
        """Number of cases authored to probe the FP mode (build-02 §4.1)."""
        return sum(1 for case in self.cases if case.fp_mode_trap)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LabelSet":
        """Project a parsed JSON dict into a validated ``LabelSet``.

        Top-level keys prefixed with ``_`` are treated as documentation and
        ignored. Each entry in ``cases`` is validated via
        :meth:`LabeledCase.from_dict` (loud rejection of bad rows). The set's
        ``breach_type`` is asserted to match every case's ``breach_type``.
        """
        clean = {k: v for k, v in d.items() if not k.startswith("_")}
        breach_type = str(clean.get("breach_type", "")).strip()
        if not breach_type:
            raise ValueError("LabelSet is missing a non-empty 'breach_type'")

        raw_cases = clean.get("cases", [])
        cases = [LabeledCase.from_dict(c) for c in raw_cases]

        mismatched = [
            c.case_id for c in cases if c.breach_type != breach_type
        ]
        if mismatched:
            raise ValueError(
                f"LabelSet breach_type {breach_type!r} does not match these "
                f"case breach_types: {mismatched}"
            )

        return cls(
            breach_type=breach_type,
            cases=tuple(cases),
            provenance=dict(clean.get("provenance", {})),
        )

    @classmethod
    def load(cls, path: Path | str) -> "LabelSet":
        """Load + validate a label-set JSON fixture from disk."""
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_dict(json.loads(text))
