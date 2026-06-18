"""X/Twitter best-effort keyless fetcher — EXPERIMENTAL.

Fetches an X user timeline without API credentials via X's public syndication
endpoint (``https://syndication.twitter.com/srv/timeline-profile/screen-name/<handle>``).
Falls back to the guest-token GraphQL endpoint when syndication fails.

FRAGILITY WARNING: This backend breaks periodically (guest tokens rotate,
endpoint shapes change, Cloudflare rules tighten). Every failure degrades
gracefully to ``[]`` + a WARNING log; it never raises. This is accepted-risk
behaviour documented in tasks/fetcher_abstraction_spec.md § X SAFEGUARDS.

X ToS note: X Terms of Service impose liquidated damages for automated
access exceeding 1,000,000 posts/24 h. The ROGUE harvest stays orders of
magnitude below that cap via a hard self-cap (default ≤200 posts/call,
configurable DOWN only via ``ROGUE_X_MAX_POSTS``).

Self-cap: ``min(limit, MAX_POSTS)`` where ``MAX_POSTS`` defaults to 200 and
may be overridden to a smaller value via the env var ``ROGUE_X_MAX_POSTS``.
Setting it to a value LARGER than 200 is silently clamped to 200 — the cap
is a hard ceiling, not a requested size.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

from .base import Fetcher
from .capabilities import Capability

if TYPE_CHECKING:
    from rogue.harvest.bright_data_client import XPost

__all__ = ["XBestEffortFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.x_besteffort")

# Hard ceiling on posts per call.  Env var may lower it but never raises it.
_ABSOLUTE_MAX_POSTS: int = 200

# Public syndication timeline endpoint — no auth required when it's up.
_SYNDICATION_URL = (
    "https://syndication.twitter.com/srv/timeline-profile/screen-name/{handle}"
)

# Guest-token endpoints used as a secondary fallback.
_GUEST_TOKEN_URL = "https://api.twitter.com/1.1/guest/activate.json"
_TIMELINE_URL = (
    "https://twitter.com/i/api/graphql/oMVVrI5kt3kOpyHHTTKf5Q/UserByScreenName"
)

# A minimal browser-like UA so syndication returns content rather than 403.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_BASE_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "en-US,en;q=0.9",
}


def _effective_max() -> int:
    """Return the effective per-call post cap, clamped to [1, _ABSOLUTE_MAX_POSTS]."""
    raw = os.environ.get("ROGUE_X_MAX_POSTS", "")
    if raw.strip():
        try:
            val = int(raw.strip())
            return max(1, min(val, _ABSOLUTE_MAX_POSTS))
        except ValueError:
            pass
    return _ABSOLUTE_MAX_POSTS


def _extract_handle(profile_url: str) -> str:
    """Pull the @handle out of an x.com (or twitter.com) profile URL.

    Accepts:
      - ``https://x.com/simonw``
      - ``https://twitter.com/simonw``
      - ``https://x.com/simonw/``
      - bare handle ``simonw``
    """
    # Strip query string / fragment first
    url = profile_url.split("?")[0].split("#")[0].rstrip("/")
    # If it looks like a URL, grab the last path segment
    m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,50})", url)
    if m:
        return m.group(1)
    # Fall back: treat the whole string as a bare handle (strip leading @)
    return url.lstrip("@")


def _parse_tweet(tweet: dict) -> "XPost | None":
    """Convert a raw tweet dict (syndication or GraphQL shape) to XPost.

    Returns None when the dict is missing required fields. Never raises.

    Field mapping:
      syndication: id_str → post_id, user.screen_name → author_handle,
                   full_text/text → body, created_at (RFC2822) → posted_at,
                   permalink synthesised from user + id_str,
                   favorite_count/retweet_count/reply_count → metrics,
                   entities.media[type=photo].media_url_https → media_urls
      GraphQL result: wrapped under result.legacy — same field names
                      (legacy is the same serialisation as v1.1).
    """
    # Import here (runtime, not TYPE_CHECKING) to build the model.
    from rogue.harvest.bright_data_client import XPost

    # GraphQL wraps the tweet under `result.legacy`
    if "result" in tweet and isinstance(tweet["result"], dict):
        tweet = tweet["result"].get("legacy", tweet["result"])

    post_id = str(tweet.get("id_str") or tweet.get("id") or "")
    if not post_id:
        return None

    body = str(tweet.get("full_text") or tweet.get("text") or "")
    handle = str(
        (tweet.get("user") or {}).get("screen_name")
        or tweet.get("author_handle")
        or ""
    )

    # created_at is RFC 2822 in the X API ("Thu Apr 06 15:28:43 +0000 2023")
    posted_at = _parse_created_at(tweet.get("created_at", ""))

    permalink = f"https://x.com/{handle}/status/{post_id}" if handle else ""

    metrics: dict = {}
    for src_key, dst_key in (
        ("favorite_count", "likes"),
        ("retweet_count", "retweets"),
        ("reply_count", "replies"),
        ("quote_count", "quotes"),
    ):
        val = tweet.get(src_key)
        if val is not None:
            try:
                metrics[dst_key] = int(val)
            except (TypeError, ValueError):
                pass

    # Extract photo media URLs (type == "photo" only; skip videos)
    media_urls: list[str] = []
    entities = tweet.get("entities") or {}
    extended = tweet.get("extended_entities") or {}
    for media_item in (extended.get("media") or entities.get("media") or []):
        if not isinstance(media_item, dict):
            continue
        if media_item.get("type") == "photo":
            url = media_item.get("media_url_https") or media_item.get("media_url")
            if isinstance(url, str) and url.startswith("http"):
                media_urls.append(url)

    return XPost(
        post_id=post_id,
        author_handle=handle,
        body=body,
        posted_at=posted_at,
        permalink=permalink,
        metrics=metrics,
        media_urls=media_urls,
    )


def _parse_created_at(value: str) -> datetime:
    """Parse X's RFC 2822 'created_at' string to an aware UTC datetime.

    Falls back to now(UTC) on any parse failure so the XPost is still valid.
    """
    if not value:
        return datetime.now(timezone.utc)
    # email.utils.parsedate_to_datetime handles RFC 2822 cleanly.
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(value).astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        pass
    # ISO fallback (some internal endpoints surface ISO-8601)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


async def _fetch_syndication(handle: str, cap: int) -> list["XPost"]:
    """Attempt the public syndication endpoint; return [] on any failure."""
    url = _SYNDICATION_URL.format(handle=handle)
    try:
        async with httpx.AsyncClient(
            headers=_BASE_HEADERS,
            timeout=httpx.Timeout(15.0, connect=8.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(url, params={"count": cap})
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("x_besteffort syndication failed for @%s: %s", handle, exc)
        return []

    tweets: list[dict] = []
    # Syndication wraps results under timeline.entries[].content.tweet
    try:
        timeline = data.get("timeline") or {}
        entries = timeline.get("entries") or data.get("tweets") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content") or {}
            tweet = content.get("tweet") or content
            if isinstance(tweet, dict) and ("id_str" in tweet or "id" in tweet):
                tweets.append(tweet)
    except Exception as exc:  # noqa: BLE001
        logger.debug("x_besteffort syndication parse error for @%s: %s", handle, exc)
        return []

    posts = []
    for t in tweets[:cap]:
        p = _parse_tweet(t)
        if p is not None:
            posts.append(p)
    return posts


async def _fetch_guest_token() -> str | None:
    """Obtain a guest token from X's activate endpoint; None on failure."""
    try:
        # Bearer token for the public web client — this is the same value
        # embedded in every X web-app bundle and is treated as a public
        # constant (not a credential).
        bearer = (
            "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
            "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
        )
        async with httpx.AsyncClient(
            headers={**_BASE_HEADERS, "Authorization": f"Bearer {bearer}"},
            timeout=httpx.Timeout(10.0, connect=6.0),
        ) as client:
            resp = await client.post(_GUEST_TOKEN_URL)
            resp.raise_for_status()
            return str(resp.json().get("guest_token", ""))
    except Exception as exc:  # noqa: BLE001
        logger.debug("x_besteffort guest-token fetch failed: %s", exc)
        return None


async def _fetch_graphql(handle: str, cap: int) -> list["XPost"]:
    """Attempt the GraphQL UserTweets endpoint with a guest token; return [] on any failure."""
    token = await _fetch_guest_token()
    if not token:
        return []

    bearer = (
        "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
        "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
    )
    headers = {
        **_BASE_HEADERS,
        "Authorization": f"Bearer {bearer}",
        "x-guest-token": token,
    }
    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(20.0, connect=8.0),
            follow_redirects=True,
        ) as client:
            # First resolve the numeric user-id from the screen name
            resp = await client.get(
                _TIMELINE_URL,
                params={
                    "variables": f'{{"screen_name":"{handle}","withSafetyModeUserFields":true}}',
                    "features": "{}",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.debug("x_besteffort graphql failed for @%s: %s", handle, exc)
        return []

    # Navigate the nested GraphQL response for tweets
    posts: list["XPost"] = []
    try:
        instructions = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline_v2", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        for instruction in instructions:
            if not isinstance(instruction, dict):
                continue
            for entry in instruction.get("entries") or []:
                if not isinstance(entry, dict):
                    continue
                tweet = (
                    entry.get("content", {})
                    .get("itemContent", {})
                    .get("tweet_results", {})
                )
                if isinstance(tweet, dict):
                    p = _parse_tweet(tweet)
                    if p is not None:
                        posts.append(p)
                        if len(posts) >= cap:
                            break
            if len(posts) >= cap:
                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("x_besteffort graphql parse error for @%s: %s", handle, exc)

    return posts


class XBestEffortFetcher(Fetcher):
    """Keyless X/Twitter timeline fetcher — EXPERIMENTAL, accepted-fragility.

    Implements only the ``X`` capability via X's public syndication endpoint
    with a guest-token GraphQL fallback. Any failure returns ``[]`` + WARNING;
    it never raises. Registered last in the fetcher preference order so Bright
    Data still wins for paying users.

    Self-cap: ``min(limit, MAX)`` where MAX ≤ 200 (env ``ROGUE_X_MAX_POSTS``
    to lower, never raise). See module docstring for the X ToS rationale.
    """

    name = "x_besteffort"
    capabilities = frozenset({Capability.X})

    @classmethod
    def is_available(cls) -> bool:
        """Always True — backend registers unconditionally (but is last-preference)."""
        return True

    async def x_user_posts(self, profile_url: str, limit: int = 50) -> list["XPost"]:
        """Fetch recent posts for an X profile URL, best-effort keyless path.

        Tries the syndication endpoint first; falls back to guest-token GraphQL.
        On any failure returns ``[]`` and logs a WARNING — never raises.
        Hard self-cap: ``min(limit, MAX_POSTS)`` where MAX_POSTS ≤ 200.
        """
        cap = min(limit, _effective_max())
        handle = _extract_handle(profile_url)
        if not handle:
            logger.warning(
                "x_besteffort: could not extract a handle from %r — returning []",
                profile_url,
            )
            return []

        try:
            posts = await _fetch_syndication(handle, cap)
            if posts:
                logger.debug(
                    "x_besteffort: syndication returned %d posts for @%s",
                    len(posts),
                    handle,
                )
                return posts[:cap]

            logger.debug(
                "x_besteffort: syndication returned 0 for @%s; trying GraphQL fallback",
                handle,
            )
            posts = await _fetch_graphql(handle, cap)
            if posts:
                logger.debug(
                    "x_besteffort: graphql returned %d posts for @%s",
                    len(posts),
                    handle,
                )
                return posts[:cap]

            logger.warning(
                "x_besteffort: best-effort X path unavailable for @%s "
                "(both syndication and guest-token GraphQL returned empty); "
                "returning [] — this backend breaks periodically, which is expected",
                handle,
            )
            return []

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "x_besteffort: best-effort X path unavailable for @%s (%s: %s); "
                "returning [] — this backend breaks periodically, which is expected",
                handle,
                type(exc).__name__,
                exc,
            )
            return []
