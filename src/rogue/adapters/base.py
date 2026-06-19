"""The :class:`TargetAdapter` base interface (Week-1 deliverable 6).

This is the only seam ROGUE crosses to reach a model. Above this line lives provider-neutral code
(``CanonicalMessage`` in, ``InvocationResult`` out); below it, and *only* below it, lives
provider-specific translation and SDK imports (architecture Rules 1–3). Four methods, all required,
all async, none provider-specific:

    invoke         CanonicalMessage[] -> InvocationResult
    capabilities   -> TargetCapabilities
    healthcheck    -> bool
    estimate_cost  CanonicalMessage[] -> UsageMetrics (no model call)

Every adapter — real or mock — must pass the same conformance suite (``core/conformance``). If OpenAI
and Anthropic both pass, ROGUE cannot tell which one it is talking to.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from ..core.capabilities import TargetCapabilities
from ..core.invocation import InvocationResult, UsageMetrics
from ..core.message import CanonicalMessage


@dataclass
class AdapterConfig:
    """Everything an adapter needs to reach one target. Credentials never leave the adapter layer."""

    model: str
    api_key: str | None = None
    base_url: str | None = None
    timeout_s: float = 90.0
    max_retries: int = 2
    extra: dict = field(default_factory=dict)


class TargetAdapter(abc.ABC):
    """Abstract base every provider adapter implements."""

    def __init__(self, config: AdapterConfig):
        self.config = config

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def provider(self) -> str:
        """Provider slug — the prefix of ``model`` (``openai/gpt-5`` → ``openai``), else the class name."""
        if "/" in self.config.model:
            return self.config.model.split("/", 1)[0]
        return type(self).__name__.removesuffix("Adapter").lower()

    @abc.abstractmethod
    async def invoke(
        self,
        messages: list[CanonicalMessage],
        *,
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        **kwargs,
    ) -> InvocationResult:
        """Send ``messages`` to the target and return a normalized :class:`InvocationResult`.

        Implementations translate canonical messages → provider wire format, call the provider, and
        translate the response back. Provider failures are raised as ``rogue.core.errors`` types.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def capabilities(self) -> TargetCapabilities:
        """What this target supports (drives routing). May be static or probed."""
        raise NotImplementedError

    @abc.abstractmethod
    async def healthcheck(self) -> bool:
        """Whether the target is reachable and credentials are valid. Should not raise on a clean down."""
        raise NotImplementedError

    @abc.abstractmethod
    async def estimate_cost(
        self, messages: list[CanonicalMessage], *, max_output_tokens: int | None = None
    ) -> UsageMetrics:
        """Estimate token usage + cost for ``messages`` **without** calling the model."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release any held clients. Default no-op; override for SDK clients."""

    async def __aenter__(self) -> TargetAdapter:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()


__all__ = ["TargetAdapter", "AdapterConfig"]
