"""Offline tests for the `seed_org` onboarding core — in-memory SQLite, no real/prod DB.

Creates only the three platform tables we touch and drives `seed_org` directly. Verifies the
secret-handling contract (raw key shaped `rk_live_`, only its sha256 hash stored), the
find-or-create org behavior, the `force` reissue path, and scope defaulting.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from rogue.db.models import Base
from rogue.platform import tenancy
from rogue.platform.models import (
    ApiKey,
    Membership,
    Organization,
    Project,
    Report,
    ScanJob,
    ScanRun,
    User,
)

# All platform tables — create the full set so FK targets (e.g. api_keys -> projects) exist when
# foreign-key enforcement is on.
_PLATFORM_TABLES = [
    Organization.__table__, User.__table__, Membership.__table__, Project.__table__,
    ApiKey.__table__, ScanRun.__table__, ScanJob.__table__, Report.__table__,
]

# Load the script by path (scripts/ is not an importable package).
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ops" / "seed_org.py"
_spec = importlib.util.spec_from_file_location("seed_org", _SCRIPT)
seed_org_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed_org_mod)
seed_org = seed_org_mod.seed_org


@pytest.fixture()
def session():
    engine = create_engine("sqlite://")
    # Enforce foreign keys on SQLite (off by default) so this suite catches FK-ordering bugs the way
    # Postgres/Neon does — e.g. inserting an api_keys row before its organizations row.
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):  # pragma: no cover - trivial pragma
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=_PLATFORM_TABLES)
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        yield sess
    finally:
        sess.close()
        engine.dispose()


def test_creates_one_org_and_one_key(session):
    org_id, raw_key = seed_org(session, name="Acme")

    orgs = session.execute(select(Organization)).scalars().all()
    keys = session.execute(select(ApiKey)).scalars().all()
    assert len(orgs) == 1
    assert len(keys) == 1
    assert orgs[0].org_id == org_id
    assert orgs[0].name == "Acme"
    assert keys[0].org_id == org_id


def test_only_hash_is_stored_never_raw(session):
    _, raw_key = seed_org(session, name="Acme")

    key = session.execute(select(ApiKey)).scalar_one()
    # The stored hash must match the raw, and the raw itself is nowhere in the row.
    assert key.key_hash == tenancy.hash_key(raw_key)
    assert key.key_hash != raw_key
    assert raw_key not in (key.prefix, key.name)


def test_raw_key_is_live_shaped_and_prefix_stored(session):
    _, raw_key = seed_org(session, name="Acme")

    key = session.execute(select(ApiKey)).scalar_one()
    assert raw_key.startswith("rk_live_")
    assert key.prefix == raw_key[:16]
    assert key.prefix.startswith("rk_live_")


def test_default_scopes(session):
    seed_org(session, name="Acme")
    key = session.execute(select(ApiKey)).scalar_one()
    assert key.scopes == ["scan:read", "scan:write"]


def test_custom_scopes(session):
    seed_org(session, name="Acme", scopes=["scan:read", "admin"])
    key = session.execute(select(ApiKey)).scalar_one()
    assert key.scopes == ["scan:read", "admin"]


def test_optional_user_created(session):
    seed_org(session, name="Acme", email="ops@acme.com")
    users = session.execute(select(User)).scalars().all()
    assert len(users) == 1
    assert users[0].email == "ops@acme.com"

    # No email -> no user row.
    seed_org(session, name="Beta")
    users = session.execute(select(User)).scalars().all()
    assert len(users) == 1


def test_rerun_same_name_does_not_duplicate_org(session):
    org_id_1, _ = seed_org(session, name="Acme")
    org_id_2, raw_key_2 = seed_org(session, name="Acme")

    orgs = session.execute(select(Organization)).scalars().all()
    keys = session.execute(select(ApiKey)).scalars().all()
    assert len(orgs) == 1
    assert org_id_1 == org_id_2
    # A fresh key is still issued each run.
    assert len(keys) == 2


def test_force_reuses_org_and_issues_fresh_key(session):
    org_id_1, raw_key_1 = seed_org(session, name="Acme")
    org_id_2, raw_key_2 = seed_org(session, name="Acme", force=True)

    orgs = session.execute(select(Organization)).scalars().all()
    keys = session.execute(select(ApiKey)).scalars().all()
    assert len(orgs) == 1
    assert org_id_1 == org_id_2
    assert len(keys) == 2
    assert raw_key_1 != raw_key_2
    stored_hashes = {k.key_hash for k in keys}
    assert tenancy.hash_key(raw_key_1) in stored_hashes
    assert tenancy.hash_key(raw_key_2) in stored_hashes
