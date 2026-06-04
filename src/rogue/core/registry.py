""":class:`AdapterRegistry` — provider extensibility without ``if provider == ...``.

Business logic never names a provider. It asks the registry to ``create`` an adapter by name and then
talks only to the :class:`~rogue.adapters.base.TargetAdapter` interface. Adding a new provider is one
``register`` line and zero core changes (the Week-1 exit criterion).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .errors import ValidationError

if TYPE_CHECKING:
    from ..adapters.base import AdapterConfig, TargetAdapter


def _target_adapter_cls() -> type:
    # Lazy import keeps this module load acyclic (adapters.base imports core types, not the registry).
    from ..adapters.base import TargetAdapter

    return TargetAdapter


class AdapterRegistry:
    """A name → adapter-class registry. Construct adapters via :meth:`create`."""

    def __init__(self) -> None:
        self._adapters: dict[str, type] = {}

    def register(self, name: str, adapter_cls: type, *, overwrite: bool = False) -> type:
        """Register ``adapter_cls`` under ``name``. Returns the class (usable as a decorator)."""
        if not name:
            raise ValidationError("adapter name must be non-empty.")
        base = _target_adapter_cls()
        if not (isinstance(adapter_cls, type) and issubclass(adapter_cls, base)):
            raise ValidationError(
                f"{getattr(adapter_cls, '__name__', adapter_cls)!r} is not a TargetAdapter subclass."
            )
        if name in self._adapters and not overwrite:
            raise ValidationError(f"adapter {name!r} already registered (pass overwrite=True).")
        self._adapters[name] = adapter_cls
        return adapter_cls

    def decorator(self, name: str, *, overwrite: bool = False):
        """Class decorator form: ``@registry.decorator("xai")``."""

        def _wrap(adapter_cls: type) -> type:
            self.register(name, adapter_cls, overwrite=overwrite)
            return adapter_cls

        return _wrap

    def get(self, name: str) -> type:
        """The registered adapter *class* for ``name``."""
        try:
            return self._adapters[name]
        except KeyError:
            raise ValidationError(
                f"no adapter registered as {name!r}; known: {', '.join(self.list()) or '(none)'}"
            ) from None

    def create(self, name: str, config: AdapterConfig | Any) -> TargetAdapter:
        """Instantiate the adapter registered as ``name`` with ``config``."""
        return self.get(name)(config)

    def list(self) -> list[str]:
        return sorted(self._adapters)

    def unregister(self, name: str) -> None:
        self._adapters.pop(name, None)

    def __contains__(self, name: object) -> bool:
        return name in self._adapters

    def __len__(self) -> int:
        return len(self._adapters)


# Process-wide default registry. Adapters register into this (adapters/__init__ does so for built-ins).
registry = AdapterRegistry()


__all__ = ["AdapterRegistry", "registry"]
