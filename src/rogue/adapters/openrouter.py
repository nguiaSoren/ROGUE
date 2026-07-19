"""OpenRouter target adapter — fronts Mistral / Google / Llama for ROGUE.

Ports the panel's OpenRouter branch (the ``mistralai/`` / ``google/`` / ``meta-llama/`` prefixes).
Critically, OpenRouter routes by the FULL ``provider/model`` string, so — unlike the OpenAI and Groq
adapters — the prefix is NOT stripped: the wire model id equals ``config.model``. The provider slug
is the model's own prefix (``mistralai`` / ``google`` / ``meta-llama``), falling back to
``openrouter`` when there is no prefix.

**Provider pinning (reproducibility, Audit-7 item 1).** OpenRouter load-balances one model across
several backend providers, so two byte-identical requests can hit different silicon and drift.
Passing ``AdapterConfig.extra["provider_pin"]`` pins the backend via OpenRouter's per-request
``extra_body={"provider": {...}}`` routing preferences (``order`` + ``allow_fallbacks: false``), so a
reproduction run always lands on the same provider. Absent/empty → the request body is byte-identical
to an un-pinned call. Because ``adapters/openai_compat`` (the shared invoke path) is intentionally not
touched, the pin is injected by wrapping the client so every ``chat.completions.create`` carries the
``extra_body`` — ``models.list`` (healthcheck) and every other call pass through untouched.
"""

from __future__ import annotations

import os
from typing import Any

from .base import AdapterConfig
from .openai_compat import OpenAICompatAdapter

__all__ = ["OpenRouterAdapter", "PROVIDER_PIN_KEY", "build_provider_pin"]

# AdapterConfig.extra key carrying the pin. Value is either the OpenRouter ``provider`` routing object
# (a dict, e.g. ``{"order": ["fireworks"], "allow_fallbacks": False}``) or a bare list of provider
# slugs (shorthand → ``{"order": [...], "allow_fallbacks": False}``). Absent/None/empty ⇒ no pinning.
PROVIDER_PIN_KEY = "provider_pin"


def build_provider_pin(
    order: list[str], *, allow_fallbacks: bool = False, **extra: Any
) -> dict[str, Any]:
    """Build the OpenRouter ``provider`` routing object for a pinned, reproducible backend.

    ``order`` is the preferred provider slug list; ``allow_fallbacks=False`` (the default) forbids
    OpenRouter from silently rerouting to another backend — the whole point of pinning. Extra
    OpenRouter routing keys (``require_parameters``, ``quantizations``, …) pass through via ``extra``.
    """
    return {"order": list(order), "allow_fallbacks": allow_fallbacks, **extra}


def _normalize_pin(raw: Any) -> dict[str, Any] | None:
    """Coerce the ``provider_pin`` config into the OpenRouter ``provider`` object, or None if unset."""
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (list, tuple)):
        return build_provider_pin(list(raw))
    return None


class _PinnedCompletions:
    """Proxy over ``chat.completions`` that folds ``extra_body`` into every ``create`` call."""

    def __init__(self, inner: Any, extra_body: dict[str, Any]) -> None:
        self._inner = inner
        self._extra_body = extra_body

    async def create(self, **kwargs: Any) -> Any:
        # Merge without clobbering a caller-supplied extra_body; the pin's ``provider`` key wins.
        kwargs["extra_body"] = {**(kwargs.get("extra_body") or {}), **self._extra_body}
        return await self._inner.create(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _PinnedChat:
    """Proxy over ``client.chat`` exposing a pinning ``completions``; everything else passes through."""

    def __init__(self, inner: Any, extra_body: dict[str, Any]) -> None:
        self._inner = inner
        self.completions = _PinnedCompletions(inner.completions, extra_body)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _PinnedClient:
    """Thin wrapper injecting ``extra_body`` into ``chat.completions.create`` only.

    ``models.list`` (healthcheck), ``close``, and every other attribute delegate to the real client
    unchanged, so the wrapper is invisible except for the one call that carries the pin.
    """

    def __init__(self, inner: Any, extra_body: dict[str, Any]) -> None:
        self._inner = inner
        self.chat = _PinnedChat(inner.chat, extra_body)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class OpenRouterAdapter(OpenAICompatAdapter):
    """OpenRouter — ``https://openrouter.ai/api/v1``, full ``provider/model`` sent as the wire id."""

    def __init__(self, config: AdapterConfig):
        super().__init__(config)
        self._base_url = "https://openrouter.ai/api/v1"
        self._api_key = config.api_key or os.environ.get("OPENROUTER_API_KEY")
        self._wire_model = config.model  # do NOT strip — OpenRouter routes by the full id
        self._price_key = config.model
        # Reproducibility pin (opt-in). None ⇒ un-pinned, request body byte-identical to before.
        pin = _normalize_pin(config.extra.get(PROVIDER_PIN_KEY))
        self._pin_extra_body: dict[str, Any] | None = {"provider": pin} if pin else None

    @property
    def provider(self) -> str:
        model = self.config.model
        return model.split("/", 1)[0] if "/" in model else "openrouter"

    def _client(self) -> Any:
        """Return the base OpenAI-compatible client, wrapped to inject the provider pin when set.

        Un-pinned (``self._pin_extra_body is None``) returns the base client untouched, so behavior is
        byte-identical to the shared ``OpenAICompatAdapter`` path. ``aclose`` still closes the real
        ``_owned_client`` (the base, not the wrapper), so cleanup is unaffected.
        """
        base = super()._client()
        if self._pin_extra_body is None:
            return base
        return _PinnedClient(base, self._pin_extra_body)
