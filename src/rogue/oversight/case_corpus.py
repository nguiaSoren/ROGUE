"""Surface 2 case corpus — the designed-label answer key + decision records.

THE INDEPENDENCE INVARIANT LIVES HERE (ADR-0011, unified spec §5, build 07 §2).
The headline number this surface produces — a human false-approve rate with a
bootstrap CI — is only worth signing if the "correct disposition" for every case
is *provably independent* of (a) the regulation text, (b) the reviewers' own
votes, and (c) the verifier model's own opinion. A leaky corpus is a signed
attestation of a number that was never established — worse than no product.

This module is the invariant's code home. Two mitigations are baked into the
model below:

  1. ``label_provenance`` is REQUIRED on every case (no default) and its allowed
     set deliberately has NO ``verifier`` member — the circularity trap
     (spec §2 source #4: "the verifier graded itself") is not even representable.
  2. ``from_dict`` rejects unknown ``case_class`` / ``designed_label`` /
     ``label_provenance`` LOUDLY with a descriptive ValueError naming the bad
     value and the allowed set — never a silent coercion. This mirrors
     ``reproduce/judge_calibration.py`` ``CalibrationCase.from_dict``.

The frozen ``GatedCase`` / ``GatedDecision`` field set below is the contract
every other §07 module (lint, decider, scorer, attestation, cockpit) imports;
do not deviate.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, field_validator

__all__ = ["GatedCase", "GatedDecision", "load_corpus", "corpus_stats"]


# --- Allowed vocabularies (single source; reused by both the Literal types and
# --- the loud from_dict rejection so the two can never drift). -----------------
CaseClass = Literal["large_wire", "high_value_refund", "vendor_change"]
DesignedLabel = Literal["APPROVE", "DENY"]
# NOTE: deliberately NO "verifier" member — the circularity trap (spec §2 #4)
# is not even representable.
LabelProvenance = Literal[
    "synthetic_designed", "expert_adjudicated", "historical_resolved"
]
Decision = Literal["APPROVE", "DENY"]

_CASE_CLASSES: tuple[str, ...] = get_args(CaseClass)
_DESIGNED_LABELS: tuple[str, ...] = get_args(DesignedLabel)
_LABEL_PROVENANCES: tuple[str, ...] = get_args(LabelProvenance)


# Canonical path to the authored starter corpus (≥40 cases, stratified across
# ≥3 case-classes, balanced APPROVE/DENY). Harvested via Bright Data.
CORPUS_FIXTURE_PATH: Path = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "tests"
    / "fixtures"
    / "oversight"
    / "designed_label_corpus.json"
)


def _reject_unknown(field_name: str, value: Any, allowed: tuple[str, ...]) -> str:
    """Loud-reject a value not in the allowed set (ADR-0011 discipline)."""
    if value not in allowed:
        raise ValueError(
            f"invalid {field_name} {value!r}; must be one of {list(allowed)}"
        )
    return str(value)


class GatedCase(BaseModel):
    """One escalated case + the disposition that is correct *by construction*.

    The ``designed_label`` is the independent answer key (a ``GroundTruthRef`` in
    the shared data-model spine); the reviewer's decision is scored against it,
    never the other way around. ``facts`` are structured CHECKABLE facts a
    reviewer verifies (amount/parties/date/what_was_flagged/...), NOT prose that
    persuades (spec §4).
    """

    case_id: str
    case_class: CaseClass
    facts: dict[str, str]
    designed_label: DesignedLabel
    designed_rationale: str
    label_provenance: LabelProvenance
    source_refs: list[str]

    model_config = {"frozen": True}

    @field_validator("case_id")
    @classmethod
    def _case_id_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("case_id must be non-empty")
        return v

    @field_validator("facts")
    @classmethod
    def _facts_non_empty(cls, v: dict[str, str]) -> dict[str, str]:
        if not v:
            raise ValueError("facts must be non-empty (structured checkable facts)")
        return v

    @field_validator("designed_rationale")
    @classmethod
    def _rationale_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("designed_rationale must be non-empty")
        return v

    @field_validator("source_refs")
    @classmethod
    def _source_refs_non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("source_refs must contain >=1 real URL (grounding)")
        return v

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GatedCase":
        """Project a JSON-fixture entry into the model with LOUD rejection.

        Unknown ``case_class`` / ``designed_label`` / ``label_provenance`` raise a
        descriptive ValueError naming the bad value + the allowed set, rather than
        relying on the Literal alone (ADR-0011). ``label_provenance`` is REQUIRED
        with no default — a missing key is a KeyError surfaced as a clear error.
        """
        cid = d.get("case_id", "?")
        try:
            case_class = _reject_unknown("case_class", d["case_class"], _CASE_CLASSES)
            designed_label = _reject_unknown(
                "designed_label", d["designed_label"], _DESIGNED_LABELS
            )
            provenance = _reject_unknown(
                "label_provenance", d["label_provenance"], _LABEL_PROVENANCES
            )
        except KeyError as exc:
            raise ValueError(
                f"case {cid!r} is missing required field {exc.args[0]!r}"
            ) from exc
        except ValueError as exc:
            raise ValueError(f"case {cid!r}: {exc}") from exc

        return cls(
            case_id=str(d["case_id"]),
            case_class=case_class,  # type: ignore[arg-type]
            facts=dict(d["facts"]),
            designed_label=designed_label,  # type: ignore[arg-type]
            designed_rationale=str(d["designed_rationale"]),
            label_provenance=provenance,  # type: ignore[arg-type]
            source_refs=list(d["source_refs"]),
        )


class GatedDecision(BaseModel):
    """One reviewer's disposition for a presented ``GatedCase``.

    ``decision_latency_s`` is an engagement signal (deliberating/asking questions
    is NOT a breach — spec §1); only ``decision`` vs the case's ``designed_label``
    determines false-approve / false-deny.
    """

    case_id: str
    reviewer: str
    decision: Decision
    deliberation_notes: str | None = None
    decision_latency_s: float | None = None
    decided_at: datetime


def load_corpus(path: str | Path | None = None) -> list[GatedCase]:
    """Load the designed-label corpus, loud-rejecting any malformed case.

    Defaults to ``tests/fixtures/oversight/designed_label_corpus.json``. Each
    entry is projected via ``GatedCase.from_dict`` (ADR-0011 loud rejection).
    """
    target = Path(path) if path is not None else CORPUS_FIXTURE_PATH
    with open(target, encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list):
        raise ValueError(
            f"corpus at {target} must be a JSON list of cases, got {type(raw).__name__}"
        )
    cases = [GatedCase.from_dict(entry) for entry in raw]

    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise ValueError(f"duplicate case_id {case.case_id!r} in corpus {target}")
        seen.add(case.case_id)
    return cases


def corpus_stats(cases: list[GatedCase]) -> dict[str, Any]:
    """Summarize a corpus for the lint/loader exit-gate: counts by label + class."""
    return {
        "n_cases": len(cases),
        "by_label": dict(Counter(c.designed_label for c in cases)),
        "by_case_class": dict(Counter(c.case_class for c in cases)),
        "by_provenance": dict(Counter(c.label_provenance for c in cases)),
    }
