"""Multi-tenant auth + RBAC primitives — the seam every `/v1` surface authenticates through.

This module owns three concerns, all DB-free at import time:

1. API-key minting/hashing — `generate_api_key` / `hash_key`. We store only the sha256 of the raw
   key (plus a short display prefix); the raw `rk_{env}_...` value is shown to the customer exactly
   once at creation time and never persisted.
2. The `Principal` (an authenticated caller's tenant identity) plus RBAC helpers — `role_at_least`
   for the owner>admin>member>viewer ladder and `has_scope` for scope checks.
3. `resolve_principal_from_token` — turns a bearer token into a `Principal`. The production path
   hashes the token and looks up a non-revoked `ApiKey` row; a test-only resolver hook lets the
   suite (and `deps.require_principal`) resolve tokens with no DB at all.

Tenant isolation discipline: every tenant-scoped query MUST be filtered by the principal's
`org_id` (and `project_id` when present). `query_scope` is the one helper that applies it — see
its docstring for the `WHERE org_id=:org` pattern. There is no implicit cross-org access.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass, field
from typing import Callable

# --------------------------------------------------------------------------------------------------
# Roles & scopes
# --------------------------------------------------------------------------------------------------

# Ordered most- to least-privileged. The index in this tuple IS the rank, so `role_at_least` is a
# simple index comparison. `owner` and `admin` are the "privileged" roles that implicitly hold every
# scope (see `has_scope`).
ROLES: tuple[str, ...] = ("owner", "admin", "member", "viewer")

# Roles that implicitly satisfy any scope check (they don't need scopes enumerated on the key).
_PRIVILEGED_ROLES: frozenset[str] = frozenset({"owner", "admin"})

# Canonical scope vocabulary. Scopes gate individual capabilities for member/viewer keys; owner and
# admin bypass the list entirely.
SCOPES: tuple[str, ...] = ("scan:read", "scan:write", "admin")

# rank-by-role lookup: lower number == more privilege.
_ROLE_RANK: dict[str, int] = {role: i for i, role in enumerate(ROLES)}


def role_at_least(role: str, minimum: str) -> bool:
    """True iff `role` is at least as privileged as `minimum` on the owner>admin>member>viewer ladder.

    Unknown roles are treated as below everything (never privileged enough), so a malformed key can
    never clear a gate.
    """
    if role not in _ROLE_RANK or minimum not in _ROLE_RANK:
        return False
    return _ROLE_RANK[role] <= _ROLE_RANK[minimum]


# --------------------------------------------------------------------------------------------------
# Principal
# --------------------------------------------------------------------------------------------------


@dataclass
class Principal:
    """An authenticated caller's tenant identity, derived from the presented API key.

    `org_id` is always present and is the isolation boundary for every tenant-scoped query.
    `project_id` narrows to a single project when the key is project-scoped (None == org-wide).
    `role` is one of `ROLES`; `scopes` is the explicit scope grant on the key (ignored for the
    privileged owner/admin roles, which hold all scopes). `key_id` identifies the issuing key row.
    """

    org_id: str
    role: str
    key_id: str
    project_id: str | None = None
    scopes: list[str] = field(default_factory=list)


def has_scope(principal: Principal, scope: str) -> bool:
    """True iff `principal` may exercise `scope`.

    Owner/admin hold every scope implicitly; all other roles must carry the scope on their key.
    """
    if principal.role in _PRIVILEGED_ROLES:
        return True
    return scope in principal.scopes


# --------------------------------------------------------------------------------------------------
# API-key minting & hashing
# --------------------------------------------------------------------------------------------------


def hash_key(raw: str) -> str:
    """sha256-hex of a raw API key. The only form we ever persist or look up by."""
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key(env: str = "live") -> tuple[str, str, str]:
    """Mint a new API key.

    Returns `(raw_key, key_hash, prefix)`:
      * `raw_key`  — `rk_{env}_{token}`, shown to the customer exactly once and NEVER stored.
      * `key_hash` — `sha256(raw_key)` hex; this is what `ApiKey.key_hash` holds and we look up by.
      * `prefix`   — `raw_key[:16]`, a display-only fragment (`ApiKey.prefix`) so the UI can show
                     "rk_live_xxxx…" without retaining the secret.
    """
    raw_key = f"rk_{env}_{secrets.token_urlsafe(32)}"
    key_hash = hash_key(raw_key)
    prefix = raw_key[:16]
    return raw_key, key_hash, prefix


# --------------------------------------------------------------------------------------------------
# Principal resolution (test-hook + lazy DB path)
# --------------------------------------------------------------------------------------------------

# Injectable resolver: a callable mapping a *raw* token -> Principal | None. When set, it is
# consulted before the DB so tests (and offline runs) can authenticate with no database. Production
# leaves this None and falls through to the `ApiKey` lookup.
_RESOLVER: Callable[[str], Principal | None] | None = None


def set_test_resolver(fn: Callable[[str], Principal | None] | None) -> None:
    """Install (or clear, with None) the in-memory token->Principal resolver hook.

    Intended for tests and offline development. `resolve_principal_from_token` consults this hook
    first; only when it is unset (or returns None) does the DB lookup run.
    """
    global _RESOLVER
    _RESOLVER = fn


def resolve_principal_from_token(
    token: str, *, session_factory: Callable[[], object] | None = None
) -> Principal | None:
    """Resolve a bearer token to a `Principal`, or None if unknown/revoked.

    Resolution order:
      1. The test resolver hook (`set_test_resolver`), if installed and it returns a Principal.
      2. The DB path: hash the token, look up a non-revoked `ApiKey` row by `key_hash`, and build a
         `Principal` from it. The session is created lazily from `session_factory` (if given) or
         from a fresh engine on `os.environ["DATABASE_URL"]` — so importing this module never opens
         a connection.

    The empty token never resolves.
    """
    if not token:
        return None

    # 1) Test/offline hook first — lets the API authenticate with no DB behind it.
    if _RESOLVER is not None:
        principal = _RESOLVER(token)
        if principal is not None:
            return principal

    # 2) DB path — imported lazily so the module (and the hook-only path) need no DB/driver.
    key_hash = hash_key(token)
    session, engine = _build_session(session_factory)
    if session is None:
        return None
    try:
        from sqlalchemy import select

        from rogue.platform.models import ApiKey

        row = session.execute(select(ApiKey).where(ApiKey.key_hash == key_hash)).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        return Principal(
            org_id=row.org_id,
            project_id=row.project_id,
            role=_role_for_key(row),
            scopes=list(row.scopes or []),
            key_id=row.key_id,
        )
    finally:
        session.close()
        if engine is not None:
            engine.dispose()


def _build_session(session_factory: Callable[[], object] | None):
    """Lazily build a Session for the DB path.

    With an injected `session_factory` we just call it (the caller owns engine lifecycle, so we
    return `engine=None` and don't dispose). Otherwise we spin up a short-lived engine on
    `DATABASE_URL` and hand back both so the caller can dispose it. Returns `(None, None)` if no
    `DATABASE_URL` is configured (the hook-only deployments).
    """
    if session_factory is not None:
        return session_factory(), None

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return None, None

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(database_url)
    return sessionmaker(bind=engine)(), engine


def _role_for_key(row: object) -> str:
    """Role carried by an API key row.

    The `api_keys` table has no role column today; a key inherits "member" by default and relies on
    its `scopes` grant for capability. (Role-bearing keys arrive with the membership join; until
    then this keeps `has_scope` honest — non-privileged unless scopes say otherwise.)
    """
    return getattr(row, "role", None) or "member"


# --------------------------------------------------------------------------------------------------
# Tenant-scoping discipline
# --------------------------------------------------------------------------------------------------


def query_scope(stmt, principal: Principal):
    """Apply the principal's tenant filter to a SQLAlchemy `select(...)`.

    Every tenant-scoped query goes through here so isolation is one decision, not N. The discipline
    it enforces is, in SQL terms::

        WHERE org_id = :org [AND project_id = :project]

    Concretely it appends `.where(entity.org_id == principal.org_id)` and, when the principal is
    project-scoped, `.where(entity.project_id == principal.project_id)`, using the statement's first
    FROM entity. Selecting an entity that has no `org_id` column is a programming error and raises.
    """
    entity = stmt.get_final_froms()[0]
    org_col = getattr(entity.c, "org_id", None)
    if org_col is None:
        raise ValueError("query_scope: target has no org_id column — it is not tenant-scoped")
    stmt = stmt.where(org_col == principal.org_id)
    project_col = getattr(entity.c, "project_id", None)
    if principal.project_id is not None and project_col is not None:
        stmt = stmt.where(project_col == principal.project_id)
    return stmt


__all__ = [
    "ROLES",
    "SCOPES",
    "Principal",
    "role_at_least",
    "has_scope",
    "hash_key",
    "generate_api_key",
    "resolve_principal_from_token",
    "set_test_resolver",
    "query_scope",
]
