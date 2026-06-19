"""Generic image-URL extraction from a document body (multimodal ingestion, Feature A).

X / Reddit plugins populate ``RawDocument.media_urls`` from structured JSON
(the ``photos`` array). The *other* sources — security blogs, GitHub READMEs,
arXiv HTML — carry their images as ``<img>`` tags (HTML) or ``![alt](url)``
(markdown) inside the body. This module turns those into the same
``media_urls`` list so the downstream media-download + vision-extraction path
(``rogue.harvest.media_ingest`` → ``rogue.extract.extraction_agent``) works for
*every* source, not just the JSON ones.

Design notes:
  * Pure-stdlib, regex-based — no bs4/lxml dependency (the harvest layer already
    avoids heavy HTML parsers; the extraction LLM does the semantic work).
  * Relative ``src`` values are resolved against the document URL so the
    Web-Unlocker download step gets an absolute URL.
  * Data-URIs, SVGs, tracking pixels and obvious non-content assets are dropped
    — we only want real raster images that could carry an attack payload.
  * Order-preserving de-dupe + a hard cap so a gallery page can't explode the
    per-doc download budget.

It is intentionally conservative: it returns ``[]`` for ``json`` / ``text`` /
``pdf_text`` bodies (JSON sources populate ``media_urls`` structurally; plain
text has no markup). The caller decides whether to merge the result with any
structurally-populated ``media_urls`` (see ``media_urls_for_document``).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

__all__ = [
    "extract_media_urls",
    "extract_media_urls_from_json",
    "media_urls_for_document",
    "DEFAULT_MEDIA_LIMIT",
]

DEFAULT_MEDIA_LIMIT = 8

# <img ... src="..."> — tolerant of single/double quotes and attribute order.
_HTML_IMG_RE = re.compile(
    r"""<img\b[^>]*?\bsrc\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
# Markdown image: ![alt](url "title") — capture the URL, stop at whitespace/paren.
_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[^)]*)?\)")

# Raster extensions we accept (a true image-payload carrier). SVG excluded — it
# is markup, not a raster the vision models read as an attack surface; GIFs kept
# (memes / screenshots are sometimes GIF).
_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|webp|bmp|tiff?)(?:[?#].*)?$", re.IGNORECASE)

# Bare image URL anywhere inside a free-text / JSON string value (HF discussion
# post bodies embed images as markdown OR as raw links). Captured then
# content-filtered by `_is_probably_content_image`.
_BARE_IMG_URL_RE = re.compile(r"https?://[^\s)\"'<>]+", re.IGNORECASE)

# JSON keys whose list/string values are known to hold a post's own images
# (not avatars). Mirrors the X/Reddit `photos` shape for any other JSON source.
_JSON_IMAGE_KEYS: frozenset[str] = frozenset(
    {"photos", "images", "image", "media", "attachments", "image_url", "img"}
)

# Cheap junk filters — 1x1 trackers, sprites, icons, avatars, emoji.
_JUNK_SUBSTRINGS: tuple[str, ...] = (
    "spacer",
    "pixel",
    "tracking",
    "/emoji/",
    "/emojis/",
    "sprite",
    "favicon",
    "1x1",
    "avatar",
    "gravatar",
    "profile_image",
    "badge",
    "shield",
    "/icons/",
    "icon-",
)


def _is_probably_content_image(url: str) -> bool:
    """Heuristic: keep real content images, drop trackers / icons / data-URIs."""
    if not url or url.startswith(("data:", "javascript:", "#")):
        return False
    low = url.lower()
    if any(j in low for j in _JUNK_SUBSTRINGS):
        return False
    # Accept if it has a known raster extension OR comes from a known image CDN
    # whose URLs are commonly extension-less (e.g. pbs.twimg.com/media/...).
    if _IMAGE_EXT_RE.search(low):
        return True
    parsed = urlparse(low)
    image_cdn_hosts = ("pbs.twimg.com", "i.redd.it", "preview.redd.it", "i.imgur.com")
    return any(host in parsed.netloc for host in image_cdn_hosts)


def extract_media_urls(
    raw_content: str,
    content_format: str,
    base_url: str,
    *,
    limit: int = DEFAULT_MEDIA_LIMIT,
) -> list[str]:
    """Extract content-image URLs from a document body.

    Handles ``html`` (``<img src>``), ``markdown`` (``![](url)``) and
    ``pdf_text`` (image URLs/links that survived PDF→text conversion) bodies;
    returns ``[]`` for ``json`` / ``text`` (JSON carries media structurally via
    ``extract_media_urls_from_json``; rendered ``text`` has its URLs stripped).
    Note ``pdf_text`` covers only image *links* in the extracted text — EMBEDDED
    raster figures need the PDF bytes (see ``media_pdf.extract_pdf_images``).
    Relative URLs are resolved against ``base_url``; results are
    content-filtered, absolute-ised, order-preserving-deduped, capped at
    ``limit``.
    """
    if content_format not in ("html", "markdown", "pdf_text"):
        return []

    candidates: list[str] = []
    if content_format == "html":
        candidates.extend(_HTML_IMG_RE.findall(raw_content))
        # Markdown image syntax also appears inside many "HTML" blog exports.
        candidates.extend(_MD_IMG_RE.findall(raw_content))
    elif content_format == "pdf_text":
        # Extracted PDF text keeps no <img> tags; image references survive as
        # markdown or bare links. Bare-URL scan is content-filtered below.
        candidates.extend(_MD_IMG_RE.findall(raw_content))
        candidates.extend(_BARE_IMG_URL_RE.findall(raw_content))
    else:  # markdown
        candidates.extend(_MD_IMG_RE.findall(raw_content))

    out: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        # Bare-URL scans (pdf_text) can capture trailing sentence punctuation.
        url = raw.strip().rstrip(".,);\"'")
        if not url:
            continue
        # Resolve relative → absolute against the source document URL.
        if not url.startswith(("http://", "https://")):
            try:
                url = urljoin(base_url, url)
            except ValueError:
                continue
        if not url.startswith(("http://", "https://")):
            continue
        if not _is_probably_content_image(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def extract_media_urls_from_json(
    obj: object,
    *,
    limit: int = DEFAULT_MEDIA_LIMIT,
) -> list[str]:
    """Recursively collect content-image URLs from a parsed JSON structure.

    For JSON sources whose images aren't a single clean `photos` array (e.g.
    HuggingFace discussion threads, where images are embedded as markdown or raw
    links inside post bodies, under best-guess/unprovisioned field names). Two
    signals are collected, field-name-agnostically:

      * any ``http(s)`` string under an image-ish key (``photos``/``images``/…);
      * markdown ``![]()`` images and bare image URLs inside ANY string leaf.

    Everything is passed through ``_is_probably_content_image`` (so avatars,
    trackers, emoji and non-rasters are dropped), order-preserving-deduped, and
    capped at ``limit``. Use for the structural ``media_urls`` of a JSON source
    that lacks a dedicated photo array; X/Reddit use their explicit field
    instead (precise > heuristic when the schema is known).
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> None:
        u = (url or "").strip().rstrip(".,);")
        if (
            u
            and u.startswith(("http://", "https://"))
            and u not in seen
            and _is_probably_content_image(u)
        ):
            seen.add(u)
            out.append(u)

    def _walk(node: object) -> None:
        if len(out) >= limit:
            return
        if isinstance(node, str):
            for m in _MD_IMG_RE.findall(node):
                _add(m)
            for u in _BARE_IMG_URL_RE.findall(node):
                _add(u)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in _JSON_IMAGE_KEYS:
                    if isinstance(value, str):
                        _add(value)
                    elif isinstance(value, list):
                        for v in value:
                            if isinstance(v, str):
                                _add(v)
                _walk(value)
        elif isinstance(node, (list, tuple)):
            for v in node:
                _walk(v)

    _walk(obj)
    return out[:limit]


def media_urls_for_document(
    *,
    media_urls: list[str],
    raw_content: str,
    content_format: str,
    base_url: str,
    limit: int = DEFAULT_MEDIA_LIMIT,
) -> list[str]:
    """Merge a document's structural ``media_urls`` with body-derived ones.

    Structural URLs (populated by the X/Reddit plugins from JSON) take
    precedence and come first; body-derived ``<img>``/``![]()`` URLs fill the
    remainder up to ``limit``. This is the single entry point the harvest
    media-download step uses so coverage is uniform across *all* sources
    regardless of whether the plugin populated ``media_urls`` itself.
    """
    out: list[str] = []
    seen: set[str] = set()
    for url in media_urls:
        u = (url or "").strip()
        if u and u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            out.append(u)
            if len(out) >= limit:
                return out
    for url in extract_media_urls(raw_content, content_format, base_url, limit=limit):
        if url not in seen:
            seen.add(url)
            out.append(url)
            if len(out) >= limit:
                break
    return out
