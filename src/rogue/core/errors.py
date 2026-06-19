"""Canonical adapter error hierarchy (Week-1 core layer).

Every provider fails differently — OpenAI 429, Anthropic 529, Gemini ``RESOURCE_EXHAUSTED`` — but
ROGUE above the adapter boundary must branch on *one* taxonomy, never a provider status integer.
Adapters translate their provider's failures into these types (the provider-specific mapping lives in
``adapters/``, per architecture Rule 1 — this module imports no provider SDK).

Today ROGUE collapses failures into a flat ``ModelResponse.error`` string with informal prefixes
(``rate_limit_exhausted:``, ``content_policy_or_bad_request:``, ``http_status_<n>:``). This hierarchy
is the structured replacement those prefixes map onto.
"""

from __future__ import annotations

from typing import Any


class AdapterError(Exception):
    """Base for every error raised by a target adapter.

    ``retryable`` tells the engine's retry layer whether a backoff-and-retry could plausibly help
    (transient) vs. is pointless (auth, validation, content policy).
    """

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        status_code: int | None = None,
        retry_after: float | None = None,
        raw: Any = None,
        retryable: bool | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.retry_after = retry_after
        self.raw = raw
        if retryable is not None:
            self.retryable = retryable

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        bits = [b for b in (self.provider, f"HTTP {self.status_code}" if self.status_code else None) if b]
        return f"{self.message} ({', '.join(bits)})" if bits else self.message


class AuthenticationError(AdapterError):
    """Missing/invalid/expired credentials (e.g. 401/403). Not retryable."""

    retryable = False


class RateLimitError(AdapterError):
    """Provider throttling (OpenAI 429 / Anthropic 529 / Gemini RESOURCE_EXHAUSTED). Retryable."""

    retryable = True


class TimeoutError(AdapterError):  # noqa: A001 - intentionally shadows builtin within this namespace
    """The provider call exceeded its deadline. Retryable."""

    retryable = True


class ProviderError(AdapterError):
    """A provider-side failure (typically 5xx / upstream error). Retryable by default."""

    retryable = True


class ValidationError(AdapterError):
    """The request was malformed or rejected as a bad request (4xx other than auth/rate). Not retryable."""

    retryable = False


class ContentPolicyError(ProviderError):
    """Provider refused/blocked on content policy or a guardrail (often surfaced as a 400).

    Extension beyond the base five: ROGUE is a *red-team* tool, so a content-policy block is a
    first-class, interesting signal (a target defending), not a generic error — and it is **not**
    retryable, unlike its ``ProviderError`` parent.
    """

    retryable = False


def from_http_status(
    status_code: int,
    *,
    provider: str | None = None,
    message: str | None = None,
    raw: Any = None,
    retry_after: float | None = None,
) -> AdapterError:
    """Map a bare HTTP status to the canonical error type (provider-agnostic).

    Adapters that can distinguish a content-policy block from a generic bad request should raise
    :class:`ContentPolicyError` directly rather than relying on this 400→ValidationError default.
    """
    msg = message or f"request failed with HTTP {status_code}"
    if status_code in (401, 403):
        return AuthenticationError(msg, provider=provider, status_code=status_code, raw=raw)
    if status_code == 408:
        return TimeoutError(msg, provider=provider, status_code=status_code, raw=raw)
    if status_code == 429:
        return RateLimitError(
            msg, provider=provider, status_code=status_code, retry_after=retry_after, raw=raw
        )
    if status_code == 400:
        return ValidationError(msg, provider=provider, status_code=status_code, raw=raw)
    if 500 <= status_code < 600:
        return ProviderError(msg, provider=provider, status_code=status_code, raw=raw)
    return ProviderError(msg, provider=provider, status_code=status_code, raw=raw)


def is_retryable(exc: BaseException) -> bool:
    """True if ``exc`` is an adapter error worth retrying (transient)."""
    return isinstance(exc, AdapterError) and exc.retryable


__all__ = [
    "AdapterError",
    "AuthenticationError",
    "RateLimitError",
    "TimeoutError",
    "ProviderError",
    "ValidationError",
    "ContentPolicyError",
    "from_http_status",
    "is_retryable",
]
