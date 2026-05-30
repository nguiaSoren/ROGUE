"""Parse a single X/Twitter status page fetched via Web Unlocker.

BD's structured X scraper (discover-by-profile) is unreliable, but Web Unlocker
on an exact ``x.com/<user>/status/<id>`` URL returns the server-rendered page —
the tweet text lives in the ``og:title`` meta (X renders it for link previews)
and the attached images are ``pbs.twimg.com/media/...`` URLs in the body. This
turns that raw HTML into ``(tweet_text, image_urls)`` so the standard pipeline
(media ingestion + multimodal extraction) can take over.

Shared by ``scripts/harvest_url.py`` (one URL on demand) and
``sources/x_via_unlocker.py`` (SERP-discover → Web-Unlock each).
"""

from __future__ import annotations

import html as _html
import re

__all__ = ["parse_x_status", "is_x_status_url", "STATUS_URL_RE"]

# pbs.twimg media id (the base form 404s without a format param — we add one).
_TWIMG_RE = re.compile(r"https://pbs\.twimg\.com/media/[A-Za-z0-9_\-]+")
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)', re.I
)
# A canonical X/Twitter status (single-post) URL.
STATUS_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:x|twitter)\.com/[A-Za-z0-9_]+/status/\d+", re.I
)


def is_x_status_url(url: str) -> bool:
    """True iff ``url`` is a single X/Twitter status (post) URL."""
    return bool(STATUS_URL_RE.match((url or "").split("?")[0]))


def parse_x_status(html: str, url: str) -> tuple[str, list[str]]:
    """Extract ``(tweet_text_body, image_urls)`` from an X status page's HTML.

    ``tweet_text_body`` is the ``og:title`` (``'<author> on X: "<text>"'`` — the
    announcement; the screenshots carry the actual payload), prefixed with the
    post URL for provenance. ``image_urls`` are the post's full-res
    ``pbs.twimg.com`` media. Returns ``("X post: <url>", [])`` if the page had no
    og:title (still useful so the URL/provenance is preserved).
    """
    html = html or ""
    m = _OG_TITLE_RE.search(html)
    title = _html.unescape(m.group(1)) if m else ""
    seen: set[str] = set()
    imgs: list[str] = []
    for base in _TWIMG_RE.findall(html):
        if base not in seen:
            seen.add(base)
            imgs.append(f"{base}?format=jpg&name=large")
    body = f"X post: {url}\n\n{title}".rstrip()
    return body, imgs
