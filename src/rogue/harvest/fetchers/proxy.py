"""Universal harvest proxy — route the origin-site scraping backends through one external proxy.

Set ``ROGUE_PROXY_URL=http://user:pass@host:port`` to send the harvest's web fetches through a
residential/datacenter proxy pool (e.g. Webshare, IPRoyal, your own) — a cheap, provider-agnostic
substitute for Bright Data's *bundled* residential network. One env var, wired once at the fetcher
layer, applied to every backend that fetches arbitrary origin sites with our IP:

  * httpx backends — ``direct`` (UNLOCK / IMAGE_BYTES), ``ddg`` (SERP, IP-rate-limited), ``local_pdf``
  * browser backends — ``crawl4ai``, ``playwright`` (BROWSER / anti-bot)

**Scope (deliberate):** it does NOT touch the LLM/judge or Bright Data calls — those keep their own
egress (BD has its own superproxy; routing LLM traffic through a scraping proxy would only slow it).
Authed-API backends (``hf_api``, ``reddit_oauth``) and the self-hosted ``searxng`` / proxy-service
``firecrawl`` are also untouched. Opt-in: unset ``ROGUE_PROXY_URL`` = today's behavior (our own IP).

Use an ``http(s)://`` proxy URL — Playwright/crawl4ai don't support SOCKS5-with-auth. A rotating
gateway endpoint (one URL that rotates IPs per request) needs no extra logic on our side.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

__all__ = ["harvest_proxy_url", "playwright_proxy"]


def harvest_proxy_url() -> str | None:
    """The configured harvest proxy URL (``ROGUE_PROXY_URL``), or ``None`` if unset.

    Passed directly as ``httpx.AsyncClient(proxy=...)`` for the httpx backends (``None`` = no proxy).
    """
    return os.environ.get("ROGUE_PROXY_URL", "").strip() or None


def playwright_proxy() -> dict[str, str] | None:
    """``ROGUE_PROXY_URL`` parsed into Playwright/crawl4ai's ``{server, username, password}`` shape.

    ``{"server": "http://host:port", "username": ..., "password": ...}`` (credentials omitted when the
    URL carries none). Returns ``None`` when unset. The browser engines take auth as separate fields,
    not embedded in the server URL — hence the split.
    """
    url = harvest_proxy_url()
    if not url:
        return None
    parts = urlsplit(url)
    if not parts.hostname:
        return None
    server = f"{parts.scheme or 'http'}://{parts.hostname}"
    if parts.port:
        server += f":{parts.port}"
    cfg: dict[str, str] = {"server": server}
    if parts.username:
        cfg["username"] = parts.username
    if parts.password:
        cfg["password"] = parts.password
    return cfg
