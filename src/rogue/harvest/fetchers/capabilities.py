"""The :class:`Capability` enum — the unit of fetcher dispatch.

One member per distinct capability the :class:`~rogue.harvest.bright_data_client.BrightDataClient`
exposes. A :class:`~rogue.harvest.fetchers.base.Fetcher` backend declares the subset it supports
(``capabilities: frozenset[Capability]``); the :class:`~rogue.harvest.fetchers.registry.FetcherRegistry`
resolves a source's required capabilities to a concrete backend per capability.

This module imports no provider SDK and nothing under :mod:`rogue.harvest` — it is the leaf of the
fetcher package's dependency graph, mirroring the layering discipline of :mod:`rogue.core`.
"""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    """A distinct fetch capability, mapped 1:1 to a ``BrightDataClient`` method group.

    ``str``-valued so a capability serializes to its name in logs / env (``ROGUE_FETCHER_ORDER``
    is keyed on backend names, but capability membership is printed in warnings).
    """

    UNLOCK = "unlock"            # anti-bot HTTP GET → html/markdown (web_unlock)
    SERP = "serp"                # web search → structured results (serp_search)
    SERP_IMAGE = "serp_image"    # image search → candidate image URLs (serp_image_search)
    BROWSER = "browser"          # JS / heavy-anti-bot render → html (scrape_browser)
    REDDIT = "reddit"            # structured subreddit listing + keyword search
    X = "x"                      # structured user timeline (scrape_x_user_posts)
    HF = "hf"                    # structured HF discussions (scrape_huggingface_discussion)
    IMAGE_BYTES = "image_bytes"  # raw image byte fetch (fetch_image_bytes)
    REDIRECT = "redirect"        # resolve shortlink → final url (resolve_redirect)


class CapabilityNotSupported(Exception):
    """Raised when a backend is asked for a capability it does not declare.

    Carries ``backend_name`` + ``capability`` so the registry / caller can log precisely which
    backend declined which capability without re-deriving it from the traceback.
    """

    def __init__(self, backend_name: str, capability: Capability) -> None:
        self.backend_name = backend_name
        self.capability = capability
        super().__init__(
            f"fetcher backend {backend_name!r} does not support capability {capability.name}"
        )


__all__ = ["Capability", "CapabilityNotSupported"]
