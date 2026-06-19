"""Tests for POST /api/newsletter — the marketing-site newsletter sign-up route.

Cases per the §-build brief:
  (a) a valid POST returns 201 and persists a row,
  (b) a duplicate email returns 200 with the same id and ``already: true``,
  (c) an invalid email returns 422.

Email-validation cases (c) need no DB — FastAPI rejects at the Pydantic layer
before the dependency runs. The persistence cases (a, b) hit a live Postgres via
a `live_engine`-style skip guard, so they `pytest.skip` cleanly when Docker/DB
is down. The fixture only creates the
table if absent and only drops it on teardown when it created it — otherwise the
leftover table pollutes `rogue_test` and breaks test_smoke's alembic round-trip.
"""

from __future__ import annotations

import os
import socket

import pytest
from fastapi.testclient import TestClient

from rogue.api.main import app, get_session
from rogue.db.models import NewsletterSubscriber

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
    """Connected engine with the newsletter_subscribers table ensured, or skip."""
    from sqlalchemy import create_engine
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy.exc import OperationalError

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
    # Ensure just the newsletter_subscribers table exists (additive; never drops
    # others). Only drop it on teardown if WE created it, so a real
    # migration-managed DB (table already at head) is left untouched while a
    # clean test DB is left clean — otherwise the leftover table collides with
    # test_smoke's alembic upgrade-from-base round-trip later in the session.
    created_here = not sa_inspect(engine).has_table(
        NewsletterSubscriber.__tablename__
    )
    if created_here:
        NewsletterSubscriber.__table__.create(bind=engine)
    yield engine
    if created_here:
        NewsletterSubscriber.__table__.drop(bind=engine, checkfirst=True)
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
# (c) invalid email → 422 (no DB needed; Pydantic rejects pre-dependency)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad_email",
    ["not-an-email", "missing-at.com", "no-dot@localhost", "@nolocal.com", "trailing@dot."],
)
def test_invalid_email_returns_422(client, bad_email) -> None:
    r = client.post("/api/newsletter", json={"email": bad_email})
    assert r.status_code == 422, r.text


def test_missing_email_returns_422(client) -> None:
    r = client.post("/api/newsletter", json={"source": "site"})
    assert r.status_code == 422, r.text


# --------------------------------------------------------------------------- #
# (a) valid POST → 201 + persisted row
# --------------------------------------------------------------------------- #


def test_valid_post_persists_row(db_client) -> None:
    client, factory = db_client
    r = client.post(
        "/api/newsletter", json={"email": "subscriber@acme.com", "source": "footer"}
    )
    assert r.status_code == 201, r.text
    payload = r.json()
    assert payload["ok"] is True
    assert isinstance(payload["id"], int)
    assert "already" not in payload

    with factory() as db:
        row = db.get(NewsletterSubscriber, payload["id"])
        assert row is not None
        assert row.email == "subscriber@acme.com"
        assert row.source == "footer"
        assert row.created_at is not None


def test_email_only_post_applies_default_source(db_client) -> None:
    client, factory = db_client
    r = client.post("/api/newsletter", json={"email": "defaults@example.org"})
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]

    with factory() as db:
        row = db.get(NewsletterSubscriber, new_id)
        assert row is not None
        assert row.source == "site"  # default applied


# --------------------------------------------------------------------------- #
# (b) duplicate email → 200 + same id + already=true (idempotent)
# --------------------------------------------------------------------------- #


def test_duplicate_email_is_idempotent(db_client) -> None:
    client, _factory = db_client
    body = {"email": "dupe@acme.com", "source": "site"}

    first = client.post("/api/newsletter", json=body)
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    second = client.post("/api/newsletter", json=body)
    assert second.status_code == 200, second.text
    payload = second.json()
    assert payload["ok"] is True
    assert payload["id"] == first_id
    assert payload["already"] is True
