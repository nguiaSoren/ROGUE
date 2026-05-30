"""Tests for the post→link following phase (Feature C) — offline, mocked client.

Covers ``rogue.harvest.link_follow_phase``: tagged-RawDocument emission, t.co
shortener resolution, domain-routed source_type (incl. *.github.io → github),
dedup against ``seen_urls``, the per-doc + run-total caps, the source-type
follow-set gate, and per-link error isolation.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from rogue.harvest.bright_data_client import BrightDataClient
from rogue.harvest.discovery_agent import DiscoveryAgent
from rogue.harvest.link_follow_phase import (
    SUGGESTED_POST_SOURCE_TYPES,
    run_link_follow_phase,
)
from rogue.harvest.sources.base import SourcePlugin
from rogue.schemas import RawDocument


class _Page:
    def __init__(self, url: str, content: str = "# fetched page body") -> None:
        self.url = url
        self.content = content
        self.content_format = "markdown"
        self.status_code = 200
        self.fetched_at = datetime.now(timezone.utc)


class _FakeClient:
    """Records calls; resolves t.co → a fixed dest; web_unlock returns a page."""

    api_key = "k"

    def __init__(self, *, resolve_map=None, fail_urls=None):
        self._resolve_map = resolve_map or {}
        self._fail_urls = set(fail_urls or [])
        self.resolved: list[str] = []
        self.unlocked: list[str] = []

    async def resolve_redirect(self, url, **kw):
        self.resolved.append(url)
        return self._resolve_map.get(url, url)

    async def web_unlock(self, url, format="markdown", **kw):
        self.unlocked.append(url)
        if url in self._fail_urls:
            raise RuntimeError("unlock boom")
        return _Page(url)


def _doc(url, body, *, source_type="x", content_format="json") -> RawDocument:
    return RawDocument(
        url=url,
        source_type=source_type,
        bright_data_product="web_scraper_api",
        fetched_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        raw_content=body,
        content_format=content_format,
        archive_hash="a" * 64,
        http_status=200,
    )


@pytest.mark.asyncio
async def test_follows_link_and_tags_provenance() -> None:
    body = json.dumps(
        {
            "url": "https://x.com/akaclandestine/status/1",
            "description": "full impl here https://t.co/cve",
            "external_url": "https://giovannigatti.github.io/cve-bench/",
        }
    )
    doc = _doc("https://x.com/akaclandestine/status/1", body)
    client = _FakeClient(
        resolve_map={"https://t.co/cve": "https://giovannigatti.github.io/cve-bench/"}
    )

    res = await run_link_follow_phase(client, [doc], seen_urls=set())

    # t.co was resolved → same dest as external_url → only ONE fetch (deduped).
    assert "https://t.co/cve" in client.resolved
    assert res.followed == 1
    d = res.docs[0]
    assert str(d.url) == "https://giovannigatti.github.io/cve-bench/"
    assert d.discovered_via == "post_link:https://x.com/akaclandestine/status/1"
    # *.github.io routes to github.
    assert d.source_type == "github"
    assert d.bright_data_product == "web_unlocker"


@pytest.mark.asyncio
async def test_dedups_against_seen_urls() -> None:
    body = "see https://github.com/x/y"
    doc = _doc("https://x.com/u/status/1", body, content_format="text")
    client = _FakeClient()
    # URL already in the pipeline (plugin/SERP/fetch_cache) → skip the fetch.
    res = await run_link_follow_phase(
        client, [doc], seen_urls={"https://github.com/x/y"}
    )
    assert res.followed == 0
    assert client.unlocked == []


@pytest.mark.asyncio
async def test_default_follows_every_source_including_arxiv() -> None:
    # Default (source_types=None) follows links from EVERY source — incl. arxiv.
    body = "code at https://github.com/acme/impl"
    doc = _doc("https://arxiv.org/abs/1", body, source_type="arxiv", content_format="text")
    client = _FakeClient()
    res = await run_link_follow_phase(client, [doc], seen_urls=set())
    assert res.followed == 1
    assert str(res.docs[0].url) == "https://github.com/acme/impl"


@pytest.mark.asyncio
async def test_explicit_source_type_set_narrows() -> None:
    # An explicit narrower set still works (opt-in gate).
    body = "code at https://github.com/acme/impl"
    doc = _doc("https://arxiv.org/abs/1", body, source_type="arxiv", content_format="text")
    client = _FakeClient()
    res = await run_link_follow_phase(
        client, [doc], seen_urls=set(), source_types=SUGGESTED_POST_SOURCE_TYPES
    )
    assert res.followed == 0  # arxiv not in the narrowed set
    assert "arxiv" not in SUGGESTED_POST_SOURCE_TYPES


@pytest.mark.asyncio
async def test_one_hop_only_followed_pages_links_not_followed() -> None:
    """1-hop: a followed page's OWN outbound links must NOT be followed."""
    body = "teaser → https://siteA.org/impl"
    doc = _doc("https://x.com/u/status/1", body, content_format="text")

    class _OneHopClient(_FakeClient):
        async def web_unlock(self, url, format="markdown", **kw):
            self.unlocked.append(url)
            # The fetched page itself links onward to siteB — must be ignored.
            return _Page(url, content="see also https://siteB.org/deeper")

    client = _OneHopClient()
    res = await run_link_follow_phase(client, [doc], seen_urls=set())
    assert res.followed == 1
    assert client.unlocked == ["https://siteA.org/impl"]  # siteB NOT fetched
    assert all("siteB" not in u for u in client.unlocked)


@pytest.mark.asyncio
async def test_per_doc_and_total_caps() -> None:
    # Each doc has UNIQUE outbound URLs (so cross-doc dedup doesn't mask the cap).
    docs = [
        _doc(
            f"https://x.com/u/status/{j}",
            " ".join(f"https://d{j}site{i}.org/p" for i in range(10)),
            content_format="text",
        )
        for j in range(5)
    ]
    client = _FakeClient()
    # per-doc cap 2 (so doc0 → 2, doc1 → would be 2…) but total cap 3 stops at 3.
    res = await run_link_follow_phase(
        client, docs, seen_urls=set(), max_links_per_doc=2, max_total=3
    )
    assert res.followed == 3
    assert len(client.unlocked) == 3


@pytest.mark.asyncio
async def test_per_link_failure_isolated() -> None:
    body = "a https://good.org/1 b https://bad.org/2 c https://good.org/3"
    doc = _doc("https://x.com/u/status/1", body, content_format="text")
    client = _FakeClient(fail_urls={"https://bad.org/2"})
    res = await run_link_follow_phase(
        client, [doc], seen_urls=set(), max_links_per_doc=5
    )
    # 2 good fetched, 1 failed → recorded in errors, never raised.
    assert res.followed == 2
    assert any("bad.org/2" in e for e in res.errors)


@pytest.mark.asyncio
async def test_empty_and_no_links_are_noops() -> None:
    client = _FakeClient()
    assert (await run_link_follow_phase(client, [], seen_urls=set())).followed == 0
    doc = _doc("https://x.com/u/1", "no links here", content_format="text")
    assert (await run_link_follow_phase(client, [doc], seen_urls=set())).followed == 0
    assert client.unlocked == []


# --------------------------------------------------------------------------- #
# resolve_redirect (the real BD method, via MockTransport)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolve_redirect_follows_to_final_url() -> None:
    final = "https://giovannigatti.github.io/cve-bench/"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "t.co":
            return httpx.Response(301, headers={"Location": final})
        return httpx.Response(200, text="ok")

    client = BrightDataClient(
        api_key="k", serp_zone="s", unlocker_zone="u", browser_zone="b",
        reddit_dataset_id=None, x_posts_dataset_id=None, hf_dataset_id=None,
    )
    out = await client.resolve_redirect(
        "https://t.co/abc", transport=httpx.MockTransport(handler)
    )
    assert out == final
    await client.aclose()


@pytest.mark.asyncio
async def test_resolve_redirect_degrades_to_input_on_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = BrightDataClient(
        api_key="k", serp_zone="s", unlocker_zone="u", browser_zone="b",
        reddit_dataset_id=None, x_posts_dataset_id=None, hf_dataset_id=None,
    )
    url = "https://t.co/dead"
    assert await client.resolve_redirect(url, transport=httpx.MockTransport(handler)) == url
    await client.aclose()


# --------------------------------------------------------------------------- #
# DiscoveryAgent integration — link-follow appends tagged docs after plugins
# --------------------------------------------------------------------------- #


class _PostPlugin(SourcePlugin):
    """Emits one X post doc whose body links out to a GitHub repo."""

    name = "post_stub"
    source_type = "x"
    bright_data_product = "web_scraper_api"

    async def fetch_since(self, client, since):
        body = json.dumps(
            {
                "url": "https://x.com/u/status/1",
                "description": "impl: https://github.com/acme/exploit",
            }
        )
        return [_doc("https://x.com/u/status/1", body)]


@pytest.mark.asyncio
async def test_discovery_agent_runs_link_follow_after_plugins() -> None:
    client = _FakeClient()
    agent = DiscoveryAgent(client, plugins=[_PostPlugin()])  # follow_links defaults True
    docs = await agent.run(since=datetime(2026, 5, 1, tzinfo=timezone.utc))

    # The plugin doc + the followed github link doc.
    urls = {str(d.url) for d in docs}
    assert "https://x.com/u/status/1" in urls
    assert "https://github.com/acme/exploit" in urls
    followed = [d for d in docs if d.discovered_via == "post_link:https://x.com/u/status/1"]
    assert len(followed) == 1 and followed[0].source_type == "github"
    assert agent.last_link_follow_count == 1


@pytest.mark.asyncio
async def test_discovery_agent_follow_links_disabled() -> None:
    client = _FakeClient()
    agent = DiscoveryAgent(client, plugins=[_PostPlugin()], follow_links=False)
    docs = await agent.run(since=datetime(2026, 5, 1, tzinfo=timezone.utc))
    assert len(docs) == 1  # only the plugin doc; no link followed
    assert client.unlocked == []
