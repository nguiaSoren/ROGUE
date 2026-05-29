"""Wave-2 harvest-layer test suite — BrightDataClient bodies + 7 source plugins.

Purpose
    Validate the parsing logic of the harvest layer without ever touching the
    live Bright Data API. Complements ``tests/test_smoke.py`` (which only
    checks import surface + table metadata + alembic round-trip) by exercising
    the actual call-path logic that ships in Wave 2.

Strategy
    * ``BrightDataClient`` tests: build a real ``BrightDataClient`` but swap
      its lazily-constructed ``httpx.AsyncClient`` for one wired to
      ``httpx.MockTransport`` (built-in, no new dep). Canonical response
      payloads are lifted from ``website/`` — SERP shape from
      ``SERP-API/parsed-json-results/parsing-search-results.md``, Reddit /
      Twitter shapes from ``WEB SCRAPER API/*/send-first-request.md``,
      Web Unlocker body shape from ``WEB-UNLOCKER/send-your-first-request.md``.
    * Plugin tests: each plugin is fed an in-test ``FakeBrightDataClient``
      stub exposing only the methods the plugin under test calls; the stub
      returns canned Pydantic models so the plugin's parser is exercised
      end-to-end without an HTTP layer at all.

Reference: ROGUE_PLAN.md §9.2 (Day-1 BrightDataClient bodies) + §9.3
(source-plugin abstraction) + tasks/todo.md §9 (Wave-2 pre-build gate).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from rogue.harvest.bright_data_client import (
    BrightDataClient,
    HFDiscussion,
    RedditPost,
    ScrapedPage,
    SerpResponse,
    UnlockedPage,
    XPost,
)
from rogue.harvest.sources.arxiv_listing import ArxivListingPlugin
from rogue.harvest.sources.base import SourcePlugin
from rogue.harvest.sources.blog_static import BlogStaticPlugin, BlogTarget
from rogue.harvest.sources.community_archive import (
    ArchiveTarget,
    CommunityArchivePlugin,
)
from rogue.harvest.sources.github_search import GithubSearchPlugin
from rogue.harvest.sources.huggingface_discussion import (
    HuggingFaceDiscussionPlugin,
)
from rogue.harvest.sources.leakhub_scrape import (
    DEFAULT_PROVIDERS as LEAKHUB_DEFAULT_PROVIDERS,
    LeakHubScrapePlugin,
)
from rogue.harvest.sources.obliteratus_hf import (
    DEFAULT_MODELS as OBLITERATUS_DEFAULT_MODELS,
    HF_ACTIVITY_URL,
    HF_ORG_SLUG,
    ObliteratusHfPlugin,
    _readme_url,
)
from rogue.harvest.sources.pliny_github import (
    L1B3RT4S_ORG_FILES,
    L1B3RT4S_RAW_PREFIX,
    L1B3RT4S_SPECIAL_FILES,
    PlinyGithubPlugin,
    _cl4r1t4s_raw_url,
    _l1b3rt4s_raw_url,
)
from rogue.harvest.sources.reddit_subreddit import RedditSubredditPlugin
from rogue.harvest.sources.x_user_timeline import XUserTimelinePlugin
from rogue.schemas import RawDocument

# --------------------------------------------------------------------------- #
# Module-level helpers
# --------------------------------------------------------------------------- #

SINCE = datetime(2026, 5, 20, tzinfo=timezone.utc)
NEWER = datetime(2026, 5, 23, tzinfo=timezone.utc)
OLDER = datetime(2026, 5, 18, tzinfo=timezone.utc)


def _make_client(
    transport: httpx.MockTransport,
    *,
    api_key: str = "test-api-key",
    reddit_dataset_id: str | None = "gd_test_reddit",
    x_posts_dataset_id: str | None = "gd_test_x",
    hf_dataset_id: str | None = None,
) -> BrightDataClient:
    """Build a ``BrightDataClient`` whose internal ``httpx.AsyncClient`` uses
    the supplied ``MockTransport``.

    We construct the AsyncClient eagerly so the same ``Authorization`` /
    ``Content-Type`` headers the production code sets are preserved — the
    only swap is the transport.
    """
    client = BrightDataClient(
        api_key=api_key,
        serp_zone="test_serp_zone",
        unlocker_zone="test_unlocker_zone",
        browser_zone="test_browser_zone",
        reddit_dataset_id=reddit_dataset_id,
        x_posts_dataset_id=x_posts_dataset_id,
        hf_dataset_id=hf_dataset_id,
    )
    client._http = httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    return client


# Canonical SERP parsed_light shape per
# website/SERP-API/parsed-json-results/parsing-search-results.md (lines 287-...).
SERP_PARSED_LIGHT_PIZZA = {
    "organic": [
        {
            "rank": 1,
            "title": "Pizza - Wikipedia",
            "link": "https://en.wikipedia.org/wiki/Pizza",
            "description": (
                "Pizza is an Italian dish consisting of a flat base of "
                "leavened wheat-based dough topped with tomato, cheese, "
                "and other ingredients."
            ),
        },
        {
            "rank": 2,
            "title": "Pizza Hut | Delivery & Carryout",
            "link": "https://www.pizzahut.com/",
            "description": "Order pizza online for fast delivery.",
        },
    ],
}

# Canonical Reddit Web Scraper API record per
# website/WEB SCRAPER API/reddit/send-first-request.md (lines 88-108).
REDDIT_RECORD_TEMPLATE = {
    "post_id": "1asdf12",
    "url": "https://www.reddit.com/r/learnpython/comments/1asdf12/how_do_i_start_learning_python/",
    "user_posted": "example_user",
    "title": "How do I start learning Python?",
    "description": "I'm a complete beginner and want to know the best resources...",
    "num_upvotes": 1240,
    "num_comments": 86,
    "date_posted": "2026-05-23T18:22:00Z",
    "tag": "Tutorial",
    "community_name": "learnpython",
    "community_url": "https://www.reddit.com/r/learnpython",
    "community_description": "Subreddit for posting questions...",
    "community_members_num": 1120000,
    "community_rank": "Top 1%",
    "photos": [],
    "videos": [],
}

# Canonical X record per
# website/WEB SCRAPER API/twitter/send-first-request.md (lines 82-92).
X_RECORD_TEMPLATE = {
    "url": "https://x.com/elonmusk/status/1234567890123456789",
    "user_posted": "elonmusk",
    "description": "Exciting times ahead...",
    "date_posted": "2026-05-23T14:30:00.000Z",
    "likes": 125000,
    "retweets": 18000,
    "replies": 5200,
    "hashtags": ["technology", "innovation"],
}


def _make_reddit_post(
    post_id: str = "1asdf12",
    posted_at: datetime | None = None,
    subreddit: str = "ChatGPTJailbreak",
) -> RedditPost:
    """Build a canned ``RedditPost`` for plugin-layer tests."""
    return RedditPost(
        post_id=post_id,
        subreddit=subreddit,
        title="Test jailbreak prompt",
        body="Here's a new method that worked on GPT-4o...",
        author="example_user",
        posted_at=posted_at or NEWER,
        permalink=f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/",
        score=1240,
        comments=[{"author": "c1", "body": "wow", "score": 12}],
    )


def _make_x_post(
    post_id: str = "1234567890123456789",
    posted_at: datetime | None = None,
    handle: str = "simonw",
) -> XPost:
    return XPost(
        post_id=post_id,
        author_handle=handle,
        body="New indirect prompt-injection vector in tool descriptions...",
        posted_at=posted_at or NEWER,
        permalink=f"https://x.com/{handle}/status/{post_id}",
        metrics={"likes": 42, "retweets": 7, "replies": 3},
    )


# --------------------------------------------------------------------------- #
# In-test fake clients for the plugin tests
# --------------------------------------------------------------------------- #


class _FakeBrightDataClient:
    """Tiny stub matching the subset of ``BrightDataClient``'s async surface
    that the source plugins actually call. Each attribute is set per-test.
    """

    def __init__(
        self,
        *,
        reddit_posts: list[RedditPost] | None = None,
        x_posts: list[XPost] | None = None,
        hf_threads: list[HFDiscussion] | None = None,
        hf_raises_runtime: bool = False,
        serp_results: dict[str, SerpResponse] | None = None,
        unlock_pages: dict[str, UnlockedPage] | None = None,
        browser_pages: dict[str, ScrapedPage] | None = None,
    ) -> None:
        self.reddit_posts = reddit_posts or []
        self.x_posts = x_posts or []
        self.hf_threads = hf_threads or []
        self.hf_raises_runtime = hf_raises_runtime
        self.serp_results = serp_results or {}
        self.unlock_pages = unlock_pages or {}
        self.browser_pages = browser_pages or {}

        self.reddit_calls: list[str] = []
        self.x_calls: list[str] = []
        self.serp_calls: list[str] = []
        self.unlock_calls: list[str] = []
        self.browser_calls: list[str] = []

    async def scrape_reddit_subreddit(
        self, subreddit: str, limit: int = 100, *, session: Any = None
    ) -> list[RedditPost]:
        self.reddit_calls.append(subreddit)
        return list(self.reddit_posts)

    async def scrape_x_user_posts(
        self, profile_url: str, limit: int = 50, *, session: Any = None
    ) -> list[XPost]:
        self.x_calls.append(profile_url)
        return list(self.x_posts)

    async def scrape_huggingface_discussion(
        self, model_id: str, *, session: Any = None
    ) -> list[HFDiscussion]:
        if self.hf_raises_runtime:
            raise RuntimeError("BRIGHTDATA_HUGGINGFACE_DATASET_ID not set")
        return list(self.hf_threads)

    async def serp_search(
        self,
        query: str,
        count: int = 10,
        engine: str = "google",
        *,
        session: Any = None,
    ) -> SerpResponse:
        self.serp_calls.append(query)
        if query in self.serp_results:
            return self.serp_results[query]
        # Default empty SerpResponse so plugins exercising the "no hits" path
        # don't crash on missing canned data.
        return SerpResponse(
            query=query,
            engine=engine,
            fetched_at=datetime.now(timezone.utc),
            organic_results=[],
            knowledge_panel=None,
            raw_json={"organic": []},
        )

    async def web_unlock(
        self, url: str, format: str = "markdown", *, session: Any = None
    ) -> UnlockedPage:
        self.unlock_calls.append(url)
        if url in self.unlock_pages:
            return self.unlock_pages[url]
        # Default to a tiny stub page so plugins that fetch unknown URLs get
        # a deterministic 200 with empty-ish content.
        return UnlockedPage(
            url=url,
            fetched_at=datetime.now(timezone.utc),
            content="",
            content_format=format if format in ("html", "markdown") else "markdown",
            status_code=200,
        )

    async def scrape_browser(
        self,
        url: str,
        wait_for_selector: str | None = None,
        scroll_pages: int = 1,
        *,
        storage_state: dict | None = None,
        session: Any = None,
    ) -> ScrapedPage:
        self.browser_calls.append(url)
        # 2026-05-26: stash the storage_state kwarg so the LeakHub auth-
        # injection path can be asserted by tests.
        if not hasattr(self, "browser_storage_state_seen"):
            self.browser_storage_state_seen = []
        self.browser_storage_state_seen.append(storage_state)
        if url in self.browser_pages:
            return self.browser_pages[url]
        return ScrapedPage(
            url=url,
            fetched_at=datetime.now(timezone.utc),
            html="<html></html>",
            rendered_text="placeholder body text",
        )


# --------------------------------------------------------------------------- #
# A. BrightDataClient — REST products
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_serp_search_returns_parsed_response() -> None:
    """SERP API ``/request`` returns parsed_light JSON → ``SerpResponse``."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/request"
        return httpx.Response(200, json=SERP_PARSED_LIGHT_PIZZA)

    client = _make_client(httpx.MockTransport(handler))
    try:
        result = await client.serp_search("pizza", count=10, engine="google")
    finally:
        await client.aclose()

    assert isinstance(result, SerpResponse)
    assert result.query == "pizza"
    assert result.engine == "google"
    assert len(result.organic_results) == 2
    assert result.organic_results[0]["link"] == "https://en.wikipedia.org/wiki/Pizza"
    assert result.raw_json == SERP_PARSED_LIGHT_PIZZA


@pytest.mark.asyncio
async def test_serp_search_http_4xx_raises_loudly() -> None:
    """400 from /request must surface as ``HTTPStatusError`` — no silent swallow."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad zone"})

    client = _make_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.serp_search("anything")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_web_unlock_returns_markdown_page() -> None:
    """Web Unlocker returns the raw response body wrapped in ``UnlockedPage``."""
    body = "# Hello\n\nMarkdown body returned by Web Unlocker."

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["zone"] == "test_unlocker_zone"
        assert payload["url"] == "https://example.com/post"
        assert payload["data_format"] == "markdown"
        return httpx.Response(200, text=body)

    client = _make_client(httpx.MockTransport(handler))
    try:
        page = await client.web_unlock("https://example.com/post", format="markdown")
    finally:
        await client.aclose()

    assert isinstance(page, UnlockedPage)
    assert page.content == body
    assert page.content_format == "markdown"
    assert page.status_code == 200
    assert str(page.url) == "https://example.com/post"


@pytest.mark.asyncio
async def test_web_unlock_handles_html_format() -> None:
    """Same call path with ``format='html'`` round-trips unchanged."""
    body = "<html><body>raw page</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["data_format"] == "html"
        return httpx.Response(200, text=body)

    client = _make_client(httpx.MockTransport(handler))
    try:
        page = await client.web_unlock("https://example.com/x", format="html")
    finally:
        await client.aclose()

    assert page.content_format == "html"
    assert page.content == body


@pytest.mark.asyncio
async def test_scrape_reddit_subreddit_parses_dataset_response() -> None:
    """Reddit "Discover by subreddit URL" → ``list[RedditPost]`` via /trigger.

    Locks the discover-mode wire contract (2026-05-26 revision):

      * Endpoint: ``/datasets/v3/trigger`` (NOT ``/scrape``). Sync /scrape
        silently returns ``200 []`` for discovery — verified live.
        ("Discovery is only available via async requests" — BD docs.)
      * Query params: ``type=discover_new`` + ``discover_by=subreddit_url``.
      * Body: bare JSON array ``[{...}]`` (NOT ``{"input": [...]}`` wrapper).
      * Trigger response: ``{"snapshot_id": "..."}`` → poll /progress → fetch /snapshot.
      * ``sort_by`` is TitleCase ("New"); lowercase is rejected by BD.
      * Input dict MUST NOT contain a ``limit`` field (BD 422s on it).
    """
    records = [
        {**REDDIT_RECORD_TEMPLATE, "post_id": "p1"},
        {**REDDIT_RECORD_TEMPLATE, "post_id": "p2", "num_upvotes": 99},
    ]
    snapshot_id = "sd_test_reddit_subreddit"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/datasets/v3/trigger":
            assert request.url.params["dataset_id"] == "gd_test_reddit"
            assert request.url.params["type"] == "discover_new"
            assert request.url.params["discover_by"] == "subreddit_url"
            body = json.loads(request.content.decode("utf-8"))
            assert isinstance(body, list), (
                "Reddit discover-mode body MUST be a bare array per BD trigger docs"
            )
            assert len(body) == 1
            assert body[0]["url"].startswith("https://www.reddit.com/r/")
            assert body[0]["sort_by"] == "New"
            assert "limit" not in body[0]
            return httpx.Response(200, json={"snapshot_id": snapshot_id})
        if path == f"/datasets/v3/progress/{snapshot_id}":
            return httpx.Response(200, json={"status": "ready", "records": 2})
        if path == f"/datasets/v3/snapshot/{snapshot_id}":
            assert request.url.params["format"] == "json"
            return httpx.Response(200, json=records)
        raise AssertionError(f"unexpected request path: {path}")

    client = _make_client(httpx.MockTransport(handler))
    try:
        posts = await client.scrape_reddit_subreddit("learnpython", limit=20)
    finally:
        await client.aclose()

    assert len(posts) == 2
    assert all(isinstance(p, RedditPost) for p in posts)
    assert posts[0].post_id == "p1"
    assert posts[0].subreddit == "learnpython"
    assert posts[0].author == "example_user"
    assert posts[0].score == 1240
    assert posts[1].score == 99
    assert posts[0].posted_at.tzinfo is not None


@pytest.mark.asyncio
async def test_scrape_reddit_keyword_parses_dataset_response() -> None:
    """Reddit "Discover by keyword" (global search) → ``list[RedditPost]``.

    Higher-yield path than subreddit_url for jailbreak content. Body shape
    per ``website/WEB SCRAPER API/reddit/send-first-request.md``:
    ``[{"keyword": ..., "date": ..., "num_of_posts": ...}]``. The
    field is ``date`` (NOT ``date_range``) — exact casing matters to BD.
    """
    records = [
        {**REDDIT_RECORD_TEMPLATE, "post_id": "kw1", "community_name": "AIJailbreak"},
    ]
    snapshot_id = "sd_test_reddit_keyword"

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/datasets/v3/trigger":
            assert request.url.params["dataset_id"] == "gd_test_reddit"
            assert request.url.params["type"] == "discover_new"
            assert request.url.params["discover_by"] == "keyword"
            body = json.loads(request.content.decode("utf-8"))
            assert isinstance(body, list) and len(body) == 1
            assert body[0]["keyword"] == "jailbreak prompt"
            assert body[0]["date"] == "Past week"  # NOT date_range
            assert body[0]["num_of_posts"] == 20
            return httpx.Response(200, json={"snapshot_id": snapshot_id})
        if path == f"/datasets/v3/progress/{snapshot_id}":
            return httpx.Response(200, json={"status": "ready", "records": 1})
        if path == f"/datasets/v3/snapshot/{snapshot_id}":
            return httpx.Response(200, json=records)
        raise AssertionError(f"unexpected request path: {path}")

    client = _make_client(httpx.MockTransport(handler))
    try:
        posts = await client.scrape_reddit_keyword(
            "jailbreak prompt", date_range="Past week", num_of_posts=20
        )
    finally:
        await client.aclose()

    assert len(posts) == 1
    assert posts[0].post_id == "kw1"
    assert posts[0].subreddit == "AIJailbreak"


@pytest.mark.asyncio
async def test_scrape_x_user_posts_parses_dataset_response() -> None:
    """X dataset response → ``list[XPost]`` via /trigger flow.

    Same /trigger contract as Reddit (2026-05-26 revision): discovery is
    async-only on BD, sync /scrape silently returns ``200 []``. Body is a
    bare JSON array, not ``{"input": [...]}``.
    """
    records = [
        {**X_RECORD_TEMPLATE},
        {**X_RECORD_TEMPLATE, "url": "https://x.com/elonmusk/status/999", "likes": 1},
    ]
    snapshot_id = "sd_test_x_profile"
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/datasets/v3/trigger":
            assert request.url.params["dataset_id"] == "gd_test_x"
            assert request.url.params["type"] == "discover_new"
            assert (
                request.url.params["discover_by"] == "profile_url_most_recent_posts"
            )
            body = json.loads(request.content.decode("utf-8"))
            assert isinstance(body, list), "X discover-mode body MUST be a bare array"
            assert len(body) == 1
            assert body[0]["url"] == "https://x.com/elonmusk"
            assert "start_date" in body[0]
            assert "end_date" in body[0]
            # X discover-by-profile-url MUST NOT contain `limit` — BD 400s on it
            # with `[["limit","This input should not contain a limit field"]]`.
            # Verified live 2026-05-26. Same pattern as Reddit subreddit_url.
            assert "limit" not in body[0]
            captured["body"] = body
            return httpx.Response(200, json={"snapshot_id": snapshot_id})
        if path == f"/datasets/v3/progress/{snapshot_id}":
            return httpx.Response(200, json={"status": "ready", "records": 2})
        if path == f"/datasets/v3/snapshot/{snapshot_id}":
            return httpx.Response(200, json=records)
        raise AssertionError(f"unexpected request path: {path}")

    client = _make_client(httpx.MockTransport(handler))
    try:
        posts = await client.scrape_x_user_posts(
            "https://x.com/elonmusk", limit=10
        )
    finally:
        await client.aclose()

    # `limit` no longer sent on the wire (see above); the caller-side `limit=10`
    # arg is now accounting-only.
    assert len(posts) == 2
    assert all(isinstance(p, XPost) for p in posts)
    assert posts[0].author_handle == "elonmusk"
    assert posts[0].post_id == "1234567890123456789"
    assert posts[0].metrics["likes"] == 125000
    assert posts[0].metrics["hashtags"] == ["technology", "innovation"]
    assert posts[1].metrics["likes"] == 1


@pytest.mark.asyncio
async def test_dataset_endpoint_202_snapshot_polls_then_downloads() -> None:
    """When /scrape returns ``{"snapshot_id": ...}`` (sync timeout fallback),
    the client must poll /progress/{id} until status='ready' then GET
    /snapshot/{id} for the actual records — NOT raise.

    Verifies the full async-polling path implemented 2026-05-26 per
    ``website/WEB SCRAPER API/management-apis/monitor-progress.md``.
    """
    polled_count = {"running": 0}
    sentinel_records = [
        {**REDDIT_RECORD_TEMPLATE, "post_id": "polled_p1"},
        {**REDDIT_RECORD_TEMPLATE, "post_id": "polled_p2"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/datasets/v3/trigger":
            # /trigger always returns 200 + snapshot_id (async-only contract).
            return httpx.Response(
                200,
                json={
                    "snapshot_id": "snap_async_xyz",
                    "message": "Your request is still in progress…",
                },
            )
        if path == "/datasets/v3/progress/snap_async_xyz":
            # Two `running` polls before flipping to `ready` — verifies the
            # loop iterates, not just one-shots on the first poll.
            polled_count["running"] += 1
            status = "ready" if polled_count["running"] >= 3 else "running"
            return httpx.Response(
                200,
                json={
                    "snapshot_id": "snap_async_xyz",
                    "dataset_id": "gd_test_reddit",
                    "status": status,
                },
            )
        if path == "/datasets/v3/snapshot/snap_async_xyz":
            # Download endpoint — returns the record array.
            assert request.url.params["format"] == "json"
            return httpx.Response(200, json=sentinel_records)
        raise AssertionError(f"unexpected request path: {path}")

    client = _make_client(httpx.MockTransport(handler))
    # Override interval to ~0 so the test completes in milliseconds.
    client.poll_interval_seconds = 0.001
    client.poll_timeout_seconds = 5.0
    try:
        posts = await client.scrape_reddit_subreddit("ChatGPTJailbreak")
    finally:
        await client.aclose()

    assert len(posts) == 2
    assert posts[0].post_id == "polled_p1"
    assert posts[1].post_id == "polled_p2"
    # 3 progress polls: 2× running + 1× ready.
    assert polled_count["running"] == 3


@pytest.mark.asyncio
async def test_snapshot_polling_raises_BrightDataSnapshotFailed_on_failed_status() -> None:
    """A ``status=failed`` response from /progress/{id} must raise
    ``BrightDataSnapshotFailed`` with the snapshot_id, not silently retry."""
    from rogue.harvest.bright_data_client import BrightDataSnapshotFailed

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/datasets/v3/trigger":
            return httpx.Response(200, json={"snapshot_id": "snap_doomed"})
        if path == "/datasets/v3/progress/snap_doomed":
            return httpx.Response(
                200,
                json={
                    "snapshot_id": "snap_doomed",
                    "status": "failed",
                    "error": "scraper crashed mid-run",
                },
            )
        raise AssertionError(f"unexpected path: {path}")

    client = _make_client(httpx.MockTransport(handler))
    client.poll_interval_seconds = 0.001
    try:
        with pytest.raises(BrightDataSnapshotFailed) as exc_info:
            await client.scrape_reddit_subreddit("ChatGPTJailbreak")
    finally:
        await client.aclose()
    assert "snap_doomed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_snapshot_polling_raises_BrightDataAsyncPollTimeout_on_deadline() -> None:
    """When /progress/{id} never transitions to ready before the configured
    timeout, the client must raise ``BrightDataAsyncPollTimeout`` carrying
    the snapshot_id so the operator can retry out-of-band."""
    from rogue.harvest.bright_data_client import BrightDataAsyncPollTimeout

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/datasets/v3/trigger":
            return httpx.Response(200, json={"snapshot_id": "snap_stuck"})
        if path == "/datasets/v3/progress/snap_stuck":
            # Always returns running — never resolves.
            return httpx.Response(
                200,
                json={"snapshot_id": "snap_stuck", "status": "running"},
            )
        raise AssertionError(f"unexpected path: {path}")

    client = _make_client(httpx.MockTransport(handler))
    # Both near-zero so the deadline trips on the very first sleep cycle.
    client.poll_interval_seconds = 0.001
    client.poll_timeout_seconds = 0.05
    try:
        with pytest.raises(BrightDataAsyncPollTimeout) as exc_info:
            await client.scrape_reddit_subreddit("ChatGPTJailbreak")
    finally:
        await client.aclose()
    assert "snap_stuck" in str(exc_info.value)


# --------------------------------------------------------------------------- #
# B. BrightDataClient — auth + cost-log
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_authorization_header_set() -> None:
    """Every outgoing request must carry ``Authorization: Bearer <key>``."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers.get("Content-Type")
        return httpx.Response(200, json={"organic": []})

    client = _make_client(httpx.MockTransport(handler), api_key="secret-xyz")
    try:
        await client.serp_search("anything")
    finally:
        await client.aclose()

    assert captured["auth"] == "Bearer secret-xyz"
    assert captured["content_type"] == "application/json"


@pytest.mark.asyncio
async def test_cost_log_inserted_when_session_passed() -> None:
    """A mocked Session must receive a ``BrightDataCostLog`` via ``session.add``."""
    from rogue.db.models import BrightDataCostLog

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>ok</html>")

    client = _make_client(httpx.MockTransport(handler))
    session = MagicMock()
    try:
        await client.web_unlock(
            "https://example.com/x", format="html", session=session
        )
    finally:
        await client.aclose()

    assert session.add.called, "session.add should be invoked when session is provided"
    (added,), _ = session.add.call_args
    assert isinstance(added, BrightDataCostLog)
    assert added.product == "unlocker"
    assert added.units == 1
    # Cost is the midpoint of the unlocker pricing band — > 0 and < 1 cent.
    assert added.cost_usd > 0.0
    assert added.cost_usd < 0.01


@pytest.mark.asyncio
async def test_cost_log_skipped_when_no_session() -> None:
    """``session=None`` must not raise and must not break the response."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hello")

    client = _make_client(httpx.MockTransport(handler))
    try:
        page = await client.web_unlock("https://example.com/y", session=None)
    finally:
        await client.aclose()

    assert page.content == "hello"


# --------------------------------------------------------------------------- #
# C. BrightDataClient — error paths
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_huggingface_raises_when_dataset_id_missing() -> None:
    """Calling HF scrape with ``hf_dataset_id=None`` must hint at the env var."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Should never be reached — pre-flight check fires first.
        return httpx.Response(500)

    client = _make_client(httpx.MockTransport(handler), hf_dataset_id=None)
    try:
        with pytest.raises(RuntimeError) as exc_info:
            await client.scrape_huggingface_discussion("test/model")
    finally:
        await client.aclose()

    assert "BRIGHTDATA_HUGGINGFACE_DATASET_ID" in str(exc_info.value)


@pytest.mark.asyncio
async def test_scrape_browser_raises_when_playwright_missing() -> None:
    """``scrape_browser`` must raise ``ImportError`` when Playwright is absent.

    Skips cleanly if Playwright happens to be installed in the dev env.
    """
    import importlib.util

    if importlib.util.find_spec("playwright") is not None:
        pytest.skip("playwright is installed in this env; ImportError path "
                    "cannot be exercised without monkeypatching find_spec")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    client = _make_client(httpx.MockTransport(handler))
    try:
        with pytest.raises(ImportError):
            await client.scrape_browser("https://example.com/")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_aclose_idempotent() -> None:
    """Two consecutive ``aclose`` calls must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"organic": []})

    client = _make_client(httpx.MockTransport(handler))
    await client.aclose()
    await client.aclose()  # second call is a no-op, must not raise.


# --------------------------------------------------------------------------- #
# D. Source plugins — parser correctness
# --------------------------------------------------------------------------- #


def _assert_basic_raw_document_shape(
    doc: RawDocument,
    *,
    expected_source_type: str,
    expected_bd_product: str,
) -> None:
    """Shared assertions every plugin-emitted RawDocument must satisfy."""
    assert doc.source_type == expected_source_type
    assert doc.bright_data_product == expected_bd_product
    assert doc.archive_hash
    assert len(doc.archive_hash) >= 7
    # discovered_via is either None or a non-empty string.
    assert doc.discovered_via is None or (
        isinstance(doc.discovered_via, str) and len(doc.discovered_via) > 0
    )


@pytest.mark.asyncio
async def test_reddit_plugin_emits_raw_documents() -> None:
    plugin = RedditSubredditPlugin(subreddits=["ChatGPTJailbreak"])
    fake = _FakeBrightDataClient(
        reddit_posts=[
            _make_reddit_post(post_id="recent", posted_at=NEWER),
            # Older than `since` — must be filtered out by the plugin.
            _make_reddit_post(post_id="ancient", posted_at=OLDER),
        ]
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 1, "the OLDER post must be filtered out"
    _assert_basic_raw_document_shape(
        docs[0],
        expected_source_type="reddit",
        expected_bd_product="web_scraper_api",
    )
    assert docs[0].metadata["subreddit"] == "ChatGPTJailbreak"
    assert docs[0].content_format == "json"


@pytest.mark.asyncio
async def test_reddit_plugin_serp_queries_substitutes_date() -> None:
    plugin = RedditSubredditPlugin(subreddits=["ChatGPTJailbreak"])
    queries = plugin.serp_queries(SINCE)
    assert len(queries) >= 1
    # since - 1 day = 2026-05-19.
    assert all("2026-05-19" in q for q in queries)


@pytest.mark.asyncio
async def test_x_plugin_emits_raw_documents() -> None:
    plugin = XUserTimelinePlugin(handles=["simonw"])
    fake = _FakeBrightDataClient(
        x_posts=[
            _make_x_post(post_id="111", posted_at=NEWER),
            _make_x_post(post_id="000", posted_at=OLDER),
        ]
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 1
    _assert_basic_raw_document_shape(
        docs[0], expected_source_type="x", expected_bd_product="web_scraper_api"
    )
    assert docs[0].metadata["author_handle"] == "simonw"


@pytest.mark.asyncio
async def test_arxiv_plugin_extracts_ids_and_fetches_abstracts() -> None:
    # The listing page must include a link that matches ABS_HREF_RE.
    listing_html = (
        '<html><body><dl><dt>'
        '<a href="/abs/2605.18239">paper 1</a>'
        '</dt><dt>'
        '<a href="/abs/2605.99999v2">paper 2</a>'
        '</dt></dl></body></html>'
    )
    abstract_html = (
        '<html><body>Abstract text — adversarial prompts...</body></html>'
    )
    listings = ["https://arxiv.org/list/cs.CR/new"]
    plugin = ArxivListingPlugin(listings=listings)

    # Build canned web_unlock pages: listing URL + per-abstract URLs.
    unlock_pages = {
        "https://arxiv.org/list/cs.CR/new": UnlockedPage(
            url="https://arxiv.org/list/cs.CR/new",
            fetched_at=datetime.now(timezone.utc),
            content=listing_html,
            content_format="html",
            status_code=200,
        ),
    }
    for arxiv_id in ("2605.18239", "2605.99999"):
        abs_url = f"https://arxiv.org/abs/{arxiv_id}"
        unlock_pages[abs_url] = UnlockedPage(
            url=abs_url,
            fetched_at=datetime.now(timezone.utc),
            content=abstract_html,
            content_format="html",
            status_code=200,
        )

    fake = _FakeBrightDataClient(unlock_pages=unlock_pages)

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 2
    for doc in docs:
        _assert_basic_raw_document_shape(
            doc, expected_source_type="arxiv", expected_bd_product="web_unlocker"
        )
        assert doc.content_format == "html"
        assert "arxiv_id" in doc.metadata


@pytest.mark.asyncio
async def test_blog_static_plugin_fetches_feed_then_posts() -> None:
    target = BlogTarget(
        name="testblog",
        feed_url="https://blog.example.com/",
        source_type="blog",
    )
    # Feed markdown contains a same-host link → post_url must be discovered.
    feed_md = (
        "# Latest posts\n\n"
        "[New post](https://blog.example.com/2026/05/24/post-one/)\n"
        "[Tag page](https://blog.example.com/tags/security/)\n"
        "[External](https://other.example.org/x)\n"
    )
    post_md = (
        "# A post\n\n"
        + "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5
    )

    plugin = BlogStaticPlugin(blogs=[target])
    fake = _FakeBrightDataClient(
        unlock_pages={
            "https://blog.example.com/": UnlockedPage(
                url="https://blog.example.com/",
                fetched_at=datetime.now(timezone.utc),
                content=feed_md,
                content_format="markdown",
                status_code=200,
            ),
            "https://blog.example.com/2026/05/24/post-one/": UnlockedPage(
                url="https://blog.example.com/2026/05/24/post-one/",
                fetched_at=datetime.now(timezone.utc),
                content=post_md,
                content_format="markdown",
                status_code=200,
            ),
        }
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 1
    _assert_basic_raw_document_shape(
        docs[0], expected_source_type="blog", expected_bd_product="web_unlocker"
    )
    assert docs[0].metadata["blog_name"] == "testblog"
    assert docs[0].content_format == "markdown"


@pytest.mark.asyncio
async def test_github_search_plugin_serp_then_readme() -> None:
    plugin = GithubSearchPlugin()
    queries = plugin.serp_queries(SINCE)
    assert any("2026-05-19" in q for q in queries)

    canned_serp = SerpResponse(
        query=queries[0],
        engine="google",
        fetched_at=datetime.now(timezone.utc),
        organic_results=[
            {
                "rank": 1,
                "title": "owner/repo: A jailbreak corpus",
                "link": "https://github.com/owner/repo",
                "description": "Jailbreak corpus for LLM red-teaming",
            },
        ],
        knowledge_panel=None,
        raw_json={},
    )
    readme_md = "# Awesome jailbreaks\n\n" + ("Body paragraph. " * 20)
    fake = _FakeBrightDataClient(
        serp_results={queries[0]: canned_serp},
        unlock_pages={
            "https://raw.githubusercontent.com/owner/repo/main/README.md": (
                UnlockedPage(
                    url="https://raw.githubusercontent.com/owner/repo/main/README.md",
                    fetched_at=datetime.now(timezone.utc),
                    content=readme_md,
                    content_format="markdown",
                    status_code=200,
                )
            ),
        },
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) >= 1
    doc = docs[0]
    _assert_basic_raw_document_shape(
        doc, expected_source_type="github", expected_bd_product="web_unlocker"
    )
    assert doc.metadata["repo"] == "owner/repo"
    assert doc.discovered_via and doc.discovered_via.startswith("serp_query: ")


@pytest.mark.asyncio
async def test_huggingface_plugin_falls_back_to_web_unlocker() -> None:
    """When the Web Scraper API path raises ``RuntimeError`` (no dataset
    provisioned), the plugin must fall back to a Web Unlocker fetch."""
    plugin = HuggingFaceDiscussionPlugin(model_ids=["bigscience/bloomz"])
    discussions_url = "https://huggingface.co/bigscience/bloomz/discussions"
    fake = _FakeBrightDataClient(
        hf_raises_runtime=True,
        unlock_pages={
            discussions_url: UnlockedPage(
                url=discussions_url,
                fetched_at=datetime.now(timezone.utc),
                content="<html><body>Discussion list</body></html>",
                content_format="html",
                status_code=200,
            ),
        },
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 1
    _assert_basic_raw_document_shape(
        docs[0],
        expected_source_type="huggingface",
        expected_bd_product="web_unlocker",
    )
    assert docs[0].metadata["fallback_path"] == "web_unlocker"


@pytest.mark.asyncio
async def test_community_archive_plugin_uses_scraping_browser() -> None:
    target = ArchiveTarget(
        name="testarchive",
        url="https://archive.example.com/",
        wait_for_selector=".card",
        scroll_pages=2,
    )
    plugin = CommunityArchivePlugin(archives=[target])
    fake = _FakeBrightDataClient(
        browser_pages={
            "https://archive.example.com/": ScrapedPage(
                url="https://archive.example.com/",
                fetched_at=datetime.now(timezone.utc),
                html="<html><body>Rendered</body></html>",
                rendered_text="Rendered text body with attack examples",
            ),
        }
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 1
    _assert_basic_raw_document_shape(
        docs[0],
        expected_source_type="community_archive",
        expected_bd_product="scraping_browser",
    )
    assert docs[0].metadata["archive_name"] == "testarchive"


def test_source_plugin_base_class_enforces_fetch_since() -> None:
    """Subclassing ``SourcePlugin`` without implementing ``fetch_since`` must
    fail to instantiate (ABC contract)."""

    class IncompletePlugin(SourcePlugin):  # type: ignore[misc]
        name = "incomplete"
        source_type = "other"
        bright_data_product = "web_unlocker"

    with pytest.raises(TypeError):
        IncompletePlugin()  # type: ignore[abstract]


# --------------------------------------------------------------------------- #
# E. Bonus: ensure the archive_hash matches the SHA-256 of raw_content
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reddit_plugin_archive_hash_matches_content() -> None:
    """``RawDocument.archive_hash`` must equal SHA-256 of ``raw_content`` —
    catches regressions in the plugin's hash computation."""
    plugin = RedditSubredditPlugin(subreddits=["LocalLLaMA"])
    fake = _FakeBrightDataClient(
        reddit_posts=[_make_reddit_post(posted_at=NEWER, subreddit="LocalLLaMA")]
    )
    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]
    assert len(docs) == 1
    expected = hashlib.sha256(docs[0].raw_content.encode("utf-8")).hexdigest()
    assert docs[0].archive_hash == expected


# Quiet the unused-import lint about timedelta — kept available for future
# tests that need ``SINCE + timedelta(...)`` deltas without re-importing.
_ = timedelta


# --------------------------------------------------------------------------- #
# G. Pliny / elder-plinius GitHub umbrella plugin (§5.1 Source #7)
# --------------------------------------------------------------------------- #
#
# Critical invariant: every L1B3RT4S filename MUST go through
# `urllib.parse.quote(filename, safe="")`. Bare `#`, `!`, `*` in the URL
# silently fail (fragment-anchor interpretation / shell-style globbing on
# some intermediaries) — verified 2026-05-25 via direct browser test
# (§5.2 Source #7).


def test_pliny_l1b3rt4s_url_builder_percent_encodes_special_chars() -> None:
    """The 4 special-character filenames MUST become %23 / %21 / %2A
    URLs — the whole reason this plugin doesn't use string concatenation."""
    assert _l1b3rt4s_raw_url("#MOTHERLOAD.txt").endswith("%23MOTHERLOAD.txt")
    assert _l1b3rt4s_raw_url("!SHORTCUTS.json").endswith("%21SHORTCUTS.json")
    assert _l1b3rt4s_raw_url("*SPECIAL_TOKENS.json").endswith("%2ASPECIAL_TOKENS.json")
    # Leading hyphens are URL-safe — no encoding needed (§5.2 note).
    assert _l1b3rt4s_raw_url("-MISCELLANEOUS-.mkd").endswith("-MISCELLANEOUS-.mkd")
    # Plain ASCII filenames pass through unchanged.
    assert _l1b3rt4s_raw_url("ANTHROPIC.mkd").endswith("/ANTHROPIC.mkd")


def test_pliny_l1b3rt4s_url_builder_never_emits_bare_hash() -> None:
    """Regression guard against string-concat regressions on the special-char list."""
    for filename in L1B3RT4S_SPECIAL_FILES:
        url = _l1b3rt4s_raw_url(filename)
        # Bare `#` in the URL would be a fragment anchor — silently empty.
        # The path portion (everything after the last `/`) must NOT contain
        # a literal `#`.
        path_segment = url.rsplit("/", 1)[-1]
        assert "#" not in path_segment, (
            f"bare # in path segment of {url!r} — fragment-anchor regression"
        )
        assert url.startswith(L1B3RT4S_RAW_PREFIX)


def test_pliny_cl4r1t4s_url_builder_preserves_slashes() -> None:
    """CL4R1T4S paths may contain subdirectories — `/` must NOT be encoded."""
    url = _cl4r1t4s_raw_url("subdir/CHATGPT.mkd")
    assert url.endswith("/subdir/CHATGPT.mkd")
    # Special chars in the leaf still get encoded.
    url2 = _cl4r1t4s_raw_url("subdir/#FOO.mkd")
    assert url2.endswith("/subdir/%23FOO.mkd")


@pytest.mark.asyncio
async def test_pliny_plugin_l1b3rt4s_direct_fetch_emits_one_doc_per_file(monkeypatch) -> None:
    """Direct-fetch path emits one RawDocument per L1B3RT4S filename whose
    Web Unlocker returns non-empty content.

    2026-05-26: L1B3RT4S discovery now uses the GitHub tree API; when the
    API helper returns [] the plugin falls back to ``l1b3rt4s_files +
    l1b3rt4s_special_files``. We monkeypatch the helper to [] so the
    fallback path is exercised with the test's small file list."""
    from rogue.harvest.sources import pliny_github as plg

    async def fake_l1b_paths() -> list[str]:
        return []

    monkeypatch.setattr(
        plg.PlinyGithubPlugin, "_discover_l1b3rt4s_paths",
        staticmethod(fake_l1b_paths),
    )

    # Trim to a tiny file list for the test so we control which fetches fire.
    test_files = ("ANTHROPIC.mkd", "OPENAI.mkd")
    test_special = ("#MOTHERLOAD.txt",)
    plugin = PlinyGithubPlugin(
        l1b3rt4s_files=test_files,
        l1b3rt4s_special_files=test_special,
        include_cl4r1t4s=False,
        include_serp_discovery=False,
    )

    body = "# A bunch of jailbreaks\n" + ("payload line. " * 20)
    unlock_pages = {
        _l1b3rt4s_raw_url(name): UnlockedPage(
            url=_l1b3rt4s_raw_url(name),
            fetched_at=datetime.now(timezone.utc),
            content=body,
            content_format="markdown",
            status_code=200,
        )
        for name in (*test_files, *test_special)
    }
    fake = _FakeBrightDataClient(unlock_pages=unlock_pages)

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 3
    # Every L1B3RT4S URL we hit MUST start with the raw-prefix.
    for doc in docs:
        _assert_basic_raw_document_shape(
            doc, expected_source_type="github", expected_bd_product="web_unlocker"
        )
        assert str(doc.url).startswith(L1B3RT4S_RAW_PREFIX)
        assert doc.metadata["repo"] == "elder-plinius/L1B3RT4S"
        # Tree-API helper returned [] in this test → plugin falls back to
        # the hardcoded l1b3rt4s_files + l1b3rt4s_special_files path.
        assert doc.metadata["fetch_path"] == "l1b3rt4s_direct_fallback"

    # The special-char file MUST have been requested via its %-encoded URL.
    motherload_url = _l1b3rt4s_raw_url("#MOTHERLOAD.txt")
    assert motherload_url in fake.unlock_calls
    # And it must contain `%23` — guards against any future regression where
    # the plugin starts using bare `#`.
    assert any("%23MOTHERLOAD.txt" in u for u in fake.unlock_calls)


@pytest.mark.asyncio
async def test_pliny_plugin_skips_empty_unlock_responses(monkeypatch) -> None:
    """An empty Web Unlocker response (fragment-anchor symptom) is skipped,
    not emitted as a near-empty RawDocument."""
    # Monkeypatch the tree-API helper to [] so the fallback hardcoded list
    # is used (deterministic; no live GitHub call from the test).
    from rogue.harvest.sources import pliny_github as plg
    async def _empty_l1b():
        return []
    monkeypatch.setattr(
        plg.PlinyGithubPlugin, "_discover_l1b3rt4s_paths",
        staticmethod(_empty_l1b),
    )

    plugin = PlinyGithubPlugin(
        l1b3rt4s_files=("ANTHROPIC.mkd",),
        l1b3rt4s_special_files=("#MOTHERLOAD.txt",),
        include_cl4r1t4s=False,
        include_serp_discovery=False,
    )
    fake = _FakeBrightDataClient(
        unlock_pages={
            # The default _FakeBrightDataClient returns empty content for any
            # URL not in unlock_pages — so leaving this dict empty exercises
            # the "no content" branch directly.
        }
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]
    assert docs == []


@pytest.mark.asyncio
async def test_pliny_plugin_cl4r1t4s_discovery_uses_github_tree_api(monkeypatch) -> None:
    """The Scraping Browser HTML of the CL4R1T4S tree must yield raw
    `.mkd` URLs which are then Web-Unlocked."""
    plugin = PlinyGithubPlugin(
        l1b3rt4s_files=(),
        l1b3rt4s_special_files=(),
        include_cl4r1t4s=True,
        include_serp_discovery=False,
    )
    # 2026-05-26: CL4R1T4S discovery switched from Scraping-Browser tree-page
    # scrape (which broke when GitHub shipped the React tree-view redesign)
    # to the GitHub Git Tree API. Mock the helper to return a fixed file list
    # representing what the API would return for the live repo.
    from rogue.harvest.sources import pliny_github as plg

    async def fake_discover() -> list[tuple[str, str]]:
        # (path, blob_sha) pairs — the real helper now returns the SHA as the
        # §11.7 pre-fetch freshness token.
        return [
            ("OPENAI/ChatGPT5-08-07-2025.mkd", "sha-openai"),
            ("ANTHROPIC/Claude-3.5-Sonnet.md", "sha-anthropic"),
            ("META/Llama-3.1-405B.txt", "sha-meta"),
            ("LICENSE", "sha-license"),  # filtered out by extension whitelist in the real helper
        ]

    monkeypatch.setattr(plg.PlinyGithubPlugin, "_discover_cl4r1t4s_paths", staticmethod(fake_discover))

    fake = _FakeBrightDataClient(
        unlock_pages={
            _cl4r1t4s_raw_url("OPENAI/ChatGPT5-08-07-2025.mkd"): UnlockedPage(
                url=_cl4r1t4s_raw_url("OPENAI/ChatGPT5-08-07-2025.mkd"),
                fetched_at=datetime.now(timezone.utc),
                content="# ChatGPT5 leaked prompt\n" + ("text " * 20),
                content_format="markdown",
                status_code=200,
            ),
            _cl4r1t4s_raw_url("ANTHROPIC/Claude-3.5-Sonnet.md"): UnlockedPage(
                url=_cl4r1t4s_raw_url("ANTHROPIC/Claude-3.5-Sonnet.md"),
                fetched_at=datetime.now(timezone.utc),
                content="# Claude 3.5 Sonnet leaked prompt\n" + ("text " * 20),
                content_format="markdown",
                status_code=200,
            ),
            _cl4r1t4s_raw_url("META/Llama-3.1-405B.txt"): UnlockedPage(
                url=_cl4r1t4s_raw_url("META/Llama-3.1-405B.txt"),
                fetched_at=datetime.now(timezone.utc),
                content="# Llama 3.1 leaked prompt\n" + ("text " * 20),
                content_format="markdown",
                status_code=200,
            ),
        },
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    # 3 content files (.mkd, .md, .txt) — LICENSE filtered out by the helper
    # (test mock returns it explicitly to verify the plugin still works when
    # the helper omits it; the real helper does the extension filtering itself).
    # Since we monkeypatched the helper to RETURN LICENSE, the plugin will
    # try to fetch it and get None (not in unlock_pages), so it's skipped.
    # Net result: 3 docs from the 3 valid files.
    assert len(docs) == 3
    paths_seen = sorted(d.metadata["path"] for d in docs)
    assert paths_seen == [
        "ANTHROPIC/Claude-3.5-Sonnet.md",
        "META/Llama-3.1-405B.txt",
        "OPENAI/ChatGPT5-08-07-2025.mkd",
    ]
    for doc in docs:
        assert doc.metadata["repo"] == "elder-plinius/CL4R1T4S"
        assert doc.metadata["fetch_path"] == "cl4r1t4s_tree_api"
        assert doc.discovered_via == "github_tree_api:CL4R1T4S"


@pytest.mark.asyncio
async def test_pliny_plugin_serp_umbrella_skips_already_covered_repos(monkeypatch) -> None:
    """SERP must NOT re-fetch L1B3RT4S or CL4R1T4S (we already cover them
    via the direct + tree-API paths)."""
    # Monkeypatch the L1B3RT4S helper to [] so phase 1 emits no docs +
    # makes no live GitHub call from the test. CL4R1T4S is disabled below.
    from rogue.harvest.sources import pliny_github as plg
    async def _empty_l1b():
        return []
    monkeypatch.setattr(
        plg.PlinyGithubPlugin, "_discover_l1b3rt4s_paths",
        staticmethod(_empty_l1b),
    )

    plugin = PlinyGithubPlugin(
        l1b3rt4s_files=(),
        l1b3rt4s_special_files=(),
        include_cl4r1t4s=False,
        include_serp_discovery=True,
    )
    query = plugin.serp_queries(SINCE)[0]
    canned = SerpResponse(
        query=query,
        engine="google",
        fetched_at=datetime.now(timezone.utc),
        organic_results=[
            {"link": "https://github.com/elder-plinius/L1B3RT4S"},  # skip
            {"link": "https://github.com/elder-plinius/CL4R1T4S"},  # skip
            {"link": "https://github.com/elder-plinius/SOME-NEW-REPO"},  # fetch
        ],
        knowledge_panel=None,
        raw_json={},
    )
    readme_url = (
        "https://raw.githubusercontent.com/elder-plinius/SOME-NEW-REPO/main/README.md"
    )
    fake = _FakeBrightDataClient(
        serp_results={query: canned},
        unlock_pages={
            readme_url: UnlockedPage(
                url=readme_url,
                fetched_at=datetime.now(timezone.utc),
                content="# SOME-NEW-REPO\n" + ("body " * 20),
                content_format="markdown",
                status_code=200,
            ),
        },
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 1
    assert docs[0].metadata["repo"] == "elder-plinius/SOME-NEW-REPO"
    assert docs[0].metadata["fetch_path"] == "serp_discovered"
    assert docs[0].discovered_via and docs[0].discovered_via.startswith("serp_query: ")
    # And we must NOT have hit either of the already-covered repo READMEs.
    assert not any("L1B3RT4S/main/README.md" in u for u in fake.unlock_calls)
    assert not any("CL4R1T4S/main/README.md" in u for u in fake.unlock_calls)


def test_pliny_plugin_serp_queries_substitutes_date() -> None:
    plugin = PlinyGithubPlugin()
    queries = plugin.serp_queries(SINCE)
    assert len(queries) == 1
    assert "site:github.com/elder-plinius" in queries[0]
    assert "2026-05-19" in queries[0]


def test_pliny_plugin_locked_org_file_list_has_no_bare_hash_in_paths() -> None:
    """Smoke-check the locked file lists: every special-char URL must encode
    its leading character. Catches anyone adding a new file via string-concat."""
    for filename in L1B3RT4S_ORG_FILES:
        # Plain ASCII names — should NOT contain any URL-unsafe chars.
        assert "#" not in filename and " " not in filename


# --------------------------------------------------------------------------- #
# H. LeakHub.ai plugin (§5.1 Source #8)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_leakhub_plugin_keeps_verified_pages_only(monkeypatch) -> None:
    """Pages whose rendered text contains the 'verified' badge are kept;
    pending-only pages are dropped (§5.1 'verified leaks only').

    Requires a populated ``LEAKHUB_SESSION_COOKIE`` env var to bypass the
    no-cookie early-return guard added 2026-05-26.
    """
    monkeypatch.setenv(
        "LEAKHUB_STORAGE_STATE",
        '{"cookies": [], "origins": [{"origin": "https://leakhub.ai", '
        '"localStorage": [{"name": "__convexAuthJWT_test", "value": "dummy"}]}]}',
    )
    plugin = LeakHubScrapePlugin(providers=["openai", "anthropic"])

    verified_url = "https://leakhub.ai/prompts/openai"
    pending_url = "https://leakhub.ai/prompts/anthropic"
    fake = _FakeBrightDataClient(
        browser_pages={
            verified_url: ScrapedPage(
                url=verified_url,
                fetched_at=datetime.now(timezone.utc),
                html="",
                rendered_text=(
                    "Leak 1 (Verified by 5 users) — system prompt: You are..."
                ),
            ),
            pending_url: ScrapedPage(
                url=pending_url,
                fetched_at=datetime.now(timezone.utc),
                html="",
                rendered_text="Leak 2 (Pending verification) — ...",
            ),
        }
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 1
    _assert_basic_raw_document_shape(
        docs[0],
        expected_source_type="other",
        expected_bd_product="scraping_browser",
    )
    assert docs[0].metadata["provider"] == "openai"
    assert docs[0].metadata["verified_filter"] is True
    # And the empty-providers telemetry must flag anthropic for the Day-1
    # morning gate (Option B fallback condition).
    assert plugin.last_run_empty_providers == ["anthropic"]


@pytest.mark.asyncio
async def test_leakhub_plugin_flags_all_empty_for_day1_morning_gate(monkeypatch) -> None:
    """If every provider returns empty / unverified content, the
    last_run_empty_providers list contains all of them — the §STATUS-flag
    condition for triggering the Option B fallback decision."""
    monkeypatch.setenv(
        "LEAKHUB_STORAGE_STATE",
        '{"cookies": [], "origins": [{"origin": "https://leakhub.ai", '
        '"localStorage": [{"name": "__convexAuthJWT_test", "value": "dummy"}]}]}',
    )
    plugin = LeakHubScrapePlugin(providers=["openai", "anthropic"])
    fake = _FakeBrightDataClient(
        browser_pages={
            "https://leakhub.ai/prompts/openai": ScrapedPage(
                url="https://leakhub.ai/prompts/openai",
                fetched_at=datetime.now(timezone.utc),
                html="",
                rendered_text="",  # empty render
            ),
            "https://leakhub.ai/prompts/anthropic": ScrapedPage(
                url="https://leakhub.ai/prompts/anthropic",
                fetched_at=datetime.now(timezone.utc),
                html="",
                rendered_text="Leak A — Pending review",  # not verified
            ),
        }
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]
    assert docs == []
    assert set(plugin.last_run_empty_providers) == {"openai", "anthropic"}


@pytest.mark.asyncio
async def test_leakhub_plugin_records_clear_error_when_storage_state_missing(
    monkeypatch,
) -> None:
    """Without LEAKHUB_STORAGE_STATE the plugin must early-return with a
    populated ``call_errors`` (NOT silently emit zero) — fix for the
    2026-05-26 "silent zero source" anti-pattern."""
    monkeypatch.delenv("LEAKHUB_STORAGE_STATE", raising=False)
    plugin = LeakHubScrapePlugin(providers=["openai"])
    fake = _FakeBrightDataClient(browser_pages={})
    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]
    assert docs == []
    assert len(plugin.call_errors) == 1
    assert "LEAKHUB_STORAGE_STATE" in plugin.call_errors[0]


@pytest.mark.asyncio
async def test_leakhub_plugin_loads_storage_state_from_file_path(
    monkeypatch, tmp_path,
) -> None:
    """LEAKHUB_STORAGE_STATE may be either inline JSON OR a path to a JSON
    file (Playwright's ``--save-storage`` output format). Both forms must
    decode into the same dict and reach scrape_browser as ``storage_state=``."""
    state = {
        "cookies": [],
        "origins": [
            {
                "origin": "https://leakhub.ai",
                "localStorage": [{"name": "__convexAuthJWT_x", "value": "tok"}],
            }
        ],
    }
    state_path = tmp_path / "leakhub_storage.json"
    state_path.write_text(json.dumps(state))
    monkeypatch.setenv("LEAKHUB_STORAGE_STATE", str(state_path))

    plugin = LeakHubScrapePlugin(providers=["openai"])
    fake = _FakeBrightDataClient(
        browser_pages={
            "https://leakhub.ai/prompts/openai": ScrapedPage(
                url="https://leakhub.ai/prompts/openai",
                fetched_at=datetime.now(timezone.utc),
                html="",
                rendered_text="Some leak (Verified) — system prompt: ...",
            ),
        }
    )
    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]
    assert len(docs) == 1
    # Verify storage_state actually reached scrape_browser
    assert fake.browser_storage_state_seen == [state]


def test_leakhub_plugin_default_providers_match_panel_vendors() -> None:
    """Default provider list mirrors the §5.1 panel-vendor set so any leak
    surfaced can pair against a reproduction config."""
    assert set(LEAKHUB_DEFAULT_PROVIDERS) == {
        "openai", "anthropic", "google", "mistral", "meta", "deepseek",
    }


def test_leakhub_plugin_serp_queries_substitutes_date() -> None:
    plugin = LeakHubScrapePlugin()
    queries = plugin.serp_queries(SINCE)
    assert len(queries) == 1
    assert "site:leakhub.ai" in queries[0]
    assert "2026-05-19" in queries[0]


# --------------------------------------------------------------------------- #
# I. OBLITERATUS HuggingFace plugin (§5.1 Source #10)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_obliteratus_plugin_fetches_readme_per_model_plus_activity() -> None:
    """Each model → one RawDocument (READme), plus one for the org activity page."""
    test_models = ("Qwen3.6-27B-OBLITERATED", "gpt2-xl-OBLITERATED")
    plugin = ObliteratusHfPlugin(models=test_models, include_activity_page=True)

    body = "# Model card\n\nThis model is abliterated via " + ("text " * 30)
    activity_body = "## Recent activity\n" + ("entry " * 20)
    unlock_pages = {
        _readme_url(m): UnlockedPage(
            url=_readme_url(m),
            fetched_at=datetime.now(timezone.utc),
            content=body,
            content_format="markdown",
            status_code=200,
        )
        for m in test_models
    }
    unlock_pages[HF_ACTIVITY_URL] = UnlockedPage(
        url=HF_ACTIVITY_URL,
        fetched_at=datetime.now(timezone.utc),
        content=activity_body,
        content_format="markdown",
        status_code=200,
    )
    fake = _FakeBrightDataClient(unlock_pages=unlock_pages)

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]

    assert len(docs) == 3  # 2 READMEs + 1 activity page
    for doc in docs:
        _assert_basic_raw_document_shape(
            doc,
            expected_source_type="huggingface",
            expected_bd_product="web_unlocker",
        )
        assert doc.metadata["org"] == HF_ORG_SLUG
    activity_docs = [d for d in docs if d.metadata.get("fetch_path") == "activity"]
    assert len(activity_docs) == 1
    readme_docs = [d for d in docs if d.metadata.get("fetch_path") == "readme"]
    assert len(readme_docs) == 2
    assert {d.metadata["model"] for d in readme_docs} == set(test_models)


@pytest.mark.asyncio
async def test_obliteratus_plugin_skips_short_readme_responses() -> None:
    """A 200 with an empty/stub body must NOT emit a RawDocument."""
    plugin = ObliteratusHfPlugin(
        models=("Qwen3-4B-OBLITERATED",),
        include_activity_page=False,
    )
    fake = _FakeBrightDataClient(
        unlock_pages={
            _readme_url("Qwen3-4B-OBLITERATED"): UnlockedPage(
                url=_readme_url("Qwen3-4B-OBLITERATED"),
                fetched_at=datetime.now(timezone.utc),
                content="404",
                content_format="markdown",
                status_code=200,
            ),
        }
    )

    docs = await plugin.fetch_since(fake, since=SINCE)  # type: ignore[arg-type]
    assert docs == []


def test_obliteratus_plugin_default_models_locked_at_six() -> None:
    """The §5.2 Source #10 locked model list has 6 models — guard against
    accidental edits to that constant."""
    assert len(OBLITERATUS_DEFAULT_MODELS) == 6


def test_obliteratus_plugin_serp_queries_substitutes_date() -> None:
    plugin = ObliteratusHfPlugin()
    queries = plugin.serp_queries(SINCE)
    assert len(queries) == 1
    assert "site:huggingface.co/OBLITERATUS" in queries[0]
    assert "2026-05-19" in queries[0]


# --------------------------------------------------------------------------- #
# J. DiscoveryAgent (§3.3, §9.3, §A.20)
# --------------------------------------------------------------------------- #


def test_default_plugins_active_set_2026_05_26() -> None:
    """8 plugins wired into harvest. XUserTimelinePlugin + LeakHubScrapePlugin
    disabled 2026-05-26 — X is too slow on BD's discover-by-profile-url
    side (>15min per handle), LeakHub auth-injection over CDP doesn't stick.
    See ``default_plugins()`` docstring for the re-enable path."""
    from rogue.harvest.discovery_agent import default_plugins

    plugins = default_plugins()
    assert len(plugins) == 8
    names = [p.name for p in plugins]
    # Active set must include these 8.
    expected = {
        "arxiv_listing", "blog_static", "reddit_subreddit",
        "huggingface_discussion", "obliteratus_hf", "github_search",
        "pliny_github", "community_archive",
    }
    assert set(names) == expected
    # And NOT include the disabled two.
    assert "x_user_timeline" not in names
    assert "leakhub_scrape" not in names


def test_discovery_agent_day1_query_picker_returns_ten() -> None:
    """Day 1 hand-tuned set is exactly 10 queries per §9.3."""
    from rogue.harvest.discovery_agent import (
        DAY1_HANDPICKED_QUERIES,
        DiscoveryAgent,
    )

    assert len(DAY1_HANDPICKED_QUERIES) == 10
    agent = DiscoveryAgent(client=None, plugins=[])  # type: ignore[arg-type]
    picked = agent.serp_queries(SINCE)
    assert len(picked) == 10
    # `{date}` must be substituted in every query.
    for q in picked:
        assert "{date}" not in q
        assert "2026-05-19" in q


def test_discovery_agent_query_picker_can_be_overridden() -> None:
    """The injection seam for the §11.6 bandit must accept any callable
    returning a list of queries."""
    from rogue.harvest.discovery_agent import DiscoveryAgent

    def bandit_stub(since: datetime) -> list[str]:
        return ["site:example.com after:2026-05-19"]

    agent = DiscoveryAgent(
        client=None,  # type: ignore[arg-type]
        plugins=[],
        query_picker=bandit_stub,
    )
    assert agent.serp_queries(SINCE) == ["site:example.com after:2026-05-19"]


class _FailingPlugin(SourcePlugin):
    """Plugin whose ``fetch_since`` always raises a non-stub exception."""

    name = "always_fails"
    source_type = "other"
    bright_data_product = "web_unlocker"

    async def fetch_since(
        self,
        client: BrightDataClient,
        since: datetime,
    ) -> list[RawDocument]:
        raise RuntimeError("simulated upstream blowup")


class _StubReturnsDocsPlugin(SourcePlugin):
    """Plugin that emits a fixed number of canned RawDocuments."""

    name = "stub_returns_two"
    source_type = "blog"
    bright_data_product = "web_unlocker"

    async def fetch_since(
        self,
        client: BrightDataClient,
        since: datetime,
    ) -> list[RawDocument]:
        fetched_at = datetime.now(timezone.utc)
        body = "stub body " * 20
        archive_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return [
            RawDocument(
                url=f"https://stub.example.com/{i}",
                source_type="blog",
                bright_data_product="web_unlocker",
                fetched_at=fetched_at,
                raw_content=body,
                content_format="markdown",
                archive_hash=archive_hash,
                http_status=200,
                metadata={"i": i},
                discovered_via=None,
            )
            for i in range(2)
        ]


@pytest.mark.asyncio
async def test_discovery_agent_run_fans_out_and_isolates_failures() -> None:
    """One failing plugin must not block the rest; per-plugin reports must
    record both successes and the error string."""
    from rogue.harvest.discovery_agent import DiscoveryAgent

    plugins = [_StubReturnsDocsPlugin(), _FailingPlugin(), _StubReturnsDocsPlugin()]
    agent = DiscoveryAgent(client=None, plugins=plugins)  # type: ignore[arg-type]

    docs = await agent.run(since=SINCE)

    # 2 + 0 + 2 = 4
    assert len(docs) == 4
    assert len(agent.last_run_reports) == 3
    by_name = {r.plugin_name: r for r in agent.last_run_reports}
    assert by_name["stub_returns_two"].n_docs == 2
    assert by_name["stub_returns_two"].error is None
    assert by_name["always_fails"].n_docs == 0
    assert by_name["always_fails"].error is not None
    assert "simulated upstream blowup" in by_name["always_fails"].error


class _NotImplementedStubPlugin(SourcePlugin):
    """Day-0-style stub that raises NotImplementedError on fetch_since."""

    name = "notimpl_stub"
    source_type = "other"
    bright_data_product = "web_unlocker"

    async def fetch_since(
        self,
        client: BrightDataClient,
        since: datetime,
    ) -> list[RawDocument]:
        raise NotImplementedError("Day-0 stub")


@pytest.mark.asyncio
async def test_discovery_agent_run_propagates_not_implemented_loudly() -> None:
    """NotImplementedError must bubble — the convention is that Day-0 stubs
    surface loudly rather than being silently swallowed (mirrors every
    individual plugin's `_safe_unlock` / try-except handling)."""
    from rogue.harvest.discovery_agent import DiscoveryAgent

    agent = DiscoveryAgent(  # type: ignore[arg-type]
        client=None,
        plugins=[_NotImplementedStubPlugin()],
    )
    with pytest.raises(NotImplementedError):
        await agent.run(since=SINCE)


# --------------------------------------------------------------------------- #
# F. Retry policy (ROGUE_PLAN.md §9.2)
# --------------------------------------------------------------------------- #
#
# Verifies the `_is_retryable` predicate wired onto `_post_json`
# (BrightDataClient) + `_do_openai_compat_call` (TargetPanel): 5xx + 429
# retry, 4xx-other-than-429 does NOT retry, and post-exhaustion RateLimit
# conversion to a structured ModelResponse on TargetPanel. We swap the
# tenacity wait to a no-op so the suite stays fast (otherwise each retry
# exhausts the wait_exponential ladder).


def _make_sequence_transport(
    responses: list[httpx.Response],
) -> tuple[httpx.MockTransport, dict[str, int]]:
    """MockTransport that returns successive responses in order.

    Returns the transport plus a call-count dict so tests can assert on the
    number of upstream attempts. After the list is exhausted, returns 500 with
    a sentinel body so the test fails loudly if it makes too many calls.
    """
    queue = list(responses)
    counter = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["calls"] += 1
        if not queue:
            return httpx.Response(500, json={"error": "test queue exhausted"})
        return queue.pop(0)

    return httpx.MockTransport(handler), counter


def _disable_retry_wait(decorated_func: Any) -> None:
    """Swap tenacity's exponential-wait for a zero-wait on a decorated method.

    Without this, each 4-attempt exhaustion test waits ~1 + 2 + 4 = 7s on
    tenacity's wait_exponential ladder. wait_none() keeps the policy
    (predicate, attempt cap) intact while making the test suite fast.
    """
    from tenacity import wait_none

    decorated_func.retry.wait = wait_none()


@pytest.mark.asyncio
async def test_serp_search_retries_on_503_then_succeeds() -> None:
    """503 → 503 → 200 sequence: tenacity retries twice, third call succeeds."""
    from rogue.harvest.bright_data_client import BrightDataClient

    _disable_retry_wait(BrightDataClient._post_json)

    transport, counter = _make_sequence_transport([
        httpx.Response(503, json={"error": "upstream busy"}),
        httpx.Response(503, json={"error": "upstream busy"}),
        httpx.Response(200, json=SERP_PARSED_LIGHT_PIZZA),
    ])
    client = _make_client(transport)
    try:
        result = await client.serp_search("pizza")
    finally:
        await client.aclose()

    assert isinstance(result, SerpResponse)
    assert counter["calls"] == 3
    assert len(result.organic_results) == 2


@pytest.mark.asyncio
async def test_serp_search_retries_on_429_then_succeeds() -> None:
    """429 → 429 → 200 sequence: rate-limited twice, third call succeeds."""
    from rogue.harvest.bright_data_client import BrightDataClient

    _disable_retry_wait(BrightDataClient._post_json)

    transport, counter = _make_sequence_transport([
        httpx.Response(429, json={"error": "rate limited"}),
        httpx.Response(429, json={"error": "rate limited"}),
        httpx.Response(200, json=SERP_PARSED_LIGHT_PIZZA),
    ])
    client = _make_client(transport)
    try:
        result = await client.serp_search("pizza")
    finally:
        await client.aclose()

    assert isinstance(result, SerpResponse)
    assert counter["calls"] == 3


@pytest.mark.asyncio
async def test_serp_search_does_not_retry_on_404() -> None:
    """404 is deterministic — must NOT retry. Exactly one call, then raise."""
    from rogue.harvest.bright_data_client import BrightDataClient

    _disable_retry_wait(BrightDataClient._post_json)

    transport, counter = _make_sequence_transport([
        httpx.Response(404, json={"error": "not found"}),
        # If a retry fires (bug), the next response would be the queue-exhausted
        # 500, but the assertion on `counter["calls"] == 1` catches it cleanly.
    ])
    client = _make_client(transport)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.serp_search("anything")
    finally:
        await client.aclose()

    assert counter["calls"] == 1, "404 must not be retried"
    assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_serp_search_exhausts_retries_on_persistent_503() -> None:
    """Three persistent 503s exhaust the retry budget; the 4th call is never made."""
    from rogue.harvest.bright_data_client import BrightDataClient

    _disable_retry_wait(BrightDataClient._post_json)

    transport, counter = _make_sequence_transport([
        httpx.Response(503, json={"error": "upstream busy"}),
        httpx.Response(503, json={"error": "upstream busy"}),
        httpx.Response(503, json={"error": "upstream busy"}),
        httpx.Response(503, json={"error": "upstream busy"}),  # never consumed
    ])
    client = _make_client(transport)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.serp_search("anything")
    finally:
        await client.aclose()

    # stop_after_attempt(3) caps total attempts at 3 — the 4th queued response
    # must remain in the queue.
    assert counter["calls"] == 3
    assert exc_info.value.response.status_code == 503


@pytest.mark.asyncio
async def test_target_panel_retries_openai_compat_on_503_then_succeeds() -> None:
    """TargetPanel: OpenAI-compat endpoint returns 503 then 200 — recovers."""
    from rogue.reproduce.target_panel import ModelResponse, TargetPanel

    _disable_retry_wait(TargetPanel._do_openai_compat_call)

    # Canonical OpenAI chat-completion response payload.
    success_payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gpt-5.4-nano",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "all good"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
    }

    transport, counter = _make_sequence_transport([
        httpx.Response(503, json={"error": {"message": "upstream busy"}}),
        httpx.Response(200, json=success_payload),
    ])

    panel = TargetPanel()
    # Pre-populate the cached client so _do_openai_compat_call uses our mocked
    # transport. We construct AsyncOpenAI with max_retries=0 to disable the
    # SDK's own retry layer so our tenacity layer is the sole retry policy.
    from openai import AsyncOpenAI

    panel._openai_client = AsyncOpenAI(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=transport),
    )
    try:
        result = await panel._call_openai_compat(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="gpt-5.4-nano",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            trial_index=0,
            client_attr="_openai_client",
            price_key="openai/gpt-5.4-nano",
        )
    finally:
        await panel._openai_client.close()  # type: ignore[union-attr]

    assert isinstance(result, ModelResponse)
    assert result.error is None
    assert result.content == "all good"
    assert counter["calls"] == 2  # one retried 503 + one successful 200


@pytest.mark.asyncio
async def test_target_panel_converts_content_policy_block_to_model_response() -> None:
    """TargetPanel: 400 content-policy block → ``ModelResponse(error=...)``.

    OpenAI returns 400 with ``code: content_filter`` when the model refuses
    a request at the provider level (typically system-prompt-leak or
    explicit-harm category). The SDK surfaces this as ``BadRequestError``
    (a 4xx that the retry predicate deliberately does NOT retry — content
    policy is deterministic, not transient). The outer wrapper must convert
    it to a structured ``ModelResponse`` with the ``content_policy_or_bad_request``
    error tag — this is a valid REFUSED outcome for the breach matrix, not
    an infrastructure failure that should bubble up and abort the run.

    Mirrors the existing rate-limit-exhaustion test (above). §10.1 checkbox
    coverage.
    """
    from rogue.reproduce.target_panel import ModelResponse, TargetPanel

    _disable_retry_wait(TargetPanel._do_openai_compat_call)

    transport, counter = _make_sequence_transport([
        httpx.Response(
            400,
            json={
                "error": {
                    "message": "Your request was rejected as a result of our safety system.",
                    "type": "invalid_request_error",
                    "code": "content_filter",
                },
            },
        ),
    ])

    panel = TargetPanel()
    from openai import AsyncOpenAI

    panel._openai_client = AsyncOpenAI(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=transport),
    )
    try:
        result = await panel._call_openai_compat(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="gpt-5.4-nano",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            trial_index=0,
            client_attr="_openai_client",
            price_key="openai/gpt-5.4-nano",
        )
    finally:
        await panel._openai_client.close()  # type: ignore[union-attr]

    # Structured failure, not raised.
    assert isinstance(result, ModelResponse)
    assert result.error is not None
    assert result.error.startswith("content_policy_or_bad_request")
    assert "content_filter" in result.error or "safety" in result.error
    assert result.content == ""
    # 400 is deterministic — must NOT be retried (predicate returns False
    # for non-429 4xx).
    assert counter["calls"] == 1


@pytest.mark.asyncio
async def test_target_panel_converts_exhausted_rate_limit_to_model_response() -> None:
    """TargetPanel: 429×3 exhausts retries — outer wrapper returns ModelResponse."""
    from rogue.reproduce.target_panel import ModelResponse, TargetPanel

    _disable_retry_wait(TargetPanel._do_openai_compat_call)

    transport, counter = _make_sequence_transport([
        httpx.Response(429, json={"error": {"message": "rate limited"}}),
        httpx.Response(429, json={"error": {"message": "rate limited"}}),
        httpx.Response(429, json={"error": {"message": "rate limited"}}),
    ])

    panel = TargetPanel()
    from openai import AsyncOpenAI

    panel._openai_client = AsyncOpenAI(
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=transport),
    )
    try:
        result = await panel._call_openai_compat(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="gpt-5.4-nano",
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.7,
            trial_index=0,
            client_attr="_openai_client",
            price_key="openai/gpt-5.4-nano",
        )
    finally:
        await panel._openai_client.close()  # type: ignore[union-attr]

    # Not raised — converted by the outer wrapper into a structured failure.
    assert isinstance(result, ModelResponse)
    assert result.error is not None
    assert result.error.startswith("rate_limit_exhausted")
    assert result.content == ""
    # 3 attempts: initial + 2 retries (stop_after_attempt(3)).
    assert counter["calls"] == 3
