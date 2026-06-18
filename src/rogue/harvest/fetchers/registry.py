""":class:`FetcherRegistry` — per-capability backend resolution, Bright Data first.

Mirrors :class:`rogue.core.registry.AdapterRegistry`: harvest code never names a backend, it asks the
registry for "a fetcher that supports capability X" and talks only to the :class:`Fetcher` interface.

Resolution is **per capability** along a preference order (default: ``brightdata`` first, so with BD
credentials present everything routes through BD = today's behavior). The free backends (Wave 1) slot
in behind BD; a backend self-registers only if its creds/deps are present, so when BD is absent
resolution falls through to whatever free backend supports the capability — the "run it free" path.

Preference order is overridable via the ``ROGUE_FETCHER_ORDER`` env var (csv of backend names).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from .base import Fetcher
from .capabilities import Capability

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("rogue.harvest.fetchers.registry")

__all__ = ["FetcherRegistry", "DEFAULT_PREFERENCE_ORDER", "build_default_registry"]


# Default backend preference order — BD FIRST (pre-loaded / first entry). When BD is absent, the
# robust free scrapers (crawl4ai, firecrawl) outrank the plain httpx `direct` backend for UNLOCK and
# the bare `playwright` backend for BROWSER — they handle JS/anti-bot that `direct` can't — so they
# win when installed/configured, falling back to direct/playwright otherwise. (Each only registers if
# its own is_available() says so, so listing it here is harmless when absent.)
# `searxng` (self-hosted metasearch) is the preferred SERP/SERP_IMAGE backend when configured — free,
# unlimited, ahead of BD's paid SERP and Firecrawl/ddg. `local_pdf` is the preferred PDF parser
# (always on: pypdf core floor + pymupdf4llm upgrade) — it's pdf_only, so it never serves general
# UNLOCK; the PDF guard reaches it for PDF URLs ahead of Firecrawl. Both lead only for the
# capabilities they serve, so they never disturb UNLOCK/BROWSER.
DEFAULT_PREFERENCE_ORDER: tuple[str, ...] = (
    "searxng",
    "local_pdf",
    "brightdata",
    "crawl4ai",
    "firecrawl",
    "direct",
    "ddg",
    "hf_api",
    "reddit_oauth",
    "playwright",
    "x_besteffort",
)


def _preference_order() -> list[str]:
    """The active preference order — ``ROGUE_FETCHER_ORDER`` (csv) if set, else the default."""
    raw = os.environ.get("ROGUE_FETCHER_ORDER", "").strip()
    if not raw:
        return list(DEFAULT_PREFERENCE_ORDER)
    names = [n.strip() for n in raw.split(",") if n.strip()]
    return names or list(DEFAULT_PREFERENCE_ORDER)


class FetcherRegistry:
    """A name → :class:`Fetcher` registry that resolves capabilities along a preference order."""

    def __init__(self, preference_order: list[str] | None = None) -> None:
        self._fetchers: dict[str, Fetcher] = {}
        # Resolved once at construction so the env is read at registry-build time, not per lookup.
        self._order: list[str] = preference_order if preference_order is not None else _preference_order()

    def register(self, fetcher: Fetcher, *, overwrite: bool = False) -> Fetcher:
        """Register ``fetcher`` under its ``name``. Returns it (so callers can keep a handle)."""
        if not isinstance(fetcher, Fetcher):
            raise TypeError(f"{fetcher!r} is not a Fetcher instance.")
        name = fetcher.name
        if not name:
            raise ValueError("fetcher.name must be a non-empty string.")
        if name in self._fetchers and not overwrite:
            raise ValueError(f"fetcher {name!r} already registered (pass overwrite=True).")
        self._fetchers[name] = fetcher
        return fetcher

    def for_capability(self, capability: Capability) -> Fetcher | None:
        """First registered backend (in preference order) that supports ``capability``, else None.

        Backends named in the preference order win first, in order. Any registered backend NOT named
        in the order is considered last (in registration order), so an unknown backend is still usable
        but never out-prioritizes a named one.
        """
        ordered = self._ordered_fetchers()
        for fetcher in ordered:
            # PDF specialists declare UNLOCK but only handle PDFs — never resolve them for general
            # (HTML) UNLOCK; the RoutingFetcher PDF guard reaches them directly for PDF URLs.
            if fetcher.pdf_only and capability is Capability.UNLOCK:
                continue
            if capability in fetcher.capabilities:
                return fetcher
        return None

    def resolve(self, required: frozenset[Capability]) -> dict[Capability, Fetcher | None]:
        """Map each required capability to the backend that will serve it (None if unresolved).

        A caller (a source / phase) inspects the result: if any value is None the capability is
        unmet — the caller should skip the source with a warning, never raise (spec §4).
        """
        return {cap: self.for_capability(cap) for cap in required}

    def get(self, name: str) -> Fetcher | None:
        """The registered fetcher for ``name``, or None."""
        return self._fetchers.get(name)

    def list(self) -> list[str]:
        """Registered backend names, in active preference order (unknown names appended)."""
        return [f.name for f in self._ordered_fetchers()]

    def _ordered_fetchers(self) -> list[Fetcher]:
        """Registered fetchers sorted by the preference order; unlisted ones appended last."""
        ranked: list[Fetcher] = []
        for name in self._order:
            f = self._fetchers.get(name)
            if f is not None:
                ranked.append(f)
        # Any registered backend not named in the order goes last, in registration order.
        for name, f in self._fetchers.items():
            if name not in self._order:
                ranked.append(f)
        return ranked

    def __contains__(self, name: object) -> bool:
        return name in self._fetchers

    def __len__(self) -> int:
        return len(self._fetchers)


def _brightdata_available() -> bool:
    """True iff the Bright Data env credentials are present enough to construct a usable client.

    Reuses the client's own ``from_env`` env-detection (which scrubs the ``.env`` inline-comment
    footgun) and checks the REQUIRED fields are non-empty: API key + the three zones. The optional
    dataset_ids (reddit/x/hf) may be unset — those capabilities simply error at call time, but the
    backend is still the right default for unlock/serp/browser/image/redirect.
    """
    from rogue.harvest.bright_data_client import BrightDataClient

    try:
        client = BrightDataClient.from_env()
    except Exception:  # noqa: BLE001 — any construction failure → BD self-excludes
        return False
    return bool(
        client.api_key
        and client.serp_zone
        and client.unlocker_zone
        and client.browser_zone
    )


def build_default_registry(
    *,
    session: "Session | None" = None,
    brightdata_client: object | None = None,
) -> FetcherRegistry:
    """Build the process registry, registering each backend only if its creds/deps are present.

    Bright Data is the default / first-preference backend: it is registered when ``brightdata_client``
    is supplied (the orchestrator passes its already-constructed client — also lets tests inject a
    double) or, failing that, when BD env credentials are present (``from_env``). ``session`` (the run
    DB session) is threaded into the BD backend so its cost-logged calls still write
    ``BrightDataCostLog`` rows when harvest routes through the abstraction; free backends ignore it.

    The free / keyless backends (``direct`` / ``ddg`` / ``hf_api`` / ``reddit_oauth`` /
    ``x_besteffort`` / ``playwright``) register behind BD, each only if its own ``is_available()`` says
    so (always-on for direct/ddg/hf/x; reddit needs ``REDDIT_CLIENT_ID/SECRET``; playwright needs the
    optional ``rogue[browser]`` extra installed). So with BD keys present everything routes through BD
    (today's behavior); with BD absent, resolution falls through to whatever free backend serves each
    capability — the "run it free" path. A backend whose construction raises is skipped with a warning.
    """
    from .brightdata import BrightDataFetcher

    registry = FetcherRegistry()

    if brightdata_client is not None:
        registry.register(BrightDataFetcher(brightdata_client, session=session))  # type: ignore[arg-type]
        logger.debug("registered fetcher backend: brightdata (injected client)")
    elif _brightdata_available():
        registry.register(BrightDataFetcher.from_env(session=session))
        logger.debug("registered fetcher backend: brightdata")
    else:
        logger.warning(
            "Bright Data credentials absent — 'brightdata' backend not registered. "
            "Free backends will serve supported capabilities; capabilities only BD covers "
            "(e.g. structured reddit/x via BD) fall to their free equivalents or are skipped."
        )

    # Free / keyless backends, each gated by its own availability check. crawl4ai + firecrawl are the
    # robust UNLOCK/BROWSER scrapers (preferred over `direct`/`playwright` per DEFAULT_PREFERENCE_ORDER
    # when available); crawl4ai needs the `rogue[crawl4ai]` extra + chromium, firecrawl needs
    # FIRECRAWL_BASE_URL or FIRECRAWL_API_KEY — their is_available() gates handle absence.
    from .crawl4ai import Crawl4AIFetcher
    from .ddg import DuckDuckGoFetcher
    from .direct import DirectFetcher
    from .firecrawl import FirecrawlFetcher
    from .hf_api import HFApiFetcher
    from .local_pdf import LocalPdfFetcher
    from .playwright import PlaywrightFetcher
    from .reddit_oauth import RedditOAuthFetcher
    from .searxng import SearXNGFetcher
    from .x_besteffort import XBestEffortFetcher

    for backend_cls in (
        SearXNGFetcher,  # preferred SERP / SERP_IMAGE when SEARXNG_URL is set (free, unlimited)
        LocalPdfFetcher,  # preferred PDF parser — always on (pypdf floor + pymupdf4llm upgrade)
        Crawl4AIFetcher,
        FirecrawlFetcher,
        DirectFetcher,
        DuckDuckGoFetcher,
        HFApiFetcher,
        RedditOAuthFetcher,
        XBestEffortFetcher,
        PlaywrightFetcher,
    ):
        try:
            if backend_cls.is_available():
                registry.register(backend_cls())
                logger.debug("registered fetcher backend: %s", backend_cls.name)
        except Exception:  # noqa: BLE001 — a flaky backend never blocks the registry
            logger.warning("fetcher backend %s failed to register; skipping", backend_cls.name, exc_info=True)

    _maybe_autoenable_firecrawl_keyless(registry)
    return registry


def is_keyless_harvest(registry: FetcherRegistry) -> bool:
    """True when the harvest is on the rate-limited free path — no Bright Data and no crawl4ai (the
    two unlimited UNLOCK backends), and Firecrawl (if present) is keyless (no API key). Used to scope
    a first-run harvest to high-yield sources so the limited keyless rate budget isn't wasted."""
    if registry.get("brightdata") is not None or registry.get("crawl4ai") is not None:
        return False
    fc = registry.get("firecrawl")
    if fc is not None and getattr(fc, "_api_key", None) is not None:
        return False  # a Firecrawl API key has real budget → don't cap
    return True


def _maybe_autoenable_firecrawl_keyless(registry: FetcherRegistry) -> None:
    """When NO robust scraper is configured (no Bright Data, no crawl4ai, no Firecrawl key/URL),
    auto-enable Firecrawl's KEYLESS free tier so a first-run harvest gets a real anti-bot
    UNLOCK/BROWSER/SERP backend instead of plain httpx ``direct`` + DuckDuckGo-HTML.

    Transparent (one-time notice) and overridable: it does NOT fire if ``firecrawl`` already
    registered (key/URL/keyless explicitly set) or if a robust backend (``brightdata``/``crawl4ai``)
    is present, and ``FIRECRAWL_KEYLESS=0`` opts out entirely (keep the plain free path).
    """
    if registry.get("firecrawl") is not None:
        return  # already configured (key/url/keyless) — nothing to do
    if any(registry.get(n) is not None for n in ("brightdata", "crawl4ai")):
        return  # a robust scraper is already serving UNLOCK/BROWSER
    if os.environ.get("FIRECRAWL_KEYLESS", "").strip().lower() in {"0", "false", "no", "off"}:
        return  # explicit opt-out

    from .firecrawl import FirecrawlFetcher

    try:
        # The constructor's no-key branch already operates keylessly (cloud base, no Authorization);
        # registering the instance directly avoids mutating the process env.
        registry.register(FirecrawlFetcher())
    except Exception:  # noqa: BLE001 — never block the registry on the auto-enable
        logger.warning("firecrawl keyless auto-enable failed; using direct/ddg", exc_info=True)
        return
    logger.warning(
        "No scraper configured — auto-enabled Firecrawl's KEYLESS free tier (real anti-bot "
        "UNLOCK/BROWSER/SERP, no account). NOTE: fetched URLs are sent to Firecrawl's free service, "
        "which is rate-limited (per-IP/day). For the full harvest install crawl4ai (free/local/"
        "unlimited: `pip install \"rogue[crawl4ai]\"`) or set FIRECRAWL_API_KEY / BRIGHTDATA_*. "
        "Set FIRECRAWL_KEYLESS=0 to keep the plain direct+DuckDuckGo path."
    )
