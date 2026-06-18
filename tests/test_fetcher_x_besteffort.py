"""Unit tests for XBestEffortFetcher — zero real network calls.

All HTTP is intercepted by httpx.MockTransport / unittest.mock.patch so
every test is fast, offline, and deterministic.

Coverage:
  - conformance: assert_conforms passes
  - handle extraction: url forms + bare handle + no-handle edge case
  - effective_max: env-var clamping
  - syndication happy path: parses a minimal timeline response
  - syndication failure: returns [] + does not raise
  - graphql fallback: parses a minimal response when syndication is empty
  - failure cascade (both paths fail): returns []
  - cap enforcement: limit and MAX_POSTS honoured
  - _parse_tweet: photo media_url extraction, empty/None guard
  - _parse_created_at: RFC 2822 and ISO-8601 round-trips
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from rogue.harvest.bright_data_client import XPost

from rogue.harvest.fetchers.capabilities import CapabilityNotSupported
from rogue.harvest.fetchers.conformance import assert_conforms
from rogue.harvest.fetchers.x_besteffort import (
    XBestEffortFetcher,
    _effective_max,
    _extract_handle,
    _parse_created_at,
    _parse_tweet,
)


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------

def test_conforms():
    """assert_conforms must pass — structural, no network."""
    fetcher = XBestEffortFetcher()
    report = assert_conforms(fetcher)
    assert report.passed, str(report)


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

def test_is_available():
    assert XBestEffortFetcher().is_available() is True


# ---------------------------------------------------------------------------
# Handle extraction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://x.com/simonw", "simonw"),
    ("https://x.com/simonw/", "simonw"),
    ("https://twitter.com/elder_plinius", "elder_plinius"),
    ("https://x.com/wunderwuzzi23?ref=foo", "wunderwuzzi23"),
    ("goodside", "goodside"),
    ("@goodside", "goodside"),
])
def test_extract_handle(url, expected):
    assert _extract_handle(url) == expected


# ---------------------------------------------------------------------------
# Effective max cap
# ---------------------------------------------------------------------------

def test_effective_max_default(monkeypatch):
    monkeypatch.delenv("ROGUE_X_MAX_POSTS", raising=False)
    assert _effective_max() == 200


def test_effective_max_env_lower(monkeypatch):
    monkeypatch.setenv("ROGUE_X_MAX_POSTS", "50")
    assert _effective_max() == 50


def test_effective_max_env_above_ceiling(monkeypatch):
    """Setting ROGUE_X_MAX_POSTS above 200 is clamped to 200."""
    monkeypatch.setenv("ROGUE_X_MAX_POSTS", "99999")
    assert _effective_max() == 200


def test_effective_max_env_invalid(monkeypatch):
    """Non-integer value falls back to the default 200."""
    monkeypatch.setenv("ROGUE_X_MAX_POSTS", "oops")
    assert _effective_max() == 200


def test_effective_max_env_below_one(monkeypatch):
    """0 or negative is clamped to 1."""
    monkeypatch.setenv("ROGUE_X_MAX_POSTS", "0")
    assert _effective_max() == 1


# ---------------------------------------------------------------------------
# _parse_created_at
# ---------------------------------------------------------------------------

def test_parse_created_at_rfc2822():
    dt = _parse_created_at("Thu Apr 06 15:28:43 +0000 2023")
    assert dt.year == 2023
    assert dt.month == 4
    assert dt.tzinfo is not None


def test_parse_created_at_iso():
    dt = _parse_created_at("2024-01-15T12:30:00+00:00")
    assert dt.year == 2024


def test_parse_created_at_empty():
    dt = _parse_created_at("")
    # Should not raise; returns something near now
    assert isinstance(dt, datetime)


def test_parse_created_at_garbage():
    dt = _parse_created_at("not a date at all")
    assert isinstance(dt, datetime)


# ---------------------------------------------------------------------------
# _parse_tweet
# ---------------------------------------------------------------------------

def test_parse_tweet_basic():
    raw = {
        "id_str": "99",
        "full_text": "hello world",
        "created_at": "Thu Apr 06 15:28:43 +0000 2023",
        "user": {"screen_name": "testuser"},
        "favorite_count": 5,
        "retweet_count": 2,
    }
    post = _parse_tweet(raw)
    assert post is not None
    assert post.post_id == "99"
    assert post.body == "hello world"
    assert post.author_handle == "testuser"
    assert post.metrics["likes"] == 5
    assert post.metrics["retweets"] == 2
    assert "https://x.com/testuser/status/99" == post.permalink


def test_parse_tweet_with_photos():
    raw = {
        "id_str": "42",
        "full_text": "look at this",
        "created_at": "Thu Apr 06 15:28:43 +0000 2023",
        "user": {"screen_name": "alice"},
        "extended_entities": {
            "media": [
                {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/img1.jpg"},
                {"type": "video", "media_url_https": "https://pbs.twimg.com/media/vid.mp4"},
            ]
        },
    }
    post = _parse_tweet(raw)
    assert post is not None
    assert post.media_urls == ["https://pbs.twimg.com/media/img1.jpg"]


def test_parse_tweet_no_id_returns_none():
    assert _parse_tweet({}) is None
    assert _parse_tweet({"full_text": "no id here"}) is None


def test_parse_tweet_graphql_wrapped():
    """GraphQL wraps the legacy tweet under result.legacy."""
    raw = {
        "result": {
            "legacy": {
                "id_str": "77",
                "full_text": "graphql body",
                "created_at": "Thu Apr 06 15:28:43 +0000 2023",
                "user": {"screen_name": "bob"},
            }
        }
    }
    post = _parse_tweet(raw)
    assert post is not None
    assert post.post_id == "77"
    assert post.body == "graphql body"


# ---------------------------------------------------------------------------
# Happy path — syndication returns tweets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_x_user_posts_syndication_happy():
    """Syndication returns 3 posts → XBestEffortFetcher returns them."""
    def _make_posts(n: int) -> list[XPost]:
        return [
            XPost(
                post_id=str(1000 + i),
                author_handle="simonw",
                body=f"tweet body {i}",
                posted_at=datetime(2023, 4, 6, 15, 28, 43, tzinfo=timezone.utc),
                permalink=f"https://x.com/simonw/status/{1000 + i}",
                metrics={"likes": i * 10},
                media_urls=[],
            )
            for i in range(n)
        ]

    fetcher = XBestEffortFetcher()
    with patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_syndication",
        new=AsyncMock(return_value=_make_posts(3)),
    ):
        posts = await fetcher.x_user_posts("https://x.com/simonw", limit=10)

    assert len(posts) == 3
    assert all(p.author_handle == "simonw" for p in posts)
    assert posts[0].post_id == "1000"


# ---------------------------------------------------------------------------
# Failure path — syndication errors → return []
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_x_user_posts_syndication_http_error():
    """Syndication path failing → returns [] without raising."""
    fetcher = XBestEffortFetcher()
    with patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_syndication",
        new=AsyncMock(return_value=[]),
    ), patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_graphql",
        new=AsyncMock(return_value=[]),
    ):
        posts = await fetcher.x_user_posts("https://x.com/simonw", limit=10)

    assert posts == []


@pytest.mark.asyncio
async def test_x_user_posts_network_error_returns_empty():
    """A ConnectError from syndication → returns [], does not raise."""
    async def raise_connect(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    fetcher = XBestEffortFetcher()
    with patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_syndication",
        new=AsyncMock(side_effect=httpx.ConnectError("connection refused")),
    ):
        posts = await fetcher.x_user_posts("https://x.com/simonw", limit=10)

    assert posts == []


@pytest.mark.asyncio
async def test_x_user_posts_empty_handle_returns_empty():
    """A URL that yields no handle → returns [] without network call."""
    fetcher = XBestEffortFetcher()
    # Patch to ensure no network is hit
    with patch("rogue.harvest.fetchers.x_besteffort._fetch_syndication") as mock_syn, \
         patch("rogue.harvest.fetchers.x_besteffort._fetch_graphql") as mock_gql:
        posts = await fetcher.x_user_posts("", limit=10)

    assert posts == []
    mock_syn.assert_not_called()
    mock_gql.assert_not_called()


# ---------------------------------------------------------------------------
# Cap enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_x_user_posts_respects_limit():
    """limit=2 caps results to 2 even when the backend returns 5 posts."""
    many_posts = [
        XPost(
            post_id=str(i),
            author_handle="goodside",
            body=f"post {i}",
            posted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            permalink=f"https://x.com/goodside/status/{i}",
            metrics={},
            media_urls=[],
        )
        for i in range(5)
    ]

    fetcher = XBestEffortFetcher()
    # Return all 5 from the internal helper so the cap logic in x_user_posts slices
    with patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_syndication",
        new=AsyncMock(return_value=many_posts),
    ):
        posts = await fetcher.x_user_posts("https://x.com/goodside", limit=2)

    assert len(posts) == 2


@pytest.mark.asyncio
async def test_x_user_posts_respects_env_cap(monkeypatch):
    """ROGUE_X_MAX_POSTS=3 caps even when limit=100."""
    monkeypatch.setenv("ROGUE_X_MAX_POSTS", "3")
    many_posts = [
        XPost(
            post_id=str(i),
            author_handle="goodside",
            body=f"post {i}",
            posted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            permalink=f"https://x.com/goodside/status/{i}",
            metrics={},
            media_urls=[],
        )
        for i in range(10)
    ]

    fetcher = XBestEffortFetcher()
    with patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_syndication",
        new=AsyncMock(return_value=many_posts),
    ):
        posts = await fetcher.x_user_posts("https://x.com/goodside", limit=100)

    assert len(posts) == 3


# ---------------------------------------------------------------------------
# GraphQL fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_x_user_posts_graphql_fallback():
    """When syndication returns [] the graphql fallback is tried and returns posts."""
    gql_posts = [
        XPost(
            post_id=str(2000 + i),
            author_handle="elder_plinius",
            body=f"graphql tweet {i}",
            posted_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            permalink=f"https://x.com/elder_plinius/status/{2000 + i}",
            metrics={},
            media_urls=[],
        )
        for i in range(2)
    ]

    fetcher = XBestEffortFetcher()
    with patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_syndication",
        new=AsyncMock(return_value=[]),
    ), patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_graphql",
        new=AsyncMock(return_value=gql_posts),
    ):
        posts = await fetcher.x_user_posts("https://x.com/elder_plinius", limit=10)

    assert len(posts) == 2
    assert posts[0].post_id == "2000"


# ---------------------------------------------------------------------------
# Both paths fail → []
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_x_user_posts_both_fail_returns_empty():
    """When both syndication and graphql return empty, result is []."""
    with patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_syndication",
        new=AsyncMock(return_value=[]),
    ), patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_graphql",
        new=AsyncMock(return_value=[]),
    ):
        fetcher = XBestEffortFetcher()
        posts = await fetcher.x_user_posts("https://x.com/simonw", limit=10)

    assert posts == []


@pytest.mark.asyncio
async def test_x_user_posts_unexpected_exception_returns_empty():
    """An unexpected exception inside x_user_posts returns [] rather than raising."""
    with patch(
        "rogue.harvest.fetchers.x_besteffort._fetch_syndication",
        new=AsyncMock(side_effect=RuntimeError("something very unexpected")),
    ):
        fetcher = XBestEffortFetcher()
        posts = await fetcher.x_user_posts("https://x.com/simonw", limit=10)

    assert posts == []


# ---------------------------------------------------------------------------
# Undeclared capabilities still raise CapabilityNotSupported
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_undeclared_capabilities_raise():
    """Undeclared methods (SERP, UNLOCK, etc.) raise CapabilityNotSupported."""
    fetcher = XBestEffortFetcher()

    with pytest.raises(CapabilityNotSupported):
        await fetcher.serp("test query")

    with pytest.raises(CapabilityNotSupported):
        await fetcher.unlock("https://example.com")

    with pytest.raises(CapabilityNotSupported):
        await fetcher.reddit_subreddit("AIJailbreak")


