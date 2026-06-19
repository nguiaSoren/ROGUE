"""Persistent cross-run URL skip-cache (ROGUE_PLAN.md §11.7).

The §11.6 bandit decides *which source/query* to spend on; this cache decides
*which individual URLs not to re-crawl*. It wraps the ``fetch_cache`` table so a
daily harvest can:

  - **Tier B (pre-fetch)** — skip the Bright Data fetch when a source's cheap
    freshness ``version_token`` (git blob SHA, arxiv updated-date, reddit
    ``created:num_comments``, HTTP ETag) is unchanged since last run.
  - **Tier A (pre-extraction, universal)** — skip the LLM extraction when the
    fetched body's ``content_hash`` (``RawDocument.archive_hash``) is unchanged.
  - record every processed URL (including zero-yield ones — the worst to
    re-crawl) so the ledger grows across runs.

Position vs. the existing dedup: the pgvector cosine gate in
``dedupe/embeddings.py`` runs AFTER the fetch + extraction are already paid for —
it stops a duplicate from being *stored*, not from being *spent on*. This cache
prunes *before* those costs. The two are complementary.

Session-backed. The caller owns the transaction — ``record`` issues a
``session.merge`` but does not commit (matches the harvest's per-doc commit
loop). The in-memory snapshot is loaded once at construction so per-URL checks
are dict lookups, not round-trips; ``record`` keeps the snapshot coherent so a
within-run re-encounter of the same URL is consistent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, NamedTuple, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from rogue.db.models import FetchCache as FetchCacheORM

__all__ = ["CachedVersion", "FetchCache", "load_snapshot"]


class CachedVersion(NamedTuple):
    """The two freshness signals we compare against, per cached URL."""

    version_token: Optional[str]
    content_hash: Optional[str]


def load_snapshot(
    session: Session, source_type: Optional[str] = None
) -> dict[str, CachedVersion]:
    """Load ``{url: CachedVersion}`` from the ledger (optionally one source)."""
    stmt = select(
        FetchCacheORM.url,
        FetchCacheORM.version_token,
        FetchCacheORM.content_hash,
    )
    if source_type is not None:
        stmt = stmt.where(FetchCacheORM.source_type == source_type)
    return {
        url: CachedVersion(version_token=vt, content_hash=ch)
        for url, vt, ch in session.execute(stmt)
    }


class FetchCache:
    """In-memory snapshot of the ``fetch_cache`` ledger + skip/record helpers.

    Construct with a live ``session`` to load from the DB, or with an explicit
    ``snapshot`` dict for offline unit tests (no DB needed for the skip logic).
    ``record`` requires a ``session``.
    """

    def __init__(
        self,
        session: Optional[Session] = None,
        source_type: Optional[str] = None,
        *,
        snapshot: Optional[Mapping[str, CachedVersion]] = None,
    ) -> None:
        self.session = session
        if snapshot is not None:
            self._snapshot: dict[str, CachedVersion] = dict(snapshot)
        elif session is not None:
            self._snapshot = load_snapshot(session, source_type)
        else:
            self._snapshot = {}

    def __len__(self) -> int:
        return len(self._snapshot)

    def should_skip_fetch(self, url: str, version_token: Optional[str]) -> bool:
        """Tier B — skip the Bright Data fetch when the cheap pre-fetch token
        matches a prior run. A ``None`` token means "no freshness info" → never
        skip (we can't prove it's unchanged)."""
        if version_token is None:
            return False
        row = self._snapshot.get(url)
        return row is not None and row.version_token == version_token

    def should_skip_extract(self, url: str, content_hash: Optional[str]) -> bool:
        """Tier A — skip the LLM extraction when the fetched body is byte-identical
        to what we last extracted. ``content_hash`` is ``RawDocument.archive_hash``."""
        if content_hash is None:
            return False
        row = self._snapshot.get(url)
        return row is not None and row.content_hash == content_hash

    def record(
        self,
        url: str,
        *,
        source_type: str,
        content_hash: Optional[str] = None,
        version_token: Optional[str] = None,
        last_status: str = "ok",
        n_primitives_yielded: int = 0,
    ) -> None:
        """Upsert one URL into the ledger (and the in-memory snapshot). Bumps
        ``last_fetched_at`` to now. Caller commits."""
        if self.session is None:
            raise RuntimeError("FetchCache.record requires a session")
        self.session.merge(
            FetchCacheORM(
                url=url,
                source_type=source_type,
                version_token=version_token,
                content_hash=content_hash,
                last_fetched_at=datetime.now(timezone.utc),
                last_status=last_status,
                n_primitives_yielded=n_primitives_yielded,
            )
        )
        self._snapshot[url] = CachedVersion(
            version_token=version_token, content_hash=content_hash
        )
