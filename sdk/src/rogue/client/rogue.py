"""The :class:`Rogue` client — the one object a customer imports.

    from rogue import Rogue
    rogue = Rogue(api_key="...")
    deployment = rogue.register(name="Support Agent", model="gpt-5", system_prompt="...")
    report = rogue.scan(deployment)
    print(report.summary())

Composes the auth manager + resource clients, owns the shared ``_request`` (headers, transparent
token refresh), and exposes the ergonomic sugar (`register`, `scan`, `scan_async`, `register_*`).
"""

from __future__ import annotations

import os
from typing import Any

from .._version import API_VERSION, __version__
from ..adapters import get_adapter
from ..exceptions import AuthenticationError
from ..models.deployment import Deployment
from ..models.report import Report
from ..models.scan import Scan
from ..transport.base import Transport
from ..transport.http import HTTPTransport
from ..utils import config as _config
from ..utils.validation import validate_api_key, validate_base_url
from .auth import AuthManager
from .deployments import DeploymentsClient
from .reports import ReportsClient
from .scans import ScansClient

DEFAULT_BASE_URL = "https://rogue-api-mr5w.onrender.com"


class Rogue:
    """Entry point to the ROGUE red-team platform."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        transport: Transport | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        """Create a client.

        :param api_key: ROGUE API key. Falls back to the ``ROGUE_API_KEY`` env var.
        :param base_url: Hosted API base URL. Falls back to ``ROGUE_BASE_URL`` then the default.
        :param transport: Inject a custom transport (e.g. ``MockTransport()`` for offline use).
            When given, ``base_url`` is ignored and ``api_key`` is optional.
        """
        # API key resolution order: explicit arg > env > stored credentials (`rogue login`).
        if api_key is None:
            api_key = os.environ.get("ROGUE_API_KEY") or _config.load_api_key()

        if transport is None:
            resolved = validate_base_url(
                base_url
                or os.environ.get("ROGUE_BASE_URL")
                or _config.load_base_url()
                or DEFAULT_BASE_URL
            )
            api_key = validate_api_key(api_key)  # a real API requires a key up front
            transport = HTTPTransport(resolved, timeout=timeout, max_retries=max_retries)
            self.base_url: str | None = resolved
        else:
            # Custom/mock transport: a key is still sent to the (mock) auth endpoint; default it.
            api_key = api_key or "demo"
            self.base_url = getattr(transport, "base_url", None)

        self._transport = transport
        self._auth = AuthManager(transport, api_key)
        self._telemetry: Any = None  # opt-in; enabled via env or enable_telemetry()

        self.deployments = DeploymentsClient(self)
        self.scans = ScansClient(self)
        self.reports = ReportsClient(self)

        self._maybe_enable_telemetry_from_env()

    # --- versioning (Deliverable 11) ----------------------------------------------------------

    @property
    def api_version(self) -> str:
        """The wire-contract version this client speaks (sent as X-Rogue-Api-Version)."""
        return API_VERSION

    @property
    def sdk_version(self) -> str:
        return __version__

    # --- shared request path ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        """Authenticated request with one transparent refresh-and-retry on token expiry."""
        self._auth.ensure()
        try:
            return self._transport.request_json(
                method, path, params=params, json=json, headers=self._auth.header()
            )
        except AuthenticationError as e:
            if e.code in ("token_expired", "invalid_token"):
                self._auth.refresh()
                return self._transport.request_json(
                    method, path, params=params, json=json, headers=self._auth.header()
                )
            raise

    # --- auth sugar (Deliverable 3) -----------------------------------------------------------

    def login(self) -> Rogue:
        """Eagerly authenticate (otherwise the first call authenticates lazily)."""
        self._auth.login()
        self._emit("login")
        return self

    def logout(self) -> None:
        self._auth.logout()

    @property
    def is_authenticated(self) -> bool:
        return self._auth.is_authenticated

    # --- deployment sugar (Deliverable 4) -----------------------------------------------------

    def register(
        self,
        name: str | None = None,
        model: str | None = None,
        *,
        deployment: Deployment | None = None,
        system_prompt: str | None = None,
        tools: list[str] | None = None,
        forbidden_topics: list[str] | None = None,
        provider: str | None = None,
    ) -> Deployment:
        """Register a deployment to red-team. See :meth:`DeploymentsClient.register`."""
        dep = self.deployments.register(
            name=name,
            model=model,
            deployment=deployment,
            system_prompt=system_prompt,
            tools=tools,
            forbidden_topics=forbidden_topics,
            provider=provider,
        )
        self._emit("deployment_registered")
        return dep

    def update(self, deployment: Deployment | str, **changes) -> Deployment:
        return self.deployments.update(deployment, **changes)

    # --- scan sugar (Deliverable 5) -----------------------------------------------------------

    def scan(
        self,
        deployment: Deployment | str | None = None,
        *,
        deployment_id: str | None = None,
        n_trials: int = 5,
        options: dict[str, Any] | None = None,
        timeout: float | None = None,
        poll_interval: float = 3.0,
    ) -> Report:
        """Run a scan and **block** until the report is ready. Returns the :class:`Report`.

        Raises :class:`ScanFailedError` if the scan fails, :class:`ScanTimeoutError` on ``timeout``.
        """
        job = self.scan_async(
            deployment, deployment_id=deployment_id, n_trials=n_trials, options=options
        )
        job.wait(timeout=timeout, poll_interval=poll_interval)
        report = job.report()
        self._emit("scan_completed", n_findings=len(report.findings))
        return report

    def scan_async(
        self,
        deployment: Deployment | str | None = None,
        *,
        deployment_id: str | None = None,
        n_trials: int = 5,
        options: dict[str, Any] | None = None,
    ) -> Scan:
        """Start a scan and return immediately with a :class:`Scan` job handle."""
        job = self.scans.start(
            deployment, deployment_id=deployment_id, n_trials=n_trials, options=options
        )
        self._emit("scan_started")
        return job

    # --- provider registration (Deliverable 8) ------------------------------------------------

    def register_provider(self, provider: str, *, label: str | None = None, **credentials) -> dict:
        """Register provider credentials ROGUE uses to reach the model when scanning.

        Customers use the typed helpers below; this is the generic escape hatch.
        """
        adapter = get_adapter(provider)
        payload = adapter.to_payload(label=label, **credentials)
        result = self._request("POST", "/v1/providers", json=payload)
        self._emit("provider_registered", provider=provider)
        return result

    def register_openai(self, api_key: str, *, label: str | None = None, **kw) -> dict:
        return self.register_provider("openai", label=label, api_key=api_key, **kw)

    def register_anthropic(self, api_key: str, *, label: str | None = None, **kw) -> dict:
        return self.register_provider("anthropic", label=label, api_key=api_key, **kw)

    def register_vertex(
        self, *, project: str, location: str, label: str | None = None, **kw
    ) -> dict:
        return self.register_provider(
            "vertex", label=label, project=project, location=location, **kw
        )

    def register_custom(self, *, base_url: str, label: str | None = None, **kw) -> dict:
        return self.register_provider("custom", label=label, base_url=base_url, **kw)

    def providers(self) -> list[dict]:
        data = self._request("GET", "/v1/providers")
        return data.get("providers", [])

    # --- telemetry seam (Deliverable 12) ------------------------------------------------------

    def enable_telemetry(self, *, endpoint: str | None = None) -> Rogue:
        """Turn on anonymous, opt-in usage telemetry (never sends prompts or customer data)."""
        try:
            from ..utils.telemetry import Telemetry

            self._telemetry = Telemetry(
                enabled=True, endpoint=endpoint, sdk_version=self.sdk_version
            )
        except Exception:  # telemetry is strictly optional
            self._telemetry = None
        return self

    def disable_telemetry(self) -> Rogue:
        self._telemetry = None
        return self

    def _maybe_enable_telemetry_from_env(self) -> None:
        try:
            from ..utils.telemetry import Telemetry

            tel = Telemetry.from_env(sdk_version=self.sdk_version)
            self._telemetry = tel if getattr(tel, "enabled", False) else None
        except Exception:
            self._telemetry = None

    def _emit(self, event: str, **fields) -> None:
        """Fire an opt-in telemetry event. No-op unless telemetry was enabled."""
        if self._telemetry is not None:
            try:
                self._telemetry.emit(event, **fields)
            except Exception:  # telemetry must never break a customer call
                pass

    # --- lifecycle ----------------------------------------------------------------------------

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> Rogue:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Rogue(base_url={self.base_url!r}, api_version={self.api_version!r})"


__all__ = ["Rogue", "DEFAULT_BASE_URL"]
