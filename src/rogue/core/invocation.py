"""The normalized result of one model call: :class:`InvocationResult` (+ usage and stop reason).

Every provider returns a different response shape, token accounting, and finish reason. This is the
one shape ROGUE sees. ``raw_response`` always preserves the provider's untouched output (debugging,
auditing, future features) — we normalize, we never discard.

Maps onto today's ``ModelResponse`` (``content``/``latency_ms``/``tokens_in``/``tokens_out``/``cost_usd``),
and fills the gap it has: a real, normalized :class:`StopReason` (target finish reasons are currently
dropped — only the judge reads Anthropic's).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .content_blocks import ContentBlock, TextBlock, ToolCallBlock
from .message import CanonicalMessage, MessageRole


class StopReason(str, Enum):
    COMPLETE = "complete"
    LENGTH = "length"
    TOOL_CALL = "tool_call"
    SAFETY = "safety"
    ERROR = "error"

    @classmethod
    def from_provider(cls, value: str | None) -> StopReason:
        """Normalize a provider finish/stop reason string to a canonical :class:`StopReason`.

        Covers the OpenAI (``stop``/``length``/``tool_calls``/``content_filter``) and Anthropic
        (``end_turn``/``max_tokens``/``tool_use``/``refusal``/``stop_sequence``) vocabularies; unknown
        or ``None`` → ``COMPLETE``.
        """
        if not value:
            return cls.COMPLETE
        v = value.lower()
        mapping = {
            "stop": cls.COMPLETE,
            "end_turn": cls.COMPLETE,
            "stop_sequence": cls.COMPLETE,
            "complete": cls.COMPLETE,
            "length": cls.LENGTH,
            "max_tokens": cls.LENGTH,
            "tool_calls": cls.TOOL_CALL,
            "tool_use": cls.TOOL_CALL,
            "function_call": cls.TOOL_CALL,
            "content_filter": cls.SAFETY,
            "refusal": cls.SAFETY,
            "safety": cls.SAFETY,
            "error": cls.ERROR,
        }
        return mapping.get(v, cls.COMPLETE)


@dataclass
class UsageMetrics:
    """Token accounting for one call. ``total_tokens`` defaults to input+output if not set."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if not self.total_tokens:
            self.total_tokens = self.input_tokens + self.output_tokens

    @classmethod
    def from_io(
        cls, input_tokens: int, output_tokens: int, *, estimated_cost_usd: float | None = None
    ) -> UsageMetrics:
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )


@dataclass
class InvocationResult:
    """The normalized outcome of a single :meth:`TargetAdapter.invoke` call."""

    content: list[ContentBlock] = field(default_factory=list)
    usage: UsageMetrics = field(default_factory=UsageMetrics)
    stop_reason: StopReason = StopReason.COMPLETE
    latency_ms: int = 0
    raw_response: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Concatenated text of all returned :class:`TextBlock`s."""
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))

    @property
    def tool_calls(self) -> list[ToolCallBlock]:
        return [b for b in self.content if isinstance(b, ToolCallBlock)]

    @property
    def is_refusal(self) -> bool:
        return self.stop_reason == StopReason.SAFETY

    def to_message(self) -> CanonicalMessage:
        """Wrap the returned content as an assistant :class:`CanonicalMessage`."""
        return CanonicalMessage(role=MessageRole.ASSISTANT, content=list(self.content))


__all__ = ["StopReason", "UsageMetrics", "InvocationResult"]
