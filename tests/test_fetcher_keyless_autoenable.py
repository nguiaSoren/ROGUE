"""Auto-enable Firecrawl keyless when no robust scraper is configured + the high-yield first-run cap.

When neither Bright Data nor crawl4ai is present (and Firecrawl isn't explicitly configured), a
first-run harvest should still get a real anti-bot backend (keyless Firecrawl) instead of plain
direct+DuckDuckGo — and scope itself to the highest-yield sources to fit the keyless rate budget.
"""

from __future__ import annotations

from rogue.harvest.discovery_agent import default_plugins, high_yield_plugins
from rogue.harvest.fetchers.base import Fetcher
from rogue.harvest.fetchers.capabilities import Capability
from rogue.harvest.fetchers.registry import (
    FetcherRegistry,
    _maybe_autoenable_firecrawl_keyless,
    is_keyless_harvest,
)


class _Stub(Fetcher):
    name = "stub"
    capabilities = frozenset({Capability.UNLOCK})


def _named(name: str) -> _Stub:
    s = _Stub()
    s.name = name
    return s


def _reg(*names: str) -> FetcherRegistry:
    reg = FetcherRegistry()
    for n in names:
        reg.register(_named(n))
    return reg


# --- auto-enable ----------------------------------------------------------------------------------

def test_autoenable_fires_when_only_fragile_free_backends(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_KEYLESS", raising=False)
    reg = _reg("direct", "ddg")
    _maybe_autoenable_firecrawl_keyless(reg)
    fc = reg.get("firecrawl")
    assert fc is not None  # auto-enabled
    assert fc._api_key is None  # keyless (no Authorization header)
    assert is_keyless_harvest(reg) is True


def test_autoenable_skips_when_crawl4ai_present(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_KEYLESS", raising=False)
    reg = _reg("crawl4ai", "direct")
    _maybe_autoenable_firecrawl_keyless(reg)
    assert reg.get("firecrawl") is None
    assert is_keyless_harvest(reg) is False  # crawl4ai = unlimited → no cap


def test_autoenable_skips_when_brightdata_present(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_KEYLESS", raising=False)
    reg = _reg("brightdata", "direct")
    _maybe_autoenable_firecrawl_keyless(reg)
    assert reg.get("firecrawl") is None
    assert is_keyless_harvest(reg) is False


def test_autoenable_respects_explicit_optout(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_KEYLESS", "0")
    reg = _reg("direct", "ddg")
    _maybe_autoenable_firecrawl_keyless(reg)
    assert reg.get("firecrawl") is None  # opted out → plain free path


def test_autoenable_noop_when_firecrawl_already_registered(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_KEYLESS", raising=False)
    reg = _reg("direct", "firecrawl")  # already configured
    _maybe_autoenable_firecrawl_keyless(reg)
    # still the original stub, not replaced
    assert isinstance(reg.get("firecrawl"), _Stub)


# --- is_keyless_harvest ---------------------------------------------------------------------------

def test_keyless_false_when_brightdata():
    assert is_keyless_harvest(_reg("brightdata", "direct")) is False


def test_keyless_true_with_only_direct_ddg():
    assert is_keyless_harvest(_reg("direct", "ddg")) is True


# --- high-yield first-run source set --------------------------------------------------------------

def test_high_yield_plugins_are_the_top_sources():
    names = [p.name for p in high_yield_plugins()]
    assert names == [
        "arxiv_listing",
        "blog_static",
        "reddit_subreddit",
        "github_search",
        "pliny_github",
    ]


def test_high_yield_is_a_subset_of_default():
    default_names = {p.name for p in default_plugins()}
    assert {p.name for p in high_yield_plugins()} <= default_names
