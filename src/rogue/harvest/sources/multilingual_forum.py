"""Multilingual forum harvest plugin (Q20) — the one non-English-first harvest source.

Every other ``harvest/sources/*`` plugin queries English communities and English phrases, so ROGUE's
whole corpus is English-centric — the single benchmark blind spot the field names as a *known-dangerous*
attack surface (GPT-4 fell to low-resource-language jailbreaks; Yong et al. 2310.02446, Deng et al.
2310.06474 / MultiJail, Wang et al. XSafety 2310.00905). This plugin closes it on the harvest side: it
runs Bright Data's *global* Reddit keyword discovery with jailbreak / prompt-injection phrases IN
non-English languages, so in-the-wild non-English attacks enter the pipeline natively — no machine
translation, so none of the translation-artifact confound the reproduce-side translate-then-reproduce
path has to control for. Each document is tagged with its query language in ``metadata["language"]`` so
the dashboard + the reproduce layer can separate the multilingual slice.

It reuses the Reddit fetcher capability + ``RedditSubredditPlugin``'s battle-tested post→RawDocument
adapter (no new Bright Data product, no new dependency). It is registered only when
``ROGUE_MULTILINGUAL_HARVEST`` is on (see ``discovery_agent.default_plugins``) so the daily harvest is
byte-identical to today when the flag is off.

Honesty: Reddit skews English, so per-language yield is uneven (highest for es/de/ja/zh communities,
thin for low-resource languages). This is the continuous *open-web* multilingual feed; Deng's public
MultiJail corpus is the complementary human-translated *benchmark* anchor (see
docs/research/multilingual_coverage.md). Keyword sets are deliberately small (each is a separate BD
/trigger job — cost scales linearly).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.harvest.sources.base import SourcePlugin
from rogue.harvest.sources.reddit_subreddit import RedditSubredditPlugin
from rogue.schemas import RawDocument

__all__ = ["MultilingualForumPlugin", "DEFAULT_MULTILINGUAL_KEYWORDS"]

logger = logging.getLogger(__name__)


# Per-language jailbreak / prompt-injection / "ignore your instructions" search phrases. Curated for the
# panel languages that have live non-English communities BD's Reddit keyword discovery can surface
# (Latin-script HRL + the largest non-Latin communities). Codes match reproduce.multilingual.languages.
DEFAULT_MULTILINGUAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "es": ("jailbreak de IA", "inyección de prompt", "ignorar instrucciones del sistema"),
    "de": ("KI Jailbreak", "Prompt Injection umgehen", "Systemanweisungen ignorieren"),
    "ja": ("AI ジェイルブレイク", "プロンプトインジェクション", "システムプロンプト 漏洩"),
    "zh": ("AI 越狱 提示词", "提示词注入", "系统提示词 泄露"),
    "ar": ("كسر حماية الذكاء الاصطناعي", "حقن الأوامر للنموذج"),
    "bn": ("এআই জেলব্রেক", "প্রম্পট ইনজেকশন"),
}


class MultilingualForumPlugin(SourcePlugin):
    """Non-English Reddit keyword discovery — one BD /trigger job per (language, keyword)."""

    name = "multilingual_forum"
    source_type = "reddit"
    bright_data_product = "web_scraper_api"
    required_capabilities: frozenset[Capability] = frozenset({Capability.REDDIT})

    def __init__(
        self,
        keywords_by_language: Optional[dict[str, tuple[str, ...]]] = None,
        per_keyword_num_of_posts: int = 30,
        keyword_date_range: str = "Past month",
    ) -> None:
        self.keywords_by_language = (
            keywords_by_language
            if keywords_by_language is not None
            else dict(DEFAULT_MULTILINGUAL_KEYWORDS)
        )
        self.per_keyword_num_of_posts = per_keyword_num_of_posts
        self.keyword_date_range = keyword_date_range
        self.call_errors: list[str] = []

    async def fetch_since(self, fetcher: Fetcher, since: datetime) -> list[RawDocument]:
        """Run every (language, keyword) discovery job in parallel; emit one RawDocument per post,
        tagged with its query language. Per-call failures are caught + logged (never raised) so one bad
        language doesn't sink the whole harvest — the same fail-soft contract as every plugin."""
        self.call_errors = []
        fetched_at = datetime.now(timezone.utc)
        seen_urls: set[str] = set()

        async def fetch_one(language: str, keyword: str) -> list[RawDocument]:
            try:
                posts = await fetcher.reddit_keyword(
                    keyword,
                    date_range=self.keyword_date_range,
                    num_of_posts=self.per_keyword_num_of_posts,
                )
            except NotImplementedError:
                raise
            except Exception as exc:  # noqa: BLE001 — fail-soft per plugin contract
                msg = f"lang={language} keyword={keyword!r}: {type(exc).__name__}: {exc}"
                self.call_errors.append(msg)
                logger.warning("multilingual keyword fetch failed: %s", msg)
                return []
            return RedditSubredditPlugin._posts_to_raw_docs(
                posts,
                since=since,
                fetched_at=fetched_at,
                seen_urls=seen_urls,
                discovered_via=f"multilingual_keyword[{language}]: {keyword}",
                extra_metadata={"discover_by": "keyword", "keyword": keyword, "language": language},
            )

        jobs = [
            fetch_one(language, kw)
            for language, keywords in self.keywords_by_language.items()
            for kw in keywords
        ]
        results = await asyncio.gather(*jobs)
        out: list[RawDocument] = []
        for batch in results:
            out.extend(batch)
        return out
