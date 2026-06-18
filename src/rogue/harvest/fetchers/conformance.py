"""The fetcher conformance suite — structural, network-free.

Mirrors :mod:`rogue.core.conformance`: a single backend-agnostic checker every :class:`Fetcher` must
pass. It asserts the **structural** contract without touching the network:

  1. ``name`` is a non-empty string and ``capabilities`` is a ``frozenset[Capability]``.
  2. Every declared capability's method is actually **overridden** on the backend (not the inherited
     base method that raises :class:`CapabilityNotSupported`).
  3. Every **undeclared** capability's method, when called, raises :class:`CapabilityNotSupported`
     carrying this backend's name + that capability — proving the base guard is intact.

No HTTP, no credentials, no model call: the suite never invokes a *declared* capability (that would
hit the network), it only verifies wiring. Use :func:`assert_conforms` to fail loudly.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field

from .base import Fetcher
from .capabilities import Capability, CapabilityNotSupported

__all__ = ["FetcherConformanceReport", "check_conformance", "assert_conforms"]


# The method that backs each capability on the Fetcher base. ``aclose`` is lifecycle, not a
# capability, so it is intentionally absent.
_CAPABILITY_METHODS: dict[Capability, str] = {
    Capability.UNLOCK: "unlock",
    Capability.SERP: "serp",
    Capability.SERP_IMAGE: "serp_image",
    Capability.BROWSER: "browser",
    Capability.REDDIT: "reddit_subreddit",  # REDDIT also covers reddit_keyword; both must be overridden
    Capability.X: "x_user_posts",
    Capability.HF: "hf_discussion",
    Capability.IMAGE_BYTES: "fetch_image_bytes",
    Capability.REDIRECT: "resolve_redirect",
}

# Capabilities that map to MORE than one base method — all must be overridden when declared.
_EXTRA_CAPABILITY_METHODS: dict[Capability, tuple[str, ...]] = {
    Capability.REDDIT: ("reddit_keyword",),
}

# A minimal, never-executed argument tuple per method, so an *undeclared* capability can be invoked
# far enough to hit the base guard (which raises before any awaiting / IO).
_PROBE_ARGS: dict[str, tuple] = {
    "unlock": ("https://example.invalid",),
    "serp": ("probe",),
    "serp_image": ("probe",),
    "browser": ("https://example.invalid",),
    "reddit_subreddit": ("probe",),
    "reddit_keyword": ("probe",),
    "x_user_posts": ("https://x.com/probe",),
    "hf_discussion": ("org/model",),
    "fetch_image_bytes": ("https://example.invalid/x.png",),
    "resolve_redirect": ("https://t.co/probe",),
}


@dataclass
class FetcherConformanceReport:
    """Outcome of the structural suite. ``checks`` is an ordered list of ``(name, ok, detail)``."""

    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(ok for _, ok, _ in self.checks)

    @property
    def failures(self) -> list[tuple[str, bool, str]]:
        return [c for c in self.checks if not c[1]]

    def __str__(self) -> str:
        lines = [f"FetcherConformanceReport(passed={self.passed}, {len(self.checks)} checks)"]
        for name, ok, detail in self.checks:
            mark = "PASS" if ok else "FAIL"
            lines.append(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        return "\n".join(lines)


def _is_overridden(fetcher: Fetcher, method_name: str) -> bool:
    """True iff ``method_name`` is defined somewhere below :class:`Fetcher` in the MRO."""
    own = getattr(type(fetcher), method_name, None)
    base = getattr(Fetcher, method_name, None)
    if own is None or base is None:
        return False
    # Compare the underlying functions — a subclass that re-defines the coroutine yields a different
    # ``__func__`` / function object than the base's.
    return getattr(own, "__func__", own) is not getattr(base, "__func__", base)


def _raises_unsupported(fetcher: Fetcher, method_name: str) -> tuple[bool, str]:
    """Call ``method_name`` with probe args; expect :class:`CapabilityNotSupported` for this backend."""
    method = getattr(fetcher, method_name)
    args = _PROBE_ARGS[method_name]
    try:
        coro = method(*args)
    except CapabilityNotSupported as exc:  # synchronous raise (shouldn't happen, but accept it)
        return _validate_exc(fetcher, exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"expected CapabilityNotSupported, raised {type(exc).__name__}: {exc}"

    if not inspect.isawaitable(coro):
        return False, f"{method_name} did not return an awaitable"
    try:
        asyncio.run(_drain(coro))
    except CapabilityNotSupported as exc:
        return _validate_exc(fetcher, exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"expected CapabilityNotSupported, raised {type(exc).__name__}: {exc}"
    return False, f"{method_name} did not raise CapabilityNotSupported for an undeclared capability"


async def _drain(coro):
    return await coro


def _validate_exc(fetcher: Fetcher, exc: CapabilityNotSupported) -> tuple[bool, str]:
    if exc.backend_name != fetcher.name:
        return False, f"exception backend_name {exc.backend_name!r} != fetcher.name {fetcher.name!r}"
    if not isinstance(exc.capability, Capability):
        return False, f"exception.capability is {type(exc.capability).__name__}, not Capability"
    return True, ""


def check_conformance(fetcher: Fetcher) -> FetcherConformanceReport:
    """Run the full structural suite, collecting every result into a report (never raises)."""
    report = FetcherConformanceReport()

    def check(name: str, ok: bool, detail: str = "") -> None:
        report.checks.append((name, bool(ok), detail))

    # --- 1. identity ------------------------------------------------------------------------
    check(
        "name.nonempty",
        isinstance(fetcher.name, str) and bool(fetcher.name),
        "" if (isinstance(fetcher.name, str) and fetcher.name) else f"name={fetcher.name!r}",
    )
    caps = fetcher.capabilities
    caps_ok = isinstance(caps, frozenset) and all(isinstance(c, Capability) for c in caps)
    check(
        "capabilities.type",
        caps_ok,
        "" if caps_ok else f"capabilities must be frozenset[Capability], got {caps!r}",
    )

    # --- 2. declared capabilities → their methods are overridden ----------------------------
    for cap in (caps if caps_ok else frozenset()):
        method_names = (_CAPABILITY_METHODS[cap], *_EXTRA_CAPABILITY_METHODS.get(cap, ()))
        for mname in method_names:
            overridden = _is_overridden(fetcher, mname)
            check(
                f"declared.{cap.name}.{mname}.overridden",
                overridden,
                "" if overridden else f"{cap.name} declared but {mname}() not overridden",
            )

    # --- 3. undeclared capabilities → calling them raises CapabilityNotSupported ------------
    for cap, mname in _CAPABILITY_METHODS.items():
        if cap in caps:
            continue
        ok, detail = _raises_unsupported(fetcher, mname)
        check(f"undeclared.{cap.name}.{mname}.raises", ok, detail)

    return report


def assert_conforms(fetcher: Fetcher) -> FetcherConformanceReport:
    """Run the suite and raise :class:`AssertionError` (with failed-check details) on any failure.

    Returns the passing report on success so callers can still inspect it.
    """
    report = check_conformance(fetcher)
    if not report.passed:
        details = "\n".join(f"  - {name}: {detail}" for name, _, detail in report.failures)
        raise AssertionError(
            f"fetcher {type(fetcher).__name__} (name={fetcher.name!r}) failed conformance:\n{details}"
        )
    return report
