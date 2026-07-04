"""Tests for the §11.7 persistent fetch-cache (skip-cache).

The skip decisions (Tier A content-hash, Tier B version-token) are pure dict
lookups, so they unit-test without a DB. The migration up/down round-trip is
exercised by test_smoke's alembic test (head now includes 0011). The DB upsert
path (``record`` + ``load_snapshot``) gets a self-contained round-trip test that
skips cleanly when Postgres is down.
"""

import os
import socket

import pytest

from rogue.harvest.fetch_cache import CachedVersion, FetchCache, load_snapshot

DEFAULT_TEST_DB = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _cache(snapshot: dict) -> FetchCache:
    """Build an offline FetchCache from an explicit snapshot (no DB)."""
    return FetchCache(snapshot=snapshot)


# --------------------------------------------------------------------------- #
# Tier A — should_skip_extract (content hash)
# --------------------------------------------------------------------------- #


def test_skip_extract_when_content_unchanged() -> None:
    fc = _cache({"u1": CachedVersion(version_token=None, content_hash="abc")})
    assert fc.should_skip_extract("u1", "abc") is True


def test_no_skip_extract_when_content_changed() -> None:
    fc = _cache({"u1": CachedVersion(None, "abc")})
    assert fc.should_skip_extract("u1", "def") is False


def test_no_skip_extract_for_new_url() -> None:
    assert _cache({}).should_skip_extract("u-new", "abc") is False


def test_no_skip_extract_when_hash_is_none() -> None:
    # No content hash means we can't prove it's unchanged → never skip.
    fc = _cache({"u1": CachedVersion(None, "abc")})
    assert fc.should_skip_extract("u1", None) is False


# --------------------------------------------------------------------------- #
# Tier A′ — should_skip_extract_url (URL-level, single-technique sources)
# --------------------------------------------------------------------------- #


def test_skip_extract_url_for_known_arxiv() -> None:
    # We already have a primitive from this arxiv URL; a re-harvest only
    # re-derives it (paraphrase-drift dup), so skip regardless of byte hash.
    fc = FetchCache(snapshot={}, extracted_urls={"https://arxiv.org/abs/2510.05699"})
    assert fc.should_skip_extract_url("https://arxiv.org/abs/2510.05699", "arxiv") is True


def test_no_skip_extract_url_for_new_arxiv() -> None:
    fc = FetchCache(snapshot={}, extracted_urls={"https://arxiv.org/abs/2510.05699"})
    assert fc.should_skip_extract_url("https://arxiv.org/abs/2605.99999", "arxiv") is False


def test_no_skip_extract_url_for_multi_artifact_source() -> None:
    # A github jailbreak dump legitimately yields many primitives per URL and can
    # grow across fetches — URL-level skip must NOT fire for it even if seen.
    fc = FetchCache(snapshot={}, extracted_urls={"https://raw.githubusercontent.com/x/JB.mkd"})
    assert fc.should_skip_extract_url("https://raw.githubusercontent.com/x/JB.mkd", "github") is False


def test_no_skip_extract_url_when_unset() -> None:
    assert FetchCache(snapshot={}).should_skip_extract_url("https://arxiv.org/abs/1", "arxiv") is False


# --------------------------------------------------------------------------- #
# Tier B — should_skip_fetch (version token)
# --------------------------------------------------------------------------- #


def test_skip_fetch_when_token_unchanged() -> None:
    fc = _cache({"u1": CachedVersion(version_token="sha1", content_hash=None)})
    assert fc.should_skip_fetch("u1", "sha1") is True


def test_no_skip_fetch_when_token_changed() -> None:
    fc = _cache({"u1": CachedVersion("sha1", None)})
    assert fc.should_skip_fetch("u1", "sha2") is False


def test_no_skip_fetch_for_new_url() -> None:
    assert _cache({}).should_skip_fetch("u-new", "sha1") is False


def test_no_skip_fetch_when_token_is_none() -> None:
    # A None token means the source gave no freshness signal → never skip.
    fc = _cache({"u1": CachedVersion("sha1", None)})
    assert fc.should_skip_fetch("u1", None) is False


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #


def test_empty_cache_len() -> None:
    assert len(_cache({})) == 0


def test_record_without_session_raises() -> None:
    with pytest.raises(RuntimeError):
        _cache({}).record("u", source_type="github")


class _Doc:
    """Minimal RawDocument stand-in for the Tier-A split simulation."""

    def __init__(self, url: str, archive_hash: str) -> None:
        self.url = url
        self.archive_hash = archive_hash


def test_tier_a_gate_splits_docs() -> None:
    # u1 unchanged → skip; u2 changed → extract; u3 new → extract.
    fc = _cache(
        {
            "https://x/1": CachedVersion(None, "h1"),
            "https://x/2": CachedVersion(None, "h2-old"),
        }
    )
    docs = [
        _Doc("https://x/1", "h1"),
        _Doc("https://x/2", "h2-new"),
        _Doc("https://x/3", "h3"),
    ]
    to_extract = [
        d for d in docs if not fc.should_skip_extract(str(d.url), d.archive_hash)
    ]
    skipped = [
        d for d in docs if fc.should_skip_extract(str(d.url), d.archive_hash)
    ]
    assert [d.url for d in to_extract] == ["https://x/2", "https://x/3"]
    assert [d.url for d in skipped] == ["https://x/1"]


# --------------------------------------------------------------------------- #
# DB round-trip (skips cleanly when Postgres is down)
# --------------------------------------------------------------------------- #


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import FetchCache as FetchCacheORM

    url = os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DB)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable at {url}: {exc} — run `docker compose up -d`")

    # Self-contained: create just this table so the test is independent of
    # migration state. Track whether WE created it so teardown only drops a
    # table we own — never one left by alembic/another fixture (dropping that
    # would pollute the shared rogue_test DB and break the alembic round-trip).
    created_here = not inspect(engine).has_table("fetch_cache")
    FetchCacheORM.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    def _clean() -> None:
        session.query(FetchCacheORM).filter(
            FetchCacheORM.url.like("test://%")
        ).delete(synchronize_session=False)
        session.commit()

    _clean()
    yield session
    _clean()
    session.close()
    if created_here:
        FetchCacheORM.__table__.drop(bind=engine, checkfirst=True)
    engine.dispose()


def test_record_and_load_roundtrip(db_session) -> None:
    fc = FetchCache(db_session)
    fc.record(
        "test://a",
        source_type="github",
        content_hash="h1",
        version_token="sha1",
        n_primitives_yielded=1,
    )
    db_session.commit()

    snap = load_snapshot(db_session)
    assert snap["test://a"] == CachedVersion(version_token="sha1", content_hash="h1")

    # A fresh cache loaded from the DB now skips both tiers for this URL.
    fresh = FetchCache(db_session)
    assert fresh.should_skip_extract("test://a", "h1") is True
    assert fresh.should_skip_fetch("test://a", "sha1") is True


def test_record_upserts_on_repeat(db_session) -> None:
    fc = FetchCache(db_session)
    fc.record("test://b", source_type="arxiv", content_hash="old")
    db_session.commit()
    fc.record("test://b", source_type="arxiv", content_hash="new")
    db_session.commit()

    snap = load_snapshot(db_session)
    assert snap["test://b"].content_hash == "new"
