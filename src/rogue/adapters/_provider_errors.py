"""Provider-SDK exception handling — retry predicate + mapping to the canonical error hierarchy.

This is the one place the adapters layer touches provider-SDK exception *types* (OpenAI / Anthropic),
so it imports them lazily and tolerates their absence. Adapters apply :data:`with_provider_retry` to
their inner call and, on a final exception, translate it via :func:`map_provider_exception` into a
``rogue.core.errors`` type. Mirrors the retry policy + error categories that lived in
``target_panel.py`` (``_is_retryable`` + the ``rate_limit_exhausted`` / ``content_policy_or_bad_request``
/ ``http_status_*`` outcomes), so the migration preserves behavior exactly.
"""

from __future__ import annotations

import asyncio

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from ..core.errors import (
    AdapterError,
    AuthenticationError,
    ContentPolicyError,
    ProviderError,
    RateLimitError,
)

_RETRY_STATUS = {429, 500, 502, 503, 504}

_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,  # builtin
    asyncio.TimeoutError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
)


def _provider_exc_classes():
    """Lazily import the OpenAI + Anthropic SDK exception classes (None when not installed)."""
    try:
        from openai import APIStatusError as OAStatus  # noqa: PLC0415
        from openai import BadRequestError as OABad  # noqa: PLC0415
        from openai import RateLimitError as OARate  # noqa: PLC0415
    except ImportError:
        OAStatus = OABad = OARate = None  # type: ignore[assignment]
    try:
        from anthropic import APIStatusError as ANStatus  # noqa: PLC0415
        from anthropic import BadRequestError as ANBad  # noqa: PLC0415
        from anthropic import RateLimitError as ANRate  # noqa: PLC0415
    except ImportError:
        ANStatus = ANBad = ANRate = None  # type: ignore[assignment]
    return {
        "rate": tuple(c for c in (OARate, ANRate) if c is not None),
        "bad": tuple(c for c in (OABad, ANBad) if c is not None),
        "status": tuple(c for c in (OAStatus, ANStatus) if c is not None),
    }


def is_retryable_exception(exc: BaseException) -> bool:
    """Retry on network transients, provider RateLimitError, and 5xx/429 APIStatusError/HTTPStatusError.

    4xx other than 429 are NOT retried (deterministic: bad request / auth / content-policy refusal).
    Verbatim port of ``target_panel._is_retryable``.
    """
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    classes = _provider_exc_classes()
    if classes["rate"] and isinstance(exc, classes["rate"]):
        return True
    if classes["status"] and isinstance(exc, classes["status"]):
        if getattr(exc, "status_code", None) in _RETRY_STATUS:
            return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRY_STATUS
    return False


# Apply to an adapter's inner provider call: 3 attempts, exp backoff 1→10s, reraise on exhaustion.
with_provider_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(is_retryable_exception),
    reraise=True,
)


def map_provider_exception(exc: BaseException, *, provider: str | None = None) -> AdapterError | None:
    """Translate a provider-SDK / httpx exception into a canonical :class:`AdapterError`.

    Returns ``None`` for an exception that is not a recognized provider failure, so the caller can
    re-raise the original (we never mask an unexpected bug as a ProviderError). Category mapping
    matches the panel's legacy outcomes:
      provider RateLimitError        -> RateLimitError       (was ``rate_limit_exhausted``)
      provider BadRequestError       -> ContentPolicyError   (was ``content_policy_or_bad_request``)
      provider APIStatusError (5xx)  -> ProviderError        (was ``http_status_<n>``)
      httpx.HTTPStatusError          -> ProviderError / Auth / RateLimit by status
    """
    classes = _provider_exc_classes()
    msg = str(exc)

    if classes["rate"] and isinstance(exc, classes["rate"]):
        return RateLimitError(msg, provider=provider, status_code=429, raw=exc)
    if classes["bad"] and isinstance(exc, classes["bad"]):
        return ContentPolicyError(
            msg, provider=provider, status_code=getattr(exc, "status_code", 400), raw=exc
        )
    if classes["status"] and isinstance(exc, classes["status"]):
        status = getattr(exc, "status_code", None)
        if status in (401, 403):
            return AuthenticationError(msg, provider=provider, status_code=status, raw=exc)
        return ProviderError(msg, provider=provider, status_code=status, raw=exc)
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return AuthenticationError(msg, provider=provider, status_code=status, raw=exc)
        if status == 429:
            return RateLimitError(msg, provider=provider, status_code=status, raw=exc)
        return ProviderError(msg, provider=provider, status_code=status, raw=exc)
    return None


__all__ = [
    "is_retryable_exception",
    "with_provider_retry",
    "map_provider_exception",
]
