"""ROGUE SDK exception hierarchy.

Everything raised by the SDK derives from :class:`RogueError`, so callers can do a single
``except RogueError`` and be exhaustive. Transport maps HTTP status + ``error.code`` (see
CONTRACT.md) onto these types so application code branches on a type, never a status integer.
"""

from __future__ import annotations

from typing import Any


class RogueError(Exception):
    """Base class for every error raised by the ROGUE SDK."""


# --- local / client-side (raised before any network call) -------------------------------------


class RogueConfigError(RogueError):
    """Misconfiguration of the client itself: missing API key, malformed base URL, no credentials."""


class ValidationError(RogueError):
    """A local validation check failed before a request was sent.

    Carries the offending field(s) so the message can point precisely at what to fix.
    """

    def __init__(self, message: str, *, field: str | None = None, fields: list[str] | None = None):
        super().__init__(message)
        self.field = field
        self.fields = fields or ([field] if field else [])


# --- API errors (a request reached the server and it answered non-2xx) -------------------------


class APIError(RogueError):
    """A request reached the API but it returned an error (default for 5xx / unmapped codes)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.details = details or {}
        self.request_id = request_id

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        base = super().__str__()
        bits = [b for b in (self.code, f"HTTP {self.status_code}" if self.status_code else None) if b]
        return f"{base} ({', '.join(bits)})" if bits else base


class AuthenticationError(APIError):
    """401 — the API key / access token is missing, invalid, or expired."""


class AuthorizationError(APIError):
    """403 — authenticated, but not permitted to perform this action."""


class NotFoundError(APIError):
    """404 — the requested resource does not exist."""


class ConflictError(APIError):
    """409 — the request conflicts with current state (e.g. duplicate)."""


class RateLimitError(APIError):
    """429 — too many requests. ``retry_after`` is seconds to wait, if the server provided it."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class APIConnectionError(RogueError):
    """Could not reach the API at all: DNS failure, connection refused, timeout, dropped socket."""


# --- scan lifecycle ----------------------------------------------------------------------------


class ScanError(RogueError):
    """Base for scan-lifecycle problems."""


class ScanFailedError(ScanError):
    """A scan finished in the ``failed`` state. ``scan`` is the final scan object."""

    def __init__(self, message: str, *, scan: Any = None):
        super().__init__(message)
        self.scan = scan


class ScanTimeoutError(ScanError):
    """``scan()`` / ``wait()`` exceeded the caller's timeout while the job was still running."""

    def __init__(self, message: str, *, scan: Any = None):
        super().__init__(message)
        self.scan = scan


__all__ = [
    "RogueError",
    "RogueConfigError",
    "ValidationError",
    "APIError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "APIConnectionError",
    "ScanError",
    "ScanFailedError",
    "ScanTimeoutError",
]
