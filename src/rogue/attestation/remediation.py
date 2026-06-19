"""Emit: fold a VERIFIED mitigation into the attestation chain (Surface 1b §8).

The mitigation analogue of ``emit.payload_for_scan`` — it turns a
:class:`RemediationResult` (a generated artifact + its re-test evidence) into a
structured ``mitigation`` attestation record that the EXISTING hash chain consumes.
It does NOT build a second chain (ADR-0011 / build-05 §8): the record is just
another payload appended to the same per-org chain via ``AttestationService.append``.

The record mirrors ``emit._finding_record``'s decision-rationale shape (``kind`` /
verdict-style disposition + a body + pointers, never blobs), and builds its body by
REUSING ``rogue.remediation.report.remediation_attestation_rows`` — the per-mitigation
row(s) already specced for the chain — so the row vocabulary lives in exactly one place.

What it stores: the verified pre/post breach rates + over-block + ``breach_ref`` + the
artifact REF (a pointer, not the artifact text — the re-test is a reproducible scan, so
the entry carries handles, not giant blobs). Free-text fields are redacted via the SAME
``report_service._redact`` the scan path uses — an append-only entry can never carry a
leaked secret.

Spec: ``docs/v2/build/05_*`` §8; reuses ``docs/v2/build/03_attestation.md`` chain.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from rogue.attestation.emit import canonical_as_of, framing_line
from rogue.platform.report_service import _redact
from rogue.remediation.report import remediation_attestation_rows
from rogue.schemas.remediation import RemediationResult

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService
    from rogue.platform.models import AttestationEntry

__all__ = ["mitigation_record", "append_mitigation"]


def mitigation_record(
    result: RemediationResult,
    *,
    scan_id: str,
    index: int,
    corpus_as_of: str | None = None,
) -> dict:
    """Build the ``mitigation`` attestation record for one :class:`RemediationResult`.

    Mirrors ``emit._finding_record``: a ``kind`` disposition, the verified rates, a
    consummation-style pointer, and a ``snapshot_ref`` handle resolving back to the
    source — never the artifact blob. The body is the canonical per-mitigation row(s)
    from ``remediation_attestation_rows`` (reused, not reinvented), redacted.

    Deterministic + self-contained: given the same ``result`` + ``scan_id`` + ``index``
    + ``corpus_as_of`` it returns a byte-identical dict, so it round-trips through
    ``chain.canonical_payload`` stably and the chain recomputes the exact ``entry_hash``.
    """
    c = result.candidate
    # REUSE the already-built row shape; a mitigation emits exactly one row today, but
    # iterate so this never silently drops a future multi-row emission.
    rows = remediation_attestation_rows(result, corpus_as_of=corpus_as_of)

    over_block_rate = result.over_block.over_block_rate if result.over_block else None
    breached_still = result.post_breach_rate > 0.0
    # The over-block CI travels as a list (JSON has no tuples) so the canonical-JSON
    # bytes are stable across a Postgres/SQLite round-trip.
    post_ci = list(result.post_breach_ci) if result.post_breach_ci is not None else None

    return {
        "kind": "mitigation",
        # The breach this mitigation answers — the "rule" dimension, mirroring the
        # finding record's rule/family axis.
        "breach_ref": c.breach_ref,
        "mitigation_type": c.mitigation_type.value,
        "candidate_id": c.candidate_id,
        # Binary disposition (mirrors finding "verdict"): did the loop accept the fix?
        "accepted": bool(result.accepted),
        "verdict": "accepted" if result.accepted else "rejected",
        # How the evidence was produced — a re-scan delta vs verified-out-of-band.
        "verified_by": result.verified_by,
        # The VERIFIED rates (the core evidence), pinned to 6 dp like the scan path.
        "pre_breach_rate": round(float(result.pre_breach_rate), 6),
        "post_breach_rate": round(float(result.post_breach_rate), 6),
        "post_breach_ci": post_ci,
        # Independent over-block measurement (ADR-0011); None when no over-block check.
        "over_block_rate": (round(float(over_block_rate), 6) if over_block_rate is not None else None),
        "iterations": int(result.iterations),
        # Whether the re-test still breached at all (the headline disposition of the fix).
        "residual_breach": breached_still,
        # The model + prompt_version that generated the artifact (reproducibility).
        "generated_by": _redact(c.generated_by),
        # Rationale is free text → redacted (an append-only entry never carries a secret).
        "rationale": _redact(c.rationale),
        # The canonical per-mitigation row(s), reused verbatim from the remediation layer.
        "rows": rows,
        # Pointer, not a blob: a stable handle to the artifact + this mitigation's source.
        # The artifact TEXT is never stored here — the re-test is a reproducible scan, so
        # the entry carries a ref that resolves back to it.
        "artifact_ref": f"{scan_id}::{c.breach_ref}::{c.candidate_id}",
        "snapshot_ref": f"{scan_id}::{c.candidate_id}::{index}",
        # Independent-label slot (ADR-0011): present so surfaces don't fork the shape.
        "ground_truth_ref": None,
        "corpus_as_of": corpus_as_of,
        "framing": (
            framing_line(_parse_as_of(corpus_as_of)) if corpus_as_of is not None else None
        ),
    }


def _parse_as_of(corpus_as_of: str) -> datetime:
    """Parse the iso ``corpus_as_of`` string back to a datetime for the framing line.

    ``mitigation_record`` takes ``corpus_as_of`` as a string (the remediation row's
    shape), but ``framing_line`` wants a datetime; re-canonicalize through the same
    ``canonical_as_of`` so the framing bytes match the scan path exactly.
    """
    dt = datetime.fromisoformat(corpus_as_of)
    # Round-trip through canonical_as_of's normalization for byte-identical framing.
    canonical_as_of(dt)
    return dt


def append_mitigation(
    service: "AttestationService",
    org_id: str,
    result: RemediationResult,
    *,
    scan_id: str,
    index: int = 0,
    corpus_as_of: datetime,
    reproducibility_ref: str | None = None,
) -> "AttestationEntry":
    """Append a verified mitigation to ``org_id``'s chain via the EXISTING engine.

    Thin: it builds the record with :func:`mitigation_record` and hands it to
    ``service.append`` with ``entry_type="mitigation"`` — the SAME per-org hash chain,
    the same lazy-genesis / monotonic-seq / idempotency invariants. No chain logic is
    duplicated here.

    ``corpus_as_of`` is the chain's mandatory "as of date D" (a datetime, passed to
    ``append``); the record body stores its canonical iso form so the payload bytes
    are stable. ``reproducibility_ref`` (defaulting to the candidate id) makes a worker
    retry idempotent, exactly as the scan path is.
    """
    iso_as_of = canonical_as_of(corpus_as_of)
    record = mitigation_record(
        result, scan_id=scan_id, index=index, corpus_as_of=iso_as_of
    )
    ref = reproducibility_ref or result.candidate.candidate_id
    return service.append(
        org_id,
        "mitigation",
        record,
        reproducibility_ref=ref,
        corpus_as_of=corpus_as_of,
    )
