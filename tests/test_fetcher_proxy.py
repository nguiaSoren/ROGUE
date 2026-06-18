"""Universal harvest proxy (ROGUE_PROXY_URL) — helper parsing + backend wiring."""

from __future__ import annotations

import httpx

from rogue.harvest.fetchers.direct import DirectFetcher
from rogue.harvest.fetchers.proxy import harvest_proxy_url, playwright_proxy


# --- harvest_proxy_url ----------------------------------------------------------------------------

def test_url_none_when_unset(monkeypatch):
    monkeypatch.delenv("ROGUE_PROXY_URL", raising=False)
    assert harvest_proxy_url() is None


def test_url_value_when_set(monkeypatch):
    monkeypatch.setenv("ROGUE_PROXY_URL", "http://u:p@host:8080")
    assert harvest_proxy_url() == "http://u:p@host:8080"


def test_url_blank_is_none(monkeypatch):
    monkeypatch.setenv("ROGUE_PROXY_URL", "   ")
    assert harvest_proxy_url() is None


# --- playwright_proxy (browser shape) -------------------------------------------------------------

def test_playwright_proxy_none_when_unset(monkeypatch):
    monkeypatch.delenv("ROGUE_PROXY_URL", raising=False)
    assert playwright_proxy() is None


def test_playwright_proxy_with_credentials(monkeypatch):
    monkeypatch.setenv("ROGUE_PROXY_URL", "http://user:pass@p.webshare.io:80")
    assert playwright_proxy() == {
        "server": "http://p.webshare.io:80",
        "username": "user",
        "password": "pass",
    }


def test_playwright_proxy_without_credentials(monkeypatch):
    monkeypatch.setenv("ROGUE_PROXY_URL", "https://proxy.internal:3128")
    assert playwright_proxy() == {"server": "https://proxy.internal:3128"}


# --- backend wiring (httpx) -----------------------------------------------------------------------

def _capture_asyncclient(monkeypatch) -> dict:
    captured: dict = {}
    real = httpx.AsyncClient

    def fake(*args, **kwargs):
        captured.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake)
    return captured


def test_direct_passes_proxy_when_set(monkeypatch):
    monkeypatch.setenv("ROGUE_PROXY_URL", "http://u:p@host:8080")
    captured = _capture_asyncclient(monkeypatch)
    DirectFetcher()._get_http()
    assert captured.get("proxy") == "http://u:p@host:8080"


def test_direct_no_proxy_when_unset(monkeypatch):
    monkeypatch.delenv("ROGUE_PROXY_URL", raising=False)
    captured = _capture_asyncclient(monkeypatch)
    DirectFetcher()._get_http()
    assert captured.get("proxy") is None
