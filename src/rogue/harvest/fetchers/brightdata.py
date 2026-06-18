"""The Bright Data fetcher backend — wraps the existing :class:`BrightDataClient`.

This is the **default / first-preference** backend: with BD credentials present, every capability
routes here and harvest behaves exactly as it does today. It does NOT reimplement any HTTP — it holds
a :class:`~rogue.harvest.bright_data_client.BrightDataClient` instance and each capability method
delegates to the matching client method with the same arguments and return type.

**Cost logging.** Every wrapped client method (except ``resolve_redirect``) takes an optional
``session=`` used to insert ``BrightDataCostLog`` rows. The clean :class:`Fetcher` interface omits
``session`` deliberately, so the adapter holds the run ``session`` (injected at construction by the
harvest orchestrator) and threads it through internally. This keeps BD spend accounting — and the
SERP bandit that reads it — working without leaking a ``session`` param onto the backend-agnostic
Protocol. Free backends have negligible cost and log nothing.

Provider-specific code (the BD SDK surface, env vars, HTTP) is confined to this module — the
:mod:`~rogue.harvest.fetchers.base` Protocol and registry stay backend-agnostic, mirroring the
``core/`` ↔ ``adapters/`` layering rule.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rogue.harvest.bright_data_client import BrightDataClient

from .base import Fetcher
from .capabilities import Capability

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from rogue.harvest.bright_data_client import (
        HFDiscussion,
        RedditPost,
        ScrapedPage,
        SerpResponse,
        UnlockedPage,
        XPost,
    )

__all__ = ["BrightDataFetcher"]


class BrightDataFetcher(Fetcher):
    """All nine capabilities, delegated to a wrapped :class:`BrightDataClient`.

    ``session`` (optional) is threaded into every cost-logged client call so BD spend rows are still
    written when harvest routes through the abstraction. Construct with the run session via
    :meth:`from_env` (the orchestrator) or pass an existing client to :meth:`__init__`.
    """

    name = "brightdata"
    capabilities = frozenset(
        {
            Capability.UNLOCK,
            Capability.SERP,
            Capability.SERP_IMAGE,
            Capability.BROWSER,
            Capability.REDDIT,
            Capability.X,
            Capability.HF,
            Capability.IMAGE_BYTES,
            Capability.REDIRECT,
        }
    )

    def __init__(self, client: BrightDataClient, *, session: "Session | None" = None) -> None:
        self._client = client
        self._session = session

    @classmethod
    def from_env(cls, *, session: "Session | None" = None) -> "BrightDataFetcher":
        """Construct via the wrapped client's own env-detection path (``BrightDataClient.from_env``).

        ``session`` (the run DB session) is held and threaded into cost-logged calls; omit it for a
        no-cost-logging instance (e.g. the availability probe in ``build_default_registry``).
        """
        return cls(BrightDataClient.from_env(), session=session)

    # --- delegated capability methods (same args + return types as the client) ---------------
    # session=self._session is threaded into every cost-logged call (all but resolve_redirect).

    async def unlock(self, url: str, format: str = "markdown") -> "UnlockedPage":
        return await self._client.web_unlock(url, format=format, session=self._session)

    async def serp(
        self,
        query: str,
        count: int = 10,
        engine: str = "google",
    ) -> "SerpResponse":
        return await self._client.serp_search(query, count=count, engine=engine, session=self._session)

    async def serp_image(self, query: str, count: int = 5) -> list[str]:
        return await self._client.serp_image_search(query, count=count, session=self._session)

    async def browser(
        self,
        url: str,
        wait_for_selector: str | None = None,
        scroll_pages: int = 1,
        *,
        storage_state: dict[str, Any] | None = None,
    ) -> "ScrapedPage":
        return await self._client.scrape_browser(
            url,
            wait_for_selector=wait_for_selector,
            scroll_pages=scroll_pages,
            storage_state=storage_state,
            session=self._session,
        )

    async def reddit_subreddit(self, subreddit: str, limit: int = 100) -> list["RedditPost"]:
        return await self._client.scrape_reddit_subreddit(subreddit, limit=limit, session=self._session)

    async def reddit_keyword(
        self,
        keyword: str,
        date_range: str = "Past week",
        num_of_posts: int = 50,
    ) -> list["RedditPost"]:
        return await self._client.scrape_reddit_keyword(
            keyword, date_range=date_range, num_of_posts=num_of_posts, session=self._session
        )

    async def x_user_posts(self, profile_url: str, limit: int = 50) -> list["XPost"]:
        return await self._client.scrape_x_user_posts(profile_url, limit=limit, session=self._session)

    async def hf_discussion(self, model_id: str) -> list["HFDiscussion"]:
        return await self._client.scrape_huggingface_discussion(model_id, session=self._session)

    async def fetch_image_bytes(self, url: str) -> tuple[bytes, str]:
        return await self._client.fetch_image_bytes(url, session=self._session)

    async def resolve_redirect(self, url: str) -> str:
        # No session param on the client side — runs on a separate auth-less httpx client.
        return await self._client.resolve_redirect(url)

    async def aclose(self) -> None:
        """Close the wrapped client's shared HTTP pool. Idempotent."""
        await self._client.aclose()
