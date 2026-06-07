"""`/v1/attestation` — the queryability surface over the per-org attestation chain (v2 §2.5 #5).

Thin handlers (same discipline as ``api/v1/scans.py``): resolve the tenant via
``require_principal``, call the ``AttestationService``, serialize. Every route is
tenant-scoped — a cross-org ``entry_id`` is a clean 404, never an existence leak.

Endpoints:
  * ``GET /v1/attestation/entries`` — list the org's chain (paginated by ``seq``;
    filters ``entry_type`` / ``since_seq``).
  * ``GET /v1/attestation/entries/{entry_id}`` — one entry + its framing line.
  * ``GET /v1/attestation/verify`` — re-walk the org's chain ("is it intact?").
  * ``GET /v1/attestation/entries/{entry_id}/replay`` — byte-reproducible
    reconstruction of one entry from its stored source ("reconstruct this for me").

Every entry response carries the non-negotiable framing line (threat-informed
assurance, not a safety guarantee, as of ``corpus_as_of``) — surfaced structurally
so a client can never render an entry without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query

from rogue.attestation.emit import framing_line
from rogue.attestation.replay import replay as _replay_entry
from rogue.attestation.schemas import (
    AttestationEntryOut,
    AttestationQueryResult,
    ChainVerificationOut,
)
from rogue.api.v1.deps import (
    get_attestation_service,
    get_scan_store,
    require_principal,
)

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService
    from rogue.platform.interfaces import ScanStore
    from rogue.platform.tenancy import Principal

router = APIRouter(prefix="/v1", tags=["attestation"])


def _envelope(code: str, message: str, **details: object) -> dict:
    err: dict = {"code": code, "message": message}
    if details:
        err["details"] = details
    return {"error": err}


def _to_out(entry) -> AttestationEntryOut:
    """Project an ORM ``AttestationEntry`` into the wire shape, surfacing the framing line."""
    return AttestationEntryOut(
        entry_id=entry.entry_id,
        seq=entry.seq,
        entry_type=entry.entry_type,
        prev_hash=entry.prev_hash,
        entry_hash=entry.entry_hash,
        payload=entry.payload or {},
        reproducibility_ref=entry.reproducibility_ref,
        ground_truth_ref=entry.ground_truth_ref,
        corpus_as_of=entry.corpus_as_of,
        created_at=entry.created_at,
        framing=framing_line(entry.corpus_as_of),
    )


# ---------------------------------------------------------------------------------------------------
# 1. GET /v1/attestation/entries — list the org's chain (paginated by seq).
# ---------------------------------------------------------------------------------------------------
@router.get("/attestation/entries")
async def list_entries(
    principal: "Principal" = Depends(require_principal),
    service: "AttestationService" = Depends(get_attestation_service),
    entry_type: str | None = Query(default=None),
    since_seq: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AttestationQueryResult:
    entries = service.list_entries(
        principal.org_id, entry_type=entry_type, since_seq=since_seq, limit=limit
    )
    out = [_to_out(e) for e in entries]
    # next_seq drives the next page: the last seq we returned, or None when exhausted.
    next_seq = out[-1].seq if len(out) == limit else None
    return AttestationQueryResult(entries=out, count=len(out), next_seq=next_seq)


# ---------------------------------------------------------------------------------------------------
# 2. GET /v1/attestation/verify — re-walk the org's chain.
# ---------------------------------------------------------------------------------------------------
@router.get("/attestation/verify")
async def verify_chain(
    principal: "Principal" = Depends(require_principal),
    service: "AttestationService" = Depends(get_attestation_service),
) -> ChainVerificationOut:
    result = service.verify(principal.org_id)
    return ChainVerificationOut(
        ok=result.ok,
        broken_at_seq=result.broken_at_seq,
        expected=result.expected,
        actual=result.actual,
    )


# ---------------------------------------------------------------------------------------------------
# 3. GET /v1/attestation/entries/{entry_id} — one entry + its framing.
# ---------------------------------------------------------------------------------------------------
@router.get("/attestation/entries/{entry_id}")
async def get_entry(
    entry_id: str,
    principal: "Principal" = Depends(require_principal),
    service: "AttestationService" = Depends(get_attestation_service),
) -> AttestationEntryOut:
    entry = service.get_entry(principal.org_id, entry_id)
    if entry is None:  # missing OR cross-org → clean 404 (no existence leak)
        raise HTTPException(
            status_code=404, detail=_envelope("not_found", f"attestation entry not found: {entry_id}")
        )
    return _to_out(entry)


# ---------------------------------------------------------------------------------------------------
# 4. GET /v1/attestation/entries/{entry_id}/replay — reconstruct + verify the entry's hash.
# ---------------------------------------------------------------------------------------------------
@router.get("/attestation/entries/{entry_id}/replay")
async def replay_entry(
    entry_id: str,
    principal: "Principal" = Depends(require_principal),
    service: "AttestationService" = Depends(get_attestation_service),
    store: "ScanStore" = Depends(get_scan_store),
) -> dict:
    entry = service.get_entry(principal.org_id, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=404, detail=_envelope("not_found", f"attestation entry not found: {entry_id}")
        )

    # Resolve a scan's reproducibility_ref (scan_id) → the persisted report dict, tenant-scoped.
    # Async store calls are awaited up-front so the (sync) replay loader is a pure dict lookup.
    resolved: dict | None = None
    ref = entry.reproducibility_ref
    if ref is not None:
        record = await store.get(ref, org_id=principal.org_id)
        if record is not None and record.report_id is not None:
            resolved = await store.get_report(record.report_id)

    result = _replay_entry(entry, report_loader=lambda _ref: resolved)
    return {
        "entry_id": entry.entry_id,
        "reproducible": result.reproducible,
        "recomputed_hash": result.recomputed_hash,
        "stored_hash": result.stored_hash,
        "drift": list(result.drift),
    }


__all__ = ["router"]
