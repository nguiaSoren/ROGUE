"""Pydantic v2 response models for the attestation `/v1` query surface.

Section E of ``docs/v2/build/03_attestation.md``: the wire shapes an auditor
sees. Pure Pydantic — no DB, no SQLAlchemy. The router and service that produce
these (``api/v1/attestation.py``, ``AttestationService``) are added by the
integration wave; this file only defines the contract.

Every entry surfaces the **framing** line (unified §2.5): *threat-informed
assurance, tested against the corpus as of date D — not a safety guarantee.*
The framing is structural, not cosmetic: it travels on the response model so a
client can never render an entry without it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

__all__ = [
    "AttestationEntryOut",
    "ChainVerificationOut",
    "AttestationQueryResult",
]


class AttestationEntryOut(BaseModel):
    """One attestation entry, minus internal cruft, as returned to the caller.

    Internal columns (the raw ORM ``payload`` blob, FK wiring) are not echoed
    verbatim; instead the high-value structured fields plus the canonical
    ``framing`` line are surfaced. ``payload`` carries the structured
    decision-rationale (§2.5 #3) for the entry's surface.
    """

    entry_id: str
    seq: int = Field(description="Per-org monotonic sequence number; genesis is 0.")
    entry_type: str = Field(description="genesis | scan | decision | mitigation | promotion")
    prev_hash: str = Field(description="entry_hash of the preceding entry (64 zeros at genesis).")
    entry_hash: str = Field(description="sha256(prev_hash || canonical_json(payload)).")
    payload: dict = Field(description="Structured decision-rationale + headline fields.")
    reproducibility_ref: str | None = Field(
        default=None,
        description="scan_id / breach_id / report_id this entry reconstructs from.",
    )
    ground_truth_ref: str | None = Field(
        default=None,
        description="Independent label this verdict is scored against (ADR-0011); may be null.",
    )
    corpus_as_of: datetime = Field(
        description="The 'as of date D' the assurance is anchored to.",
    )
    created_at: datetime
    framing: str = Field(
        description=(
            "Non-negotiable scope line surfaced on every entry: threat-informed "
            "assurance, not a safety guarantee, as of corpus_as_of."
        ),
    )


class ChainVerificationOut(BaseModel):
    """The auditor's 'is this chain intact?' answer.

    Mirrors ``chain.ChainVerification``: ``ok`` plus, on a break, the offending
    ``seq`` and the expected (recomputed) vs actual (stored) hash.
    """

    ok: bool
    broken_at_seq: int | None = None
    expected: str | None = None
    actual: str | None = None


class AttestationQueryResult(BaseModel):
    """A paginated slice of an org's chain (the queryability spine, §2.5 #5)."""

    entries: list[AttestationEntryOut]
    count: int = Field(description="Number of entries in this page.")
    next_seq: int | None = Field(
        default=None,
        description="seq to pass as `since_seq` for the next page; null when exhausted.",
    )
