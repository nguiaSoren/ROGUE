"""Offline unit tests for `rogue.platform.tenancy` — no DB, no network.

Covers key minting/hashing round-trips, the RBAC ladder + scope checks, and principal resolution
through the in-memory test-resolver hook (the path `deps.require_principal` takes when there's no
database wired).
"""

from __future__ import annotations

import pytest

from rogue.platform.tenancy import (
    Principal,
    generate_api_key,
    has_scope,
    hash_key,
    resolve_principal_from_token,
    role_at_least,
    set_test_resolver,
)


# --------------------------------------------------------------------------------------------------
# API-key minting & hashing
# --------------------------------------------------------------------------------------------------


def test_generate_api_key_hash_round_trips():
    raw, key_hash, prefix = generate_api_key()
    # The stored hash must be exactly sha256(raw) — re-hashing the raw key reproduces it.
    assert hash_key(raw) == key_hash
    # sha256 hex is 64 chars; the raw key is never equal to its hash (we never store the secret).
    assert len(key_hash) == 64
    assert raw != key_hash


def test_generate_api_key_prefix_and_env_shape():
    raw, _hash, prefix = generate_api_key(env="live")
    assert raw.startswith("rk_live_")
    assert prefix == raw[:16]
    assert len(prefix) == 16
    # A non-default env is reflected in the raw key.
    raw_test, _h, _p = generate_api_key(env="test")
    assert raw_test.startswith("rk_test_")


def test_generate_api_key_is_unique():
    raw1, hash1, _ = generate_api_key()
    raw2, hash2, _ = generate_api_key()
    assert raw1 != raw2
    assert hash1 != hash2


# --------------------------------------------------------------------------------------------------
# RBAC ladder
# --------------------------------------------------------------------------------------------------


def test_role_at_least_ordering():
    # owner clears every gate; viewer clears only viewer.
    assert role_at_least("owner", "viewer")
    assert role_at_least("owner", "owner")
    assert role_at_least("admin", "member")
    assert role_at_least("member", "member")
    assert role_at_least("viewer", "viewer")
    # Lower roles do not clear higher gates.
    assert not role_at_least("viewer", "member")
    assert not role_at_least("member", "admin")
    assert not role_at_least("admin", "owner")


def test_role_at_least_unknown_role_never_clears():
    assert not role_at_least("intruder", "viewer")
    assert not role_at_least("owner", "intruder")


# --------------------------------------------------------------------------------------------------
# Scope checks
# --------------------------------------------------------------------------------------------------


def test_has_scope_owner_and_admin_have_all():
    owner = Principal(org_id="org_1", role="owner", key_id="k1", scopes=[])
    admin = Principal(org_id="org_1", role="admin", key_id="k2", scopes=[])
    for scope in ("scan:read", "scan:write", "admin", "anything:else"):
        assert has_scope(owner, scope)
        assert has_scope(admin, scope)


def test_has_scope_viewer_is_limited_to_granted():
    viewer = Principal(org_id="org_1", role="viewer", key_id="k3", scopes=["scan:read"])
    assert has_scope(viewer, "scan:read")
    assert not has_scope(viewer, "scan:write")
    assert not has_scope(viewer, "admin")


def test_has_scope_member_checks_list():
    member = Principal(org_id="org_1", role="member", key_id="k4", scopes=["scan:read", "scan:write"])
    assert has_scope(member, "scan:write")
    assert not has_scope(member, "admin")


# --------------------------------------------------------------------------------------------------
# Principal resolution via the in-memory test hook (no DB)
# --------------------------------------------------------------------------------------------------


@pytest.fixture
def fake_keystore():
    """Register an in-memory token->Principal map and tear it down after the test."""
    principal = Principal(
        org_id="org_acme",
        project_id="proj_1",
        role="member",
        scopes=["scan:read", "scan:write"],
        key_id="key_abc",
    )
    keys = {"good-token": principal}  # revoked keys are simply absent from the map

    def _resolver(token: str):
        return keys.get(token)

    set_test_resolver(_resolver)
    try:
        yield principal
    finally:
        set_test_resolver(None)


def test_resolve_via_test_resolver(fake_keystore):
    principal = resolve_principal_from_token("good-token")
    assert principal is fake_keystore
    assert principal.org_id == "org_acme"
    assert principal.project_id == "proj_1"
    assert principal.scopes == ["scan:read", "scan:write"]
    assert principal.key_id == "key_abc"


def test_resolve_unknown_token_returns_none(fake_keystore):
    # Unknown token: the hook returns None and there is no DATABASE_URL fallback in tests.
    assert resolve_principal_from_token("nope-not-a-key", session_factory=lambda: None) is None


def test_resolve_revoked_token_returns_none(fake_keystore):
    # A "revoked" key is one that no longer resolves through the keystore -> None.
    assert resolve_principal_from_token("revoked-token", session_factory=lambda: None) is None


def test_resolve_empty_token_returns_none():
    assert resolve_principal_from_token("") is None


def test_resolve_no_hook_no_db_returns_none(monkeypatch):
    # With no resolver hook installed and no DATABASE_URL, resolution is a clean None (no DB touched).
    set_test_resolver(None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert resolve_principal_from_token("any-token") is None
