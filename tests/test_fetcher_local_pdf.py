"""LocalPdfFetcher — local PDF→markdown specialist (always on: pypdf floor + pymupdf4llm upgrade)."""

from __future__ import annotations

import importlib.util
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from rogue.harvest.fetchers import local_pdf as local_pdf_mod
from rogue.harvest.fetchers.capabilities import Capability
from rogue.harvest.fetchers.direct import DirectFetcher
from rogue.harvest.fetchers.local_pdf import LocalPdfFetcher
from rogue.harvest.fetchers.registry import FetcherRegistry
from rogue.harvest.fetchers.routing import RoutingFetcher


def _pdf_bytes(text: str) -> bytes:
    """Build a tiny real PDF carrying ``text`` (via pymupdf, which is present in the dev env)."""
    import pymupdf  # type: ignore[import-not-found]

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _mock_get(pdf_bytes: bytes) -> AsyncMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.content = pdf_bytes
    resp.url = "https://x.com/t.pdf"
    resp.raise_for_status.return_value = None
    return AsyncMock(return_value=resp)


def test_flags_and_capabilities():
    assert Capability.UNLOCK in LocalPdfFetcher.capabilities
    assert LocalPdfFetcher.handles_pdf is True
    assert LocalPdfFetcher.pdf_only is True


def test_always_available():
    # pypdf is a core dependency, so the local PDF backend is always available.
    assert LocalPdfFetcher.is_available() is True


def test_pdf_only_excluded_from_general_unlock_but_used_for_pdf_urls():
    reg = FetcherRegistry(preference_order=["local_pdf", "direct"])
    reg.register(LocalPdfFetcher())
    reg.register(DirectFetcher())
    assert reg.for_capability(Capability.UNLOCK).name == "direct"  # pdf_only skipped for HTML
    rf = RoutingFetcher(reg)
    assert rf._unlock_backend("https://x.com/paper.pdf").name == "local_pdf"
    assert rf._unlock_backend("https://x.com/post.html").name == "direct"


@pytest.mark.asyncio
async def test_parses_pdf_with_pymupdf4llm_upgrade():
    if importlib.util.find_spec("pymupdf4llm") is None:
        pytest.skip("rogue[pdf] (pymupdf4llm) not installed")
    fc = LocalPdfFetcher()
    with patch.object(fc._get_http(), "get", _mock_get(_pdf_bytes("Hello ROGUE upgrade path"))):
        page = await fc.unlock("https://x.com/t.pdf")
    await fc.aclose()
    assert page.content_format == "markdown"
    assert "Hello ROGUE upgrade path" in page.content


@pytest.mark.asyncio
async def test_parses_pdf_via_pypdf_floor(monkeypatch):
    # Force the floor: simulate pymupdf4llm absent → must still parse via the core pypdf path.
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *a, **k):
        return None if name == "pymupdf4llm" else real_find_spec(name, *a, **k)

    monkeypatch.setattr(local_pdf_mod.importlib.util, "find_spec", fake_find_spec)

    fc = LocalPdfFetcher()
    with patch.object(fc._get_http(), "get", _mock_get(_pdf_bytes("Hello ROGUE floor path"))):
        page = await fc.unlock("https://x.com/t.pdf")
    await fc.aclose()
    assert "Hello ROGUE floor path" in page.content
