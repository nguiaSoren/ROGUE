"""Outbound-link extraction from a harvested document (Feature C — post→link following).

When a harvested post links OUT to a website, that site is often the full
implementation of the technique the post only teases (e.g. @akaclandestine's X
post → ``giovannigatti.github.io/cve-bench/``). This module pulls those outbound
content links out of a post/doc body so the link-follow phase can fetch + process
them 1-hop.

It is deliberately distinct from ``media_extract.py`` (which pulls IMAGE URLs for
Feature A): here we want links to *pages* (repos, papers, write-ups), so image /
asset URLs, same-site navigation, and social-media chrome are filtered OUT.

Pure-stdlib, regex-based (no bs4) — handles every ``content_format``:
  * ``json``  (X/Reddit post records) — bare URLs in the serialized body
    (``description`` text, ``external_url`` field, t.co links);
  * ``html``  — ``<a href>`` + bare URLs;
  * ``markdown`` — ``[text](url)`` (NOT ``![img]()``) + bare URLs;
  * ``text``  — bare URLs.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

__all__ = [
    "extract_outbound_urls",
    "is_shortener",
    "SHORTENER_HOSTS",
    "DEFAULT_LINKS_PER_DOC",
]

DEFAULT_LINKS_PER_DOC = 3

# URL shorteners whose final destination must be resolved before dedup/routing
# (an X post body is full of ``t.co`` links). Resolution is a cheap auth-less
# HEAD/GET hop (``Fetcher.resolve_redirect``), NOT a billed fetch.
SHORTENER_HOSTS: frozenset[str] = frozenset(
    {
        "t.co",
        "bit.ly",
        "buff.ly",
        "ow.ly",
        "tinyurl.com",
        "goo.gl",
        "dlvr.it",
        "trib.al",
        "lnkd.in",
        "rb.gy",
        "is.gd",
        "shorturl.at",
    }
)

# <a href="..."> (tolerant of quote style + attribute order).
_HTML_A_RE = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)
# Markdown link [text](url) — the leading (?<!!) excludes image links ![](...).
_MD_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[^)]*)?\)")
# Bare URL anywhere (incl. inside a JSON string value).
_BARE_URL_RE = re.compile(r"https?://[^\s)\"'<>\\]+", re.IGNORECASE)

# Asset / media extensions — a link to one of these is not a page to process
# (images are Feature A; the rest aren't extractable as a text technique).
_ASSET_EXT_RE = re.compile(
    r"\.(?:png|jpe?g|gif|webp|bmp|tiff?|svg|ico|css|js|mjs|woff2?|ttf|eot|"
    r"mp4|webm|mov|avi|mp3|wav|zip|gz|tar|dmg|exe)(?:[?#].*)?$",
    re.IGNORECASE,
)

# Hosts whose links are social chrome / non-article media, never an
# implementation page — skip so we don't burn an Unlocker fetch on them.
_NOISE_HOST_SUBSTRINGS: tuple[str, ...] = (
    "pbs.twimg.com",
    "video.twimg.com",
    "abs.twimg.com",
    "i.redd.it",
    "preview.redd.it",
    "external-preview.redd.it",
    "redditstatic.com",
    "redditmedia.com",
    "youtube.com",
    "youtu.be",
    "instagram.com",
    "tiktok.com",
    "facebook.com",
    "imgur.com",
    "giphy.com",
)


def is_shortener(url: str) -> bool:
    """True iff ``url``'s host is a known URL shortener (needs redirect resolution)."""
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return False
    host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host in SHORTENER_HOSTS


def _registrable(host: str) -> str:
    """Crude registrable-domain key: last two labels (x.com, github.io).

    Good enough to tell 'same site' (x.com/a vs x.com/b) from 'links out'
    (x.com → github.com). Subdomain nuance (foo.github.io) is intentionally
    collapsed so a user's own ``*.github.io`` still reads as an outbound site.
    """
    host = (host or "").lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _should_follow(url: str, source_registrable: str) -> bool:
    """Keep only outbound, non-asset, non-noise http(s) page links."""
    low = url.lower()
    if not low.startswith(("http://", "https://")):
        return False
    if _ASSET_EXT_RE.search(low):
        return False
    if any(n in low for n in _NOISE_HOST_SUBSTRINGS):
        return False
    parsed = urlparse(low)
    if not parsed.netloc:
        return False
    # Same-site links aren't "following out" (a reddit post linking to reddit,
    # an x post linking to another x status) — skip. Shorteners are exempt:
    # their registrable domain is the shortener, not the destination.
    if not is_shortener(url) and _registrable(parsed.netloc) == source_registrable:
        return False
    return True


def extract_outbound_urls(
    raw_content: str,
    content_format: str,
    source_url: str,
    *,
    limit: int = DEFAULT_LINKS_PER_DOC,
) -> list[str]:
    """Extract outbound page-link URLs from a document body.

    Pulls ``<a href>`` / markdown-link / bare URLs per ``content_format``, drops
    asset/image/social-noise links and same-site navigation, resolves relative
    paths is NOT done (outbound links are absolute by nature), de-dupes
    order-preserving, trims trailing punctuation, and caps at ``limit``. Returns
    ``[]`` when the body has no qualifying outbound link.
    """
    source_registrable = _registrable(urlparse(source_url).netloc) if source_url else ""

    candidates: list[str] = []
    if content_format == "html":
        candidates.extend(_HTML_A_RE.findall(raw_content))
        candidates.extend(_BARE_URL_RE.findall(raw_content))
    elif content_format == "markdown":
        candidates.extend(_MD_LINK_RE.findall(raw_content))
        candidates.extend(_BARE_URL_RE.findall(raw_content))
    else:  # json / text / pdf_text — bare URLs only
        candidates.extend(_BARE_URL_RE.findall(raw_content))

    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        url = raw.strip().rstrip(".,);]\"'")
        if not url or url in seen:
            continue
        if not _should_follow(url, source_registrable):
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out
