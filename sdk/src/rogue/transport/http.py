"""Production transport: HTTP over httpx, with retries tuned for the deployed ROGUE API.

The API runs on Render's free tier (sleeps after ~15 min idle, ~30–50s cold start) in front of a
Neon database that auto-suspends. So transient 502/503/504s and dropped sockets are *expected*, not
exceptional — we retry them with backoff. httpx is imported lazily so the package (and its
MockTransport-backed tests) import fine even where httpx isn't installed.
"""

from __future__ import annotations

import time
from typing import Any

from .._version import API_VERSION, __version__
from ..exceptions import APIConnectionError
from .base import Response, Transport

_RETRY_STATUS = {502, 503, 504}
_DEFAULT_TIMEOUT = 60.0  # generous: a cold Render boot can take tens of seconds


class HTTPTransport(Transport):
    """Talks to a real ROGUE Hosted API over HTTPS."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = 3,
        client: Any | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = client  # injectable for tests; otherwise lazily built
        self._owns_client = client is None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import httpx  # noqa: PLC0415
            except ImportError as e:  # pragma: no cover
                raise APIConnectionError(
                    "httpx is required for real HTTP requests; `pip install httpx`."
                ) from e
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._client

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        import httpx  # noqa: PLC0415 - safe; only reached after _get_client succeeds

        client = self._get_client()
        hdrs = {
            "User-Agent": f"rogue-python/{__version__}",
            "X-Rogue-Api-Version": API_VERSION,
            "Accept": "application/json",
            **(headers or {}),
        }
        # Drop None query params so they don't serialize as the string "None".
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = client.request(
                    method, path, params=clean_params or None, json=json, headers=hdrs
                )
            except httpx.HTTPError as e:
                last_exc = e
                if attempt < self.max_retries:
                    time.sleep(self._backoff(attempt))
                    continue
                raise APIConnectionError(f"could not reach ROGUE API at {self.base_url}: {e}") from e

            if resp.status_code in _RETRY_STATUS and attempt < self.max_retries:
                time.sleep(self._backoff(attempt))
                continue

            return Response(
                status_code=resp.status_code,
                data=self._parse(resp),
                headers={k.lower(): v for k, v in resp.headers.items()},
            )

        # Unreachable in practice; satisfies type-checkers.
        raise APIConnectionError(  # pragma: no cover
            f"could not reach ROGUE API at {self.base_url}: {last_exc}"
        )

    @staticmethod
    def _parse(resp: Any) -> Any:
        if not resp.content:
            return None
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                return resp.json()
            except ValueError:
                return None
        return resp.text

    @staticmethod
    def _backoff(attempt: int) -> float:
        # 1.5s, 3s, 6s — matches the dashboard's apiGet retry profile for Render cold boots.
        return 1.5 * (2**attempt)

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None


__all__ = ["HTTPTransport"]
