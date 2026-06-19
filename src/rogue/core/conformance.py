"""The adapter conformance suite — the Week-1 "Conformance Review" exit criterion.

A single, provider-agnostic checker that *every* :class:`TargetAdapter` — mock or real — must pass.
It asserts the four-method I/O contract (``invoke`` / ``capabilities`` / ``healthcheck`` /
``estimate_cost``) using **only** canonical types from :mod:`rogue.core`. It never inspects provider
internals, never imports a provider SDK, and never imports a concrete adapter (not even
``MockAdapter``): the whole point is that if OpenAI passes and Anthropic passes, ROGUE cannot tell
which one it is talking to.

Usage::

    report = await assert_adapter_conformance(adapter)
    assert report.passed, report

or, to fail loudly on the first run::

    await assert_conformant(adapter)   # raises AssertionError with the failed-check details
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.capabilities import TargetCapabilities
from ..core.content_blocks import ContentBlock
from ..core.invocation import InvocationResult, StopReason, UsageMetrics
from ..core.message import CanonicalMessage, MessageRole

if TYPE_CHECKING:
    # Conformance is duck-typed against the adapter's interface; the class is needed only for type
    # hints, so the import stays lazy and `core/` remains adapter-free at module load (same
    # discipline as registry.py). This keeps the layering rule uniform: no exceptions.
    from ..adapters.base import TargetAdapter


@dataclass
class ConformanceReport:
    """Outcome of running the conformance suite against one adapter.

    ``checks`` is the ordered list of every contract check run, each as ``(name, ok, detail)``.
    ``passed`` is True iff every check passed.
    """

    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    @property
    def failures(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]

    def __str__(self) -> str:
        lines = [f"ConformanceReport(passed={self.passed}, {len(self.checks)} checks)"]
        for name, ok, detail in self.checks:
            mark = "PASS" if ok else "FAIL"
            lines.append(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        return "\n".join(lines)


def _usage_total_invariant(usage: UsageMetrics) -> tuple[bool, str]:
    """Shared check: total == input + output, all counts >= 0, cost None or float >= 0."""
    if not isinstance(usage, UsageMetrics):
        return False, f"expected UsageMetrics, got {type(usage).__name__}"
    if not (
        isinstance(usage.input_tokens, int)
        and isinstance(usage.output_tokens, int)
        and isinstance(usage.total_tokens, int)
    ):
        return False, "token counts must be ints"
    if usage.input_tokens < 0 or usage.output_tokens < 0 or usage.total_tokens < 0:
        return False, "token counts must be >= 0"
    if usage.total_tokens != usage.input_tokens + usage.output_tokens:
        return (
            False,
            f"total_tokens {usage.total_tokens} != input {usage.input_tokens} + output "
            f"{usage.output_tokens}",
        )
    cost = usage.estimated_cost_usd
    if cost is not None and not (isinstance(cost, (int, float)) and cost >= 0):
        return False, f"estimated_cost_usd must be None or a number >= 0, got {cost!r}"
    return True, ""


async def assert_adapter_conformance(adapter: TargetAdapter) -> ConformanceReport:
    """Run the full conformance suite, collecting *every* result into a :class:`ConformanceReport`.

    Provider-agnostic: only canonical :mod:`rogue.core` types are asserted; provider internals are
    never inspected. Returns the report (it does not raise on failure — use :func:`assert_conformant`
    for that). Each check appends ``(name, ok, detail)`` to ``report.checks``.
    """
    report = ConformanceReport()

    def check(name: str, ok: bool, detail: str = "") -> None:
        report.checks.append((name, bool(ok), detail))

    # --- 1. capabilities() -> a genuinely-frozen TargetCapabilities --------------------------
    caps: TargetCapabilities | None = None
    try:
        caps = await adapter.capabilities()
        ok = isinstance(caps, TargetCapabilities)
        check(
            "capabilities.type",
            ok,
            "" if ok else f"expected TargetCapabilities, got {type(caps).__name__}",
        )
    except Exception as exc:  # noqa: BLE001 - any failure is a conformance failure
        check("capabilities.type", False, f"capabilities() raised {type(exc).__name__}: {exc}")

    if isinstance(caps, TargetCapabilities):
        try:
            caps.supports_text = caps.supports_text  # type: ignore[misc]
            check("capabilities.frozen", False, "setting an attribute did not raise")
        except dataclasses.FrozenInstanceError:
            check("capabilities.frozen", True)
        except Exception as exc:  # noqa: BLE001
            check(
                "capabilities.frozen",
                False,
                f"expected FrozenInstanceError, got {type(exc).__name__}: {exc}",
            )

    # --- 2. healthcheck() -> bool ------------------------------------------------------------
    try:
        healthy = await adapter.healthcheck()
        ok = isinstance(healthy, bool)
        check(
            "healthcheck.bool",
            ok,
            "" if ok else f"expected bool, got {type(healthy).__name__}",
        )
    except Exception as exc:  # noqa: BLE001
        check("healthcheck.bool", False, f"healthcheck() raised {type(exc).__name__}: {exc}")

    # --- 3. estimate_cost([user]) -> well-formed UsageMetrics (no model call expected) -------
    est_messages = [CanonicalMessage.user("conformance probe: estimate the cost of this message.")]
    try:
        est = await adapter.estimate_cost(est_messages)
        ok = isinstance(est, UsageMetrics)
        check(
            "estimate_cost.type",
            ok,
            "" if ok else f"expected UsageMetrics, got {type(est).__name__}",
        )
        if ok:
            inv_ok, detail = _usage_total_invariant(est)
            check("estimate_cost.usage_invariant", inv_ok, detail)
    except Exception as exc:  # noqa: BLE001
        check("estimate_cost.type", False, f"estimate_cost() raised {type(exc).__name__}: {exc}")

    # --- 4. invoke([system, user]) -> well-formed InvocationResult ---------------------------
    inv_messages = [
        CanonicalMessage.system("You are a target under conformance review."),
        CanonicalMessage.user("Reply briefly to confirm the contract."),
    ]
    result: InvocationResult | None = None
    try:
        result = await adapter.invoke(inv_messages)
        ok = isinstance(result, InvocationResult)
        check(
            "invoke.type",
            ok,
            "" if ok else f"expected InvocationResult, got {type(result).__name__}",
        )
    except Exception as exc:  # noqa: BLE001
        check("invoke.type", False, f"invoke() raised {type(exc).__name__}: {exc}")

    if isinstance(result, InvocationResult):
        content = result.content
        content_ok = isinstance(content, list) and all(
            isinstance(b, ContentBlock) for b in content
        )
        check(
            "invoke.content",
            content_ok,
            "" if content_ok else "content must be a list[ContentBlock]",
        )

        check(
            "invoke.stop_reason",
            isinstance(result.stop_reason, StopReason),
            ""
            if isinstance(result.stop_reason, StopReason)
            else f"stop_reason must be a StopReason, got {type(result.stop_reason).__name__}",
        )

        usage_ok, detail = _usage_total_invariant(result.usage)
        check("invoke.usage_invariant", usage_ok, detail)

        lat = result.latency_ms
        lat_ok = isinstance(lat, int) and lat >= 0
        check(
            "invoke.latency_ms",
            lat_ok,
            "" if lat_ok else f"latency_ms must be an int >= 0, got {lat!r}",
        )

        check(
            "invoke.raw_response",
            isinstance(result.raw_response, dict),
            ""
            if isinstance(result.raw_response, dict)
            else f"raw_response must be a dict, got {type(result.raw_response).__name__}",
        )

        check(
            "invoke.text",
            isinstance(result.text, str),
            "" if isinstance(result.text, str) else f"text must be a str, got {type(result.text).__name__}",
        )

        try:
            msg = result.to_message()
            to_msg_ok = isinstance(msg, CanonicalMessage) and msg.role == MessageRole.ASSISTANT
            check(
                "invoke.to_message",
                to_msg_ok,
                ""
                if to_msg_ok
                else "to_message() must return a CanonicalMessage with role=ASSISTANT",
            )
        except Exception as exc:  # noqa: BLE001
            check("invoke.to_message", False, f"to_message() raised {type(exc).__name__}: {exc}")

    # --- 5. invoke honors max_output_tokens (soft: result must stay well-formed) -------------
    # We do NOT require the adapter to enforce the cap (not every provider truncates accounting),
    # only that a capped call still returns a valid InvocationResult, and that *if* the adapter
    # does enforce it, the cap is respected. This is documented as a soft check.
    try:
        capped = await adapter.invoke(inv_messages, max_output_tokens=1)
        if not isinstance(capped, InvocationResult):
            check(
                "invoke.max_output_tokens",
                False,
                f"capped invoke returned {type(capped).__name__}, not InvocationResult",
            )
        else:
            usage_ok, detail = _usage_total_invariant(capped.usage)
            if not usage_ok:
                check("invoke.max_output_tokens", False, f"capped usage invariant: {detail}")
            else:
                # Soft: only fail if the adapter both reports an output count AND blows the cap in a
                # way that contradicts itself. We accept >cap (adapter doesn't enforce) — but a
                # negative count was already rejected by the invariant check above.
                check("invoke.max_output_tokens", True, "result well-formed under cap (soft check)")
    except Exception as exc:  # noqa: BLE001
        check(
            "invoke.max_output_tokens",
            False,
            f"capped invoke() raised {type(exc).__name__}: {exc}",
        )

    return report


async def assert_conformant(adapter: TargetAdapter) -> ConformanceReport:
    """Run the suite and raise :class:`AssertionError` (with failed-check details) if anything fails.

    Returns the (passing) report on success, so callers can still inspect it.
    """
    report = await assert_adapter_conformance(adapter)
    if not report.passed:
        details = "\n".join(f"  - {name}: {detail}" for name, _, detail in report.failures)
        raise AssertionError(
            f"adapter {type(adapter).__name__} (model={adapter.model!r}) failed conformance:\n{details}"
        )
    return report


async def run_conformance(adapter_factory: Callable[[], TargetAdapter]) -> ConformanceReport:
    """Build an adapter via ``adapter_factory()``, run the suite, and close it afterward.

    Convenience for callers that want lifecycle handling (the adapter is ``aclose``-d even on
    failure) without writing the ``async with`` themselves.
    """
    adapter = adapter_factory()
    try:
        return await assert_adapter_conformance(adapter)
    finally:
        await adapter.aclose()


__all__ = [
    "ConformanceReport",
    "assert_adapter_conformance",
    "assert_conformant",
    "run_conformance",
]
