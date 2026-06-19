"""Offline tests for the typed runtime configuration seam (rogue.config).

No DB, no network — all reads go through Settings.from_env({...}) with an
explicit mapping so the tests never touch the real os.environ.
"""

from __future__ import annotations

import rogue.config as config_module
from rogue.config import Settings, get_settings

# Canonical dev fallback — must match api/main.py and mcp_server/server.py.
_DEV_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


def test_defaults_when_env_empty() -> None:
    s = Settings.from_env({})
    # Database falls back to the shared dev URL.
    assert s.database_url == _DEV_DATABASE_URL
    # Model defaults.
    assert s.judge_model == "anthropic/claude-sonnet-4-6"
    assert s.judge_fallback_model == "deepseek/deepseek-v4-flash"
    # MCP transport defaults.
    assert s.mcp_transport == "stdio"
    assert s.mcp_port == 8001
    assert s.mcp_host == "127.0.0.1"
    # Credentials and optional queue url are unset.
    assert s.openai_api_key is None
    assert s.anthropic_api_key is None
    assert s.redis_url is None


def test_overrides_honored() -> None:
    s = Settings.from_env(
        {
            "DATABASE_URL": "postgresql+psycopg://u:p@db:5432/other",
            "OPENAI_API_KEY": "sk-test-openai",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "JUDGE_MODEL": "anthropic/claude-opus-4-8",
            "REDIS_URL": "redis://localhost:6379/0",
            "ROGUE_MCP_TRANSPORT": "streamable-http",
            "ROGUE_MCP_PORT": "9000",
            "ROGUE_MCP_HOST": "0.0.0.0",
            "SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/xxx",
        }
    )
    assert s.database_url == "postgresql+psycopg://u:p@db:5432/other"
    assert s.judge_model == "anthropic/claude-opus-4-8"
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.mcp_transport == "streamable-http"
    # str env value coerced to int by pydantic.
    assert s.mcp_port == 9000
    assert s.mcp_host == "0.0.0.0"
    # SecretStr wraps the value but exposes it via get_secret_value().
    assert s.openai_api_key is not None
    assert s.openai_api_key.get_secret_value() == "sk-test-openai"
    assert s.anthropic_api_key.get_secret_value() == "sk-ant-test"
    assert s.slack_webhook_url.get_secret_value() == "https://hooks.slack.com/services/xxx"


def test_blank_env_value_uses_default() -> None:
    # An empty-string env var (e.g. GEMINI_API_KEY=) must not mask the None
    # default, and a blank DATABASE_URL must not blank the dev fallback.
    s = Settings.from_env({"GEMINI_API_KEY": "", "DATABASE_URL": ""})
    assert s.gemini_api_key is None
    assert s.database_url == _DEV_DATABASE_URL


def test_secrets_not_exposed_in_repr_or_str() -> None:
    secret = "sk-super-secret-value-12345"
    s = Settings.from_env({"OPENAI_API_KEY": secret, "ANTHROPIC_API_KEY": secret})
    # The raw secret must never appear in repr() or str() of the settings.
    assert secret not in repr(s)
    assert secret not in str(s)
    # And not in the field's own repr either.
    assert secret not in repr(s.openai_api_key)
    # But the value is still retrievable through the explicit accessor.
    assert s.openai_api_key.get_secret_value() == secret


def test_redacted_dict_reports_presence_not_value() -> None:
    secret = "sk-redact-me"
    s = Settings.from_env({"OPENAI_API_KEY": secret})
    red = s.redacted_dict()
    # Secret fields become booleans.
    assert red["openai_api_key"] is True
    assert red["anthropic_api_key"] is False
    assert red["slack_webhook_url"] is False
    # The raw secret is nowhere in the redacted view.
    assert secret not in str(red)
    # Non-secret fields keep their actual value.
    assert red["database_url"] == _DEV_DATABASE_URL
    assert red["judge_model"] == "anthropic/claude-sonnet-4-6"
    assert red["mcp_port"] == 8001


def test_get_settings_is_cached_singleton() -> None:
    # Reset any prior cache so this test is order-independent.
    config_module._cached_settings = None
    first = get_settings()
    second = get_settings()
    assert first is second
