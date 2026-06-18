"""X (Twitter) user-timeline harvest plugin (source #11 in docs/sources.md).

Tracks the 12-account roster locked at Day 0
(``docs/sources.md`` §11): simonw, plinz, embracethered, llm_sec, garak_ml,
lakera, pliny, hardmaru, AnthropicAI, OpenAIDevs, GoogleDeepMind, doomslide.

  * **Primary product:** Web Scraper API (X "posts-by-profile-URL" prebuilt
    dataset; ``website/WEB SCRAPER API/twitter/send-first-request.md``).
    Wrapped by :meth:`BrightDataClient.scrape_x_user_posts`, which since
    2026-05-26 uses /trigger (async) — sync /scrape returned ``200 []``
    silently for discover-mode.
  * **Fallback:** none — if the X scraper dataset fails, the source is
    marked stale and we let the next harvest run retry.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["XUserTimelinePlugin"]


# Trimmed 2026-05-26 from 12 → 4 handles. BD's X discover-by-profile-url
# scraper averages 5-15min per /trigger snapshot; the original 12-handle
# default ran serial via for-loop, putting the daily harvest at risk of
# 1-3hr just for X. The 4 kept are jailbreak/red-team practitioner accounts
# (highest signal-to-noise for AttackPrimitive extraction):
#   * elder_plinius   — Pliny the Prompter; the L1B3RT4S / CL4R1T4S corpus author
#   * wunderwuzzi23   — Johann Rehberger (embracethered.com); prompt-injection →
#                       RCE, MCP / tool-exfiltration write-ups
#   * simonw          — Simon Willison; *named* prompt injection; daily commentary
#   * goodside        — Riley Goodside; *discovered* prompt injection (2022)
# (Handles verified on X 2026-05-30 — the prior list "pliny / embracethered /
#  llm_sec" used wrong/nonexistent usernames; @elder_plinius and @wunderwuzzi23
#  are the real handles, llm_sec did not exist → replaced with @goodside.)
# Dropped: garak_ml / lakera (org accounts, mostly product PR); hardmaru
# (general ML, low jailbreak content); AnthropicAI / OpenAIDevs / GoogleDeepMind
# (vendor PR — not attacker-side); doomslide / plinz (low post frequency).
# Re-add any by passing `handles=[...]` to the constructor.
DEFAULT_HANDLES = [
    "elder_plinius",
    "wunderwuzzi23",
    "simonw",
    "goodside",
]


class XUserTimelinePlugin(SourcePlugin):
    """X user-timeline harvester (Web Scraper API)."""

    name = "x_user_timeline"
    source_type = "x"
    bright_data_product = "web_scraper_api"
    required_capabilities: frozenset[Capability] = frozenset({Capability.X})

    def __init__(
        self,
        handles: Optional[list[str]] = None,
        per_user_limit: int = 50,
    ) -> None:
        self.handles = handles if handles is not None else list(DEFAULT_HANDLES)
        self.per_user_limit = per_user_limit
        self.call_errors: list[str] = []

    def serp_queries(self, since: datetime) -> list[str]:
        """Per-account SERP discovery queries (docs/sources.md §11)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [f"site:x.com/{handle} after:{date_str}" for handle in self.handles]

    async def fetch_since(
        self,
        fetcher: Fetcher,
        since: datetime,
    ) -> list[RawDocument]:
        """Fetch each account's recent posts; emit one RawDocument per post."""
        self.call_errors = []
        logger = logging.getLogger(__name__)
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)

        for handle in self.handles:
            profile_url = f"https://x.com/{handle}"
            try:
                posts = await fetcher.x_user_posts(
                    profile_url, limit=self.per_user_limit
                )
            except NotImplementedError:
                raise
            except Exception as exc:
                # Surface real BD errors instead of silently dropping them.
                msg = f"@{handle}: {type(exc).__name__}: {exc}"
                self.call_errors.append(msg)
                logger.warning("x user fetch failed: %s", msg)
                continue

            for post in posts:
                if post.posted_at <= since:
                    continue

                raw_content = json.dumps(post.model_dump(mode="json"), sort_keys=True)
                archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()

                # Metrics live in a free-form dict (likes / retweets / replies
                # per `website/WEB SCRAPER API/twitter/send-first-request.md`).
                # Spread them into metadata for the dashboard's freshness panel.
                metadata: dict = {
                    "author_handle": post.author_handle,
                    "post_id": post.post_id,
                }
                if isinstance(post.metrics, dict):
                    metadata.update(post.metrics)

                try:
                    docs.append(
                        RawDocument(
                            url=post.permalink,
                            source_type=self.source_type,
                            bright_data_product=self.bright_data_product,
                            fetched_at=fetched_at,
                            raw_content=raw_content,
                            content_format="json",
                            archive_hash=archive_hash,
                            http_status=200,
                            metadata=metadata,
                            discovered_via=None,
                            # Multimodal ingestion (Feature A): the post's own
                            # images (Pliny screenshots of jailbreak prompts) so
                            # the media-download step can fetch + vision-read them.
                            media_urls=list(post.media_urls),
                        )
                    )
                except Exception:
                    continue
        return docs
