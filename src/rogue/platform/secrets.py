"""Tenant secret store — encrypt customer target credentials at rest; the queue carries only a handle.

The audit-critical fix: a hosted scan must NOT persist the customer's raw target key into `scan_jobs`.
Instead the API boundary calls `SecretStore.put(raw)` → a `secref_…` handle + Fernet ciphertext in the
`secrets` table; the `ScanSpec` that gets persisted/enqueued carries only `target.api_key_ref` (the
handle). The worker calls `SecretStore.resolve(ref)` just-in-time, holds the raw key in memory for the
scan, and never writes it back. A DB dump of `scan_jobs`/`scan_runs` now leaks nothing usable; a dump of
`secrets` leaks only ciphertext (you'd also need `SECRET_ENCRYPTION_KEY`).

Encryption is Fernet (AES128-CBC + HMAC) with the key from `SECRET_ENCRYPTION_KEY` (a
`Fernet.generate_key()` value). If that env var is unset the store is simply not wired and the platform
falls back to today's raw-passthrough behavior (fine for the local SDK / tests, not for a hosted pilot).
"""

from __future__ import annotations

import abc
import os

from .memory import _new_id

_DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


class SecretStore(abc.ABC):
    """Put a raw secret → opaque `secref_` handle; resolve it back (org-scoped)."""

    @abc.abstractmethod
    def put(self, raw: str, *, org_id: str) -> str: ...

    @abc.abstractmethod
    def resolve(self, secref: str, *, org_id: str) -> str | None: ...

    @abc.abstractmethod
    def delete(self, secref: str) -> None: ...


class InMemorySecretStore(SecretStore):
    """Test/single-process store — keeps the raw secret in-process (no DB), org-scoped on resolve."""

    def __init__(self) -> None:
        self._d: dict[str, tuple[str, str]] = {}

    def put(self, raw: str, *, org_id: str) -> str:
        ref = _new_id("secref")
        self._d[ref] = (org_id, raw)
        return ref

    def resolve(self, secref: str, *, org_id: str) -> str | None:
        v = self._d.get(secref)
        if v is None or v[0] != org_id:
            return None
        return v[1]

    def delete(self, secref: str) -> None:
        self._d.pop(secref, None)


class PostgresSecretStore(SecretStore):
    """Durable store — Fernet ciphertext in the `secrets` table; the raw key only ever exists in memory
    at put/resolve time."""

    def __init__(self, session_factory, fernet) -> None:
        self._sf = session_factory
        self._f = fernet

    def put(self, raw: str, *, org_id: str) -> str:
        from datetime import datetime, timezone

        from .models import Secret

        ref = _new_id("secref")
        ct = self._f.encrypt(raw.encode())
        with self._sf() as s:
            s.add(Secret(secret_id=ref, org_id=org_id, ciphertext=ct, created_at=datetime.now(timezone.utc)))
            s.commit()
        return ref

    def resolve(self, secref: str, *, org_id: str) -> str | None:
        from .models import Secret

        with self._sf() as s:
            row = s.get(Secret, secref)
            if row is None or row.org_id != org_id:  # cross-tenant resolve → nothing
                return None
            return self._f.decrypt(row.ciphertext).decode()

    def delete(self, secref: str) -> None:
        from .models import Secret

        with self._sf() as s:
            row = s.get(Secret, secref)
            if row is not None:
                s.delete(row)
                s.commit()


def build_postgres_secret_store(database_url: str | None = None, encryption_key: str | None = None):
    """Build a `PostgresSecretStore`, or return None if `SECRET_ENCRYPTION_KEY` isn't configured (the
    platform then falls back to raw-passthrough — see module docstring)."""
    key = encryption_key or os.environ.get("SECRET_ENCRYPTION_KEY")
    if not key:
        return None
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    fernet = Fernet(key.encode() if isinstance(key, str) else key)
    url = database_url or os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
    return PostgresSecretStore(sessionmaker(bind=engine), fernet)


__all__ = ["SecretStore", "InMemorySecretStore", "PostgresSecretStore", "build_postgres_secret_store"]
