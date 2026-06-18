"""Scraper-agnostic harvest backends — the :class:`Fetcher` abstraction.

ROGUE's harvest is decoupled from Bright Data by routing every fetch through a backend-agnostic
:class:`Fetcher` interface. Bright Data is the default / first-preference backend (wrapping the
existing :class:`~rogue.harvest.bright_data_client.BrightDataClient`); free/keyless backends slot in
behind it (Wave 1) so the harvest→scan loop can run without a BD account.

Mirrors the ``core/`` ↔ ``adapters/`` provider-abstraction pattern: harvest code asks the
:class:`FetcherRegistry` for "a backend that supports capability X" and talks only to the
:class:`Fetcher` interface — provider specifics live in the per-backend modules.
"""

from __future__ import annotations

from .base import Fetcher
from .brightdata import BrightDataFetcher
from .capabilities import Capability, CapabilityNotSupported
from .registry import FetcherRegistry, build_default_registry, is_keyless_harvest
from .routing import RoutingFetcher

__all__ = [
    "Fetcher",
    "Capability",
    "CapabilityNotSupported",
    "FetcherRegistry",
    "build_default_registry",
    "is_keyless_harvest",
    "BrightDataFetcher",
    "RoutingFetcher",
]
