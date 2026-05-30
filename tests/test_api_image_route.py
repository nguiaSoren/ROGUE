"""Tests for GET /api/attacks/{id}/image — the drawer's real-image route.

Offline: the DB session is dependency-overridden with a fake that returns a
primitive carrying a chosen ``payload_slots['base_image']``. Locks the
path-traversal guard (only files under data/media_cache may be served) and the
happy path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rogue.api.main import app, get_session
from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
from rogue.db.models import PrimitiveImage as PrimitiveImageORM

_PNG = b"\x89PNG\r\n\x1a\n" + b"img-bytes"


class _FakePrimitive:
    def __init__(self, slots):
        self.payload_slots = slots
        self.image = None  # the one-to-one DB image relationship


class _FakeSession:
    """Model-aware fake: returns the primitive for AttackPrimitive lookups and a
    chosen PrimitiveImage row (or None) for the DB-image lookup."""

    def __init__(self, primitive, db_image=None):
        self._primitive = primitive
        self._db_image = db_image

    def get(self, model, _pid):
        if model is PrimitiveImageORM:
            return self._db_image
        if model is AttackPrimitiveORM:
            return self._primitive
        return None

    def close(self):
        pass


def _with_primitive(primitive, db_image=None):
    def _gen():
        yield _FakeSession(primitive, db_image)

    return _gen


@pytest.fixture
def client():
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


class _FakeDbImage:
    def __init__(self, image_bytes, media_type):
        self.image_bytes = image_bytes
        self.media_type = media_type


def test_serves_db_stored_bytes_first(client) -> None:
    """DB-FIRST: primitive_images bytes are served (this is what works on the
    deployed Neon-backed site, where there is no local media-cache file)."""
    db_img = _FakeDbImage(_PNG, "image/png")
    app.dependency_overrides[get_session] = _with_primitive(_FakePrimitive({}), db_image=db_img)
    r = client.get("/api/attacks/x/image")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content == _PNG


def test_404_when_primitive_missing(client) -> None:
    app.dependency_overrides[get_session] = _with_primitive(None)
    assert client.get("/api/attacks/none/image").status_code == 404


def test_404_when_no_base_image(client) -> None:
    app.dependency_overrides[get_session] = _with_primitive(_FakePrimitive({}))
    assert client.get("/api/attacks/x/image").status_code == 404


def test_404_on_path_traversal_outside_media_cache(client) -> None:
    app.dependency_overrides[get_session] = _with_primitive(
        _FakePrimitive({"base_image": "/etc/passwd"})
    )
    # The /etc/passwd path is outside the media-cache root → not served (404).
    assert client.get("/api/attacks/x/image").status_code == 404


def test_404_when_file_absent_in_cache(client) -> None:
    app.dependency_overrides[get_session] = _with_primitive(
        _FakePrimitive({"base_image": "data/media_cache/ingested/does_not_exist.png"})
    )
    assert client.get("/api/attacks/x/image").status_code == 404


def test_serves_carrier_by_primitive_id_fallback(client) -> None:
    """§11.8 layout: even with NO base_image in payload_slots, the per-attack
    carrier (data/media_cache/{id}/carrier.*) is found by primitive id."""
    pid = "01KTESTCARRIERPRIM000000000"
    asset_dir = Path("data/media_cache") / pid
    asset_dir.mkdir(parents=True, exist_ok=True)
    f = asset_dir / "carrier.png"
    f.write_bytes(_PNG)
    try:
        app.dependency_overrides[get_session] = _with_primitive(_FakePrimitive({}))
        r = client.get(f"/api/attacks/{pid}/image")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content == _PNG
    finally:
        f.unlink(missing_ok=True)
        asset_dir.rmdir()


def test_serves_image_under_media_cache(client) -> None:
    cache_dir = Path("data/media_cache")
    cache_dir.mkdir(parents=True, exist_ok=True)
    f = cache_dir / "_test_api_route.png"
    f.write_bytes(_PNG)
    try:
        app.dependency_overrides[get_session] = _with_primitive(
            _FakePrimitive({"base_image": str(f)})
        )
        r = client.get("/api/attacks/x/image")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content == _PNG
    finally:
        f.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# REPORT_DEFAULT_DATE — literal-date pin (no DB for the literal branch)
# --------------------------------------------------------------------------- #


def test_default_report_date_literal_pin(monkeypatch) -> None:
    import rogue.api.main as m
    from datetime import date as _date

    monkeypatch.setattr(m, "REPORT_DEFAULT_DATE", "2026-05-30")
    # literal branch returns without touching the DB → object() is never used
    assert m._default_report_date(object()) == _date(2026, 5, 30)


def test_default_report_date_bad_literal_falls_back(monkeypatch) -> None:
    import rogue.api.main as m

    monkeypatch.setattr(m, "REPORT_DEFAULT_DATE", "not-a-date")

    class _Result:
        def scalar(self):
            return None

    class _DB:
        def execute(self, *a, **k):
            return _Result()

    assert m._default_report_date(_DB()) is None  # fell through to the most-data query
