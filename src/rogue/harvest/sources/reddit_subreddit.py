"""Reddit harvest plugin (sources #1-3 in docs/sources.md).

Two complementary discovery paths run on every invocation:

  1. **Per-subreddit listing** (``client.scrape_reddit_subreddit``) — pull
     the most-recent posts from each configured subreddit. Best for active
     general subs (verified 2026-05-26: r/learnpython returns 999 posts);
     returns 0 for some niche / quarantined subs (e.g. r/ChatGPTJailbreak)
     so we never rely on it alone.

  2. **Global keyword discovery** (``client.scrape_reddit_keyword``) — search
     Reddit *globally* for jailbreak / prompt-injection phrases. Surfaces
     hits from any subreddit, including the long tail (r/AIJailbreak,
     r/ArtificialIntelligence, r/MachineLearning, etc.). Verified 2026-05-26:
     "jailbreak prompt" returns 20 records in ~78s via /trigger.

Both paths return ``RedditPost`` records that we serialize identically into
``RawDocument`` shapes. Deduplication across paths happens at the dedup layer
via ``archive_hash`` — a post that surfaces from both subreddit_url AND
keyword discovery becomes one cluster, not two.

  * **Primary product:** Web Scraper API (Reddit pre-built dataset,
    ``gd_lvz8ah06191smkebj4``). See ``website/WEB SCRAPER API/reddit/`` for
    the canonical request shapes; both discovery modes use the SAME
    dataset_id, distinguished by ``discover_by`` query param.
  * **Fallback:** none — the prebuilt scraper covers the surface.

History: pre-2026-05-26 this plugin used sync /scrape which returned
``200 []`` silently for all discover-mode requests. Migrated to async
/trigger via the new ``BrightDataClient._trigger_and_poll`` helper.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from rogue.harvest.bright_data_client import BrightDataClient
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["RedditSubredditPlugin", "DEFAULT_KEYWORDS"]


logger = logging.getLogger(__name__)


DEFAULT_SUBREDDITS = [
    "ChatGPTJailbreak",
    "LocalLLaMA",
    "PromptEngineering",
]


# Keyword discovery phrases. These are the GLOBAL-search analogues of the
# §5.2 per-subreddit SERP queries — distilled to bare phrases since BD's
# discover-by-keyword takes free text, not SERP-style operators. Each phrase
# is a separate /trigger job + snapshot, so keep the list tight (~4-6
# entries) or daily harvest time inflates linearly. Per-keyword caps via
# `num_of_posts` keep the per-job poll time under 5 min.
DEFAULT_KEYWORDS: tuple[str, ...] = (
    "jailbreak prompt",          # verified 20 hits 2026-05-26
    "prompt injection",
    "system prompt leak",
    "indirect prompt injection",
    "LLM jailbreak",
)


class RedditSubredditPlugin(SourcePlugin):
    """Reddit harvester (Web Scraper API) — subreddit_url + keyword discovery."""

    name = "reddit_subreddit"
    source_type = "reddit"
    bright_data_product = "web_scraper_api"

    def __init__(
        self,
        subreddits: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        per_subreddit_limit: int = 100,
        per_keyword_num_of_posts: int = 50,
        keyword_date_range: str = "Past week",
    ) -> None:
        self.subreddits = subreddits if subreddits is not None else list(DEFAULT_SUBREDDITS)
        self.keywords = keywords if keywords is not None else list(DEFAULT_KEYWORDS)
        self.per_subreddit_limit = per_subreddit_limit
        self.per_keyword_num_of_posts = per_keyword_num_of_posts
        self.keyword_date_range = keyword_date_range
        # Per-call telemetry surfaced into PluginRunReport.call_errors.
        self.call_errors: list[str] = []

    def serp_queries(self, since: datetime) -> list[str]:
        """Per-subreddit SERP discovery queries (docs/sources.md §1-3)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        queries: list[str] = []
        if "ChatGPTJailbreak" in self.subreddits:
            queries.extend(
                [
                    f"site:reddit.com/r/ChatGPTJailbreak after:{date_str}",
                    f'site:reddit.com/r/ChatGPTJailbreak "new method" after:{date_str}',
                    f'site:reddit.com/r/ChatGPTJailbreak "GPT-4o" OR "Claude" OR "Gemini" '
                    f"after:{date_str}",
                ]
            )
        if "LocalLLaMA" in self.subreddits:
            queries.extend(
                [
                    f'site:reddit.com/r/LocalLLaMA "jailbreak" OR "uncensor" after:{date_str}',
                    f'site:reddit.com/r/LocalLLaMA "system prompt" "leak" after:{date_str}',
                ]
            )
        if "PromptEngineering" in self.subreddits:
            queries.append(
                f'site:reddit.com/r/PromptEngineering "injection" OR "jailbreak" '
                f"after:{date_str}"
            )
        return queries

    async def fetch_since(
        self,
        client: BrightDataClient,
        since: datetime,
    ) -> list[RawDocument]:
        """Run subreddit_url + keyword discovery; emit one RawDocument per post.

        Both paths are parallelized via ``asyncio.gather`` because each BD
        ``/trigger`` snapshot is independent + spends most wall-clock blocked
        on remote polling (5-8 min per sub via discover_by=subreddit_url;
        ~60-80s per keyword via discover_by=keyword). Pre-2026-05-26 PM, the
        serial-loop version put a 4-sub + 5-keyword run at ~45 min worst-case;
        parallel cuts that to whichever single call is slowest (~5-8 min).
        """
        self.call_errors = []
        fetched_at = datetime.now(timezone.utc)
        seen_urls: set[str] = set()

        async def fetch_one_subreddit(sub: str) -> list[RawDocument]:
            try:
                posts = await client.scrape_reddit_subreddit(
                    sub, limit=self.per_subreddit_limit
                )
            except NotImplementedError:
                raise
            except Exception as exc:
                msg = f"subreddit:{sub}: {type(exc).__name__}: {exc}"
                self.call_errors.append(msg)
                logger.warning("reddit subreddit fetch failed: %s", msg)
                return []
            return self._posts_to_raw_docs(
                posts, since=since, fetched_at=fetched_at, seen_urls=seen_urls,
                discovered_via=None,
                extra_metadata={"discover_by": "subreddit_url"},
            )

        async def fetch_one_keyword(kw: str) -> list[RawDocument]:
            try:
                posts = await client.scrape_reddit_keyword(
                    kw,
                    date_range=self.keyword_date_range,
                    num_of_posts=self.per_keyword_num_of_posts,
                )
            except NotImplementedError:
                raise
            except Exception as exc:
                msg = f"keyword:{kw!r}: {type(exc).__name__}: {exc}"
                self.call_errors.append(msg)
                logger.warning("reddit keyword fetch failed: %s", msg)
                return []
            return self._posts_to_raw_docs(
                posts, since=since, fetched_at=fetched_at, seen_urls=seen_urls,
                discovered_via=f"reddit_keyword: {kw}",
                extra_metadata={"discover_by": "keyword", "keyword": kw},
            )

        # Parallel fan-out across both paths. seen_urls dedup races aren't a
        # correctness problem (worst case: one duplicate RawDocument that the
        # dedup layer collapses); python's GIL makes set ops effectively
        # atomic for our scale.
        results = await asyncio.gather(
            *(fetch_one_subreddit(s) for s in self.subreddits),
            *(fetch_one_keyword(k) for k in self.keywords),
        )
        out: list[RawDocument] = []
        for batch in results:
            out.extend(batch)
        return out

    @staticmethod
    def _posts_to_raw_docs(
        posts,
        *,
        since: datetime,
        fetched_at: datetime,
        seen_urls: set[str],
        discovered_via: str | None,
        extra_metadata: dict,
    ) -> list[RawDocument]:
        """Adapt typed ``RedditPost`` records into ``RawDocument`` instances.

        Drops posts older than ``since`` AND ones already emitted by an
        earlier discovery path (keyed by ``permalink``) so the same post
        surfaced by both subreddit_url + keyword paths becomes one doc, not
        two — saves a duplicate extraction-LLM call per overlap.
        """
        out: list[RawDocument] = []
        for post in posts:
            if not post.permalink or post.permalink in seen_urls:
                continue
            if post.posted_at <= since:
                continue
            seen_urls.add(post.permalink)
            raw_content = json.dumps(post.model_dump(mode="json"), sort_keys=True)
            archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
            try:
                out.append(
                    RawDocument(
                        url=post.permalink,
                        source_type="reddit",
                        bright_data_product="web_scraper_api",
                        fetched_at=fetched_at,
                        raw_content=raw_content,
                        content_format="json",
                        archive_hash=archive_hash,
                        http_status=200,
                        metadata={
                            "subreddit": post.subreddit,
                            "score": post.score,
                            "author": post.author,
                            "post_id": post.post_id,
                            "title": post.title,
                            "n_comments": len(post.comments),
                            **extra_metadata,
                        },
                        discovered_via=discovered_via,
                    )
                )
            except Exception as exc:
                # Bad URL / oversize content / etc. — drop the doc, keep going.
                logger.debug("reddit post -> RawDocument failed: %s", exc)
                continue
        return out
