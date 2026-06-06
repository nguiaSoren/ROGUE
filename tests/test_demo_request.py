"""Tests for POST /api/demo-request — the marketing-site lead-capture route.

Three cases per the §-build brief:
  (a) a valid POST returns 201 and persists a row,
  (b) an invalid email returns 422,
  (c) the optional fields omitted still works.

Email-validation cases (b) need no DB — FastAPI rejects at the Pydantic layer
before the dependency runs. The persistence cases (a, c) hit a live Postgres via
the same `live_engine`-style skip guard used in `tests/test_smoke.py`, so they
`pytest.skip` cleanly when Docker/DB is down.
"""

from __future__ import annotations

import os
import socket

import pytest
from fastapi.testclient import TestClient

from rogue.api.main import app, get_session
from rogue.db.models import DemoRequest

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


@pytest.fixture
def client():
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def live_engine():
    """Connected engine with the demo_requests table ensured, or skip cleanly."""
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError

    from sqlalchemy import inspect as sa_inspect

    url = _database_url()
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"Postgres not reachable at {url}: {exc.__class__.__name__}: {exc} "
            "— run `docker compose up -d`"
        )
    # Ensure just the demo_requests table exists (additive; never drops others).
    # Only drop it on teardown if WE created it, so a real migration-managed DB
    # (table already at head) is left untouched while a clean test DB is left
    # clean — otherwise the leftover table collides with test_smoke's alembic
    # upgrade-from-base round-trip later in the session.
    created_here = not sa_inspect(engine).has_table(DemoRequest.__tablename__)
    if created_here:
        DemoRequest.__table__.create(bind=engine)
    yield engine
    if created_here:
        DemoRequest.__table__.drop(bind=engine, checkfirst=True)
    engine.dispose()


@pytest.fixture
def db_client(client, live_engine):
    """Test client whose get_session is bound to the live engine."""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=live_engine, expire_on_commit=False)

    def _override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = _override
    yield client, factory


# --------------------------------------------------------------------------- #
# (b) invalid email → 422 (no DB needed; Pydantic rejects pre-dependency)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad_email",
    ["not-an-email", "missing-at.com", "no-dot@localhost", "@nolocal.com", "trailing@dot."],
)
def test_invalid_email_returns_422(client, bad_email) -> None:
    r = client.post("/api/demo-request", json={"email": bad_email})
    assert r.status_code == 422, r.text


def test_missing_email_returns_422(client) -> None:
    r = client.post("/api/demo-request", json={"name": "Acme"})
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# (a) valid POST → 201 + persisted row
# --------------------------------------------------------------------------- #


def test_valid_post_persists_row(db_client) -> None:
    client, factory = db_client
    body = {
        "name": "Jane Doe",
        "company": "Acme Corp",
        "email": "jane@acme.com",
        "deployment_type": "claude-on-bedrock",
        "message": "We want a red-team scan of our support bot.",
    }
    r = client.post("/api/demo-request", json=body)
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["ok"] is True
    assert isinstance(payload["id"], int)

    with factory() as db:
        row = db.get(DemoRequest, payload["id"])
        assert row is not None
        assert row.email == "jane@acme.com"
        assert row.company == "Acme Corp"
        assert row.deployment_type == "claude-on-bedrock"
        assert row.source == "request-demo"  # default applied
        assert row.created_at is not None


# --------------------------------------------------------------------------- #
# (c) optional fields omitted still works
# --------------------------------------------------------------------------- #


def test_email_only_post_succeeds(db_client) -> None:
    client, factory = db_client
    r = client.post("/api/demo-request", json={"email": "solo@example.org"})
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]

    with factory() as db:
        row = db.get(DemoRequest, new_id)
        assert row is not None
        assert row.email == "solo@example.org"
        assert row.name is None
        assert row.company is None
        assert row.deployment_type is None
        assert row.message is None
        assert row.source == "request-demo"
