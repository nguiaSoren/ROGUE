"""Typed runtime configuration for ROGUE.

This module is the single seam other modules should migrate to for reading
runtime configuration. Today the codebase scatters ``os.environ.get(...)``
calls across layers, and two of them (``api/main.py`` and
``mcp_server/server.py``) each hardcode the same ``DATABASE_URL`` dev fallback.
``Settings`` centralizes those reads into one validated object so the fallback,
the env-var names, and the defaults live in exactly one place.

Migration note (NOT done here — see ROGUE_PLAN.md §A.3 / §8.2): callers should
replace their bespoke ``os.environ.get`` reads with ``get_settings()`` and pull
the field they need (e.g. ``get_settings().database_url``). This module does not
modify those callers; it only provides the seam.

Every credential is a ``pydantic.SecretStr`` so that ``repr(settings)`` and any
incidental logging redact the value rather than leaking it. Use
``redacted_dict()`` for a log-safe view: it carries the non-secret fields plus a
boolean per secret indicating only whether it is set.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, SecretStr

# Canonical dev fallback, duplicated today in api/main.py and
# mcp_server/server.py. Kept here so the migration target owns one copy.
_DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"

# Model defaults. judge_model mirrors .env.example's JUDGE_MODEL; the fallback
# model has no env-var of its own yet, so its default lives here as the spec.
_DEFAULT_JUDGE_MODEL = "anthropic/claude-sonnet-4-6"
_DEFAULT_JUDGE_FALLBACK_MODEL = "deepseek/deepseek-v4-flash"

# MCP transport defaults mirror .env.example's ROGUE_MCP_* block.
_DEFAULT_MCP_TRANSPORT = "stdio"
_DEFAULT_MCP_PORT = 8001
_DEFAULT_MCP_HOST = "127.0.0.1"

# Map of Settings field name -> environment variable name. Names are the
# canonical ones from .env.example; fields without an .env.example entry use a
# sensible upper-snake name (REDIS_URL, JUDGE_FALLBACK_MODEL).
_ENV_NAMES: dict[str, str] = {
    "database_url": "DATABASE_URL",
    "openai_api_key": "OPENAI_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openrouter_api_key": "OPENROUTER_API_KEY",
    "groq_api_key": "GROQ_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "judge_model": "JUDGE_MODEL",
    "judge_fallback_model": "JUDGE_FALLBACK_MODEL",
    "slack_webhook_url": "SLACK_WEBHOOK_URL",
    # build-06 §8 Surface-1 Slack delivery: bot token + request-signature secret.
    "slack_bot_token": "SLACK_BOT_TOKEN",
    "slack_signing_secret": "SLACK_SIGNING_SECRET",
    "secret_encryption_key": "SECRET_ENCRYPTION_KEY",
    "redis_url": "REDIS_URL",
    "mcp_transport": "ROGUE_MCP_TRANSPORT",
    "mcp_port": "ROGUE_MCP_PORT",
    "mcp_host": "ROGUE_MCP_HOST",
}

# Fields holding credentials — redacted_dict() reports a presence boolean for
# each instead of the value.
_SECRET_FIELDS: frozenset[str] = frozenset(
    {
        "openai_api_key",
        "anthropic_api_key",
        "openrouter_api_key",
        "groq_api_key",
        "gemini_api_key",
        "slack_webhook_url",
        "slack_bot_token",
        "slack_signing_secret",
        "secret_encryption_key",
    }
)


class Settings(BaseModel):
    """Validated, typed view of ROGUE's runtime environment.

    Build via :meth:`from_env`, which reads the canonical env-var names. Prefer
    the module-level :func:`get_settings` accessor in application code so the
    environment is read once and cached.
    """

    # ---------- Database ----------
    database_url: str = _DEFAULT_DATABASE_URL

    # ---------- LLM provider keys (credentials) ----------
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    # ---------- Model selection ----------
    judge_model: str = _DEFAULT_JUDGE_MODEL
    judge_fallback_model: str = _DEFAULT_JUDGE_FALLBACK_MODEL

    # ---------- Tenant-secret encryption (Fernet key for rogue.platform.secrets) ----------
    secret_encryption_key: SecretStr | None = None

    # ---------- Notifications (credential) ----------
    slack_webhook_url: SecretStr | None = None
    # build-06 §8 Surface-1 Slack delivery: bot OAuth token + request-signature secret.
    slack_bot_token: SecretStr | None = None
    slack_signing_secret: SecretStr | None = None

    # ---------- Future queue ----------
    redis_url: str | None = None

    # ---------- MCP server transport ----------
    mcp_transport: str = _DEFAULT_MCP_TRANSPORT
    mcp_port: int = _DEFAULT_MCP_PORT
    mcp_host: str = _DEFAULT_MCP_HOST

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Construct ``Settings`` from a mapping of environment variables.

        ``env`` defaults to ``os.environ``. Only keys that are present (and, for
        string/secret fields, non-empty) are passed through; everything else
        falls back to the field default. This keeps an empty-string env var
        (e.g. ``GEMINI_API_KEY=``) from masking the ``None`` default.
        """
        source: Mapping[str, str] = os.environ if env is None else env
        values: dict[str, object] = {}
        for field_name, env_name in _ENV_NAMES.items():
            raw = source.get(env_name)
            if raw is None or raw == "":
                # Absent or blank — let the field default apply.
                continue
            values[field_name] = raw
        # Pydantic coerces mcp_port str->int and wraps secret strings in
        # SecretStr per the field annotations.
        return cls(**values)

    def redacted_dict(self) -> dict[str, object]:
        """Return a log-safe view of the settings.

        Non-secret fields appear with their value; each secret field appears as
        a boolean indicating only whether it is set (``True``/``False``), never
        the value itself.
        """
        result: dict[str, object] = {}
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            if field_name in _SECRET_FIELDS:
                result[field_name] = value is not None
            else:
                result[field_name] = value
        return result


# Module-level lazy singleton. Populated on first get_settings() call so the
# environment is read exactly once per process.
_cached_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings`.

    Reads ``os.environ`` once on first call and caches the result. Subsequent
    calls return the same instance. Tests that need a fresh read should call
    ``Settings.from_env(...)`` directly rather than relying on this accessor.
    """
    global _cached_settings
    if _cached_settings is None:
        _cached_settings = Settings.from_env()
    return _cached_settings
