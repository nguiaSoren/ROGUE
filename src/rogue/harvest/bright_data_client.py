"""Bright Data unified client — Day 1 implementation.

Wraps all 5 Bright Data products used by ROGUE with one consistent interface:

  1. Web Scraper API (pre-built scrapers) — Reddit, X/Twitter, HuggingFace
  2. SERP API — Google / Bing structured search results
  3. Web Unlocker — WAF-bypassing single-page fetch (HTML or markdown)
  4. Scraping Browser — Playwright-over-websocket fallback for dynamic pages
  5. MCP Server — wired separately at the agent layer, NOT through this client

Status: Day 1 (§9.2). The class signature + Pydantic return-types remain the
locked Day 0 contract — only method bodies / private helpers / module-level
constants changed. Every HTTP call goes through a single shared
``httpx.AsyncClient`` (lazy-init via ``_get_http``) so connection pooling is
preserved across hundreds of harvest fan-outs. Retries: tenacity, 3 attempts,
exponential backoff, via the ``_is_retryable`` predicate — fires on network
transients (``ConnectError``, ``ReadTimeout``, ``WriteTimeout``,
``RemoteProtocolError``) AND on ``HTTPStatusError`` with status_code in
``{429, 500, 502, 503, 504}``. 4xx other than 429 are deterministic (bad
request / auth / not-found) and propagate to the caller after the first
attempt. Each method optionally writes a ``BrightDataCostLog`` row when given a
SQLAlchemy ``Session``; commit is the caller's responsibility.

Canonical spec: ROGUE_PLAN.md §A.7. Cost model: §6.1. Day 1 work: §9.2.

Callers MUST ``await client.aclose()`` at shutdown to release the shared HTTP
client; otherwise asyncio will log unclosed-transport warnings on process exit.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, Optional
from urllib.parse import quote_plus

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from rogue.harvest.media_extract import (
    extract_media_urls_from_json as _extract_media_urls_from_json,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("rogue.harvest.bright_data_client")

__all__ = [
    "BrightDataClient",
    "RedditPost",
    "XPost",
    "HFDiscussion",
    "SerpResponse",
    "UnlockedPage",
    "ScrapedPage",
]


# ---------------------------------------------------------------------------
# Module-level constants — pricing table per §6.1.
# ---------------------------------------------------------------------------

# Per-unit cost estimates derived from §6.1 of ROGUE_PLAN.md. Stored as a
# module-level table so cost-log inserts compute deterministically and the
# Day-2 cost-budget guardrails can audit estimated vs. actual spend.
_COST_PER_UNIT: dict[str, float] = {
    "serp": 0.0015,                    # $1.50 / 1k queries → $0.0015 each
    "unlocker": 0.0025,                # $0.001–$0.005 per page → midpoint
    "web_scraper_api_record": 0.0015,  # $1.50 / 1k records → $0.0015 each
    "scraping_browser_session": 0.01,  # $0.005–$0.02 per session → midpoint
}


def _estimate_cost(product_key: str, units: int = 1) -> float:
    """Compute estimated USD cost for ``units`` of ``product_key``."""
    return _COST_PER_UNIT.get(product_key, 0.0) * units


# Retry policy (per ROGUE_PLAN.md §9.2). Retry on (a) network transients,
# (b) HTTPStatusError with status_code in {429, 500, 502, 503, 504} as
# surfaced by ``raise_for_status``. 4xx other than 429 are deterministic
# (bad request / auth / not-found) and re-issuing won't help — they
# propagate to the caller as ``HTTPStatusError``. Tenacity reraises after
# the final attempt so the caller sees the underlying error.
# See tasks/LESSONS.md 2026-05-25 retry-policy completion.
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.RemoteProtocolError,
)


# ---------------------------------------------------------------------------
# Async-polling fallback defaults (see ``_scrape_dataset`` async branch).
# ---------------------------------------------------------------------------
#
# Bright Data's sync scrape endpoint has a hard 60s timeout. Past that, it
# returns a body with ``{"snapshot_id": "..."}`` and the caller is expected
# to switch to the async polling flow (GET /datasets/v3/progress/{id} →
# GET /datasets/v3/snapshot/{id}). The defaults below mirror BD's own
# Python example in ``website/WEB SCRAPER API/twitter/async-requests.md``
# (10s between polls) plus a generous ceiling so a single high-volume
# subreddit can't stall a daily harvest.
_POLL_INTERVAL_SECONDS_DEFAULT = 10.0
_POLL_TIMEOUT_SECONDS_DEFAULT = 600.0  # 10 minutes


class BrightDataAsyncPollTimeout(RuntimeError):
    """Raised when a snapshot does not transition to ``ready`` in time."""


class BrightDataSnapshotFailed(RuntimeError):
    """Raised when a snapshot's progress status reports ``failed``."""


def _env_clean(name: str) -> str | None:
    """Return ``os.environ[name]`` stripped of whitespace + inline ``#`` comments.

    Returns None when the cleaned value is empty OR starts with ``#``. Defensive
    against the ``.env`` footgun where the value carries an inline comment
    (python-dotenv treats anything-after-equals as the value):

        BRIGHTDATA_HUGGINGFACE_DATASET_ID=    # leave blank if so

    Without this scrub, that value would be sent verbatim to BD and yield a 404.
    """
    raw = os.environ.get(name, "").strip()
    if not raw or raw.startswith("#"):
        return None
    return raw


def _is_retryable(exc: BaseException) -> bool:
    """Return True if ``exc`` is a network transient or a 5xx/429 HTTPStatusError.

    Used by tenacity's ``retry_if_exception`` predicate on ``_post_json``.
    4xx other than 429 are deterministic — bad request, auth failure, or a
    genuine 404 — so they're not retried. See ROGUE_PLAN.md §9.2.
    """
    if isinstance(exc, _TRANSIENT_ERRORS):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return False


# ---------------------------------------------------------------------------
# Return-type models (Pydantic v2 BaseModel — matches §A.7's choice)
# ---------------------------------------------------------------------------


class RedditPost(BaseModel):
    """Single Reddit post + its top-level comments. Returned by the Web Scraper
    API pre-built Reddit dataset. Field names match ROGUE_PLAN.md §A.7."""

    post_id: str
    subreddit: str
    title: str
    body: str
    author: str
    posted_at: datetime
    permalink: str
    score: int
    comments: list[dict] = Field(default_factory=list)
    # Image URLs attached to the post (the Reddit dataset's `photos` array —
    # same shape as the X dataset). Powers multimodal ingestion (Feature A): an
    # image-only Reddit post (a screenshot of a jailbreak) lands here. Excludes
    # `videos`. See XPost.media_urls for the full rationale.
    media_urls: list[str] = Field(default_factory=list)


class XPost(BaseModel):
    """Single X/Twitter post. Returned by the Web Scraper API pre-built
    posts-by-profile-URL dataset. Field names match §A.7."""

    post_id: str
    author_handle: str
    body: str
    posted_at: datetime
    permalink: str
    metrics: dict = Field(default_factory=dict)
    # Image URLs attached to the post (the X dataset's `photos` array — see
    # website/WEB SCRAPER API/social-media-apis/twitter-posts-discover-by-profile-url-most-recent.md).
    # Powers multimodal ingestion (Feature A): a Pliny screenshot of a jailbreak
    # prompt lands here. Excludes `videos` (vision LLMs take stills, not clips)
    # and `profile_image_link` (the author avatar — never a payload).
    media_urls: list[str] = Field(default_factory=list)


class HFDiscussion(BaseModel):
    """A single HuggingFace model-card discussion thread. Returned by the
    Web Scraper API HuggingFace dataset (where available). Field names match §A.7."""

    model_id: str
    thread_id: str
    title: str
    posts: list[dict] = Field(default_factory=list)
    started_at: datetime
    # Image URLs embedded in the thread's posts (multimodal ingestion, Feature
    # A). HF discussions carry images as markdown/links inside post bodies under
    # best-guess (unprovisioned) field names, so these are collected by a
    # field-name-agnostic JSON walk rather than a single `photos` array.
    media_urls: list[str] = Field(default_factory=list)


class SerpResponse(BaseModel):
    """SERP API response: organic results + optional knowledge panel +
    full raw JSON for downstream parsing. Matches §A.7's ``SerpResult`` shape."""

    query: str
    engine: str
    fetched_at: datetime
    organic_results: list[dict] = Field(default_factory=list)
    knowledge_panel: Optional[dict] = None
    raw_json: dict = Field(default_factory=dict)


class UnlockedPage(BaseModel):
    """Web Unlocker response: HTML or markdown content for a single URL."""

    url: str
    fetched_at: datetime
    content: str
    content_format: Literal["html", "markdown"]
    status_code: int


class ScrapedPage(BaseModel):
    """Scraping Browser response: raw HTML + rendered text after JS execution."""

    url: str
    fetched_at: datetime
    html: str
    rendered_text: str


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class BrightDataClient:
    """Async client wrapping all 5 Bright Data products used by ROGUE.

    Shared ``httpx.AsyncClient`` is lazy-initialized via ``_get_http`` on first
    call so importing this module remains zero-IO. Callers should
    ``await client.aclose()`` at shutdown to release the connection pool.
    """

    def __init__(
        self,
        api_key: str,
        serp_zone: str,
        unlocker_zone: str,
        browser_zone: str,
        reddit_dataset_id: str | None,
        x_posts_dataset_id: str | None,
        hf_dataset_id: str | None,
        *,
        poll_interval_seconds: float = _POLL_INTERVAL_SECONDS_DEFAULT,
        poll_timeout_seconds: float = _POLL_TIMEOUT_SECONDS_DEFAULT,
    ) -> None:
        self.api_key = api_key
        self.serp_zone = serp_zone
        self.unlocker_zone = unlocker_zone
        self.browser_zone = browser_zone
        self.reddit_dataset_id = reddit_dataset_id
        self.x_posts_dataset_id = x_posts_dataset_id
        self.hf_dataset_id = hf_dataset_id
        # Async-polling fallback tunables — defaults align with BD's own
        # example (10s interval) + a 10-minute ceiling. Tests override to
        # near-zero so the polling path completes in milliseconds.
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_timeout_seconds = poll_timeout_seconds
        self._base_url = "https://api.brightdata.com"
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "BrightDataClient":
        """Construct from environment variables (see .env.example).

        Required: ``BRIGHTDATA_API_KEY``, ``BRIGHTDATA_SERP_ZONE``,
        ``BRIGHTDATA_UNLOCKER_ZONE``, ``BRIGHTDATA_BROWSER_ZONE``.
        Optional (may be empty if dataset not yet provisioned on Day 1):
        ``BRIGHTDATA_REDDIT_DATASET_ID``, ``BRIGHTDATA_X_POSTS_DATASET_ID``,
        ``BRIGHTDATA_HUGGINGFACE_DATASET_ID``.

        Day 1 wiring helper — lets callers do ``BrightDataClient.from_env()``
        without re-listing every variable. Defensive against the common
        ``.env`` footgun where a value contains an inline ``#`` comment
        (e.g. ``BRIGHTDATA_HUGGINGFACE_DATASET_ID=    # leave blank if so``)
        — python-dotenv loads the comment as part of the value, which would
        otherwise be sent as the dataset_id and yield a 404. We strip
        whitespace + treat any value starting with ``#`` as effectively
        unset. Verified 2026-05-26 via per-source smoke test.
        """
        # Async-snapshot poll timeout is env-overridable: BD's X
        # discover-by-profile scraper can take 15-30+ min, exceeding the 600s
        # default, so a Pliny-X harvest needs e.g.
        # BRIGHTDATA_POLL_TIMEOUT_SECONDS=1800. Falls back to the defaults on a
        # blank/unparseable value.
        def _float_env(name: str, default: float) -> float:
            raw = _env_clean(name)
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        return cls(
            api_key=_env_clean("BRIGHTDATA_API_KEY") or "",
            serp_zone=_env_clean("BRIGHTDATA_SERP_ZONE") or "",
            unlocker_zone=_env_clean("BRIGHTDATA_UNLOCKER_ZONE") or "",
            browser_zone=_env_clean("BRIGHTDATA_BROWSER_ZONE") or "",
            reddit_dataset_id=_env_clean("BRIGHTDATA_REDDIT_DATASET_ID"),
            x_posts_dataset_id=_env_clean("BRIGHTDATA_X_POSTS_DATASET_ID"),
            hf_dataset_id=_env_clean("BRIGHTDATA_HUGGINGFACE_DATASET_ID"),
            poll_interval_seconds=_float_env(
                "BRIGHTDATA_POLL_INTERVAL_SECONDS", _POLL_INTERVAL_SECONDS_DEFAULT
            ),
            poll_timeout_seconds=_float_env(
                "BRIGHTDATA_POLL_TIMEOUT_SECONDS", _POLL_TIMEOUT_SECONDS_DEFAULT
            ),
        )

    # ------------------------------------------------------------------
    # Shared httpx client lifecycle
    # ------------------------------------------------------------------

    def _get_http(self) -> httpx.AsyncClient:
        """Return the shared ``AsyncClient``, constructing it on first use.

        Lazy init keeps the constructor and ``from_env`` zero-IO so importing
        / type-checking this module never requires network or credentials.
        """
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._http

    async def aclose(self) -> None:
        """Release the shared HTTP client. Idempotent.

        Callers MUST invoke this at shutdown to avoid asyncio
        unclosed-transport warnings (e.g. as a FastAPI lifespan handler or
        inside a ``finally:`` block at the end of a harvest run).
        """
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Cost-tracking helper
    # ------------------------------------------------------------------

    def _log_cost(
        self,
        session: "Session | None",
        product: str,
        units: int,
        cost_usd: float,
        notes: str | None = None,
    ) -> None:
        """Insert a ``BrightDataCostLog`` row when ``session`` is provided.

        The caller controls the transaction — we only ``session.add()``. No
        commit, no flush. If ``session`` is None this is a no-op so test paths
        and library-only consumers don't need to wire a DB at all.
        """
        if session is None:
            return
        # Local import to keep the module import-safe even if SQLAlchemy isn't
        # available at runtime (e.g. CLI utilities that only need the client).
        from rogue.db.models import BrightDataCostLog

        session.add(
            BrightDataCostLog(
                product=product,
                units=units,
                cost_usd=cost_usd,
                ran_at=datetime.now(timezone.utc),
                notes=notes,
            )
        )

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _post_json(
        self,
        url: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """POST + ``raise_for_status`` with tenacity retry per ``_is_retryable``.

        Retries on network transients AND on 5xx/429 ``HTTPStatusError`` (see
        ``_is_retryable`` for the full predicate). 4xx other than 429
        propagate immediately as ``HTTPStatusError`` — they are deterministic
        (bad request / auth / not-found) so re-issuing won't help. Tenacity
        reraises after the final attempt; ``response.raise_for_status()`` is
        what surfaces non-2xx as ``HTTPStatusError`` in the first place.
        """
        client = self._get_http()
        response = await client.post(url, json=json, params=params)
        response.raise_for_status()
        return response

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """GET sibling of :meth:`_post_json` — same retry predicate.

        Used by the async-polling fallback for the BD progress + snapshot
        endpoints (both are GETs against ``/datasets/v3/{progress,snapshot}/{id}``).
        """
        client = self._get_http()
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Async-polling fallback (BD sync timeout → snapshot_id → poll → fetch)
    # ------------------------------------------------------------------

    async def _poll_snapshot_until_ready(self, snapshot_id: str) -> None:
        """Poll ``/datasets/v3/progress/{snapshot_id}`` until status='ready'.

        BD status enum (per ``monitor-progress.md``): ``starting`` /
        ``running`` / ``ready`` / ``failed``. Polling cadence + deadline are
        driven by the instance's ``poll_interval_seconds`` /
        ``poll_timeout_seconds`` (defaults 10s + 600s; tests set near-zero).

        Raises :class:`BrightDataSnapshotFailed` on ``failed`` status and
        :class:`BrightDataAsyncPollTimeout` when the deadline trips before
        ``ready`` — both carry the snapshot_id so the caller can resume
        out-of-band (e.g. by hand-fetching the partial snapshot).
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.poll_timeout_seconds
        progress_url = f"{self._base_url}/datasets/v3/progress/{snapshot_id}"

        last_status = "unknown"
        while True:
            response = await self._get_json(progress_url)
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            last_status = str(payload.get("status", "unknown"))

            if last_status == "ready":
                return
            if last_status == "failed":
                raise BrightDataSnapshotFailed(
                    f"BD snapshot {snapshot_id!r} reported status=failed: "
                    f"{payload}"
                )
            # ``starting`` / ``running`` / anything-else → sleep + retry.
            if loop.time() >= deadline:
                raise BrightDataAsyncPollTimeout(
                    f"BD snapshot {snapshot_id!r} did not reach status=ready "
                    f"within {self.poll_timeout_seconds:.0f}s "
                    f"(last status: {last_status})"
                )
            await asyncio.sleep(self.poll_interval_seconds)

    async def _download_snapshot(self, snapshot_id: str) -> list[dict[str, Any]]:
        """GET ``/datasets/v3/snapshot/{snapshot_id}?format=json`` → records.

        The download endpoint returns the same record shape as the sync
        ``/scrape`` endpoint — a JSON array on success. Defensive cast in
        case a single object slips through (some scrapers return one even
        when N inputs were sent).
        """
        download_url = f"{self._base_url}/datasets/v3/snapshot/{snapshot_id}"
        response = await self._get_json(download_url, params={"format": "json"})
        data = response.json()
        if isinstance(data, dict):
            return [data]
        return list(data)

    # ------------------------------------------------------------------
    # Web Scraper API (pre-built scrapers) — product #1 in §6.1
    # Cost: ~$1.50 per 1k records, pay-per-success.
    # ------------------------------------------------------------------

    async def _trigger_and_poll(
        self,
        dataset_id: str,
        inputs: list[dict[str, Any]],
        *,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """POST ``/datasets/v3/trigger`` → poll progress → download snapshot.

        Required for *discover-mode* scrapers (``discover_by=subreddit_url``,
        ``discover_by=keyword``, ``discover_by=profile_url_most_recent_posts``).
        Per BD docs: "Discovery is only available via async requests"
        (``website/WEB SCRAPER API/twitter/introduction.md``). The sync
        ``/scrape`` endpoint silently returns ``200 []`` for these modes
        when discovery would have produced records — verified 2026-05-26
        against Reddit ``r/learnpython`` (sync 200 [] vs trigger 999 records)
        and Reddit ``discover_by=keyword`` ("jailbreak prompt" returned 20).

        Body shape is the bare JSON array ``[{...}, {...}]`` per every BD
        ``/trigger`` example we have (Reddit + X async-requests.md), not
        the ``{"input": [...]}`` wrapper that ``_scrape_dataset`` accepts.

        Validation errors (HTTP 400 with body ``{"error":"...", "code":"validation_error"}``)
        propagate as :class:`httpx.HTTPStatusError` — the caller can read
        ``exc.response.text`` to surface the exact field error.
        """
        params: dict[str, Any] = {"dataset_id": dataset_id, "format": "json"}
        if extra_params:
            params.update(extra_params)
        response = await self._post_json(
            f"{self._base_url}/datasets/v3/trigger",
            json=inputs,
            params=params,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"BD /trigger returned non-JSON body "
                f"(status={response.status_code}): {response.text[:300]!r}"
            ) from exc
        snapshot_id = (
            payload.get("snapshot_id") if isinstance(payload, dict) else None
        )
        if not snapshot_id:
            raise RuntimeError(
                f"BD /trigger response missing snapshot_id: {payload!r}"
            )
        await self._poll_snapshot_until_ready(str(snapshot_id))
        return await self._download_snapshot(str(snapshot_id))

    async def _scrape_dataset(
        self,
        dataset_id: str,
        inputs: list[dict[str, Any]],
        *,
        extra_params: dict[str, Any] | None = None,
        wrap_input: bool = False,
    ) -> list[dict[str, Any]]:
        """POST to ``/datasets/v3/scrape`` and return the parsed JSON records.

        Body shape is selectable via ``wrap_input``:

          * ``wrap_input=False`` (default) — sends the bare JSON-array
            ``[{...}, {...}]``. BD's sync endpoint accepts this for
            collect-by-URL scrapers like Reddit and the SERP API; the
            original Day-0 code path uses it.
          * ``wrap_input=True`` — sends the canonical ``{"input": [...]}``
            wrapper per the OpenAPI schema in
            ``website/WEB SCRAPER API/synchronous-requests.md:115-142``.
            Required by *discover-mode* scrapers (X "discover by profile
            URL most recent posts") where the bare-list form silently
            falls back to collect-by-URL behaviour and returns empty
            results.

        The sync endpoint has a 1-minute timeout; if exceeded the API
        returns a ``202`` with a ``snapshot_id`` and we surface a clear
        RuntimeError so callers can decide to fall back to async polling.
        """
        params: dict[str, Any] = {"dataset_id": dataset_id, "format": "json"}
        if extra_params:
            params.update(extra_params)

        body: Any = {"input": inputs} if wrap_input else inputs
        response = await self._post_json(
            f"{self._base_url}/datasets/v3/scrape",
            json=body,
            params=params,
        )

        # BD sync timeout fallback: when the scrape exceeds the 60s sync
        # ceiling, the endpoint returns a body of shape
        # ``{"snapshot_id": "...", "message": "..."}`` and the caller is
        # expected to poll /datasets/v3/progress/{id} until ready then
        # GET /datasets/v3/snapshot/{id} for the records.
        #
        # The HTTP status code is inconsistent across BD endpoints — the
        # OpenAPI spec documents 202, but live calls (verified 2026-05-26
        # against the Reddit + X discover-mode endpoints) often return 200
        # with the same snapshot_id body. Detect on the *body shape* not
        # on the status code, so we don't get tripped by either.
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and "snapshot_id" in payload:
            snapshot_id = str(payload["snapshot_id"])
            await self._poll_snapshot_until_ready(snapshot_id)
            return await self._download_snapshot(snapshot_id)

        # Sync success — the endpoint returns a JSON array on success.
        # Defensive cast in case a single object slips through (some
        # scrapers return one even when N inputs were sent).
        if isinstance(payload, dict):
            return [payload]
        if payload is None:
            return []
        return list(payload)

    async def scrape_reddit_subreddit(
        self,
        subreddit: str,
        limit: int = 100,
        *,
        session: "Session | None" = None,
    ) -> list[RedditPost]:
        """Web Scraper API — Reddit "Discover by subreddit URL" mode.

        POSTs to ``/datasets/v3/scrape?dataset_id={reddit_dataset_id}`` with
        the subreddit URL and returns structured ``RedditPost`` records
        (post + top-level comments). Cost: ~$1.50 / 1k records (§6.1 product
        #1). Up to 20 URLs per request.

        IMPORTANT — discover-mode params: the Reddit dataset
        (``gd_lvz8ah06191smkebj4``) is a single dataset_id with FOUR modes
        ("Collect by URL", "Discover by author URL", "Discover by keyword",
        "Discover by subreddit URL") selected via ``type`` + ``discover_by``
        query parameters. Without them, BD silently falls back to ``Collect
        by URL`` mode — which expects a specific post URL like
        ``/r/x/comments/abc/.../`` not the subreddit listing URL we send
        — and returns empty results. See ``tasks/LESSONS.md`` 2026-05-26
        entry for the full pattern (same trap applies to X).

        Also uses ``wrap_input=True`` to send the canonical
        ``{"input": [...]}`` body shape required by discover-mode scrapers.
        """
        if not self.reddit_dataset_id:
            raise RuntimeError(
                "BRIGHTDATA_REDDIT_DATASET_ID not set — provision the Reddit "
                'Web Scraper API dataset and pick the "Discover by subreddit '
                'URL" mode in the Bright Data control panel.'
            )

        # The discover-by-subreddit-url input schema does NOT accept a
        # `limit` field — BD validates and rejects it ("This input should
        # not contain a limit field"). Record count is scraper-config-driven
        # on BD's side; the plugin filters surplus posts client-side via
        # `since`. The `limit` arg below is preserved for API compat but
        # only flows into the cost-log notes line; no over-the-wire effect.
        #
        # `sort_by` is TitleCase ("New" / "Hot" / "Top" / "Rising"); lowercase
        # values are rejected by BD validation despite the docs example using
        # `"hot"`. Verified 2026-05-26 via /trigger validation_error response.
        #
        # Uses `_trigger_and_poll` (async /trigger) instead of `_scrape_dataset`
        # (sync /scrape) because discovery is async-only on BD per the docs
        # ("Discovery is only available via async requests"); sync silently
        # returns `200 []` for discover-mode requests.
        subreddit_url = f"https://www.reddit.com/r/{subreddit}/"
        inputs = [{"url": subreddit_url, "sort_by": "New"}]
        records = await self._trigger_and_poll(
            self.reddit_dataset_id,
            inputs,
            extra_params={
                "type": "discover_new",
                "discover_by": "subreddit_url",
            },
        )
        posts = [_record_to_reddit_post(r, subreddit_fallback=subreddit) for r in records]

        cost = _estimate_cost("web_scraper_api_record", units=len(posts))
        self._log_cost(
            session,
            product="web_scraper_api",
            units=len(posts),
            cost_usd=cost,
            notes=f"reddit:{subreddit}",
        )
        return posts

    async def scrape_reddit_keyword(
        self,
        keyword: str,
        date_range: str = "Past week",
        num_of_posts: int = 50,
        *,
        session: "Session | None" = None,
    ) -> list[RedditPost]:
        """Web Scraper API — Reddit "Discover by keyword" mode.

        Higher-yield path than ``scrape_reddit_subreddit`` for jailbreak/
        prompt-injection content: searches Reddit *globally* (not gated by
        a single subreddit), so it surfaces hits from r/AIJailbreak,
        r/ArtificialIntelligence, r/MachineLearning, etc. — anywhere the
        keyword appears. Verified 2026-05-26: "jailbreak prompt" returns
        20 records in ~78s via /trigger; for comparison
        ``discover_by=subreddit_url`` on r/ChatGPTJailbreak returns 0.

        Args:
            keyword: free-text search phrase (e.g. "jailbreak prompt",
                "prompt injection", "system prompt leak"). Combined keywords
                like "jailbreak GPT-5" are accepted.
            date_range: BD-controlled date enum — "Past day", "Past week",
                "Past month", "Past year", "All time". Default "Past week"
                matches the daily-harvest cadence with a small overlap.
            num_of_posts: requested max records. BD's discover mode caps this
                internally; values above ~100 may take 4+ minutes to poll.

        Body shape: ``[{"keyword": ..., "date": ..., "num_of_posts": ...}]``
        per ``website/WEB SCRAPER API/reddit/send-first-request.md`` line 188.
        ``date`` (NOT ``date_range``) is the BD field name — exact casing
        matters.
        """
        if not self.reddit_dataset_id:
            raise RuntimeError(
                "BRIGHTDATA_REDDIT_DATASET_ID not set — provision the Reddit "
                "Web Scraper API dataset (the same dataset_id covers "
                "subreddit_url + keyword discovery modes)."
            )
        inputs = [
            {"keyword": keyword, "date": date_range, "num_of_posts": num_of_posts},
        ]
        records = await self._trigger_and_poll(
            self.reddit_dataset_id,
            inputs,
            extra_params={
                "type": "discover_new",
                "discover_by": "keyword",
            },
        )
        posts = [_record_to_reddit_post(r, subreddit_fallback="") for r in records]

        cost = _estimate_cost("web_scraper_api_record", units=len(posts))
        self._log_cost(
            session,
            product="web_scraper_api",
            units=len(posts),
            cost_usd=cost,
            notes=f"reddit-keyword:{keyword[:80]}",
        )
        return posts

    async def scrape_x_user_posts(
        self,
        profile_url: str,
        limit: int = 50,
        *,
        session: "Session | None" = None,
    ) -> list[XPost]:
        """Web Scraper API — X "Discover by profile URL — Most recent posts".

        POSTs to ``/datasets/v3/scrape?dataset_id={x_posts_dataset_id}`` with
        the profile URL and returns structured ``XPost`` records. Cost:
        ~$1.50 / 1k records (§6.1 product #1).

        IMPORTANT — discover-mode params: the X dataset
        (``gd_lwxkxvnf1cynvib9co``) is a single dataset_id with multiple
        modes selected via ``type`` + ``discover_by`` query parameters.
        Without them, BD silently falls back to ``Collect by URL`` mode
        (which expects a status URL not a profile URL) and returns empty
        results. See ``tasks/LESSONS.md`` 2026-05-26 entry for the full
        rationale + verification flow.

        Also uses ``wrap_input=True`` to send the canonical
        ``{"input": [...]}`` body shape; discover-mode scrapers require it.
        ``start_date`` / ``end_date`` fields on each input dict are
        accepted by the scraper and left empty (= no time filter) since
        ``XUserTimelinePlugin`` does the date filtering client-side
        against the harvest's ``since`` cursor.
        """
        if not self.x_posts_dataset_id:
            raise RuntimeError(
                "BRIGHTDATA_X_POSTS_DATASET_ID not set — provision the X "
                '"Discover by profile URL — Most recent posts" Web Scraper API dataset.'
            )

        # Uses `_trigger_and_poll` (async /trigger) — discovery is async-only
        # on BD, same constraint as Reddit. Sync /scrape silently returned
        # `200 []` for discover-by-profile-url before the 2026-05-26 fix.
        #
        # Like Reddit's discover-by-subreddit-url, this mode REJECTS a
        # `limit` field on the input dict — BD 400s with
        # `{"errors":[["limit","This input should not contain a limit field"]]}`.
        # Record count is scraper-config-driven on BD's side; the `limit`
        # arg below only flows into the cost-log notes line for accounting.
        # Verified 2026-05-26 via direct /trigger probe.
        _ = limit  # parameter kept for caller-API stability; no over-the-wire effect
        inputs = [
            {"url": profile_url, "start_date": "", "end_date": ""},
        ]
        records = await self._trigger_and_poll(
            self.x_posts_dataset_id,
            inputs,
            extra_params={
                "type": "discover_new",
                "discover_by": "profile_url_most_recent_posts",
            },
        )
        posts = [_record_to_x_post(r) for r in records]

        cost = _estimate_cost("web_scraper_api_record", units=len(posts))
        self._log_cost(
            session,
            product="web_scraper_api",
            units=len(posts),
            cost_usd=cost,
            notes=f"x:{profile_url}",
        )
        return posts

    async def scrape_huggingface_discussion(
        self,
        model_id: str,
        *,
        session: "Session | None" = None,
    ) -> list[HFDiscussion]:
        """Web Scraper API — HuggingFace model-card discussions dataset.

        Standard scrape pattern keyed on ``hf_dataset_id``. If
        ``hf_dataset_id`` is None the helpful runtime error directs the
        source-plugin layer to fall back to ``web_unlock`` against the
        public HF discussions page. Cost band: ~$1.50 / 1k records
        (§6.1 product #1).
        """
        if self.hf_dataset_id is None:
            raise RuntimeError(
                "BRIGHTDATA_HUGGINGFACE_DATASET_ID not set — HF discussions "
                "may not be in BD's pre-built list yet; fall back to "
                "web_unlock at the source-plugin layer "
                "(huggingface_discussion.py)"
            )

        discussions_url = f"https://huggingface.co/{model_id}/discussions"
        inputs = [{"url": discussions_url, "model_id": model_id}]
        records = await self._scrape_dataset(self.hf_dataset_id, inputs)
        discussions = [_record_to_hf_discussion(r, model_id_fallback=model_id) for r in records]

        cost = _estimate_cost("web_scraper_api_record", units=len(discussions))
        self._log_cost(
            session,
            product="web_scraper_api",
            units=len(discussions),
            cost_usd=cost,
            notes=f"hf:{model_id}",
        )
        return discussions

    # ------------------------------------------------------------------
    # SERP API — product #2 in §6.1
    # Cost: ~$1.50–$3.00 per 1k queries, retries free, parsing included.
    # ------------------------------------------------------------------

    async def serp_search(
        self,
        query: str,
        count: int = 10,
        engine: str = "google",
        *,
        session: "Session | None" = None,
    ) -> SerpResponse:
        """SERP API — structured search results for Google or Bing.

        POSTs to ``/request`` with ``data_format=parsed_light`` per §6.1: top
        organic results only, ~2x faster + cheaper than full JSON. The Bing
        path uses ``parsed`` (Bing-specific) which the API maps to Bing's
        parsed-JSON shape.
        """
        engine_lc = engine.lower()
        encoded = quote_plus(query)
        if engine_lc == "google":
            target_url = (
                f"https://www.google.com/search?q={encoded}"
                f"&hl=en&gl=us&num={count}"
            )
            data_format = "parsed_light"
        elif engine_lc == "bing":
            # REVIEW Day 1 §9.2 — Bing query-string pattern is best-guess from
            # the SERP-API/get-started-bing-serp-api.md flow; live verify the
            # `count` parameter name (Bing uses `count` not `num`).
            target_url = f"https://www.bing.com/search?q={encoded}&count={count}"
            data_format = "parsed"
        else:
            raise ValueError(f"Unsupported SERP engine: {engine!r} (use 'google' or 'bing')")

        body = {
            "zone": self.serp_zone,
            "url": target_url,
            "format": "raw",
            "data_format": data_format,
        }
        response = await self._post_json(f"{self._base_url}/request", json=body)

        try:
            raw_json: dict = response.json()
        except ValueError:
            # The endpoint occasionally returns raw HTML when `data_format`
            # is ignored upstream — wrap it so callers still get a SerpResponse.
            raw_json = {"raw_text": response.text}

        organic = raw_json.get("organic") if isinstance(raw_json, dict) else None
        knowledge = (
            raw_json.get("knowledge") if isinstance(raw_json, dict) else None
        ) or (raw_json.get("overview") if isinstance(raw_json, dict) else None)

        result = SerpResponse(
            query=query,
            engine=engine_lc,
            fetched_at=datetime.now(timezone.utc),
            organic_results=list(organic) if isinstance(organic, list) else [],
            knowledge_panel=knowledge if isinstance(knowledge, dict) else None,
            raw_json=raw_json if isinstance(raw_json, dict) else {"raw": raw_json},
        )

        self._log_cost(
            session,
            product="serp_api",
            units=1,
            cost_usd=_estimate_cost("serp", units=1),
            notes=f"{engine_lc}:{query[:80]}",
        )
        return result

    # ------------------------------------------------------------------
    # Web Unlocker — product #3 in §6.1
    # Cost: a few cents per page fetch, typically $0.001–$0.005.
    # ------------------------------------------------------------------

    async def web_unlock(
        self,
        url: str,
        format: str = "markdown",
        *,
        session: "Session | None" = None,
    ) -> UnlockedPage:
        """Web Unlocker — WAF-bypassing single-page fetch.

        POSTs to ``/request`` with the Unlocker zone. Returns either raw
        HTML (``format='html'``) or markdown (``format='markdown'``, default)
        for direct feeding to the extraction LLM. Cost: per-page-fetch,
        typically a few cents (§6.1 product #3).
        """
        fmt = format.lower()
        if fmt not in ("html", "markdown"):
            raise ValueError(f"Unsupported Web Unlocker format: {format!r}")

        # Per website/WEB-UNLOCKER/send-your-first-request.md the API uses
        # ``format: "raw"`` to return the unmodified target response; the
        # ``data_format`` field then selects markdown/html post-processing.
        body = {
            "zone": self.unlocker_zone,
            "url": url,
            "format": "raw",
            "data_format": fmt,
        }
        response = await self._post_json(f"{self._base_url}/request", json=body)

        result = UnlockedPage(
            url=url,
            fetched_at=datetime.now(timezone.utc),
            content=response.text,
            content_format=fmt,  # type: ignore[arg-type]
            status_code=response.status_code,
        )

        self._log_cost(
            session,
            product="web_unlocker",
            units=1,
            cost_usd=_estimate_cost("unlocker", units=1),
            notes=url[:200],
        )
        return result

    async def resolve_redirect(
        self,
        url: str,
        *,
        timeout: float = 10.0,
        transport: "httpx.BaseTransport | httpx.AsyncBaseTransport | None" = None,
    ) -> str:
        """Resolve a short/redirect URL to its final destination (Feature C).

        The post→link follower needs the REAL destination of a ``t.co``-style
        shortener so dedup / domain-routing / provenance key on the true URL,
        not the opaque short link. Implemented as a cheap HEAD (GET fallback for
        shorteners that reject HEAD) that follows redirects — **NOT** a
        BD-billed Web Unlocker fetch, and on a SEPARATE auth-less httpx client
        so the BD bearer token is never leaked to the third-party shortener.

        ``transport`` is a test seam (inject an ``httpx.MockTransport``); None
        uses the default network transport.

        Returns the FINAL URL, or the input ``url`` unchanged on any error /
        timeout (degrade-safe — a failed resolution just means we follow the
        short link as-is downstream).
        """
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=timeout, transport=transport
            ) as client:
                resp = await client.head(url)
                # Some shorteners 405/400 on HEAD — retry with GET (no body read
                # needed; we only want the post-redirect URL).
                if resp.status_code >= 400:
                    resp = await client.get(url)
                final = str(resp.url)
                return final or url
        except Exception as exc:  # noqa: BLE001 — degrade to the unresolved url
            logger.debug("resolve_redirect failed for %s: %s", url[:120], exc)
            return url

    # ------------------------------------------------------------------
    # Media fetch (§11.8) — SERP image search + binary download.
    # Real-image carriers for multimodal attacks (composited via base_image).
    # ------------------------------------------------------------------

    async def serp_image_search(
        self,
        query: str,
        count: int = 5,
        *,
        session: "Session | None" = None,
    ) -> list[str]:
        """SERP API — Google **Images** search; return candidate image URLs.

        Uses ``udm=2`` (Google image-search mode, replaced ``tbm=isch`` in 2026)
        + ``brd_json=1`` (Bright Data parsed JSON) per
        ``website/SERP-API/send-your-first-request.md``. Returns up to ``count``
        URLs, full-resolution (``original_image``) first, falling back to the
        thumbnail (``image``). Empty list if the search returns nothing parseable.
        """
        encoded = quote_plus(query)
        target_url = (
            f"https://www.google.com/search?q={encoded}&udm=2&brd_json=1&hl=en&gl=us"
        )
        body = {"zone": self.serp_zone, "url": target_url, "format": "raw"}
        response = await self._post_json(f"{self._base_url}/request", json=body)

        urls: list[str] = []
        try:
            data = response.json()
        except ValueError:
            data = {}
        images = data.get("images") if isinstance(data, dict) else None
        if isinstance(images, list):
            for img in images:
                if not isinstance(img, dict):
                    continue
                u = img.get("original_image") or img.get("image")
                if isinstance(u, str) and u.startswith("http"):
                    urls.append(u)
                if len(urls) >= count:
                    break

        self._log_cost(
            session,
            product="serp_api",
            units=1,
            cost_usd=_estimate_cost("serp", units=1),
            notes=f"images:{query[:80]}",
        )
        return urls

    async def fetch_image_bytes(
        self,
        url: str,
        *,
        session: "Session | None" = None,
    ) -> tuple[bytes, str]:
        """Web Unlocker — download the RAW BYTES of a (binary) URL, e.g. an image.

        Unlike :meth:`web_unlock` (which returns ``response.text`` for HTML /
        markdown and would mangle binary), this returns ``response.content``
        unmodified plus the upstream ``content-type`` — the bytes ready to
        base64 onto a ``RenderedAttack`` / composite as a ``base_image``. Per
        ``website/WEB-UNLOCKER/send-your-first-request.md`` (``format:"raw"``).
        """
        body = {"zone": self.unlocker_zone, "url": url, "format": "raw"}
        response = await self._post_json(f"{self._base_url}/request", json=body)
        content_type = response.headers.get("content-type", "application/octet-stream")

        self._log_cost(
            session,
            product="web_unlocker",
            units=1,
            cost_usd=_estimate_cost("unlocker", units=1),
            notes=f"image:{url[:180]}",
        )
        return response.content, content_type

    # ------------------------------------------------------------------
    # Scraping Browser (fallback) — product #4 in §6.1
    # Cost: bandwidth-billed, a few cents per session.
    # ------------------------------------------------------------------

    async def scrape_browser(
        self,
        url: str,
        wait_for_selector: str | None = None,
        scroll_pages: int = 1,
        *,
        storage_state: dict[str, Any] | None = None,
        session: "Session | None" = None,
    ) -> ScrapedPage:
        """Scraping Browser — Playwright-over-websocket fallback.

        Connects to ``wss://{user}:{pass}@brd.superproxy.io:9222`` per
        ``website/SCRAPING-BROWSER/quickstart.md`` and ``code-examples.md``
        (the Python ``connect_over_cdp`` path). Browser AUTH is
        ``brd-customer-{cid}-zone-{browser_zone}:{password}``; the customer
        ID + password live in ``BRIGHTDATA_BROWSER_CUSTOMER_ID`` and
        ``BRIGHTDATA_BROWSER_PASSWORD`` since the Day 0 constructor only
        locks the zone name.

        # REVIEW Day 1 §9.2 — this path is the least exercised on Day 1.
        # Playwright is intentionally a lazy import (not a hard pyproject
        # dep); if Day-1 hits this path heavily, add `playwright` to
        # ``[project.optional-dependencies].browser`` and run
        # ``playwright install chromium``.
        """
        if importlib.util.find_spec("playwright") is None:
            raise ImportError(
                "scrape_browser requires Playwright but it is not installed. "
                "Run: pip install playwright && playwright install chromium "
                "(Day-1 chooser decides whether to add this as a hard dep)."
            )

        customer_id = os.environ.get("BRIGHTDATA_BROWSER_CUSTOMER_ID", "")
        password = os.environ.get("BRIGHTDATA_BROWSER_PASSWORD", "")
        if not customer_id or not password:
            raise RuntimeError(
                "Scraping Browser requires BRIGHTDATA_BROWSER_CUSTOMER_ID and "
                "BRIGHTDATA_BROWSER_PASSWORD env vars (they are not on the "
                "locked Day 0 constructor signature)."
            )

        auth = f"brd-customer-{customer_id}-zone-{self.browser_zone}:{password}"
        endpoint = f"wss://{auth}@brd.superproxy.io:9222"

        # Lazy import keeps the module import-safe when playwright isn't
        # installed (find_spec above gives a clearer ImportError above).
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]

        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(endpoint)
            try:
                # CDP-attached contexts (BD's remote Scraping Browser) do NOT
                # reliably honor ``new_context(storage_state=...)`` for the
                # per-origin localStorage arm — Playwright sends the blob
                # but the server discards it because no origin has been
                # navigated yet at context-creation. Verified 2026-05-26
                # against LeakHub: passing storage_state via new_context
                # yielded the same "Sign in" nav as anonymous fetch.
                #
                # Working pattern: ``add_init_script`` injects a tiny piece
                # of JS that runs BEFORE every navigation's page scripts on
                # the current origin — including the SPA bundle that boots
                # auth state. Setting localStorage here runs after the page
                # context is bound to the origin (post-navigation), but
                # before the SPA's React/Convex auth init reads it.
                # Cookies stay on ``add_cookies`` (origin-independent;
                # Playwright accepts them pre-navigation just fine).
                context = await browser.new_context()
                if storage_state and storage_state.get("cookies"):
                    await context.add_cookies(storage_state["cookies"])

                if storage_state and storage_state.get("origins"):
                    import json as _json
                    for origin_entry in storage_state["origins"]:
                        ls_entries = origin_entry.get("localStorage", [])
                        if not ls_entries:
                            continue
                        # Init script runs on every page in this context
                        # before page scripts. localStorage.setItem on the
                        # current origin — Playwright already binds the
                        # origin partition before init scripts run.
                        init_js = (
                            "(() => { const entries = "
                            + _json.dumps(ls_entries)
                            + "; for (const e of entries) { try { "
                            + "window.localStorage.setItem(e.name, e.value); "
                            + "} catch (err) {} } })();"
                        )
                        await context.add_init_script(init_js)

                page = await context.new_page()

                # 2-minute goto timeout matches the website/ code examples;
                # most BD-unlocked pages return well inside that window.
                await page.goto(url, timeout=2 * 60_000)

                if wait_for_selector:
                    await page.wait_for_selector(wait_for_selector, timeout=30_000)

                # Optional N-times scroll for lazy-loaded feeds. Cheap and
                # idempotent so the default of 1 still touches the page.
                for _ in range(max(0, scroll_pages - 1)):
                    await page.evaluate("window.scrollBy(0, window.innerHeight);")

                html = await page.content()
                # ``inner_text('body')`` is the closest one-shot Playwright API
                # to "rendered text"; downstream code can re-extract richer
                # text via BeautifulSoup if needed.
                rendered_text = await page.evaluate("document.body.innerText")
            finally:
                await browser.close()

        result = ScrapedPage(
            url=url,
            fetched_at=datetime.now(timezone.utc),
            html=html,
            rendered_text=rendered_text or "",
        )

        self._log_cost(
            session,
            product="scraping_browser",
            units=1,
            cost_usd=_estimate_cost("scraping_browser_session", units=1),
            notes=url[:200],
        )
        return result


# ---------------------------------------------------------------------------
# Record → Pydantic adapters (defensive, matches §A.7 field names)
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime:
    """Best-effort parse of a Bright Data ``date_posted`` style string.

    Bright Data returns ISO-8601 strings (`2025-03-14T18:22:00Z`); a few
    older scrapers send Unix timestamps. Both are accepted here. If parsing
    fails we fall back to "now UTC" so the Pydantic model still validates
    rather than dropping the entire record.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            # ``fromisoformat`` accepts trailing 'Z' since Python 3.11.
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _photo_urls_from_record(record: dict[str, Any]) -> list[str]:
    """Lift a social-post record's image array (`photos`, `images` fallback).

    Shared by the X and Reddit adapters — both BD social datasets expose the
    same `photos: [url, ...]` shape (`null` on text-only posts). Keeps only
    http(s) string URLs; `videos` and `profile_image_link` are never read here.
    """
    return [
        u
        for u in (record.get("photos") or record.get("images") or [])
        if isinstance(u, str) and u.startswith(("http://", "https://"))
    ]


def _record_to_reddit_post(record: dict[str, Any], *, subreddit_fallback: str) -> RedditPost:
    """Adapt one Reddit scraper record into a ``RedditPost``.

    Field names follow website/WEB SCRAPER API/reddit/send-first-request.md
    (``post_id``, ``user_posted``, ``title``, ``description``, etc.).
    """
    post_id = str(record.get("post_id") or record.get("id") or "")
    return RedditPost(
        post_id=post_id,
        subreddit=str(record.get("community_name") or subreddit_fallback),
        title=str(record.get("title") or ""),
        body=str(record.get("description") or record.get("body") or ""),
        author=str(record.get("user_posted") or record.get("author") or ""),
        posted_at=_parse_dt(record.get("date_posted") or record.get("posted_at")),
        permalink=str(record.get("url") or record.get("permalink") or ""),
        score=int(record.get("num_upvotes") or record.get("score") or 0),
        comments=list(record.get("comments") or []),
        media_urls=_photo_urls_from_record(record),
    )


def _record_to_x_post(record: dict[str, Any]) -> XPost:
    """Adapt one X/Twitter scraper record into an ``XPost``.

    Field names follow website/WEB SCRAPER API/twitter/send-first-request.md
    (``url``, ``user_posted``, ``description``, ``date_posted``,
    ``likes``/``retweets``/``replies``).
    """
    url = str(record.get("url") or record.get("permalink") or "")
    # Trailing ``/status/{id}`` is the canonical X post-id surface; fall back
    # to a record-level id if the scraper provides one.
    post_id = str(record.get("post_id") or record.get("id") or url.rsplit("/", 1)[-1])
    metrics = {
        k: record[k]
        for k in ("likes", "retweets", "replies", "views", "hashtags")
        if k in record
    }
    # `photos` is the X dataset's image array (verified against the posts
    # discover-by-profile schema). `videos` and `profile_image_link` are
    # deliberately excluded — see XPost.media_urls docstring.
    media_urls = _photo_urls_from_record(record)
    return XPost(
        post_id=post_id,
        author_handle=str(record.get("user_posted") or record.get("author") or ""),
        body=str(record.get("description") or record.get("body") or ""),
        posted_at=_parse_dt(record.get("date_posted") or record.get("posted_at")),
        permalink=url,
        metrics=metrics,
        media_urls=media_urls,
    )


def _record_to_hf_discussion(
    record: dict[str, Any], *, model_id_fallback: str
) -> HFDiscussion:
    """Adapt one HF discussion record into an ``HFDiscussion``.

    # REVIEW Day 1 §9.2 — HF discussions are not in BD's pre-built scraper
    # list as of writing; field names here are conservative best-guess and
    # will need a live-payload pass once the dataset_id is provisioned (or
    # the source plugin falls back to web_unlock instead).
    """
    return HFDiscussion(
        model_id=str(record.get("model_id") or model_id_fallback),
        thread_id=str(record.get("thread_id") or record.get("id") or ""),
        title=str(record.get("title") or ""),
        posts=list(record.get("posts") or []),
        started_at=_parse_dt(record.get("started_at") or record.get("date_posted")),
        # Walk the whole record (post bodies included) for embedded images —
        # field-name-agnostic because the HF discussion schema is best-guess.
        media_urls=_extract_media_urls_from_json(record),
    )
