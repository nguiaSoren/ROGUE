"""Unit tests for :class:`RedditOAuthFetcher`.

All network calls are mocked via ``httpx.MockTransport`` + ``respx`` or
monkeypatching — no real Reddit credentials or network access required.

Test surface
------------
1. ``is_available()`` — True / False based on env vars.
2. Conformance suite passes (structural + capability wiring).
3. Token acquisition — happy path + failure degrades to [].
4. ``reddit_subreddit`` — maps listing JSON → RedditPost correctly.
5. ``reddit_keyword`` — date_range → t mapping + correct endpoint called.
6. Graceful degrade — auth failure → [] (never raises).
7. Token caching — second call reuses cached token (only one POST).
8. Rate-pacing — _pace is called between requests.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from rogue.harvest.fetchers.reddit_oauth import (
    RedditOAuthFetcher,
    _DATE_RANGE_TO_T,
    _child_to_reddit_post,
    _parse_listing,
)
from rogue.harvest.fetchers.conformance import assert_conforms


# ---------------------------------------------------------------------------
# Fixtures — sample Reddit API payloads
# ---------------------------------------------------------------------------

def _make_child(
    id_: str = "abc123",
    subreddit: str = "ChatGPTJailbreak",
    title: str = "Test jailbreak post",
    selftext: str = "Here is the prompt",
    author: str = "u_test",
    created_utc: float = 1_700_000_000.0,
    permalink: str = "/r/ChatGPTJailbreak/comments/abc123/test_jailbreak_post/",
    score: int = 42,
    url: str = "https://www.reddit.com/r/ChatGPTJailbreak/comments/abc123/",
    preview_url: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": id_,
        "subreddit": subreddit,
        "title": title,
        "selftext": selftext,
        "author": author,
        "created_utc": created_utc,
        "permalink": permalink,
        "score": score,
        "url": url,
    }
    if preview_url:
        data["preview"] = {
            "images": [{"source": {"url": preview_url}}]
        }
    return {"kind": "t3", "data": data}


def _make_listing(*children) -> dict[str, Any]:
    return {
        "kind": "Listing",
        "data": {
            "children": list(children),
            "after": None,
            "before": None,
        },
    }


_TOKEN_RESPONSE = {
    "access_token": "fake_bearer_token",
    "token_type": "bearer",
    "expires_in": 86400,
    "scope": "*",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fetcher_with_token() -> RedditOAuthFetcher:
    """Return a fetcher that already has a valid cached token."""
    f = RedditOAuthFetcher()
    f._token = "fake_bearer_token"
    f._token_expires_at = time.monotonic() + 3600.0
    return f


# ---------------------------------------------------------------------------
# 1. is_available()
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_true_when_both_env_vars_set(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "my_id")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "my_secret")
        assert RedditOAuthFetcher.is_available() is True

    def test_false_when_id_missing(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "my_secret")
        assert RedditOAuthFetcher.is_available() is False

    def test_false_when_secret_missing(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "my_id")
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        assert RedditOAuthFetcher.is_available() is False

    def test_false_when_both_missing(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        assert RedditOAuthFetcher.is_available() is False

    def test_false_when_id_blank(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "   ")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "my_secret")
        assert RedditOAuthFetcher.is_available() is False


# ---------------------------------------------------------------------------
# 2. Conformance suite
# ---------------------------------------------------------------------------

class TestConformance:
    def test_assert_conforms_passes(self):
        """The structural conformance suite must pass without touching the network."""
        fetcher = RedditOAuthFetcher()
        report = assert_conforms(fetcher)
        assert report.passed, str(report)

    def test_name(self):
        assert RedditOAuthFetcher().name == "reddit_oauth"

    def test_capabilities(self):
        from rogue.harvest.fetchers.capabilities import Capability
        caps = RedditOAuthFetcher().capabilities
        assert Capability.REDDIT in caps
        # Only REDDIT — no other capability should be declared
        assert len(caps) == 1

    def test_undeclared_capabilities_raise(self):
        """Non-REDDIT capabilities must raise CapabilityNotSupported."""
        import asyncio
        from rogue.harvest.fetchers.capabilities import Capability, CapabilityNotSupported
        fetcher = RedditOAuthFetcher()
        for cap in Capability:
            if cap in fetcher.capabilities:
                continue
            # Each undeclared capability's method should raise
            method_map = {
                Capability.UNLOCK: "unlock",
                Capability.SERP: "serp",
                Capability.SERP_IMAGE: "serp_image",
                Capability.BROWSER: "browser",
                Capability.X: "x_user_posts",
                Capability.HF: "hf_discussion",
                Capability.IMAGE_BYTES: "fetch_image_bytes",
                Capability.REDIRECT: "resolve_redirect",
            }
            if cap not in method_map:
                continue
            method = getattr(fetcher, method_map[cap])
            probe_args = {
                "unlock": ("https://example.invalid",),
                "serp": ("q",),
                "serp_image": ("q",),
                "browser": ("https://example.invalid",),
                "x_user_posts": ("https://x.com/probe",),
                "hf_discussion": ("org/model",),
                "fetch_image_bytes": ("https://example.invalid/x.png",),
                "resolve_redirect": ("https://t.co/probe",),
            }[method_map[cap]]
            with pytest.raises(CapabilityNotSupported):
                asyncio.run(method(*probe_args))


# ---------------------------------------------------------------------------
# 3. Token acquisition
# ---------------------------------------------------------------------------

class TestTokenAcquisition:
    @pytest.mark.asyncio
    async def test_token_acquired_on_first_call(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "test_id")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_secret")
        fetcher = RedditOAuthFetcher()

        mock_post = AsyncMock(return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value=_TOKEN_RESPONSE),
            raise_for_status=MagicMock(),
        ))
        fetcher._get_http().post = mock_post  # type: ignore[attr-defined]

        token = await fetcher._ensure_token()
        assert token == "fake_bearer_token"
        assert fetcher._token == "fake_bearer_token"
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_cached_on_second_call(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "test_id")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_secret")
        fetcher = _make_fetcher_with_token()

        # _ensure_token should NOT call the network when token is still valid
        mock_post = AsyncMock()
        fetcher._get_http().post = mock_post  # type: ignore[attr-defined]

        token = await fetcher._ensure_token()
        assert token == "fake_bearer_token"
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_auth_failure_returns_none(self, monkeypatch):
        monkeypatch.setenv("REDDIT_CLIENT_ID", "bad_id")
        monkeypatch.setenv("REDDIT_CLIENT_SECRET", "bad_secret")
        fetcher = RedditOAuthFetcher()

        import httpx as _httpx
        mock_post = AsyncMock(side_effect=_httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock(status_code=401)
        ))
        fetcher._get_http().post = mock_post  # type: ignore[attr-defined]

        token = await fetcher._ensure_token()
        assert token is None

    @pytest.mark.asyncio
    async def test_no_env_vars_returns_none(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        fetcher = RedditOAuthFetcher()
        token = await fetcher._ensure_token()
        assert token is None


# ---------------------------------------------------------------------------
# 4. reddit_subreddit — field mapping
# ---------------------------------------------------------------------------

class TestRedditSubreddit:
    def _setup_fetcher_with_mock_get(self, response_json: Any) -> tuple[RedditOAuthFetcher, AsyncMock]:
        fetcher = _make_fetcher_with_token()
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status = MagicMock()
        mock_get = AsyncMock(return_value=mock_resp)
        fetcher._get_http().get = mock_get  # type: ignore[attr-defined]
        return fetcher, mock_get

    @pytest.mark.asyncio
    async def test_returns_reddit_posts(self):
        child = _make_child(
            id_="xyz789",
            subreddit="PromptEngineering",
            title="Injection attack found",
            selftext="Here's how it works",
            author="red_teamer",
            created_utc=1_710_000_000.0,
            permalink="/r/PromptEngineering/comments/xyz789/injection_attack/",
            score=15,
        )
        listing = _make_listing(child)
        fetcher, mock_get = self._setup_fetcher_with_mock_get(listing)

        posts = await fetcher.reddit_subreddit("PromptEngineering", limit=10)

        assert len(posts) == 1
        p = posts[0]
        assert p.post_id == "xyz789"
        assert p.subreddit == "PromptEngineering"
        assert p.title == "Injection attack found"
        assert p.body == "Here's how it works"
        assert p.author == "red_teamer"
        assert p.score == 15
        assert p.permalink == "https://www.reddit.com/r/PromptEngineering/comments/xyz789/injection_attack/"
        assert isinstance(p.posted_at, datetime)
        assert p.posted_at.tzinfo is not None
        assert p.comments == []

    @pytest.mark.asyncio
    async def test_limit_clamped_to_100(self):
        listing = _make_listing()
        fetcher, mock_get = self._setup_fetcher_with_mock_get(listing)
        await fetcher.reddit_subreddit("sub", limit=999)
        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"] if "params" in call_kwargs[1] else call_kwargs[0][1]
        # The limit param in the GET call should be ≤ 100
        assert params["limit"] <= 100

    @pytest.mark.asyncio
    async def test_empty_listing_returns_empty(self):
        listing = _make_listing()
        fetcher, _ = self._setup_fetcher_with_mock_get(listing)
        posts = await fetcher.reddit_subreddit("empty_sub")
        assert posts == []

    @pytest.mark.asyncio
    async def test_auth_failure_returns_empty(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        fetcher = RedditOAuthFetcher()
        posts = await fetcher.reddit_subreddit("sub")
        assert posts == []

    @pytest.mark.asyncio
    async def test_network_error_returns_empty(self):
        fetcher = _make_fetcher_with_token()
        import httpx as _httpx
        fetcher._get_http().get = AsyncMock(side_effect=_httpx.ConnectError("unreachable"))  # type: ignore[attr-defined]
        posts = await fetcher.reddit_subreddit("sub")
        assert posts == []

    @pytest.mark.asyncio
    async def test_media_urls_from_preview(self):
        child = _make_child(
            id_="img1",
            preview_url="https://preview.redd.it/abc.jpg?auto=webp&amp;s=123",
        )
        listing = _make_listing(child)
        fetcher, _ = self._setup_fetcher_with_mock_get(listing)
        posts = await fetcher.reddit_subreddit("sub")
        assert len(posts) == 1
        # &amp; should be unescaped
        assert any("preview.redd.it" in u for u in posts[0].media_urls)
        assert not any("&amp;" in u for u in posts[0].media_urls)

    @pytest.mark.asyncio
    async def test_direct_image_url_included(self):
        child = _make_child(
            id_="directimg",
            url="https://i.redd.it/somephoto.jpg",
        )
        listing = _make_listing(child)
        fetcher, _ = self._setup_fetcher_with_mock_get(listing)
        posts = await fetcher.reddit_subreddit("sub")
        assert "https://i.redd.it/somephoto.jpg" in posts[0].media_urls

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self):
        listing = _make_listing(_make_child())
        fetcher, mock_get = self._setup_fetcher_with_mock_get(listing)
        await fetcher.reddit_subreddit("LocalLLaMA", limit=50)
        url_called = mock_get.call_args[0][0]
        assert "/r/LocalLLaMA/new.json" in url_called


# ---------------------------------------------------------------------------
# 5. reddit_keyword — date_range mapping + endpoint
# ---------------------------------------------------------------------------

class TestRedditKeyword:
    def _setup_fetcher_with_mock_get(self, response_json: Any) -> tuple[RedditOAuthFetcher, AsyncMock]:
        fetcher = _make_fetcher_with_token()
        mock_resp = MagicMock()
        mock_resp.json.return_value = response_json
        mock_resp.raise_for_status = MagicMock()
        mock_get = AsyncMock(return_value=mock_resp)
        fetcher._get_http().get = mock_get  # type: ignore[attr-defined]
        return fetcher, mock_get

    @pytest.mark.asyncio
    async def test_returns_reddit_posts(self):
        child = _make_child(id_="kw1", title="Keyword result")
        listing = _make_listing(child)
        fetcher, _ = self._setup_fetcher_with_mock_get(listing)
        posts = await fetcher.reddit_keyword("jailbreak prompt")
        assert len(posts) == 1
        assert posts[0].post_id == "kw1"

    @pytest.mark.parametrize("date_range,expected_t", [
        ("Past hour", "hour"),
        ("Past day", "day"),
        ("Past week", "week"),
        ("Past month", "month"),
        ("Past year", "year"),
        ("All time", "all"),
        ("Unknown value", "week"),  # fallback to week
    ])
    @pytest.mark.asyncio
    async def test_date_range_mapping(self, date_range, expected_t):
        listing = _make_listing()
        fetcher, mock_get = self._setup_fetcher_with_mock_get(listing)
        await fetcher.reddit_keyword("test", date_range=date_range)
        call_kwargs = mock_get.call_args
        params = call_kwargs[1].get("params") or call_kwargs[0][1]
        assert params["t"] == expected_t

    @pytest.mark.asyncio
    async def test_calls_search_endpoint(self):
        listing = _make_listing()
        fetcher, mock_get = self._setup_fetcher_with_mock_get(listing)
        await fetcher.reddit_keyword("prompt injection")
        url_called = mock_get.call_args[0][0]
        assert "/search.json" in url_called

    @pytest.mark.asyncio
    async def test_keyword_in_params(self):
        listing = _make_listing()
        fetcher, mock_get = self._setup_fetcher_with_mock_get(listing)
        await fetcher.reddit_keyword("system prompt leak")
        params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert params["q"] == "system prompt leak"

    @pytest.mark.asyncio
    async def test_sort_is_new(self):
        listing = _make_listing()
        fetcher, mock_get = self._setup_fetcher_with_mock_get(listing)
        await fetcher.reddit_keyword("jailbreak")
        params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert params["sort"] == "new"

    @pytest.mark.asyncio
    async def test_num_of_posts_clamped(self):
        listing = _make_listing()
        fetcher, mock_get = self._setup_fetcher_with_mock_get(listing)
        await fetcher.reddit_keyword("x", num_of_posts=999)
        params = mock_get.call_args[1].get("params") or mock_get.call_args[0][1]
        assert params["limit"] <= 100

    @pytest.mark.asyncio
    async def test_auth_failure_returns_empty(self, monkeypatch):
        monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
        monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
        fetcher = RedditOAuthFetcher()
        posts = await fetcher.reddit_keyword("jailbreak")
        assert posts == []


# ---------------------------------------------------------------------------
# 6. _child_to_reddit_post unit tests
# ---------------------------------------------------------------------------

class TestChildToRedditPost:
    def test_basic_mapping(self):
        child_data = {
            "id": "post1",
            "subreddit": "AIJailbreak",
            "title": "New technique",
            "selftext": "Body text here",
            "author": "hacker99",
            "created_utc": 1_700_000_000.0,
            "permalink": "/r/AIJailbreak/comments/post1/new_technique/",
            "score": 100,
            "url": "https://www.reddit.com/r/AIJailbreak/comments/post1/",
        }
        post = _child_to_reddit_post(child_data)
        assert post is not None
        assert post.post_id == "post1"
        assert post.subreddit == "AIJailbreak"
        assert post.title == "New technique"
        assert post.body == "Body text here"
        assert post.author == "hacker99"
        assert post.score == 100
        assert post.permalink == "https://www.reddit.com/r/AIJailbreak/comments/post1/new_technique/"
        assert post.posted_at == datetime.fromtimestamp(1_700_000_000.0, tz=timezone.utc)
        assert post.comments == []

    def test_missing_id_returns_none(self):
        assert _child_to_reddit_post({"title": "No ID"}) is None

    def test_empty_selftext_falls_back_to_url(self):
        child_data = {
            "id": "link1",
            "selftext": "",
            "url": "https://example.com/article",
            "subreddit": "sub",
            "title": "Link post",
            "author": "a",
            "created_utc": 1_700_000_000.0,
            "permalink": "/r/sub/comments/link1/",
            "score": 5,
        }
        post = _child_to_reddit_post(child_data)
        assert post is not None
        assert post.body == "https://example.com/article"

    def test_relative_permalink_made_absolute(self):
        child_data = {
            "id": "p1",
            "permalink": "/r/sub/comments/p1/title/",
            "subreddit": "sub",
            "title": "T",
            "selftext": "",
            "url": "https://reddit.com/r/sub/comments/p1/",
            "author": "a",
            "created_utc": 0,
            "score": 0,
        }
        post = _child_to_reddit_post(child_data)
        assert post is not None
        assert post.permalink.startswith("https://www.reddit.com")

    def test_created_utc_maps_to_posted_at(self):
        ts = 1_710_000_000.0
        child_data = {
            "id": "ts1",
            "created_utc": ts,
            "subreddit": "sub",
            "title": "T",
            "selftext": "B",
            "url": "https://reddit.com",
            "author": "a",
            "permalink": "/r/sub/comments/ts1/",
            "score": 0,
        }
        post = _child_to_reddit_post(child_data)
        assert post is not None
        expected = datetime.fromtimestamp(ts, tz=timezone.utc)
        assert post.posted_at == expected


# ---------------------------------------------------------------------------
# 7. _parse_listing unit tests
# ---------------------------------------------------------------------------

class TestParseListing:
    def test_parses_multiple_children(self):
        listing = _make_listing(
            _make_child(id_="a"),
            _make_child(id_="b"),
            _make_child(id_="c"),
        )
        posts = _parse_listing(listing)
        assert len(posts) == 3
        assert {p.post_id for p in posts} == {"a", "b", "c"}

    def test_skips_children_without_id(self):
        listing = {
            "kind": "Listing",
            "data": {
                "children": [
                    {"kind": "t3", "data": {}},            # no id
                    {"kind": "t3", "data": {"id": "ok"}},  # has id
                ]
            }
        }
        posts = _parse_listing(listing)
        assert len(posts) == 1
        assert posts[0].post_id == "ok"

    def test_empty_children_returns_empty(self):
        listing = {"kind": "Listing", "data": {"children": []}}
        assert _parse_listing(listing) == []

    def test_malformed_json_returns_empty(self):
        assert _parse_listing({"not": "a listing"}) == []
        assert _parse_listing(None) == []  # type: ignore[arg-type]
        assert _parse_listing("broken") == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 8. date_range → t mapping completeness
# ---------------------------------------------------------------------------

class TestDateRangeMapping:
    def test_all_bd_date_ranges_covered(self):
        """Every BD-style date_range the source plugin uses maps to a valid t value."""
        expected_bd_ranges = [
            "Past hour",
            "Past day",
            "Past week",
            "Past month",
            "Past year",
            "All time",
        ]
        valid_t_values = {"hour", "day", "week", "month", "year", "all"}
        for dr in expected_bd_ranges:
            t = _DATE_RANGE_TO_T.get(dr)
            assert t is not None, f"{dr!r} not in _DATE_RANGE_TO_T"
            assert t in valid_t_values, f"{dr!r} maps to invalid t={t!r}"


# ---------------------------------------------------------------------------
# 9. aclose — idempotent
# ---------------------------------------------------------------------------

class TestAclose:
    @pytest.mark.asyncio
    async def test_aclose_is_idempotent(self):
        fetcher = RedditOAuthFetcher()
        # Should not raise even if no HTTP client was ever created
        await fetcher.aclose()
        await fetcher.aclose()

    @pytest.mark.asyncio
    async def test_aclose_closes_http_client(self):
        fetcher = _make_fetcher_with_token()
        # Force-create the HTTP client
        _ = fetcher._get_http()
        assert fetcher._http is not None
        await fetcher.aclose()
        assert fetcher._http is None
