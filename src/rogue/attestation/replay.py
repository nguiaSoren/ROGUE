"""Replay: byte-reproducible reconstruction of an attestation entry.

The honest "replayable" property (v2 §2.5 #4): given an entry's
``reproducibility_ref``, re-read the source the scan persisted, recompute the
payload via ``emit.payload_for_scan``, recompute ``entry_hash`` via
``chain.compute_hash(entry.prev_hash, payload)``, and assert it equals the stored
``entry_hash``.

**Reconstruction-from-stored, not re-execution** (ADR-0012). NO model call, NO
judge call — re-firing the model is non-deterministic and out of scope. Replay is
pure reconstruction from the stored inputs the worker had at decision time (the
persisted hosted-scan report).

This is *two* tamper checks working together: the chain catches edits to the entry
(``verify_chain``); replay catches edits to the SOURCE rows (if the stored report
is altered, the recomputed hash no longer matches and ``reproducible`` is False).

The source is resolved via an injected ``report_loader(reproducibility_ref) ->
dict | None`` so this module imports no DB shape and is testable offline; the API
wires it to the platform store's ``get_report``-by-scan resolver.

Spec: ``docs/v2/build/03_attestation.md`` §D.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from rogue.attestation import emit
from rogue.attestation.chain import compute_hash

__all__ = ["ReplayResult", "replay"]


@dataclass(frozen=True)
class ReplayResult:
    """The auditor's "reconstruct this for me" answer.

    ``reproducible`` is True iff the payload re-derived from the stored source
    hashes to the entry's stored ``entry_hash``. ``drift`` enumerates why it
    didn't (missing source, hash mismatch) when it's False.
    """

    reproducible: bool
    recomputed_hash: str | None = None
    stored_hash: str | None = None
    drift: tuple[str, ...] = ()


def _entry_field(entry, name):
    """Read ``name`` off an ORM entry or a dict (same dual-shape tolerance as chain)."""
    if isinstance(entry, dict):
        return entry.get(name)
    return getattr(entry, name, None)


def replay(entry, *, report_loader: Callable[[str], dict | None]) -> ReplayResult:
    """Reconstruct ``entry`` from its source and verify the hash byte-for-byte.

    ``entry`` is an ``AttestationEntry`` ORM row (or a dict with the same fields).
    ``report_loader`` resolves the entry's ``reproducibility_ref`` (the scan_id) to
    the persisted report dict the worker stored. Returns a :class:`ReplayResult`.
    """
    stored_hash = _entry_field(entry, "entry_hash")
    prev_hash = _entry_field(entry, "prev_hash")
    ref = _entry_field(entry, "reproducibility_ref")
    corpus_as_of = _entry_field(entry, "corpus_as_of")

    drift: list[str] = []

    if ref is None:
        return ReplayResult(
            reproducible=False,
            stored_hash=stored_hash,
            drift=("entry has no reproducibility_ref to reconstruct from",),
        )

    report = report_loader(ref)
    if report is None:
        return ReplayResult(
            reproducible=False,
            stored_hash=stored_hash,
            drift=(f"source for reproducibility_ref={ref!r} not found",),
        )

    # corpus_as_of must be a datetime for emit; ORM gives a datetime, a dict may give
    # an iso string — normalize so the recomputed framing matches the original byte-for-byte.
    if isinstance(corpus_as_of, str):
        corpus_as_of = datetime.fromisoformat(corpus_as_of)

    payload = emit.payload_for_scan(report, {"scan_id": ref}, corpus_as_of=corpus_as_of)
    recomputed_hash = compute_hash(prev_hash, payload)

    if recomputed_hash != stored_hash:
        drift.append(
            "recomputed entry_hash does not match stored entry_hash "
            "(source rows changed since the entry was written, or a non-determinism bug)"
        )

    return ReplayResult(
        reproducible=not drift,
        recomputed_hash=recomputed_hash,
        stored_hash=stored_hash,
        drift=tuple(drift),
    )
