"""Unit tests for :class:`~rogue.harvest.fetchers.ddg.DuckDuckGoFetcher`.

All network calls are mocked — no real DDG requests are made.  The test suite
covers:

  1. Conformance — structural contract (name, capabilities, overrides, undeclared caps)
  2. ``serp()`` — parses DDG HTML into a valid :class:`SerpResponse`
  3. ``serp()`` — ``engine`` kwarg is accepted and silently ignored
  4. ``serp()`` — graceful degrade on network error (returns empty SerpResponse)
  5. ``serp()`` — graceful degrade on HTTP error status
  6. ``serp_image()`` — extracts image URLs from inline DDG JSON data
  7. ``serp_image()`` — graceful degrade on network error (returns [])
  8. ``is_available()`` — always True
  9. ``aclose()`` — idempotent, no crash on double-call
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from rogue.harvest.bright_data_client import SerpResponse
from rogue.harvest.fetchers.capabilities import Capability
from rogue.harvest.fetchers.conformance import assert_conforms
from rogue.harvest.fetchers.ddg import DuckDuckGoFetcher, _DDGResultParser, _extract_image_urls

# ---------------------------------------------------------------------------
# Saved DDG HTML snippets (no real network required)
# ---------------------------------------------------------------------------

# A realistic (stripped) fragment of the DDG HTML endpoint response.
# The key structure: <div class="web-result"> wrapping <a class="result__a">
# and a snippet element.  DDG's live HTML uses /l/?uddg=<encoded-url> hrefs.
_DDG_HTML_SNIPPET = """\
<!DOCTYPE html>
<html>
<head><title>DuckDuckGo</title></head>
<body>
<div id="links" class="results">

  <div class="web-result">
    <div class="result__body">
      <a class="result__a" href="/l/?uddg=https%3A%2F%2Fgithub.com%2Fuser%2Frepo&rut=abc">
        GitHub repo title
      </a>
      <div class="result__snippet">A repository containing jailbreak prompts.</div>
    </div>
  </div>

  <div class="web-result">
    <a class="result__a" data-href="https://example.com/blog/post" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fblog%2Fpost">
      Example Blog Post
    </a>
    <div class="result__snippet">  An interesting article about  prompt   injection.  </div>
  </div>

  <div class="web-result">
    <a class="result__a" href="https://arxiv.org/abs/2401.99999">
      Direct URL result
    </a>
    <a class="result__snippet">ArXiv paper on adversarial LLM attacks.</a>
  </div>

</div>
</body>
</html>
"""

# A DDG image-search response fragment containing inline JSON image data.
_DDG_IMAGE_HTML_SNIPPET = """\
<!DOCTYPE html>
<html><head><title>DuckDuckGo Images</title></head>
<body>
<script>
DDG.ready(function() {
    var imageData = [
        {"image":"https://cdn.example.com/img/photo1.jpg","thumbnail":"https://duckduckgo.com/i/thumb1.jpg","title":"Photo 1"},
        {"image":"https://static.example.org/images/photo2.png","thumbnail":"https://duckduckgo.com/i/thumb2.jpg","title":"Photo 2"},
        {"image":"https://duckduckgo.com/proxy/img/photo3.jpg","thumbnail":"https://duckduckgo.com/i/thumb3.jpg","title":"DDG proxy (skip)"},
        {"image":"https://upload.wikimedia.org/wikipedia/commons/photo4.jpg","thumbnail":"https://duckduckgo.com/i/thumb4.jpg","title":"Photo 4"},
        {"image":"https://media.example.net/p/photo5.gif","thumbnail":"https://duckduckgo.com/i/thumb5.jpg","title":"Photo 5"},
        {"image":"https://extra.example.com/photo6.jpg","thumbnail":"https://duckduckgo.com/i/thumb6.jpg","title":"Photo 6"},
    ];
});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_response(text: str, status_code: int = 200) -> MagicMock:
    """Build a fake httpx.Response-like object."""
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code),
        )
    return resp


def run(coro):
    """Run a coroutine synchronously (no event loop boilerplate in each test)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Conformance
# ---------------------------------------------------------------------------

class TestConformance:
    def test_assert_conforms(self):
        """assert_conforms must pass without raising."""
        fetcher = DuckDuckGoFetcher()
        report = assert_conforms(fetcher)
        assert report.passed, str(report)

    def test_name(self):
        assert DuckDuckGoFetcher.name == "ddg"

    def test_capabilities(self):
        caps = DuckDuckGoFetcher.capabilities
        assert isinstance(caps, frozenset)
        assert Capability.SERP in caps
        assert Capability.SERP_IMAGE in caps
        # Capabilities NOT declared — ensure the set is exact
        for cap in Capability:
            if cap not in (Capability.SERP, Capability.SERP_IMAGE):
                assert cap not in caps, f"{cap} should not be in ddg capabilities"

    def test_is_available(self):
        assert DuckDuckGoFetcher.is_available() is True


# ---------------------------------------------------------------------------
# 2. _DDGResultParser unit tests (pure parsing, no I/O)
# ---------------------------------------------------------------------------

class TestDDGResultParser:
    def test_parses_three_results(self):
        parser = _DDGResultParser(max_results=10)
        parser.feed(_DDG_HTML_SNIPPET)
        results = parser.get_results()
        assert len(results) == 3

    def test_first_result_link_decoded(self):
        """uddg= query parameter must be percent-decoded to the real URL."""
        parser = _DDGResultParser(max_results=10)
        parser.feed(_DDG_HTML_SNIPPET)
        results = parser.get_results()
        # First result uses a /l/?uddg= redirect
        assert results[0]["link"] == "https://github.com/user/repo"

    def test_second_result_prefers_data_href(self):
        """data-href attribute takes priority over uddg-decoded href."""
        parser = _DDGResultParser(max_results=10)
        parser.feed(_DDG_HTML_SNIPPET)
        results = parser.get_results()
        assert results[1]["link"] == "https://example.com/blog/post"

    def test_third_result_direct_url(self):
        """A direct https:// href (no DDG redirect) is returned as-is."""
        parser = _DDGResultParser(max_results=10)
        parser.feed(_DDG_HTML_SNIPPET)
        results = parser.get_results()
        assert results[2]["link"] == "https://arxiv.org/abs/2401.99999"

    def test_title_stripped(self):
        parser = _DDGResultParser(max_results=10)
        parser.feed(_DDG_HTML_SNIPPET)
        results = parser.get_results()
        assert results[0]["title"] == "GitHub repo title"

    def test_snippet_whitespace_collapsed(self):
        parser = _DDGResultParser(max_results=10)
        parser.feed(_DDG_HTML_SNIPPET)
        results = parser.get_results()
        # Snippet with internal runs of spaces should be collapsed
        assert results[1]["snippet"] == "An interesting article about prompt injection."

    def test_max_results_respected(self):
        parser = _DDGResultParser(max_results=2)
        parser.feed(_DDG_HTML_SNIPPET)
        results = parser.get_results()
        assert len(results) == 2

    def test_empty_html(self):
        parser = _DDGResultParser(max_results=10)
        parser.feed("<html><body></body></html>")
        assert parser.get_results() == []


# ---------------------------------------------------------------------------
# 3. _extract_image_urls unit tests
# ---------------------------------------------------------------------------

class TestExtractImageUrls:
    def test_extracts_non_ddg_urls(self):
        urls = _extract_image_urls(_DDG_IMAGE_HTML_SNIPPET, count=10)
        # DDG-hosted proxy URL should be excluded
        for u in urls:
            assert "duckduckgo.com" not in u

    def test_count_limit(self):
        urls = _extract_image_urls(_DDG_IMAGE_HTML_SNIPPET, count=3)
        assert len(urls) == 3

    def test_returns_https_urls(self):
        urls = _extract_image_urls(_DDG_IMAGE_HTML_SNIPPET, count=10)
        for u in urls:
            assert u.startswith("https://")

    def test_expected_urls_present(self):
        urls = _extract_image_urls(_DDG_IMAGE_HTML_SNIPPET, count=10)
        assert "https://cdn.example.com/img/photo1.jpg" in urls
        assert "https://static.example.org/images/photo2.png" in urls

    def test_empty_html(self):
        assert _extract_image_urls("<html></html>", count=5) == []

    def test_no_duplicates(self):
        # Duplicate the pattern in the HTML
        html = _DDG_IMAGE_HTML_SNIPPET + _DDG_IMAGE_HTML_SNIPPET
        urls = _extract_image_urls(html, count=100)
        assert len(urls) == len(set(urls))


# ---------------------------------------------------------------------------
# 4. DuckDuckGoFetcher.serp() — with mocked httpx client
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Patch asyncio.sleep to a no-op so tests don't actually wait 0.5 s each."""
    async def _instant(*_a, **_kw):
        return None
    monkeypatch.setattr("rogue.harvest.fetchers.ddg.asyncio.sleep", _instant)


class TestDDGFetcherSerp:
    def _make_fetcher_with_mock(self, html: str, status: int = 200) -> tuple[DuckDuckGoFetcher, MagicMock]:
        fetcher = DuckDuckGoFetcher()
        mock_response = _make_mock_response(html, status)
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.get = AsyncMock(return_value=mock_response)
        fetcher._http = mock_client
        return fetcher, mock_client

    def test_serp_returns_serp_response(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("jailbreak prompts"))
        assert isinstance(result, SerpResponse)

    def test_serp_query_field(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("jailbreak prompts"))
        assert result.query == "jailbreak prompts"

    def test_serp_engine_field_is_ddg(self):
        """Engine field is always 'ddg' regardless of the engine kwarg."""
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("test", engine="google"))
        assert result.engine == "ddg"

    def test_serp_engine_kwarg_accepted_and_ignored(self):
        """engine= kwarg accepted for compat but ignored — no exception raised."""
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        # Should not raise regardless of engine value
        result_google = run(fetcher.serp("test", engine="google"))
        result_bing = run(fetcher.serp("test", engine="bing"))
        assert result_google.engine == "ddg"
        assert result_bing.engine == "ddg"

    def test_serp_organic_results_populated(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("jailbreak"))
        assert len(result.organic_results) == 3

    def test_serp_organic_result_has_link(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("jailbreak"))
        for r in result.organic_results:
            assert "link" in r
            assert r["link"].startswith("http")

    def test_serp_organic_result_has_title(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("jailbreak"))
        for r in result.organic_results:
            assert "title" in r

    def test_serp_organic_result_has_snippet(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("jailbreak"))
        for r in result.organic_results:
            assert "snippet" in r

    def test_serp_fetched_at_is_utc(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("test"))
        assert isinstance(result.fetched_at, datetime)
        assert result.fetched_at.tzinfo is not None

    def test_serp_count_respected(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        result = run(fetcher.serp("test", count=2))
        assert len(result.organic_results) <= 2

    def test_serp_posts_to_correct_endpoint(self):
        fetcher, mock_client = self._make_fetcher_with_mock(_DDG_HTML_SNIPPET)
        run(fetcher.serp("test query"))
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "html.duckduckgo.com" in call_args[0][0]

    def test_serp_network_error_returns_empty(self):
        """On httpx.NetworkError, serp() returns an empty SerpResponse — never raises."""
        fetcher = DuckDuckGoFetcher()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=httpx.NetworkError("connection refused"))
        fetcher._http = mock_client

        result = run(fetcher.serp("test"))
        assert isinstance(result, SerpResponse)
        assert result.organic_results == []
        assert result.query == "test"

    def test_serp_http_error_returns_empty(self):
        """On HTTP 429 / 503, serp() returns an empty SerpResponse — never raises."""
        fetcher, _ = self._make_fetcher_with_mock("", status=429)
        result = run(fetcher.serp("test"))
        assert isinstance(result, SerpResponse)
        assert result.organic_results == []

    def test_serp_empty_html_returns_empty(self):
        fetcher, _ = self._make_fetcher_with_mock("<html><body></body></html>")
        result = run(fetcher.serp("test"))
        assert isinstance(result, SerpResponse)
        assert result.organic_results == []


# ---------------------------------------------------------------------------
# 5. DuckDuckGoFetcher.serp_image() — with mocked httpx client
# ---------------------------------------------------------------------------

class TestDDGFetcherSerpImage:
    def _make_fetcher_with_mock(self, html: str, status: int = 200) -> tuple[DuckDuckGoFetcher, MagicMock]:
        fetcher = DuckDuckGoFetcher()
        mock_response = _make_mock_response(html, status)
        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        fetcher._http = mock_client
        return fetcher, mock_client

    def test_returns_list_of_strings(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_IMAGE_HTML_SNIPPET)
        result = run(fetcher.serp_image("jailbreak meme"))
        assert isinstance(result, list)
        assert all(isinstance(u, str) for u in result)

    def test_count_limit(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_IMAGE_HTML_SNIPPET)
        result = run(fetcher.serp_image("test", count=3))
        assert len(result) <= 3

    def test_no_ddg_proxy_urls(self):
        fetcher, _ = self._make_fetcher_with_mock(_DDG_IMAGE_HTML_SNIPPET)
        result = run(fetcher.serp_image("test"))
        for u in result:
            assert "duckduckgo.com" not in u

    def test_network_error_returns_empty_list(self):
        """On network failure, serp_image() returns [] — never raises."""
        fetcher = DuckDuckGoFetcher()
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.NetworkError("connection refused"))
        fetcher._http = mock_client

        result = run(fetcher.serp_image("test"))
        assert result == []

    def test_http_error_returns_empty_list(self):
        fetcher, _ = self._make_fetcher_with_mock("", status=503)
        result = run(fetcher.serp_image("test"))
        assert result == []

    def test_empty_response_returns_empty_list(self):
        fetcher, _ = self._make_fetcher_with_mock("<html></html>")
        result = run(fetcher.serp_image("test"))
        assert result == []

    def test_gets_correct_endpoint(self):
        fetcher, mock_client = self._make_fetcher_with_mock(_DDG_IMAGE_HTML_SNIPPET)
        run(fetcher.serp_image("test"))
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        assert "duckduckgo.com" in call_args[0][0]


# ---------------------------------------------------------------------------
# 6. aclose() — lifecycle
# ---------------------------------------------------------------------------

class TestAclose:
    def test_aclose_no_client(self):
        """aclose() before any request is a no-op (idempotent)."""
        fetcher = DuckDuckGoFetcher()
        run(fetcher.aclose())  # must not raise

    def test_aclose_idempotent(self):
        """Double-calling aclose() must not raise."""
        fetcher = DuckDuckGoFetcher()
        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        fetcher._http = mock_client

        run(fetcher.aclose())
        run(fetcher.aclose())  # second call: _http is None now, must not raise

    def test_aclose_calls_client_aclose(self):
        fetcher = DuckDuckGoFetcher()
        mock_client = MagicMock()
        mock_client.aclose = AsyncMock()
        fetcher._http = mock_client

        run(fetcher.aclose())
        mock_client.aclose.assert_awaited_once()
        assert fetcher._http is None
