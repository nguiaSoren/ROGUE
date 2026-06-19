"""RoutingFetcher PDF guard — a PDF URL whose default UNLOCK backend returns raw bytes is
re-routed to a registered ``handles_pdf`` backend (e.g. Firecrawl), so the harvest never feeds
binary PDF garbage to the extraction agent. Non-PDF URLs are unaffected.
"""

from __future__ import annotations

import pytest

from rogue.harvest.fetchers.base import Fetcher
from rogue.harvest.fetchers.capabilities import Capability
from rogue.harvest.fetchers.registry import FetcherRegistry
from rogue.harvest.fetchers.routing import RoutingFetcher, _looks_like_pdf


class _StubDefault(Fetcher):
    name = "stub_default"
    capabilities = frozenset({Capability.UNLOCK})
    handles_pdf = False  # returns raw bytes for PDFs (like brightdata/direct)

    async def unlock(self, url, format="markdown"):  # pragma: no cover - not invoked in these tests
        return (self.name, url)


class _StubPdf(Fetcher):
    name = "stub_pdf"
    capabilities = frozenset({Capability.UNLOCK})
    handles_pdf = True  # general UNLOCK that also parses PDFs (like firecrawl)

    async def unlock(self, url, format="markdown"):  # pragma: no cover
        return (self.name, url)


class _StubLocalPdf(Fetcher):
    name = "stub_local_pdf"
    capabilities = frozenset({Capability.UNLOCK})
    handles_pdf = True
    pdf_only = True  # PDF specialist (like pymupdf4llm) — never serves general HTML UNLOCK

    async def unlock(self, url, format="markdown"):  # pragma: no cover
        return (self.name, url)


def _registry(order, *fetchers):
    reg = FetcherRegistry(preference_order=order)
    for f in fetchers:
        reg.register(f)
    return reg


def test_pdf_url_reroutes_to_handles_pdf_backend():
    # Default order puts the non-PDF backend first; a PDF URL must still pick the PDF backend.
    rf = RoutingFetcher(_registry(["stub_default", "stub_pdf"], _StubDefault(), _StubPdf()))
    assert rf._unlock_backend("https://x.com/paper.pdf").name == "stub_pdf"
    assert rf._unlock_backend("https://arxiv.org/pdf/2307.15043").name == "stub_pdf"


def test_non_pdf_url_uses_default():
    rf = RoutingFetcher(_registry(["stub_default", "stub_pdf"], _StubDefault(), _StubPdf()))
    assert rf._unlock_backend("https://x.com/post.html").name == "stub_default"


def test_pdf_url_falls_back_when_no_pdf_backend():
    # No handles_pdf backend registered → keep the default (degrade, don't crash).
    rf = RoutingFetcher(_registry(["stub_default"], _StubDefault()))
    assert rf._unlock_backend("https://x.com/paper.pdf").name == "stub_default"


def test_pdf_prefers_local_specialist_over_general_pdf_backend():
    # Regression: a pdf_only local specialist (pymupdf4llm) must win for PDFs over a general UNLOCK
    # backend that ALSO handles PDFs (firecrawl) — even though for_capability(UNLOCK) returns the
    # latter (the specialist is pdf_only → skipped there). HTML still goes to the general backend.
    rf = RoutingFetcher(_registry(["stub_local_pdf", "stub_pdf"], _StubLocalPdf(), _StubPdf()))
    assert rf._unlock_backend("https://x.com/paper.pdf").name == "stub_local_pdf"
    assert rf._unlock_backend("https://x.com/post.html").name == "stub_pdf"


def test_pdf_url_kept_when_default_already_handles_pdf():
    # If the first UNLOCK backend already parses PDFs, don't reroute.
    rf = RoutingFetcher(_registry(["stub_pdf", "stub_default"], _StubDefault(), _StubPdf()))
    assert rf._unlock_backend("https://x.com/paper.pdf").name == "stub_pdf"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://a.com/x.pdf", True),
        ("https://a.com/X.PDF", True),
        ("https://arxiv.org/pdf/2307.15043", True),
        ("https://a.com/pdf/report", True),
        ("https://a.com/page.html", False),
        ("https://a.com/pdfviewer", False),  # not a /pdf/ segment nor a .pdf suffix
        ("https://a.com/file.pdf?download=1", True),  # query string ignored (path-based)
    ],
)
def test_looks_like_pdf(url, expected):
    assert _looks_like_pdf(url) is expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://arxiv.org/pdf/2307.15043", "https://arxiv.org/abs/2307.15043"),
        ("https://arxiv.org/pdf/2307.15043v2.pdf", "https://arxiv.org/abs/2307.15043v2"),
        ("http://www.arxiv.org/pdf/1234.5678", "http://www.arxiv.org/abs/1234.5678"),
        ("https://example.com/paper.pdf", "https://example.com/paper.pdf"),  # non-arxiv unchanged
        ("https://arxiv.org/abs/2307.15043", "https://arxiv.org/abs/2307.15043"),  # already HTML
    ],
)
def test_prefer_html_url_rewrites_arxiv_pdf(url, expected):
    from rogue.harvest.fetchers.routing import _prefer_html_url

    assert _prefer_html_url(url) == expected
