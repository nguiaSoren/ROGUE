"""Authentication (Deliverable 3): API key → short-lived access token, with refresh.

Flow: ``api_key`` → ``POST /v1/auth/token`` → access + refresh tokens. The access token is attached
as ``Authorization: Bearer`` on every subsequent request; on expiry the SDK refreshes transparently
(see :meth:`Rogue._request`). The manager is in-memory; the CLI's ``rogue login`` persists the API
key via :mod:`rogue.utils.config`.
"""

from __future__ import annotations

from typing import Any

from ..exceptions import AuthenticationError, RogueConfigError


class AuthManager:
    """Holds the API key and the current access/refresh tokens for one client."""

    def __init__(self, transport: Any, api_key: str | None):
        self._transport = transport
        self._api_key = api_key
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    @property
    def api_key(self) -> str | None:
        return self._api_key

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def is_authenticated(self) -> bool:
        return self._access_token is not None

    def login(self) -> AuthManager:
        """Exchange the API key for tokens. Raises RogueConfigError if no key is set."""
        if not self._api_key:
            raise RogueConfigError(
                "No API key. Pass Rogue(api_key=...) or set ROGUE_API_KEY (or run `rogue login`)."
            )
        data = self._transport.request_json(
            "POST", "/v1/auth/token", json={"api_key": self._api_key}
        )
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token")
        return self

    def logout(self) -> None:
        """Drop the in-memory tokens (does not delete a persisted API key)."""
        self._access_token = None
        self._refresh_token = None

    def ensure(self) -> str:
        """Return a usable access token, logging in on first use."""
        if not self._access_token:
            self.login()
        return self._access_token  # type: ignore[return-value]

    def refresh(self) -> str:
        """Refresh the access token; fall back to a full re-login if refresh is unavailable."""
        if self._refresh_token:
            try:
                data = self._transport.request_json(
                    "POST", "/v1/auth/refresh", json={"refresh_token": self._refresh_token}
                )
                self._access_token = data["access_token"]
                return self._access_token
            except AuthenticationError:
                pass  # refresh token rejected → fall through to full login
        self.login()
        return self._access_token  # type: ignore[return-value]

    def header(self) -> dict[str, str]:
        """Authorization header from the *current* token (call :meth:`ensure` first)."""
        return {"Authorization": f"Bearer {self._access_token}"} if self._access_token else {}


__all__ = ["AuthManager"]
