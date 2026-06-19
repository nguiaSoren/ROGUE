"""The signed-attestation layer — tamper-evident, reproducible, queryable record.

The tamper-evident, reproducible, queryable record every surface emits (v2 §2.5).
This package now ships the full Phase-0 harm/scan path:

* ``chain`` — the pure, DB-free hash-chain primitives (the auditable math).
* ``schemas`` — the Pydantic ``/v1`` response shapes.
* ``AttestationService`` — the append engine + verifier over Postgres (one
  append-only, per-org hash chain; ADR-0012).
* ``payload_for_scan`` (``emit``) — the seam from a finished scan to a structured
  decision-rationale payload (redacted; carries the framing line + ``corpus_as_of``).
* ``replay`` — byte-reproducible reconstruction from stored inputs (no model call).

Completeness scoping (honest, per v2 §2.5 #2): a COMPLETED scan appends exactly one
``scan`` entry; FAILED / CANCELED scans are recorded in ``scan_runs.status`` and are
NOT attested — there is no verdict to attest. Appends are idempotent on the scan's
``reproducibility_ref`` so a worker retry never double-appends.
"""

from __future__ import annotations

from rogue.attestation.chain import (
    ENTRY_TYPES,
    GENESIS_PREV,
    ChainVerification,
    canonical_payload,
    compute_hash,
    verify_chain,
)
from rogue.attestation.emit import payload_for_scan
from rogue.attestation.remediation import append_mitigation, mitigation_record
from rogue.attestation.replay import ReplayResult
from rogue.attestation.replay import replay as replay  # noqa: PLC0414 — re-export the function
from rogue.attestation.schemas import (
    AttestationEntryOut,
    AttestationQueryResult,
    ChainVerificationOut,
)
from rogue.attestation.service import AttestationService

__all__ = [
    # chain primitives
    "ENTRY_TYPES",
    "GENESIS_PREV",
    "ChainVerification",
    "canonical_payload",
    "compute_hash",
    "verify_chain",
    # response schemas
    "AttestationEntryOut",
    "AttestationQueryResult",
    "ChainVerificationOut",
    # append engine + verifier
    "AttestationService",
    # emit seam
    "payload_for_scan",
    # mitigation seam (Surface 1b §8)
    "mitigation_record",
    "append_mitigation",
    # replay
    "replay",
    "ReplayResult",
]
