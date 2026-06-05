"""Transport abstraction: how the SDK actually moves bytes to/from the Hosted API.

A ``Transport`` only knows how to send one request and hand back a :class:`Response`. Error mapping
(HTTP status + ``error.code`` → typed exception, per CONTRACT.md) is shared here in
:meth:`Transport.request_json`, so :class:`~rogue.transport.http.HTTPTransport` and
:class:`~rogue.transport.mock.MockTransport` behave identically to the layers above them.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from ..exceptions import (
    APIError,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)


@dataclass
class Response:
    """A transport-level response: HTTP status, parsed JSON body (or None), and headers."""

    status_code: int
    data: Any = None
    headers: dict[str, str] = field(default_factory=dict)


# error.code → exception class (takes precedence over the status-based fallback).
_CODE_MAP: dict[str, type[APIError]] = {
    "invalid_request": ValidationError,  # type: ignore[dict-item]
    "validation_error": ValidationError,  # type: ignore[dict-item]
    "invalid_api_key": AuthenticationError,
    "invalid_token": AuthenticationError,
    "token_expired": AuthenticationError,
    "forbidden": AuthorizationError,
    "not_found": NotFoundError,
    "conflict": ConflictError,
    "rate_limited": RateLimitError,
}

# HTTP status → exception class (fallback when error.code is missing/unknown).
_STATUS_MAP: dict[int, type[APIError]] = {
    400: ValidationError,  # type: ignore[dict-item]
    401: AuthenticationError,
    403: AuthorizationError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def raise_for_response(resp: Response) -> None:
    """Raise the appropriate typed exception for a non-2xx response. No-op for 2xx."""
    if 200 <= resp.status_code < 300:
        return

    body = resp.data if isinstance(resp.data, dict) else {}
    err = body.get("error") if isinstance(body.get("error"), dict) else {}
    code = err.get("code")
    message = err.get("message") or f"request failed with HTTP {resp.status_code}"
    details = err.get("details") if isinstance(err.get("details"), dict) else {}
    request_id = resp.headers.get("x-request-id") or resp.headers.get("X-Request-Id")

    exc_cls: type[APIError] = (
        _CODE_MAP.get(code or "") or _STATUS_MAP.get(resp.status_code) or APIError
    )

    if exc_cls is ValidationError:
        raise ValidationError(message, fields=list(details.keys()) or None)

    kwargs: dict[str, Any] = dict(
        status_code=resp.status_code, code=code, details=details, request_id=request_id
    )
    if exc_cls is RateLimitError:
        retry = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
        try:
            retry_after = float(retry) if retry is not None else None
        except ValueError:
            retry_after = None
        raise RateLimitError(message, retry_after=retry_after, **kwargs)

    raise exc_cls(message, **kwargs)


class Transport(abc.ABC):
    """Send one request, return a :class:`Response`. Subclasses implement :meth:`request`."""

    @abc.abstractmethod
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        """Perform the request. ``path`` is contract-relative (e.g. ``/v1/scans``)."""
        raise NotImplementedError

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Request, raise typed exceptions on non-2xx, and return the parsed JSON body on success."""
        resp = self.request(method, path, params=params, json=json, headers=headers)
        raise_for_response(resp)
        return resp.data

    def close(self) -> None:  # pragma: no cover - default no-op
        """Release any held resources (overridden by HTTPTransport)."""


__all__ = ["Response", "Transport", "raise_for_response"]
