"""The ``searxng`` fetcher backend — self-hosted metasearch for SERP + image search.

`SearXNG <https://github.com/searxng/searxng>`_ aggregates 70+ search engines (Google, Bing,
DuckDuckGo, …) behind one JSON API. Self-hosted it is **free and unlimited** — the preferred SERP /
SERP_IMAGE backend when configured (ahead of BD's paid SERP and the keyless-Firecrawl / fragile
DuckDuckGo-HTML fallbacks). Point ``SEARXNG_URL`` at your instance (e.g. ``http://localhost:8888``);
the instance must have the JSON output format enabled (``search.formats: [html, json]`` in its
``settings.yml``).

Degrade-safe like the DuckDuckGo backend: any network/API failure returns an empty result rather
than raising — a search miss never crashes a harvest run.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

from rogue.harvest.bright_data_client import SerpResponse

from .base import Fetcher
from .capabilities import Capability

__all__ = ["SearXNGFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.searxng")

_UA = "Mozilla/5.0 (compatible; ROGUE-harvest/1.0; +https://rogue-eosin.vercel.app)"


class SearXNGFetcher(Fetcher):
    """SearXNG-backed SERP + image search. Capabilities: ``SERP``, ``SERP_IMAGE``."""

    name = "searxng"
    capabilities = frozenset({Capability.SERP, Capability.SERP_IMAGE})

    def __init__(self) -> None:
        self._base_url = os.environ.get("SEARXNG_URL", "").strip().rstrip("/")
        self._http: httpx.AsyncClient | None = None

    @classmethod
    def is_available(cls) -> bool:
        """True iff ``SEARXNG_URL`` is set (points at a self-hosted instance)."""
        return bool(os.environ.get("SEARXNG_URL", "").strip())

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"User-Agent": _UA, "Accept": "application/json"},
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._http

    async def _search(self, query: str, categories: str) -> dict[str, Any]:
        """GET the SearXNG JSON API for ``query`` in ``categories`` (e.g. 'general' / 'images')."""
        client = self._get_http()
        response = await client.get(
            "/search",
            params={"q": query, "format": "json", "categories": categories},
        )
        response.raise_for_status()
        return response.json()

    async def serp(self, query: str, count: int = 10, engine: str = "google") -> SerpResponse:
        """Web search via SearXNG (``categories=general``) → :class:`SerpResponse`.

        ``engine`` is accepted for contract compatibility but ignored — SearXNG manages its own
        engine set. Each result maps to an ``organic_results`` entry carrying both ``link`` and
        ``url`` (+ ``title``/``description``) for the harvest's tolerant URL extraction. Degrade-safe.
        """
        empty = SerpResponse(
            query=query,
            engine="searxng",
            fetched_at=datetime.now(timezone.utc),
            organic_results=[],
            knowledge_panel=None,
            raw_json={},
        )
        try:
            data = await self._search(query, "general")
            results = data.get("results") or []
            organic = [
                {
                    "link": r.get("url"),
                    "url": r.get("url"),
                    "title": r.get("title"),
                    "description": r.get("content"),
                    "snippet": r.get("content"),
                }
                for r in results[:count]
                if isinstance(r, dict) and r.get("url")
            ]
            return SerpResponse(
                query=query,
                engine="searxng",
                fetched_at=datetime.now(timezone.utc),
                organic_results=organic,
                knowledge_panel=None,
                raw_json={"result_count": len(organic)},
            )
        except Exception as exc:  # noqa: BLE001 — never crash a harvest run
            logger.warning("SearXNGFetcher.serp: %s — returning empty", exc)
            return empty

    async def serp_image(self, query: str, count: int = 5) -> list[str]:
        """Image search via SearXNG (``categories=images``) → up to ``count`` image URLs. Degrade-safe."""
        try:
            data = await self._search(query, "images")
            results = data.get("results") or []
            urls: list[str] = []
            for r in results:
                if not isinstance(r, dict):
                    continue
                candidate = r.get("img_src") or r.get("thumbnail_src") or r.get("url")
                if candidate and str(candidate).startswith("http"):
                    urls.append(candidate)
                if len(urls) >= count:
                    break
            return urls
        except Exception as exc:  # noqa: BLE001 — never crash a harvest run
            logger.warning("SearXNGFetcher.serp_image: %s — returning []", exc)
            return []

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
