"""``AttestationService`` — the append engine + chain verifier over Postgres.

The persistence side of the attestation layer (build 03 §B). It owns the *only*
write path into ``attestation_entries`` and keeps the per-org chain consistent:

* **One chain per ``org_id``** (ADR-0006 tenancy). ``seq`` is per-org monotonic;
  the genesis entry (seq 0, ``entry_type="genesis"``, ``prev_hash=GENESIS_PREV``)
  is written lazily on the org's first append.
* **Serialized appends.** ``append`` reads ``MAX(seq)`` + the head ``entry_hash``
  for the org inside ONE ``SELECT … FOR UPDATE`` transaction (the same Postgres-lock
  house pattern as the job queue, ADR-0009/0002), so two concurrent appends can't
  race to the same ``seq``. SQLite (offline tests) ignores the clause and is
  single-threaded, so the invariant still holds there.
* **The hash chain.** Each entry's ``prev_hash`` == the prior entry's
  ``entry_hash`` (genesis → ``GENESIS_PREV``); ``entry_hash`` = ``compute_hash``.
  This is the LINK that ``chain.verify_chain`` enforces — handoff from Wave 1.
* **``corpus_as_of`` is mandatory.** The "as of date D" framing is structural; an
  append without it is refused.
* **Idempotent on ``reproducibility_ref``.** If an entry with the same
  ``reproducibility_ref`` already exists for the org, ``append`` returns it
  unchanged instead of double-appending — so a worker retry can't duplicate a
  scan's attestation.

Mirrors the ``PostgresScanStore`` session discipline: one short-lived session per
call, no transaction held across an await boundary.

Spec: ``docs/v2/build/03_attestation.md`` §B; ADR-0012.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select

from rogue.attestation.chain import (
    GENESIS_PREV,
    ChainVerification,
    compute_hash,
    verify_chain,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from rogue.platform.models import AttestationEntry


def _now() -> datetime:
    return datetime.now(timezone.utc)


# `rogue.platform.models` imports `ENTRY_TYPES` from `attestation.chain`, so importing
# it at this module's top level would close an import cycle (models → attestation.chain
# → attestation/__init__ → service → models). It is resolved once, lazily, on first use.
def _AttestationEntry():
    from rogue.platform.models import AttestationEntry

    return AttestationEntry


def _new_id(prefix: str) -> str:
    from rogue.platform.memory import _new_id as _gen

    return _gen(prefix)


class AttestationService:
    """Append-only writer + verifier for the per-org attestation chain.

    Construct with a SQLAlchemy ``sessionmaker`` (or any zero-arg callable returning
    a ``Session`` usable as a context manager), exactly like ``PostgresScanStore`` /
    ``PostgresJobQueue``.
    """

    def __init__(self, session_factory: "sessionmaker") -> None:
        self._session_factory = session_factory

    # --- internals ----------------------------------------------------------- #

    def _ensure_genesis(self, session: "Session", org_id: str) -> AttestationEntry | None:
        """Return the org's genesis row, writing it lazily (seq 0) if absent.

        Called inside the locked ``append`` transaction. The genesis payload is
        minimal and fixed so the chain root is deterministic per org.
        """
        AttestationEntry = _AttestationEntry()
        existing = session.execute(
            select(AttestationEntry)
            .where(AttestationEntry.org_id == org_id, AttestationEntry.seq == 0)
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        payload = {"entry_type": "genesis", "org_id": org_id}
        now = _now()
        genesis = AttestationEntry(
            entry_id=_new_id("att"),
            org_id=org_id,
            seq=0,
            entry_type="genesis",
            prev_hash=GENESIS_PREV,
            entry_hash=compute_hash(GENESIS_PREV, payload),
            payload=payload,
            reproducibility_ref=None,
            ground_truth_ref=None,
            # Genesis predates any corpus snapshot; pin it to creation time so the
            # NOT-NULL column holds and the root is timestamped.
            corpus_as_of=now,
            created_at=now,
        )
        session.add(genesis)
        session.flush()  # assign within the txn so the next append reads it as head
        return genesis

    def _head_locked(self, session: "Session", org_id: str) -> AttestationEntry | None:
        """The org's highest-``seq`` entry, taken with a row lock (FOR UPDATE).

        On Postgres this serializes concurrent appends for the org; on SQLite the
        clause is a no-op (single-threaded tests). Returns None when the org has no
        chain yet (caller writes genesis first).
        """
        AttestationEntry = _AttestationEntry()
        stmt = (
            select(AttestationEntry)
            .where(AttestationEntry.org_id == org_id)
            .order_by(AttestationEntry.seq.desc())
            .limit(1)
            .with_for_update()
        )
        return session.execute(stmt).scalar_one_or_none()

    # --- public API ---------------------------------------------------------- #

    def append(
        self,
        org_id: str,
        entry_type: str,
        payload: dict,
        *,
        reproducibility_ref: str | None = None,
        ground_truth_ref: str | None = None,
        corpus_as_of: datetime,
    ) -> AttestationEntry:
        """Append one entry to ``org_id``'s chain and return it.

        Serializes on the org's chain head via ``FOR UPDATE``. Writes genesis lazily
        if the org has no chain. Refuses without ``corpus_as_of``. Idempotent on
        ``reproducibility_ref``: an existing entry with the same ref is returned
        unchanged (no double-append on retry).
        """
        if corpus_as_of is None:  # the "as of date D" framing is structural, not cosmetic
            raise ValueError("AttestationService.append requires corpus_as_of (the 'as of date D').")

        AttestationEntry = _AttestationEntry()
        with self._session_factory() as session:
            # Idempotency: a prior append for this reproducibility_ref short-circuits.
            if reproducibility_ref is not None:
                dup = session.execute(
                    select(AttestationEntry).where(
                        AttestationEntry.org_id == org_id,
                        AttestationEntry.reproducibility_ref == reproducibility_ref,
                    )
                ).scalars().first()
                if dup is not None:
                    session.expunge(dup)
                    return dup

            head = self._head_locked(session, org_id)
            if head is None:
                head = self._ensure_genesis(session, org_id)

            prev_hash = head.entry_hash
            seq = head.seq + 1
            entry = AttestationEntry(
                entry_id=_new_id("att"),
                org_id=org_id,
                seq=seq,
                entry_type=entry_type,
                prev_hash=prev_hash,
                entry_hash=compute_hash(prev_hash, payload),
                payload=payload,
                reproducibility_ref=reproducibility_ref,
                ground_truth_ref=ground_truth_ref,
                corpus_as_of=corpus_as_of,
                created_at=_now(),
            )
            session.add(entry)
            session.commit()
            session.refresh(entry)
            session.expunge(entry)
            return entry

    def verify(self, org_id: str) -> ChainVerification:
        """Load the org's chain in ``seq`` order and re-walk it (``chain.verify_chain``)."""
        AttestationEntry = _AttestationEntry()
        with self._session_factory() as session:
            entries = list(
                session.execute(
                    select(AttestationEntry)
                    .where(AttestationEntry.org_id == org_id)
                    .order_by(AttestationEntry.seq.asc())
                ).scalars()
            )
        return verify_chain(entries)

    def head(self, org_id: str) -> AttestationEntry | None:
        """The org's highest-``seq`` entry (no lock), or None when the chain is empty."""
        AttestationEntry = _AttestationEntry()
        with self._session_factory() as session:
            entry = session.execute(
                select(AttestationEntry)
                .where(AttestationEntry.org_id == org_id)
                .order_by(AttestationEntry.seq.desc())
                .limit(1)
            ).scalar_one_or_none()
            if entry is not None:
                session.expunge(entry)
            return entry

    def list_entries(
        self,
        org_id: str,
        *,
        entry_type: str | None = None,
        since_seq: int | None = None,
        limit: int = 50,
    ) -> list[AttestationEntry]:
        """List the org's chain in ``seq`` order, paginated by ``since_seq`` (exclusive)."""
        AttestationEntry = _AttestationEntry()
        with self._session_factory() as session:
            stmt = select(AttestationEntry).where(AttestationEntry.org_id == org_id)
            if entry_type is not None:
                stmt = stmt.where(AttestationEntry.entry_type == entry_type)
            if since_seq is not None:
                stmt = stmt.where(AttestationEntry.seq > since_seq)
            stmt = stmt.order_by(AttestationEntry.seq.asc()).limit(limit)
            entries = list(session.execute(stmt).scalars())
            for e in entries:
                session.expunge(e)
            return entries

    def get_entry(self, org_id: str, entry_id: str) -> AttestationEntry | None:
        """Fetch one entry by id, scoped to ``org_id`` (cross-org → None, no existence leak)."""
        AttestationEntry = _AttestationEntry()
        with self._session_factory() as session:
            entry = session.get(AttestationEntry, entry_id)
            if entry is None or entry.org_id != org_id:
                return None
            session.expunge(entry)
            return entry


__all__ = ["AttestationService"]
