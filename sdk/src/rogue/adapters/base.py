"""Provider adapters (Deliverable 8): the customer-facing seam for registering model credentials.

Customers never touch these directly — they call ``rogue.register_openai(api_key=...)`` etc. Each
adapter knows the *shape* of one provider's credentials (which fields are required), validates them
locally, normalizes the model id, and produces the ``POST /v1/providers`` payload. This is where
future scale comes from: adding a provider = adding one small adapter, no client changes.
"""

from __future__ import annotations

from ..exceptions import ValidationError


class Adapter:
    """Base adapter. Subclasses declare ``provider``, ``required``, and ``optional`` fields."""

    provider: str = ""
    required: tuple[str, ...] = ("api_key",)
    optional: tuple[str, ...] = ()

    def build_credentials(self, **kwargs) -> dict:
        """Validate + collect the credential fields for this provider. Raises ValidationError."""
        creds = {k: v for k, v in kwargs.items() if v is not None}
        missing = [f for f in self.required if not creds.get(f)]
        if missing:
            raise ValidationError(
                f"{self.provider or 'provider'}: missing required credential(s): "
                f"{', '.join(missing)}",
                fields=missing,
            )
        allowed = set(self.required) | set(self.optional)
        unknown = sorted(set(creds) - allowed)
        if unknown:
            raise ValidationError(
                f"{self.provider or 'provider'}: unexpected credential field(s): "
                f"{', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})",
                fields=unknown,
            )
        return creds

    def normalize_model(self, model: str) -> str:
        """Return the model id in the form this provider expects (identity by default)."""
        return model

    def to_payload(self, *, label: str | None = None, **kwargs) -> dict:
        """Build the ``POST /v1/providers`` request body."""
        return {
            "provider": self.provider,
            "label": label or "default",
            "credentials": self.build_credentials(**kwargs),
        }


class _GenericAdapter(Adapter):
    """Fallback for an unregistered provider: requires an api_key, accepts a base_url."""

    required = ("api_key",)
    optional = ("base_url", "organization", "project", "location", "credentials_json", "headers")

    def __init__(self, provider: str):
        self.provider = provider


_REGISTRY: dict[str, Adapter] = {}


def register_adapter(adapter: Adapter) -> None:
    """Register an adapter instance under its ``provider`` name."""
    if not adapter.provider:
        raise ValueError("adapter must declare a non-empty .provider")
    _REGISTRY[adapter.provider] = adapter


def get_adapter(provider: str) -> Adapter:
    """Return the registered adapter for ``provider``, or a generic fallback."""
    return _REGISTRY.get(provider) or _GenericAdapter(provider)


def registered_providers() -> list[str]:
    return sorted(_REGISTRY)


__all__ = [
    "Adapter",
    "register_adapter",
    "get_adapter",
    "registered_providers",
]
