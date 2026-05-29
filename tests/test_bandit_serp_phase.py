"""Tests for `rogue.harvest.bandit_serp_phase`.

The (c-serp) bandit-driven SERP discovery phase shipped 2026-05-27. These
tests lock the contract so it can't silently regress:

  * Empty picked_arms → fast no-op (zero network calls)
  * Per-arm SERP runs concurrently; one timeout doesn't stall others
  * URL dedup against `seen_urls` skips already-known content (no double-fetch)
  * Per-arm cost = $0.0015 SERP + $0.0025 per fetched URL
  * SERP failure on one arm: that arm gets only the SERP cost, no fetches
  * Web Unlocker failure on one URL: per-arm logged, other URLs continue
  * Returned RawDocuments are tagged `discovered_via=f"serp_arm:{arm_id}"`
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from rogue.harvest.bandit_serp_phase import (
    BanditSerpPhaseResult,
    run_bandit_serp_phase,
)
from rogue.harvest.bright_data_client import SerpResponse, UnlockedPage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(
    *,
    serp_responses: dict[str, SerpResponse] | None = None,
    serp_exceptions: dict[str, Exception] | None = None,
    unlock_responses: dict[str, UnlockedPage] | None = None,
    unlock_exceptions: dict[str, Exception] | None = None,
) -> MagicMock:
    """Build a fake BrightDataClient with per-query SERP + per-URL fetch behavior."""
    client = MagicMock()

    async def fake_serp(query: str, count: int = 10, *, session=None, **_):
        if serp_exceptions and query in serp_exceptions:
            raise serp_exceptions[query]
        if serp_responses and query in serp_responses:
            return serp_responses[query]
        return _empty_serp(query)

    async def fake_unlock(url: str, format: str = "markdown", *, session=None, **_):
        if unlock_exceptions and url in unlock_exceptions:
            raise unlock_exceptions[url]
        if unlock_responses and url in unlock_responses:
            return unlock_responses[url]
        return _default_unlock(url, format)

    client.serp_search = AsyncMock(side_effect=fake_serp)
    client.web_unlock = AsyncMock(side_effect=fake_unlock)
    return client


def _serp(query: str, links: list[str]) -> SerpResponse:
    return SerpResponse(
        query=query,
        engine="google",
        fetched_at=datetime.now(timezone.utc),
        organic_results=[{"link": link} for link in links],
        knowledge_panel=None,
        raw_json={},
    )


def _empty_serp(query: str) -> SerpResponse:
    return SerpResponse(
        query=query,
        engine="google",
        fetched_at=datetime.now(timezone.utc),
        organic_results=[],
        knowledge_panel=None,
        raw_json={},
    )


def _default_unlock(url: str, fmt: str) -> UnlockedPage:
    return UnlockedPage(
        url=url,
        fetched_at=datetime.now(timezone.utc),
        content=f"# Page content for {url}\n\nbody",
        content_format=fmt,
        status_code=200,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_picked_arms_fast_noop() -> None:
    """No picked arms → returns empty result with zero network calls."""
    client = _mock_client()
    result = await run_bandit_serp_phase(client, picked_arms=[])

    assert isinstance(result, BanditSerpPhaseResult)
    assert result.docs == []
    assert result.per_arm_cost == {}
    assert result.per_arm_errors == {}
    client.serp_search.assert_not_called()
    client.web_unlock.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_serp_then_fetch_emits_tagged_raw_documents() -> None:
    """One picked arm → one SERP → N fetches → N tagged RawDocuments."""
    client = _mock_client(
        serp_responses={
            "test query": _serp(
                "test query",
                ["https://example.com/a", "https://example.com/b"],
            )
        }
    )

    result = await run_bandit_serp_phase(
        client, picked_arms=[("my_arm", "test query")]
    )

    assert len(result.docs) == 2
    assert all(d.discovered_via == "serp_arm:my_arm" for d in result.docs)
    assert all(d.bright_data_product == "web_unlocker" for d in result.docs)
    # Cost = 1 SERP × $0.0015 + 2 fetches × $0.0025 = $0.0065
    assert result.per_arm_cost["my_arm"] == pytest.approx(0.0065)
    assert result.per_arm_errors == {}


@pytest.mark.asyncio
async def test_seen_urls_dedup_skips_already_known_urls() -> None:
    """URLs in seen_urls are filtered before Web Unlocker — no double-spend."""
    client = _mock_client(
        serp_responses={
            "q": _serp("q", ["https://a.com/x", "https://b.com/y"]),
        }
    )

    result = await run_bandit_serp_phase(
        client,
        picked_arms=[("arm1", "q")],
        seen_urls={"https://a.com/x"},
    )

    assert len(result.docs) == 1
    assert str(result.docs[0].url) == "https://b.com/y"
    # 1 SERP + 1 fetch = $0.0015 + $0.0025 = $0.004
    assert result.per_arm_cost["arm1"] == pytest.approx(0.004)


@pytest.mark.asyncio
async def test_serp_failure_isolates_to_one_arm() -> None:
    """SERP exception on arm A doesn't kill arm B; A still gets the SERP cost debit."""
    client = _mock_client(
        serp_exceptions={"bad_query": RuntimeError("BD 500")},
        serp_responses={"good_query": _serp("good_query", ["https://ok.com/1"])},
    )

    result = await run_bandit_serp_phase(
        client,
        picked_arms=[("bad_arm", "bad_query"), ("good_arm", "good_query")],
    )

    # bad_arm: 0 docs, $0.0015 SERP cost (the call we attempted), error logged
    assert "bad_arm" in result.per_arm_errors
    assert "serp_failed" in result.per_arm_errors["bad_arm"][0]
    assert result.per_arm_cost["bad_arm"] == pytest.approx(0.0015)
    # good_arm: 1 doc, $0.0015 + $0.0025 = $0.004
    assert result.per_arm_cost["good_arm"] == pytest.approx(0.004)
    assert len(result.docs) == 1
    assert result.docs[0].discovered_via == "serp_arm:good_arm"


@pytest.mark.asyncio
async def test_fetch_failure_isolates_per_url() -> None:
    """One bad Web Unlocker doesn't kill the arm's other URLs."""
    client = _mock_client(
        serp_responses={
            "q": _serp("q", ["https://ok.com/1", "https://bad.com/2", "https://ok.com/3"]),
        },
        unlock_exceptions={"https://bad.com/2": RuntimeError("403 forbidden")},
    )

    result = await run_bandit_serp_phase(client, picked_arms=[("arm", "q")])

    # 2 successful fetches, 1 failure logged; cost includes only successful fetches
    # (the failed fetch's cost is NOT debited per the implementation contract).
    assert len(result.docs) == 2
    assert "arm" in result.per_arm_errors
    assert any("fetch_failed" in e for e in result.per_arm_errors["arm"])
    # 1 SERP + 2 successful unlocks = $0.0015 + 2 × $0.0025 = $0.0065
    assert result.per_arm_cost["arm"] == pytest.approx(0.0065)


@pytest.mark.asyncio
async def test_serp_timeout_debits_only_serp_cost() -> None:
    """Slow SERP cancelled by per-arm timeout; arm pays the SERP cost only."""

    async def slow_serp(query, count=10, *, session=None, **_):
        await asyncio.sleep(5)  # exceeds the 0.1s timeout
        return _empty_serp(query)

    client = MagicMock()
    client.serp_search = AsyncMock(side_effect=slow_serp)
    client.web_unlock = AsyncMock()

    result = await run_bandit_serp_phase(
        client,
        picked_arms=[("slow_arm", "q")],
        arm_timeout_s=0.1,
    )

    assert result.docs == []
    assert "slow_arm" in result.per_arm_errors
    assert "serp_timeout" in result.per_arm_errors["slow_arm"][0]
    assert result.per_arm_cost["slow_arm"] == pytest.approx(0.0015)
    client.web_unlock.assert_not_called()


@pytest.mark.asyncio
async def test_max_urls_per_arm_caps_fetches() -> None:
    """max_urls_per_arm bounds the per-arm fetch count even if SERP returns more."""
    client = _mock_client(
        serp_responses={
            "q": _serp("q", [f"https://x.com/{i}" for i in range(20)]),
        }
    )

    result = await run_bandit_serp_phase(
        client, picked_arms=[("arm", "q")], max_urls_per_arm=3
    )

    assert len(result.docs) == 3
    # 1 SERP + 3 fetches = $0.0015 + 3 × $0.0025 = $0.009
    assert result.per_arm_cost["arm"] == pytest.approx(0.009)


@pytest.mark.asyncio
async def test_inferred_source_type_routes_per_domain() -> None:
    """RawDocument.source_type is inferred from the URL domain."""
    client = _mock_client(
        serp_responses={
            "q": _serp(
                "q",
                [
                    "https://arxiv.org/abs/2605.18239",
                    "https://github.com/elder-plinius/L1B3RT4S",
                    "https://www.reddit.com/r/x/comments/abc",
                    "https://other.example.com/post",
                ],
            )
        }
    )

    result = await run_bandit_serp_phase(client, picked_arms=[("arm", "q")])

    by_url = {str(d.url): d for d in result.docs}
    assert by_url["https://arxiv.org/abs/2605.18239"].source_type == "arxiv"
    assert by_url["https://github.com/elder-plinius/L1B3RT4S"].source_type == "github"
    assert by_url["https://www.reddit.com/r/x/comments/abc"].source_type == "reddit"
    assert by_url["https://other.example.com/post"].source_type == "blog"


@pytest.mark.asyncio
async def test_non_http_links_skipped_silently() -> None:
    """`javascript:`, `mailto:`, missing links don't crash the parser."""
    client = _mock_client(
        serp_responses={
            "q": SerpResponse(
                query="q",
                engine="google",
                fetched_at=datetime.now(timezone.utc),
                organic_results=[
                    {"link": "javascript:void(0)"},
                    {"link": ""},
                    {},  # no link key at all
                    {"link": "https://valid.com/1"},
                ],
                knowledge_panel=None,
                raw_json={},
            )
        }
    )

    result = await run_bandit_serp_phase(client, picked_arms=[("arm", "q")])

    assert len(result.docs) == 1
    assert str(result.docs[0].url) == "https://valid.com/1"
