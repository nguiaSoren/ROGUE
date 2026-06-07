"""Attestation chain primitives — the pure, DB-free auditable core.

This module is the mathematical heart of the signed-attestation layer
(`docs/v2/build/03_attestation.md` §B, unified spec §2.5): the tamper-evident
hash chain every surface emits. It deliberately imports **nothing** from the
database / platform layers — like ``reproduce/calibration_sampling.py`` pins a
hash recipe for reproducibility, this pins the chain's recipe so verification is
testable offline and re-derivable on any machine.

The chain
=========
Each entry hashes the previous entry's hash together with the canonical JSON of
its own payload::

    entry_hash = sha256(prev_hash || canonical_json(payload)).hexdigest()

The genesis entry uses ``prev_hash = GENESIS_PREV`` (64 zeros). ``seq`` is a
per-org monotonic integer (the genesis entry is seq 0). The chain's
verifiability depends on **byte-identical re-serialization** of the payload, so
:func:`canonical_payload` is pinned exactly and MUST NOT be "improved" — any
change to the JSON encoding silently invalidates every previously written hash.

Append-engine, persistence, and replay (``AttestationService`` / ``emit`` /
``replay``) are added by the integration wave; this file is only the primitives.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ENTRY_TYPES",
    "GENESIS_PREV",
    "ChainVerification",
    "canonical_payload",
    "compute_hash",
    "verify_chain",
]

# The single source of the entry-type vocabulary. The ORM CHECK constraint and
# the migration derive their allowed values from this tuple (no duplication, per
# the CLAUDE.md schema convention). "genesis" is first because it is seq 0.
ENTRY_TYPES: tuple[str, ...] = ("genesis", "scan", "decision", "mitigation", "promotion")

# prev_hash of the genesis entry: 64 zero hex chars (a sha256 width of zeros).
GENESIS_PREV: str = "0" * 64


@dataclass(frozen=True)
class ChainVerification:
    """Result of re-walking a chain.

    ``ok`` is True iff every entry's recomputed hash matched its stored
    ``entry_hash`` (and the prev-hash links were consistent). On the first
    break, ``broken_at_seq`` is the ``seq`` of the offending entry and
    ``expected`` / ``actual`` are the recomputed vs. stored hashes for that
    entry (both ``None`` when ``ok``).
    """

    ok: bool
    broken_at_seq: int | None = None
    expected: str | None = None
    actual: str | None = None


def canonical_payload(payload: dict) -> str:
    """Serialize ``payload`` to the chain's canonical JSON form.

    Pinned EXACTLY — the chain's verifiability depends on byte-identical
    re-serialization across calls, processes, and machines:

    * ``sort_keys=True`` — key order can't change the bytes.
    * ``separators=(",", ":")`` — no incidental whitespace.
    * ``ensure_ascii=False`` — Unicode is emitted as UTF-8 text, not escaped,
      so the byte form is stable regardless of the source string's escaping.

    Do not "improve" this. Any change to the encoding invalidates every hash
    already written to the chain.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, payload: dict) -> str:
    """Compute an entry hash: ``sha256(prev_hash || canonical_json(payload))``.

    ``prev_hash`` is the previous entry's ``entry_hash`` (or :data:`GENESIS_PREV`
    for the genesis entry). Returns the hex digest.
    """
    return hashlib.sha256((prev_hash + canonical_payload(payload)).encode()).hexdigest()


def _field(entry: Any, name: str) -> Any:
    """Read ``name`` from an entry that may be a dict or an attribute object.

    Entries are accepted as either plain dicts (``{"seq", "prev_hash",
    "payload", "entry_hash"}``) or objects exposing the same names as
    attributes (e.g. the ORM ``AttestationEntry`` added by the integration
    wave). This keeps the verifier usable both in offline tests and against
    live rows without importing either shape.
    """
    if isinstance(entry, dict):
        return entry[name]
    return getattr(entry, name)


def verify_chain(entries: list) -> ChainVerification:
    """Re-walk ``entries`` and recompute every hash, returning the first break.

    ``entries`` is a list of chain entries (dicts or attribute objects), each
    carrying ``seq``, ``prev_hash``, ``payload``, and ``entry_hash``. They are
    sorted by ``seq`` here, so input order does not matter.

    The walk checks two invariants per entry:

    1. **Link** — each entry's ``prev_hash`` equals the prior entry's
       ``entry_hash`` (genesis must link to :data:`GENESIS_PREV`).
    2. **Content** — ``compute_hash(prev_hash, payload)`` equals the stored
       ``entry_hash`` (catches any edit to the payload).

    On the first failing entry, returns ``ok=False`` with that entry's ``seq``
    and the ``expected`` (recomputed) vs ``actual`` (stored) hash. An empty
    chain is vacuously ``ok``.
    """
    ordered = sorted(entries, key=lambda e: _field(e, "seq"))

    prior_hash = GENESIS_PREV
    for entry in ordered:
        seq = _field(entry, "seq")
        prev_hash = _field(entry, "prev_hash")
        payload = _field(entry, "payload")
        stored = _field(entry, "entry_hash")

        # Invariant 1: the link to the prior entry. A broken link is reported
        # against the entry that should have pointed at the prior hash, with
        # the recomputed hash for that entry as `expected`.
        if prev_hash != prior_hash:
            return ChainVerification(
                ok=False,
                broken_at_seq=seq,
                expected=compute_hash(prior_hash, payload),
                actual=stored,
            )

        # Invariant 2: the content hash, using the entry's own prev_hash (which
        # equals prior_hash here) so a payload edit is caught.
        recomputed = compute_hash(prev_hash, payload)
        if recomputed != stored:
            return ChainVerification(
                ok=False,
                broken_at_seq=seq,
                expected=recomputed,
                actual=stored,
            )

        prior_hash = stored

    return ChainVerification(ok=True)
