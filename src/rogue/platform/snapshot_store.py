"""Content-addressed capture store — so a Slack security-channel post links to a stored transcript
pointer (a `snapshot_ref`) instead of inlining the raw blob.

Content-addressed = the ref is derived from the content (`sha256:<hexdigest>`), so identical content
dedups to the same ref and storing it twice is idempotent. The ref is org-scoped on read: a capture
stored under one org is invisible to another (no cross-tenant leak, no existence signal).

Callers pass either `bytes` or `str` (a `str` is encoded utf-8 before hashing/storage).
"""

from __future__ import annotations

import abc
import hashlib
import os

from sqlalchemy import select

from .memory import _new_id

_DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def _as_bytes(content: bytes | str) -> bytes:
    """Normalize caller input: encode a `str` as utf-8; pass `bytes` through."""
    return content.encode("utf-8") if isinstance(content, str) else content


def compute_ref(content: bytes) -> str:
    """The single source of the addressing scheme: `sha256:<hexdigest>` of the content."""
    return "sha256:" + hashlib.sha256(content).hexdigest()


class SnapshotStore(abc.ABC):
    """Put content → content-addressed `snapshot_ref`; get it back (org-scoped)."""

    @abc.abstractmethod
    def put(self, content: bytes | str, *, org_id: str, content_type: str = "transcript") -> str: ...

    @abc.abstractmethod
    def get(self, snapshot_ref: str, *, org_id: str) -> bytes | None: ...


class InMemorySnapshotStore(SnapshotStore):
    """Test/single-process store — keeps the blob in-process (no DB), org-scoped on get."""

    def __init__(self) -> None:
        self._d: dict[tuple[str, str], bytes] = {}

    def put(self, content: bytes | str, *, org_id: str, content_type: str = "transcript") -> str:
        data = _as_bytes(content)
        ref = compute_ref(data)
        self._d.setdefault((org_id, ref), data)  # idempotent / content-addressed
        return ref

    def get(self, snapshot_ref: str, *, org_id: str) -> bytes | None:
        return self._d.get((org_id, snapshot_ref))


class PostgresSnapshotStore(SnapshotStore):
    """Durable store — the blob lives in the `snapshot_captures` table, addressed by `(org_id, ref)`."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def put(self, content: bytes | str, *, org_id: str, content_type: str = "transcript") -> str:
        from datetime import datetime, timezone

        from .models import SnapshotCapture

        data = _as_bytes(content)
        ref = compute_ref(data)
        with self._sf() as s:
            existing = s.execute(
                select(SnapshotCapture).where(
                    SnapshotCapture.org_id == org_id, SnapshotCapture.snapshot_ref == ref
                )
            ).scalar_one_or_none()
            if existing is None:  # content-addressed → existing row already holds identical content
                s.add(
                    SnapshotCapture(
                        id=_new_id("snap"),
                        org_id=org_id,
                        snapshot_ref=ref,
                        content_type=content_type,
                        content=data,
                        created_at=datetime.now(timezone.utc),
                    )
                )
                s.commit()
        return ref

    def get(self, snapshot_ref: str, *, org_id: str) -> bytes | None:
        from .models import SnapshotCapture

        with self._sf() as s:
            row = s.execute(
                select(SnapshotCapture).where(
                    SnapshotCapture.org_id == org_id, SnapshotCapture.snapshot_ref == snapshot_ref
                )
            ).scalar_one_or_none()
            return bytes(row.content) if row is not None else None


def build_postgres_snapshot_store(database_url: str | None = None) -> PostgresSnapshotStore:
    """Build a `PostgresSnapshotStore` bound to a pooled engine (snapshots aren't secrets — no
    `secret_store` needed)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = database_url or os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
    return PostgresSnapshotStore(sessionmaker(bind=engine))


__all__ = [
    "compute_ref",
    "SnapshotStore",
    "InMemorySnapshotStore",
    "PostgresSnapshotStore",
    "build_postgres_snapshot_store",
]
