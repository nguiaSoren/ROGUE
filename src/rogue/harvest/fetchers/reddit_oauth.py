"""Reddit OAuth fetcher backend — free path using Reddit's "script" app credentials.

Reddit's keyless ``.json`` endpoint is being shut down in 2026. This backend
authenticates via the OAuth2 **client_credentials** grant (a Reddit "script"
app) and calls ``https://oauth.reddit.com/...`` directly. Cost: free. Rate
limit: 60 requests/minute (authenticated). Registers only when both
``REDDIT_CLIENT_ID`` and ``REDDIT_CLIENT_SECRET`` are present in the
environment.

OAuth flow
----------
1. POST ``https://www.reddit.com/api/v1/access_token``
   - HTTP Basic auth: client_id:client_secret
   - body: ``grant_type=client_credentials``
   - header: ``User-Agent: <REDDIT_USER_AGENT>``
2. Response: ``{"access_token": "...", "token_type": "bearer",
   "expires_in": 86400, ...}``
3. Subsequent API calls: ``Authorization: Bearer <token>`` to
   ``https://oauth.reddit.com/...``

Token is cached in memory + expiry timestamp; re-fetched automatically
when it expires (or 60 s before, as a grace margin).

Endpoints
---------
``reddit_subreddit(sub, limit)``
    ``GET https://oauth.reddit.com/r/{sub}/new.json?limit={limit}``
    Returns listing children mapped to :class:`RedditPost`.

``reddit_keyword(keyword, date_range, num_of_posts)``
    ``GET https://oauth.reddit.com/search.json?q=...&sort=new&t={t}&limit=...``
    ``date_range`` maps to Reddit's ``t`` (time-filter) param:
        "Past hour"  → ``hour``
        "Past day"   → ``day``
        "Past week"  → ``week``  (default)
        "Past month" → ``month``
        "Past year"  → ``year``
        "All time"   → ``all``

RedditPost field mapping
------------------------
Reddit OAuth ``/r/sub/new`` listing child ``data`` fields → RedditPost fields:

    id            → post_id   (prefixed "t3_" on fullname; bare ``id`` here)
    subreddit     → subreddit
    title         → title
    selftext      → body      (text posts); url used as fallback for link posts
    author        → author
    created_utc   → posted_at (Unix float → UTC datetime)
    permalink     → permalink (relative "/r/…"; prepended with reddit.com base)
    score         → score
    comments      → []        (Reddit listing doesn't include comments inline)
    url/preview   → media_urls (images only; non-image ``url`` excluded)

Required env vars
-----------------
REDDIT_CLIENT_ID     — OAuth app "client ID" (from https://www.reddit.com/prefs/apps)
REDDIT_CLIENT_SECRET — OAuth app "secret" (same page)
REDDIT_USER_AGENT    — descriptive UA string, e.g.
                       "rogue-red-team/0.1 by u/your_username"
                       Reddit's API ToS requires a descriptive UA; missing one
                       causes 429s independent of rate-limiting.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import Fetcher
from .capabilities import Capability

# Imported at runtime (not TYPE_CHECKING) because we construct instances;
# safe because bright_data_client is already a project dependency.
from rogue.harvest.bright_data_client import RedditPost

__all__ = ["RedditOAuthFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.reddit_oauth")

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API_BASE = "https://oauth.reddit.com"
_DEFAULT_UA = "rogue-red-team/0.1"

# Refresh the token 60 s before it truly expires to avoid mid-run expiry.
_EXPIRY_GRACE_SECONDS = 60.0

# Minimum seconds between successive API calls to stay under 60 req/min.
# 1.0 s → maximum 60 calls/min; slightly conservative but safe.
_MIN_CALL_INTERVAL = 1.0

# Map the BD-style ``date_range`` strings (used by scrape_reddit_keyword and
# the source plugin) to Reddit's ``t`` param for /search.
_DATE_RANGE_TO_T: dict[str, str] = {
    "Past hour": "hour",
    "Past day": "day",
    "Past week": "week",
    "Past month": "month",
    "Past year": "year",
    "All time": "all",
}


def _get_env(name: str) -> str:
    """Return stripped env var value, or '' if absent/blank."""
    return os.environ.get(name, "").strip()


def _parse_utc(created_utc: Any) -> datetime:
    """Convert a Reddit ``created_utc`` Unix float to a UTC-aware datetime."""
    try:
        ts = float(created_utc)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc)


def _extract_image_urls(child_data: dict[str, Any]) -> list[str]:
    """Extract image URLs from a Reddit listing child's ``data`` dict.

    Reddit exposes images via ``preview.images[].source.url`` (HTML-encoded,
    needing ``&amp;`` → ``&``) and ``url`` when the post is a direct image
    link (i.e. the domain is i.redd.it or i.imgur.com).
    """
    urls: list[str] = []

    # preview block (highest-res "source" per image)
    preview = child_data.get("preview") or {}
    for img in preview.get("images") or []:
        if not isinstance(img, dict):
            continue
        source = img.get("source") or {}
        u = source.get("url", "")
        # Reddit HTML-encodes & in preview URLs
        u = u.replace("&amp;", "&")
        if u.startswith(("http://", "https://")):
            urls.append(u)

    # Direct image link posts
    direct_url = child_data.get("url", "")
    if isinstance(direct_url, str) and (
        "i.redd.it" in direct_url
        or "i.imgur.com" in direct_url
        or direct_url.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
    ):
        if direct_url.startswith(("http://", "https://")) and direct_url not in urls:
            urls.append(direct_url)

    return urls


def _child_to_reddit_post(child_data: dict[str, Any]) -> RedditPost | None:
    """Map one Reddit listing child ``data`` dict → :class:`RedditPost`.

    Returns ``None`` if the child is missing a valid ``id`` (defensive against
    empty/stickied entries that occasionally appear in the listing).
    """
    post_id = str(child_data.get("id") or "").strip()
    if not post_id:
        return None

    subreddit = str(child_data.get("subreddit") or "")
    title = str(child_data.get("title") or "")

    # selftext for text posts; fall back to url for link posts (gives context
    # to the extraction LLM about what the link post points to).
    body = str(child_data.get("selftext") or child_data.get("url") or "")

    author = str(child_data.get("author") or "")
    posted_at = _parse_utc(child_data.get("created_utc"))

    # Reddit returns relative permalinks like /r/sub/comments/…; make absolute.
    rel_permalink = str(child_data.get("permalink") or "")
    permalink = (
        f"https://www.reddit.com{rel_permalink}"
        if rel_permalink.startswith("/")
        else rel_permalink
    )

    score = int(child_data.get("score") or 0)
    media_urls = _extract_image_urls(child_data)

    return RedditPost(
        post_id=post_id,
        subreddit=subreddit,
        title=title,
        body=body,
        author=author,
        posted_at=posted_at,
        permalink=permalink,
        score=score,
        comments=[],          # inline comments not available in listing responses
        media_urls=media_urls,
    )


def _parse_listing(data: Any) -> list[RedditPost]:
    """Parse a Reddit listing JSON response → ``list[RedditPost]``.

    Handles both the bare listing shape (``{"kind": "Listing", "data": {...}}``
    ) and the search response shape which is the same at top level.
    """
    posts: list[RedditPost] = []
    try:
        listing_data = data.get("data") or {}
        children = listing_data.get("children") or []
        for child in children:
            if not isinstance(child, dict):
                continue
            child_data = child.get("data") or {}
            post = _child_to_reddit_post(child_data)
            if post is not None:
                posts.append(post)
    except Exception as exc:  # noqa: BLE001
        logger.warning("reddit_oauth: failed to parse listing: %s", exc)
    return posts


class RedditOAuthFetcher(Fetcher):
    """Reddit fetcher via OAuth2 client-credentials — the free harvest path.

    Registers only when ``REDDIT_CLIENT_ID`` and ``REDDIT_CLIENT_SECRET`` are
    set in the environment. Implements only :attr:`~Capability.REDDIT`; all
    other capabilities fall through to ``CapabilityNotSupported`` (inherited
    from :class:`Fetcher`).

    Thread / async safety: token refresh and the ``_last_call_at`` pacing
    timestamp are module-level instance variables, not shared across instances.
    For ROGUE's single-threaded async harvest this is sufficient.
    """

    name = "reddit_oauth"
    capabilities = frozenset({Capability.REDDIT})

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires_at: float = 0.0   # monotonic time
        self._last_call_at: float = 0.0        # monotonic time; pacing guard
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # is_available — used by the registry to decide whether to register
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """True iff both required env vars are present and non-empty."""
        return bool(_get_env("REDDIT_CLIENT_ID") and _get_env("REDDIT_CLIENT_SECRET"))

    # ------------------------------------------------------------------
    # HTTP client lifecycle
    # ------------------------------------------------------------------

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            ua = _get_env("REDDIT_USER_AGENT") or _DEFAULT_UA
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers={"User-Agent": ua},
                follow_redirects=True,
            )
        return self._http

    async def aclose(self) -> None:
        """Release the held HTTP client. Idempotent."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _token_is_valid(self) -> bool:
        return (
            self._token is not None
            and time.monotonic() < self._token_expires_at - _EXPIRY_GRACE_SECONDS
        )

    async def _ensure_token(self) -> str | None:
        """Return a valid bearer token, refreshing if necessary.

        Returns ``None`` (and logs a warning) on any auth failure so callers
        can degrade gracefully.
        """
        if self._token_is_valid():
            return self._token

        client_id = _get_env("REDDIT_CLIENT_ID")
        client_secret = _get_env("REDDIT_CLIENT_SECRET")
        ua = _get_env("REDDIT_USER_AGENT") or _DEFAULT_UA

        if not client_id or not client_secret:
            logger.warning("reddit_oauth: REDDIT_CLIENT_ID/SECRET not set — cannot authenticate")
            return None

        http = self._get_http()
        try:
            resp = await http.post(
                _TOKEN_URL,
                auth=(client_id, client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": ua},
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("reddit_oauth: token fetch failed: %s", exc)
            return None

        token = payload.get("access_token")
        if not token:
            logger.warning("reddit_oauth: token response missing access_token: %r", payload)
            return None

        expires_in = float(payload.get("expires_in") or 3600)
        self._token = str(token)
        self._token_expires_at = time.monotonic() + expires_in
        logger.debug("reddit_oauth: acquired bearer token (expires_in=%ss)", expires_in)
        return self._token

    # ------------------------------------------------------------------
    # Rate-pacing helper
    # ------------------------------------------------------------------

    async def _pace(self) -> None:
        """Ensure at least ``_MIN_CALL_INTERVAL`` seconds between API calls."""
        import asyncio
        now = time.monotonic()
        gap = self._last_call_at + _MIN_CALL_INTERVAL - now
        if gap > 0:
            await asyncio.sleep(gap)
        self._last_call_at = time.monotonic()

    # ------------------------------------------------------------------
    # Internal authenticated GET
    # ------------------------------------------------------------------

    async def _api_get(self, path: str, params: dict[str, Any] | None = None) -> Any | None:
        """Authenticated GET against ``https://oauth.reddit.com{path}``.

        Returns the parsed JSON body, or ``None`` on any failure (auth,
        network, non-2xx, parse error) — callers degrade to ``[]``.
        """
        token = await self._ensure_token()
        if token is None:
            return None

        await self._pace()

        url = f"{_API_BASE}{path}"
        http = self._get_http()
        try:
            resp = await http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "reddit_oauth: HTTP %s for %s — %s",
                exc.response.status_code, url, exc,
            )
            # Invalidate the token on 401 so the next call re-authenticates.
            if exc.response.status_code == 401:
                self._token = None
                self._token_expires_at = 0.0
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("reddit_oauth: request to %s failed: %s", url, exc)
            return None

    # ------------------------------------------------------------------
    # Fetcher capability implementations
    # ------------------------------------------------------------------

    async def reddit_subreddit(self, subreddit: str, limit: int = 100) -> list[RedditPost]:
        """Fetch the newest posts from ``subreddit`` via the OAuth API.

        Calls ``GET /r/{subreddit}/new.json?limit={limit}``. Reddit caps
        ``limit`` at 100 per request; values above 100 are silently clamped
        server-side. Returns ``[]`` on any failure (degrade-safe).
        """
        clamped = min(max(1, limit), 100)
        data = await self._api_get(
            f"/r/{subreddit}/new.json",
            params={"limit": clamped, "raw_json": 1},
        )
        if data is None:
            logger.warning("reddit_oauth: reddit_subreddit(%r) returned no data", subreddit)
            return []
        posts = _parse_listing(data)
        logger.debug("reddit_oauth: reddit_subreddit(%r) → %d posts", subreddit, len(posts))
        return posts

    async def reddit_keyword(
        self,
        keyword: str,
        date_range: str = "Past week",
        num_of_posts: int = 50,
    ) -> list[RedditPost]:
        """Search Reddit globally for ``keyword`` via the OAuth API.

        Calls ``GET /search.json?q={keyword}&sort=new&t={t}&limit={n}``.
        ``date_range`` is the same BD-style enum the source plugin passes
        (e.g. ``"Past week"``); it is mapped to Reddit's ``t`` param.
        Returns ``[]`` on any failure.
        """
        t = _DATE_RANGE_TO_T.get(date_range, "week")
        clamped = min(max(1, num_of_posts), 100)
        data = await self._api_get(
            "/search.json",
            params={
                "q": keyword,
                "sort": "new",
                "t": t,
                "limit": clamped,
                "raw_json": 1,
            },
        )
        if data is None:
            logger.warning(
                "reddit_oauth: reddit_keyword(%r, %r) returned no data",
                keyword, date_range,
            )
            return []
        posts = _parse_listing(data)
        logger.debug(
            "reddit_oauth: reddit_keyword(%r, t=%r) → %d posts",
            keyword, t, len(posts),
        )
        return posts
