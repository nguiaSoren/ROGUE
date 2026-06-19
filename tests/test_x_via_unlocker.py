"""Tests for the SERP-discover + Web-Unlock X harvester (offline, mocked client).

Covers ``rogue.harvest.x_status`` (parse a status page) + the
``XViaUnlockerPlugin`` (SERP organic results → status URLs → Web-Unlock + parse
each → RawDocuments), including status-URL filtering, dedup, media extraction,
and per-URL error isolation.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rogue.harvest.sources import XViaUnlockerPlugin
from rogue.harvest.x_status import is_x_status_url, parse_x_status

SINCE = datetime(2026, 5, 30, tzinfo=timezone.utc)

_X_HTML = (
    '<meta property="og:title" content="Pliny on X: &quot;CLAUDE-OPUS-4.8 LIBERATED&quot;">'
    "body https://pbs.twimg.com/media/ABC123 more https://pbs.twimg.com/media/DEF456"
)


class _Serp:
    def __init__(self, organic):
        self.organic_results = organic


class _Page:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status


class _FakeClient:
    def __init__(self, *, serp_results, html_for=None, fail_urls=None):
        self._serp = serp_results
        self._html_for = html_for or {}
        self._fail = set(fail_urls or [])
        self.serp_calls = 0
        self.unlocked: list[str] = []

    async def serp(self, query, count=10, engine="google"):
        self.serp_calls += 1
        return _Serp(self._serp)

    async def unlock(self, url, format="html"):
        self.unlocked.append(url)
        if url in self._fail:
            raise RuntimeError("unlock boom")
        return _Page(self._html_for.get(url, _X_HTML))


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #


def test_parse_x_status_pulls_text_and_images() -> None:
    body, imgs = parse_x_status(_X_HTML, "https://x.com/elder_plinius/status/9")
    assert "CLAUDE-OPUS-4.8 LIBERATED" in body
    assert body.startswith("X post: https://x.com/elder_plinius/status/9")
    assert imgs == [
        "https://pbs.twimg.com/media/ABC123?format=jpg&name=large",
        "https://pbs.twimg.com/media/DEF456?format=jpg&name=large",
    ]


def test_is_x_status_url() -> None:
    assert is_x_status_url("https://x.com/elder_plinius/status/2060085595808936024")
    assert is_x_status_url("https://twitter.com/a/status/1?s=20")
    assert not is_x_status_url("https://x.com/elder_plinius")  # profile, not a post
    assert not is_x_status_url("https://github.com/x/y")


# --------------------------------------------------------------------------- #
# plugin
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_serp_queries_per_handle() -> None:
    p = XViaUnlockerPlugin(handles=["elder_plinius", "goodside"])
    qs = p.serp_queries(SINCE)
    assert qs == [
        "site:x.com/elder_plinius after:2026-05-29",
        "site:x.com/goodside after:2026-05-29",
    ]


@pytest.mark.asyncio
async def test_fetch_since_discovers_unlocks_and_parses() -> None:
    organic = [
        {"link": "https://x.com/elder_plinius/status/2060085595808936024?s=20"},
        {"link": "https://x.com/elder_plinius"},                 # profile → skip
        {"link": "https://github.com/x/y"},                       # non-x → skip
        {"url": "https://x.com/elder_plinius/status/123"},
    ]
    client = _FakeClient(serp_results=organic)
    docs = await XViaUnlockerPlugin(handles=["elder_plinius"]).fetch_since(client, SINCE)

    assert {str(d.url) for d in docs} == {
        "https://x.com/elder_plinius/status/2060085595808936024",
        "https://x.com/elder_plinius/status/123",
    }
    d = docs[0]
    assert d.source_type == "x"
    assert d.bright_data_product == "web_unlocker"
    assert d.discovered_via == "x_serp:elder_plinius"
    assert len(d.media_urls) == 2  # the two pbs.twimg screenshots


@pytest.mark.asyncio
async def test_per_url_unlock_failure_isolated() -> None:
    organic = [
        {"link": "https://x.com/p/status/1"},
        {"link": "https://x.com/p/status/2"},
    ]
    client = _FakeClient(serp_results=organic, fail_urls={"https://x.com/p/status/1"})
    plugin = XViaUnlockerPlugin(handles=["p"])
    docs = await plugin.fetch_since(client, SINCE)
    assert {str(d.url) for d in docs} == {"https://x.com/p/status/2"}
    assert any("status/1 unlock" in e for e in plugin.call_errors)


@pytest.mark.asyncio
async def test_serp_failure_isolated_per_handle() -> None:
    class _SerpFails(_FakeClient):
        async def serp(self, query, count=10, engine="google"):
            raise RuntimeError("serp down")

    plugin = XViaUnlockerPlugin(handles=["a", "b"])
    docs = await plugin.fetch_since(_SerpFails(serp_results=[]), SINCE)
    assert docs == []
    assert len(plugin.call_errors) == 2  # one per handle, never raised
