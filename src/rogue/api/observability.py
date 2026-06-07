"""Production-readiness wiring for the ROGUE API: logging, error reporting, rate limiting.

Everything here degrades to a clean no-op when the optional dependencies
(``sentry-sdk``, ``slowapi``) or the env vars that activate them are absent — so
local dev, tests, and CI stay green whether or not the deps are installed.

Three concerns:
  * ``configure_logging()`` — idempotent root-logger setup. ``LOG_LEVEL`` (default
    INFO) sets the level; ``LOG_JSON=1`` emits one JSON object per line, else a
    clean console format.
  * ``init_sentry()`` — opt-in error reporting. No-op unless ``sentry-sdk`` is
    installed AND ``SENTRY_DSN`` is set.
  * ``get_limiter()`` — a SlowAPI ``Limiter`` keyed by client IP, or ``None`` when
    ``slowapi`` is absent. ``RATE_LIMIT_DEFAULT`` / ``RATE_LIMIT_SCANS`` carry the
    default and the tighter scan-creation limit (both env-overridable).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("rogue.api")


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #


class _JsonLogFormatter(logging.Formatter):
    """Render a log record as a single-line JSON object: ts, level, logger, msg."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# Sentinel marking the handler we install, so configure_logging() is idempotent
# (repeated calls don't stack duplicate handlers — e.g. tests that re-import).
_ROGUE_HANDLER_FLAG = "_rogue_observability_handler"


def configure_logging() -> None:
    """Install a single root log handler honoring ``LOG_LEVEL`` / ``LOG_JSON``.

    Idempotent: if our handler is already attached we only refresh its level,
    rather than adding a second handler.
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    json_mode = os.environ.get("LOG_JSON", "").strip().lower() in {"1", "true", "yes", "on"}

    root = logging.getLogger()
    root.setLevel(level)

    # Idempotency: reuse our existing handler if present.
    for handler in root.handlers:
        if getattr(handler, _ROGUE_HANDLER_FLAG, False):
            handler.setLevel(level)
            return

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    if json_mode:
        handler.setFormatter(_JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
        )
    setattr(handler, _ROGUE_HANDLER_FLAG, True)
    root.addHandler(handler)


# --------------------------------------------------------------------------- #
# Sentry
# --------------------------------------------------------------------------- #


def init_sentry() -> bool:
    """Initialize Sentry error reporting if available + configured.

    No-op (returns False) when ``sentry-sdk`` isn't installed or ``SENTRY_DSN``
    is unset. Uses a low traces sample rate and reads the environment tag from
    ``ROGUE_ENV`` (default ``production``).
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        return False

    try:
        traces_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    except ValueError:
        traces_rate = 0.1

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("ROGUE_ENV", "production"),
        traces_sample_rate=traces_rate,
        integrations=[StarletteIntegration(), FastApiIntegration()],
    )
    logger.info("Sentry error reporting initialized")
    return True


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #

# Limits read from env with sane defaults. The default cap covers the read API;
# the tighter scan cap covers the money-spending scan-creation POST.
RATE_LIMIT_DEFAULT = os.environ.get("RATE_LIMIT_DEFAULT", "120/minute")
RATE_LIMIT_SCANS = os.environ.get("RATE_LIMIT_SCANS", "10/minute")

try:  # optional dep — absent in local/CI until pyproject adds it
    from slowapi import Limiter
    from slowapi.util import get_remote_address
except ImportError:  # pragma: no cover - exercised only when slowapi missing
    Limiter = None  # type: ignore[assignment,misc]
    get_remote_address = None  # type: ignore[assignment]


def rate_limiting_available() -> bool:
    """True iff slowapi is importable (so a Limiter can be built)."""
    return Limiter is not None


def get_limiter() -> Any:
    """A SlowAPI ``Limiter`` keyed by client IP, or ``None`` when slowapi is absent.

    Callers must tolerate ``None`` (decorators become no-ops, middleware is
    skipped) so the API runs identically with or without the dependency.
    """
    if Limiter is None:
        return None
    return Limiter(key_func=get_remote_address, default_limits=[RATE_LIMIT_DEFAULT])


__all__ = [
    "configure_logging",
    "init_sentry",
    "get_limiter",
    "rate_limiting_available",
    "RATE_LIMIT_DEFAULT",
    "RATE_LIMIT_SCANS",
]
