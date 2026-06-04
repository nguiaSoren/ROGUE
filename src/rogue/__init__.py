"""ROGUE — open-web LLM threat intelligence + red-team SDK. See ROGUE_PLAN.md.

Customer SDK — point it at a model and scan::

    from rogue import Client
    client = Client(endpoint="https://api.company.com/v1", api_key="...")
    report = client.scan()
    print(report.summary())

The SDK surface (``Client`` + the report objects) is exposed lazily via PEP-562 ``__getattr__`` so a
bare ``import rogue`` (used widely across the platform's internals) stays cheap and free of import
cycles — the adapter/report machinery only loads when you actually touch ``rogue.Client``.
"""

from __future__ import annotations

__all__ = ["Client", "ScanReport", "Finding", "ValidationResult", "BenchmarkReport"]

_REPORT_NAMES = {"ScanReport", "Finding", "ValidationResult", "BenchmarkReport"}


def __getattr__(name: str):  # PEP 562
    if name == "Client":
        from .client import Client

        return Client
    if name in _REPORT_NAMES:
        from . import report

        return getattr(report, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
