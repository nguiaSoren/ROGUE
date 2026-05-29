"""Static-blog harvest plugin (sources #7-9 + #12-14 in docs/sources.md).

Generic Web-Unlocker-backed plugin that handles every "fetch an index page,
extract post URLs, fetch each post" blog in the source list:

  * Simon Willison's blog (#7)
  * Embrace The Red (#8)
  * Lakera blog (#9)
  * MITRE ATLAS (#12)
  * OWASP LLM Top 10 (#13)
  * Vendor safety blogs (#14) — anthropic.com/news, openai.com/blog,
    deepmind.google/discover/blog

  * **Primary product:** Web Unlocker (markdown output → easy to feed the
    extraction LLM directly). See
    ``website/WEB-UNLOCKER/send-your-first-request.md`` for the canonical
    request shape and ``website/WEB-UNLOCKER/configuration.md`` for the
    ``format=markdown`` option used here.
  * **Fallback:** none — if Web Unlocker fails on a feed, the blog goes
    stale per §9.3.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from rogue.harvest.bright_data_client import BrightDataClient
from rogue.schemas import RawDocument, SourceType

from .base import SourcePlugin

__all__ = ["BlogStaticPlugin", "BlogTarget"]


@dataclass(frozen=True)
class BlogTarget:
    """One blog to crawl: a human name, an index/feed URL, a source_type."""

    name: str
    feed_url: str
    source_type: SourceType


DEFAULT_BLOGS: tuple[BlogTarget, ...] = (
    BlogTarget("simonwillison", "https://simonwillison.net/tags/prompt-injection/", "blog"),
    BlogTarget("embracethered", "https://embracethered.com/blog/", "blog"),
    BlogTarget("lakera", "https://www.lakera.ai/blog", "blog"),
    BlogTarget("mitre_atlas", "https://atlas.mitre.org/", "mitre"),
    BlogTarget("owasp_llm_top10", "https://genai.owasp.org/llm-top-10/", "owasp"),
    BlogTarget("anthropic_news", "https://www.anthropic.com/news", "vendor_safety_blog"),
    BlogTarget("openai_blog", "https://openai.com/blog", "vendor_safety_blog"),
    BlogTarget(
        "deepmind_blog",
        "https://deepmind.google/discover/blog/",
        "vendor_safety_blog",
    ),
)


# Markdown-format Web Unlocker output renders links as `[text](url)`.
# REVIEW Day 1: each blog renders its index slightly differently in markdown.
# Simon Willison's tag pages use `[Title](/2026/may/24/...)` (relative URLs);
# Embrace The Red and OWASP put `[Title](https://...)` (absolute); Lakera
# may wrap article cards in `<div>` that survive the HTML→markdown pass as
# `[Read more](...)` instead of the article title. Validate on Day 1 by
# fetching each feed once + sanity-checking that we get 5-50 unique post URLs.
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


class BlogStaticPlugin(SourcePlugin):
    """Generic Web-Unlocker-backed static blog harvester."""

    name = "blog_static"
    source_type = "blog"  # default; per-target source_type wins on each doc
    bright_data_product = "web_unlocker"

    def __init__(self, blogs: Iterable[BlogTarget] | None = None) -> None:
        self.blogs: list[BlogTarget] = list(blogs) if blogs is not None else list(DEFAULT_BLOGS)

    def serp_queries(self, since: datetime) -> list[str]:
        """Per-blog SERP queries (docs/sources.md §7-9 + §12-14)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [
            f'site:simonwillison.net "prompt injection" after:{date_str}',
            f'site:simonwillison.net "indirect injection" after:{date_str}',
            f"site:embracethered.com after:{date_str}",
            'site:embracethered.com "MCP" OR "tool" OR "exfiltration"',
            f'site:lakera.ai "attack" OR "jailbreak" after:{date_str}',
            f"site:atlas.mitre.org after:{date_str}",
            f'"MITRE ATLAS" "new technique" OR "T1" after:{date_str}',
            f"site:genai.owasp.org after:{date_str}",
            '"OWASP" "LLM Top 10" "2026" OR "update"',
            f'site:anthropic.com/news "safety" OR "red team" after:{date_str}',
            f'site:openai.com/blog "safety" OR "red team" after:{date_str}',
            f'site:deepmind.google "safety" OR "red team" after:{date_str}',
        ]

    async def fetch_since(
        self,
        client: BrightDataClient,
        since: datetime,
    ) -> list[RawDocument]:
        """Per blog: fetch the feed, parse out post URLs, fetch each post."""
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)

        for target in self.blogs:
            try:
                feed = await client.web_unlock(target.feed_url, format="markdown")
            except NotImplementedError:
                raise
            except Exception:
                continue

            post_urls = self._extract_post_urls(target.feed_url, feed.content)

            for post_url in post_urls:
                try:
                    page = await client.web_unlock(post_url, format="markdown")
                except NotImplementedError:
                    raise
                except Exception:
                    continue

                if not page.content or len(page.content) < 50:
                    continue

                raw_content = page.content
                archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
                try:
                    docs.append(
                        RawDocument(
                            url=post_url,
                            source_type=target.source_type,
                            bright_data_product=self.bright_data_product,
                            fetched_at=fetched_at,
                            raw_content=raw_content,
                            content_format="markdown",
                            archive_hash=archive_hash,
                            http_status=page.status_code,
                            metadata={
                                "blog_name": target.name,
                                "feed_url": target.feed_url,
                            },
                            discovered_via=None,  # direct listing, not SERP
                        )
                    )
                except Exception:
                    continue

        # REVIEW Day 1: we don't currently filter by `since`. Most blog
        # indexes show posts newest-first so the first ~20 links are
        # always recent enough — but for backfill mode we'll need to either
        # (a) parse the post's `<time datetime="...">` after fetch, or
        # (b) trust the SERP `after:{date}` filter on the discovery side.
        _ = since
        return docs

    @staticmethod
    def _extract_post_urls(feed_url: str, feed_markdown: str) -> list[str]:
        """Pull plausible post URLs out of the feed page's markdown content.

        Keeps only links whose host matches the feed's host (filters out
        third-party links inside the page chrome). Deduplicates while
        preserving discovery order.
        """
        feed_host = urlparse(feed_url).netloc
        seen: set[str] = set()
        out: list[str] = []
        for _text, href in MARKDOWN_LINK_RE.findall(feed_markdown):
            # Resolve relative URLs (e.g. Simon Willison's `/2026/may/24/...`).
            absolute = urljoin(feed_url, href.strip())
            host = urlparse(absolute).netloc
            if host != feed_host:
                continue
            # Skip obvious chrome links: tag pages, author pages, the feed
            # itself, RSS endpoints, fragments-only URLs.
            path = urlparse(absolute).path
            if path in {"", "/"} or absolute == feed_url:
                continue
            if path.endswith((".xml", ".rss", ".atom")):
                continue
            if "/tag/" in path or "/tags/" in path or "/author/" in path:
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            out.append(absolute)
        # Cap to a conservative per-blog ceiling so a long index page doesn't
        # eat the harvest budget — DiscoveryAgent should pick fewer-but-richer
        # candidates.
        return out[:25]
