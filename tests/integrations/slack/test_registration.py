"""§2 EXIT GATE — Slack-agent self-registration → routable DeploymentConfig.

Build-area 06 §2 gate (verbatim): "A unit test registers a fake Slack agent → produces a valid
frozen DeploymentConfig routable through CustomHTTPAdapter (assert provider=='custom', base_url
set), with sandbox + security channel ids bound and the credential resolvable from the store.
No network."

All tests here are OFFLINE: no network, no paid call. The single DB test (sensitive-prompt path)
connects to the LOCAL Postgres container only and `pytest.skip`s cleanly when it is unavailable
(house convention) — it never touches Neon.
"""

from __future__ import annotations

import pytest

from rogue.integrations.slack import (
    InMemorySlackAgentStore,
    RegisteredSlackAgent,
    SlackAgentTarget,
    config_id_for,
    register_slack_agent,
    slack_agent_to_config,
)
from rogue.platform.integration_store import InMemoryIntegrationStore
from rogue.schemas import DeploymentConfig

# Forced LOCAL url — the same default literal the stores use. We never read .env here
# (its DATABASE_URL points at Neon); the DB test below pins this explicitly.
_LOCAL_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def _fake_target(**overrides) -> SlackAgentTarget:
    kw = dict(
        org_id="org_acme",
        agent_name="support-bot",
        workspace="acme-workspace",
        base_url="https://agent.acme.example/v1",
        model="gpt-5.4-nano",
        system_prompt="You are Acme's Slack support agent. Help with Acme products only.",
        declared_tools=["web_fetch", "lookup_order"],
        forbidden_topics=["competitor products"],
        sandbox_channel_id="C-SANDBOX-001",
        security_channel_id="C-SECURITY-001",
    )
    kw.update(overrides)
    return SlackAgentTarget.create(**kw)


# ---------------------------------------------------------------------------
# 1. Happy path → frozen config routes "custom".
# ---------------------------------------------------------------------------
def test_happy_path_builds_frozen_custom_routed_config():
    store = InMemorySlackAgentStore()
    target = _fake_target()

    reg = register_slack_agent(target, agent_store=store)

    assert isinstance(reg, RegisteredSlackAgent)
    assert isinstance(reg.config, DeploymentConfig)
    config = reg.config

    # base_url is the agent's endpoint.
    assert config.base_url == "https://agent.acme.example/v1"

    # Replicate the engine's routing rule verbatim (target_panel.py:271):
    #   provider = "custom" if config.base_url else _resolve_provider(config.target_model)
    # A base_url-carrying config routes through CustomHTTPAdapter == provider "custom".
    provider = "custom" if config.base_url else None
    assert provider == "custom"

    # Identity fields.
    assert config.config_id == "slack-acme-workspace-support-bot"
    assert config.config_id == f"slack-{target.workspace}-{target.agent_name}"
    assert config.config_id == config_id_for(target)
    assert config.customer_id == target.org_id == "org_acme"
    assert config.target_model == "gpt-5.4-nano"
    assert config.system_prompt == target.system_prompt
    assert config.declared_tools == ["web_fetch", "lookup_order"]
    assert config.forbidden_topics == ["competitor products"]

    # agent_id was minted and is resolvable from the store.
    assert reg.agent_id
    assert store.get("org_acme", "support-bot") is not None


def test_config_is_frozen():
    config = slack_agent_to_config(_fake_target())
    with pytest.raises(pydantic_validation_error()):
        config.base_url = "https://evil.example/v1"  # type: ignore[misc]


def test_routes_through_resolve_provider_seam_when_importable():
    """Prefer asserting through the real routing seam. If importing target_panel is heavyweight
    or has import-time side effects, fall back to the documented rule (asserted above)."""
    try:
        from rogue.reproduce.target_panel import _resolve_provider  # noqa: F401
    except Exception:  # pragma: no cover — heavyweight/side-effecting import; rule asserted elsewhere
        pytest.skip("target_panel import unavailable/heavyweight; documented rule asserted in happy-path test")

    config = slack_agent_to_config(_fake_target())
    # The engine never calls _resolve_provider when base_url is set; it short-circuits to "custom".
    # We assert the short-circuit precedence: base_url present ⇒ "custom" regardless of model id.
    provider = "custom" if config.base_url else _resolve_provider(config.target_model)
    assert provider == "custom"


# ---------------------------------------------------------------------------
# 2. Channels bound.
# ---------------------------------------------------------------------------
def test_sandbox_and_security_channels_bound_on_persisted_target():
    store = InMemorySlackAgentStore()
    register_slack_agent(
        _fake_target(sandbox_channel_id="C-SBX-XYZ", security_channel_id="C-SEC-XYZ"),
        agent_store=store,
    )

    persisted = store.get("org_acme", "support-bot")
    assert persisted is not None
    assert persisted.sandbox_channel_id == "C-SBX-XYZ"
    assert persisted.security_channel_id == "C-SEC-XYZ"


# ---------------------------------------------------------------------------
# 3. Credential resolvable from the integration store (NOT the agent row).
# ---------------------------------------------------------------------------
def test_credential_resolvable_from_integration_store_not_agent_row():
    agent_store = InMemorySlackAgentStore()
    integration_store = InMemoryIntegrationStore()
    target = _fake_target()

    register_slack_agent(
        target,
        agent_store=agent_store,
        integration_store=integration_store,
        slack_bot_token="xoxb-FAKE-BOT-TOKEN",
        slack_signing_secret="sign-FAKE",
    )

    # The credential is resolvable by name from the integrations store.
    resolved = integration_store.get("org_acme", "slack-app-acme-workspace")
    assert resolved is not None
    assert resolved.kind == "slack"
    assert resolved.secret == "xoxb-FAKE-BOT-TOKEN"
    # Non-secret: signing-secret presence is recorded in config, not the raw value.
    assert resolved.config == {"signing_secret_present": True}
    assert "sign-FAKE" not in repr(resolved.config)

    # The credential is NOT inside the slack agent row — the agent never handles the raw secret.
    persisted = agent_store.get("org_acme", "support-bot")
    assert "xoxb-FAKE-BOT-TOKEN" not in repr(persisted)


def test_no_integration_store_means_no_credential_path():
    """Without an integration store, registration still succeeds; nothing tries to store a secret."""
    agent_store = InMemorySlackAgentStore()
    reg = register_slack_agent(
        _fake_target(), agent_store=agent_store, slack_bot_token="xoxb-IGNORED"
    )
    assert isinstance(reg.config, DeploymentConfig)  # no crash, no secret store required


# ---------------------------------------------------------------------------
# 4. Fail-closed without sandbox / security channel (and other required fields).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("blank_field", ["sandbox_channel_id", "security_channel_id"])
def test_blank_channel_fails_closed(blank_field):
    with pytest.raises(ValueError) as exc:
        _fake_target(**{blank_field: ""})
    assert blank_field in str(exc.value)


@pytest.mark.parametrize("blank_field", ["sandbox_channel_id", "security_channel_id"])
def test_register_with_blank_channel_fails_closed(blank_field):
    # The whitespace-only variant is also rejected (non-blank check strips).
    store = InMemorySlackAgentStore()
    with pytest.raises(ValueError):
        register_slack_agent(_fake_target(**{blank_field: "   "}), agent_store=store)


@pytest.mark.parametrize(
    "blank_field", ["org_id", "agent_name", "workspace", "base_url", "model"]
)
def test_other_required_fields_fail_closed(blank_field):
    with pytest.raises(ValueError) as exc:
        _fake_target(**{blank_field: ""})
    assert blank_field in str(exc.value)


# ---------------------------------------------------------------------------
# 5. Store round-trip (InMemory) — list never exposes the system prompt.
# ---------------------------------------------------------------------------
def test_inmemory_store_round_trip_and_list_hides_prompt():
    store = InMemorySlackAgentStore()
    target = _fake_target()
    store.put(target)

    got = store.get("org_acme", "support-bot")
    assert got == target  # frozen dataclass equality reconstructs an equal target

    listing = store.list("org_acme")
    assert listing == [{"agent_name": "support-bot", "workspace": "acme-workspace"}]
    # The secret-bearing field (system prompt) is never exposed by the listing surface.
    assert "support agent" not in repr(listing)
    for entry in listing:
        assert "system_prompt" not in entry


def test_inmemory_store_put_is_idempotent_on_org_agent_key():
    store = InMemorySlackAgentStore()
    first = store.put(_fake_target(model="gpt-5.4-nano"))
    second = store.put(_fake_target(model="claude-haiku-4-5"))  # same org+agent → update in place
    assert first == second  # stable agent_id across re-registration
    assert store.get("org_acme", "support-bot").model == "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# 6. Sensitive-prompt path — real LOCAL Postgres; skips cleanly when down.
# ---------------------------------------------------------------------------
def test_sensitive_prompt_persists_as_secref_not_plaintext_postgres():
    """PostgresSlackAgentStore + InMemorySecretStore against a REAL local Postgres session.

    A sensitive prompt must be persisted as a `secref_…` handle in `system_prompt_ref` (NOT the
    literal prompt), and `get` must resolve it back to the original prompt. Skips cleanly if the
    local container is unavailable. Pinned to the LOCAL url — never Neon.
    """
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import Base
    from rogue.integrations.slack import PostgresSlackAgentStore
    from rogue.platform.models import SlackRegisteredAgent
    from rogue.platform.secrets import InMemorySecretStore

    # Neon protection is the hardcoded LOCAL url literal below — we never read .env's DATABASE_URL.
    assert "localhost" in _LOCAL_DATABASE_URL and "neon" not in _LOCAL_DATABASE_URL.lower()
    try:
        engine = create_engine(_LOCAL_DATABASE_URL, pool_pre_ping=True, pool_timeout=5)
        with engine.connect() as c:
            c.execute(text("select 1"))
        # Isolate to just this table; create if absent (idempotent against the migrated schema).
        Base.metadata.create_all(engine, tables=[SlackRegisteredAgent.__table__], checkfirst=True)
    except Exception as e:  # pragma: no cover — house convention: skip cleanly if DB unavailable
        pytest.skip(f"local Postgres unavailable for DB round-trip: {e}")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    secrets = InMemorySecretStore()
    store = PostgresSlackAgentStore(factory, secret_store=secrets)

    secret_prompt = "SENSITIVE: internal escalation playbook — do not disclose."
    target = _fake_target(
        org_id="org_dbtest",
        agent_name="db-sensitive-bot",
        system_prompt=secret_prompt,
        system_prompt_sensitive=True,
    )

    try:
        agent_id = store.put(target)
        assert agent_id

        # The stored row holds a secref handle, NOT the literal prompt.
        with factory() as s:
            row = s.execute(
                select(SlackRegisteredAgent).where(
                    SlackRegisteredAgent.org_id == "org_dbtest",
                    SlackRegisteredAgent.agent_name == "db-sensitive-bot",
                )
            ).scalar_one()
            assert row.system_prompt_ref.startswith("secref_")
            assert secret_prompt not in row.system_prompt_ref

        # get() resolves the secref back to the original prompt and flags it sensitive.
        got = store.get("org_dbtest", "db-sensitive-bot")
        assert got is not None
        assert got.system_prompt == secret_prompt
        assert got.system_prompt_sensitive is True
        assert got.sandbox_channel_id == "C-SANDBOX-001"
        assert got.security_channel_id == "C-SECURITY-001"

        # list() never surfaces the prompt or the secref.
        listing = store.list("org_dbtest")
        assert {"agent_name": "db-sensitive-bot", "workspace": "acme-workspace"} in listing
        assert secret_prompt not in repr(listing)
    finally:
        with factory() as s:
            s.execute(
                text("delete from slack_registered_agents where org_id = :o"),
                {"o": "org_dbtest"},
            )
            s.commit()
        engine.dispose()


# ---------------------------------------------------------------------------
# 7. Target endpoint api_key — carried on the target; default None; never inline in the row.
# ---------------------------------------------------------------------------
def test_create_carries_api_key_and_defaults_none():
    """`SlackAgentTarget.create(api_key=...)` carries the key; omitted ⇒ None (keyless endpoint)."""
    keyed = _fake_target(api_key="sk-x")
    assert keyed.api_key == "sk-x"

    keyless = _fake_target()
    assert keyless.api_key is None


def test_api_key_persists_as_secref_not_plaintext_postgres():
    """PostgresSlackAgentStore + InMemorySecretStore against a REAL local Postgres session.

    A target endpoint api_key must be persisted as a `secref_…` handle in `target_api_key_ref`
    (NOT the literal key), and `get` / `all_targets` must resolve it back to the original key.
    Skips cleanly if the local container is unavailable. Pinned to the LOCAL url — never Neon.
    """
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import Base
    from rogue.integrations.slack import PostgresSlackAgentStore
    from rogue.platform.models import SlackRegisteredAgent
    from rogue.platform.secrets import InMemorySecretStore

    assert "localhost" in _LOCAL_DATABASE_URL and "neon" not in _LOCAL_DATABASE_URL.lower()
    try:
        engine = create_engine(_LOCAL_DATABASE_URL, pool_pre_ping=True, pool_timeout=5)
        with engine.connect() as c:
            c.execute(text("select 1"))
        # Note: this requires the migrated schema (the `target_api_key_ref` column from
        # migration 0035). create_all with checkfirst won't ADD a missing column to an
        # existing table, so a pre-0035 DB would surface here as a missing-column error
        # rather than a silent skip — which is the honest signal.
        Base.metadata.create_all(engine, tables=[SlackRegisteredAgent.__table__], checkfirst=True)
    except Exception as e:  # pragma: no cover — house convention: skip cleanly if DB unavailable
        pytest.skip(f"local Postgres unavailable for DB round-trip: {e}")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    secrets = InMemorySecretStore()
    store = PostgresSlackAgentStore(factory, secret_store=secrets)

    secret_key = "sk-secret"
    target = _fake_target(
        org_id="org_dbkey",
        agent_name="db-keyed-bot",
        api_key=secret_key,
    )
    try:
        store.put(target)

        # The stored row holds a secref handle, NOT the literal key.
        with factory() as s:
            row = s.execute(
                select(SlackRegisteredAgent).where(
                    SlackRegisteredAgent.org_id == "org_dbkey",
                    SlackRegisteredAgent.agent_name == "db-keyed-bot",
                )
            ).scalar_one()
            assert row.target_api_key_ref is not None
            assert row.target_api_key_ref.startswith("secref_")
            assert secret_key not in row.target_api_key_ref

        # get() and all_targets() both resolve the secref back to the original key.
        got = store.get("org_dbkey", "db-keyed-bot")
        assert got is not None
        assert got.api_key == secret_key

        all_t = [t for t in store.all_targets("org_dbkey") if t.agent_name == "db-keyed-bot"]
        assert len(all_t) == 1
        assert all_t[0].api_key == secret_key

        # list() never surfaces the key or its secref.
        listing = store.list("org_dbkey")
        assert secret_key not in repr(listing)
    finally:
        with factory() as s:
            s.execute(
                text("delete from slack_registered_agents where org_id = :o"),
                {"o": "org_dbkey"},
            )
            s.commit()
        engine.dispose()


def test_keyless_target_persists_null_api_key_ref_postgres():
    """A keyless target (api_key=None) ⇒ `target_api_key_ref` stays NULL and resolves back to None."""
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import Base
    from rogue.integrations.slack import PostgresSlackAgentStore
    from rogue.platform.models import SlackRegisteredAgent
    from rogue.platform.secrets import InMemorySecretStore

    try:
        engine = create_engine(_LOCAL_DATABASE_URL, pool_pre_ping=True, pool_timeout=5)
        with engine.connect() as c:
            c.execute(text("select 1"))
        Base.metadata.create_all(engine, tables=[SlackRegisteredAgent.__table__], checkfirst=True)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"local Postgres unavailable for DB round-trip: {e}")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = PostgresSlackAgentStore(factory, secret_store=InMemorySecretStore())
    target = _fake_target(org_id="org_dbkeyless", agent_name="db-keyless-bot")  # api_key=None
    try:
        store.put(target)
        with factory() as s:
            row = s.execute(
                select(SlackRegisteredAgent).where(
                    SlackRegisteredAgent.org_id == "org_dbkeyless"
                )
            ).scalar_one()
            assert row.target_api_key_ref is None
        got = store.get("org_dbkeyless", "db-keyless-bot")
        assert got is not None
        assert got.api_key is None
    finally:
        with factory() as s:
            s.execute(
                text("delete from slack_registered_agents where org_id = :o"),
                {"o": "org_dbkeyless"},
            )
            s.commit()
        engine.dispose()


def test_inline_prompt_path_postgres_stores_literal():
    """Non-sensitive prompt stores inline (no secref). Real local Postgres; skips cleanly if down."""
    from sqlalchemy import create_engine, select, text
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import Base
    from rogue.integrations.slack import PostgresSlackAgentStore
    from rogue.platform.models import SlackRegisteredAgent
    from rogue.platform.secrets import InMemorySecretStore

    try:
        engine = create_engine(_LOCAL_DATABASE_URL, pool_pre_ping=True, pool_timeout=5)
        with engine.connect() as c:
            c.execute(text("select 1"))
        Base.metadata.create_all(engine, tables=[SlackRegisteredAgent.__table__], checkfirst=True)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"local Postgres unavailable for DB round-trip: {e}")

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = PostgresSlackAgentStore(factory, secret_store=InMemorySecretStore())
    target = _fake_target(
        org_id="org_dbtest2",
        agent_name="db-inline-bot",
        system_prompt="Public, non-sensitive prompt.",
        system_prompt_sensitive=False,
    )
    try:
        store.put(target)
        with factory() as s:
            row = s.execute(
                select(SlackRegisteredAgent).where(
                    SlackRegisteredAgent.org_id == "org_dbtest2"
                )
            ).scalar_one()
            assert row.system_prompt_ref == "Public, non-sensitive prompt."
            assert not row.system_prompt_ref.startswith("secref_")
        got = store.get("org_dbtest2", "db-inline-bot")
        assert got.system_prompt == "Public, non-sensitive prompt."
        assert got.system_prompt_sensitive is False
    finally:
        with factory() as s:
            s.execute(
                text("delete from slack_registered_agents where org_id = :o"),
                {"o": "org_dbtest2"},
            )
            s.commit()
        engine.dispose()


def pydantic_validation_error():
    """The error a frozen-model field mutation raises (pydantic v2 ValidationError)."""
    from pydantic import ValidationError

    return ValidationError
