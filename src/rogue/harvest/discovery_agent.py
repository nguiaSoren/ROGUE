"""DiscoveryAgent — orchestrates the harvest layer.

Day-1 version (this file): hand-tuned 10-query SERP set + all 10 source
plugins, fanned out via ``asyncio.gather`` with per-plugin error isolation.
The "5–10 SERP queries per day out of a pool of 39" framing from §3.3 is
fulfilled by :data:`DAY1_HANDPICKED_QUERIES` — that constant is what the
§11.6 epsilon-greedy bandit replaces on Day 2 evening (the bandit lives in
``rogue.harvest.bandit`` and plugs in here via the ``query_picker`` arg).

Day-2 evening (§11.6): swap ``query_picker`` for a callable returning the
top-k arms from the persisted bandit state at
``data/discovery_bandit.json``. Per-arm reward = number of NEW canonical
primitives surfaced from that query's plugin (recorded after the dedup pass).

Pipeline position (ROGUE_PLAN.md §3.1)::

    DiscoveryAgent.run(since)           ◄── this file
            │
            ▼
    SourcePlugin.fetch_since(client, since)  for each registered plugin
            │
            ▼
    list[RawDocument]                   ◄── returned to the caller
            │
            ▼  (later, §9.4)
    ExtractionAgent.extract(raw_doc)    ──► AttackPrimitive

Scope discipline (§13):
  * **No retry logic here** — lives in :class:`BrightDataClient`.
  * **No cost tracking here** — lives in :class:`BrightDataClient`.
  * **No bandit logic here** — lives in ``rogue.harvest.bandit`` and
    plugs in via the ``query_picker`` injection seam.
  * **No extraction here** — that's §9.4 (``extract/extraction_agent.py``).

Spec: ROGUE_PLAN.md §3.3, §9.3, §A.20 (Appendix-A canonical sketch — adapted
for the locked Day-0 ``SourcePlugin``/``RawDocument`` shapes).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from rogue.harvest.bright_data_client import BrightDataClient

if TYPE_CHECKING:
    from rogue.harvest.bandit import EpsilonGreedyBandit
from rogue.harvest.sources import (
    ArxivListingPlugin,
    BlogStaticPlugin,
    CommunityArchivePlugin,
    GithubSearchPlugin,
    HuggingFaceDiscussionPlugin,
    # LeakHubScrapePlugin,  # disabled 2026-05-26 — see default_plugins() docstring
    ObliteratusHfPlugin,
    PlinyGithubPlugin,
    RedditSubredditPlugin,
    SourcePlugin,
    # XUserTimelinePlugin,  # disabled 2026-05-26 — see default_plugins() docstring
)
from rogue.schemas import RawDocument

logger = logging.getLogger(__name__)

__all__ = [
    "DAY1_HANDPICKED_QUERIES",
    "DiscoveryAgent",
    "MULTIMODAL_ARM_IDS",
    "PluginRunReport",
    "default_plugins",
    "default_bandit_arms",
]


# --------------------------------------------------------------------------- #
# Day-1 hand-tuned query set
# --------------------------------------------------------------------------- #

# 10 SERP queries hand-picked from the 39-query pool in §5.2 to maximize
# expected daily-delta yield across the 5 Bright Data products. Two from
# each high-yield source bucket; ``{date}`` is the literal substitution
# token consumed by :meth:`DiscoveryAgent.serp_queries`.
#
# This is the Day-1 anchor that §11.6's epsilon-greedy bandit replaces
# Day-2 evening — same shape (list of query templates), so the drop-in
# replacement is a one-line swap at the ``query_picker`` arg of
# :class:`DiscoveryAgent`.
DAY1_HANDPICKED_QUERIES: tuple[str, ...] = (
    # Source #1-2 r/GPT_jailbreaks + r/ClaudeAIJailbreak (community successors)
    'site:reddit.com/r/GPT_jailbreaks "new method" after:{date}',
    'site:reddit.com/r/ClaudeAIJailbreak "system prompt" OR "constitution" after:{date}',
    # Source #5 arXiv (highest research-signal density)
    'site:arxiv.org "prompt injection" after:{date}',
    'site:arxiv.org "indirect prompt injection" after:{date}',
    # Source #6 GitHub (broadened vendor coverage 2026-05-25)
    'site:github.com prompt-injection updated:>{date}',
    'site:github.com jailbreak (GPT OR "ChatGPT" OR Claude OR Anthropic OR Gemini '
    'OR Mistral OR Mixtral OR Llama OR Qwen OR DeepSeek OR Gemma OR Falcon) '
    'updated:>{date}',
    # Source #7 Pliny umbrella (catches obfuscated-repo names)
    'site:github.com/elder-plinius updated:>{date}',
    # Source #11 Simon Willison (highest curated-commentary signal)
    'site:simonwillison.net "prompt injection" after:{date}',
    # Source #12 Embrace The Red (practitioner-grade write-ups)
    'site:embracethered.com after:{date}',
    # Source #16 MITRE ATLAS (taxonomy refreshes)
    'site:atlas.mitre.org after:{date}',
)


# --------------------------------------------------------------------------- #
# §11.6 bandit query pool — the FULL 39-query arm set (superset of the
# Day-1 hand-picked 10). Each arm has a stable `arm_id` (used as the dict
# key in the persisted bandit state) and a query template with `{date}`.
# --------------------------------------------------------------------------- #


def default_bandit_arms() -> list:
    """Return the full bandit arm pool, one per §5.2 SERP query.

    Imported lazily on demand by `harvest_once.py` — avoiding an unconditional
    import lets this module stay bandit-free for callers that only need the
    plugin orchestration.

    arm_id format: ``{source_label}_{slug}`` where slug is a short hash of
    the query. Stable across runs so the persisted state file in
    ``data/discovery_bandit.json`` keeps reward attribution.
    """
    from rogue.harvest.bandit import QueryArm

    pool: list = []
    # Reddit
    pool.append(QueryArm("reddit_gptjb_new_method",
        'site:reddit.com/r/GPT_jailbreaks "new method" after:{date}'))
    pool.append(QueryArm("reddit_gptjb_after",
        'site:reddit.com/r/GPT_jailbreaks after:{date}'))
    pool.append(QueryArm("reddit_claudejb_sysprompt",
        'site:reddit.com/r/ClaudeAIJailbreak "system prompt" OR "constitution" after:{date}'))
    pool.append(QueryArm("reddit_claudejb_after",
        'site:reddit.com/r/ClaudeAIJailbreak after:{date}'))
    pool.append(QueryArm("reddit_localllama_uncensor",
        'site:reddit.com/r/LocalLLaMA "jailbreak" OR "uncensor" after:{date}'))
    pool.append(QueryArm("reddit_localllama_sysleak",
        'site:reddit.com/r/LocalLLaMA "system prompt" "leak" after:{date}'))
    pool.append(QueryArm("reddit_prompteng_inj",
        'site:reddit.com/r/PromptEngineering "injection" OR "jailbreak" after:{date}'))
    # arXiv
    pool.append(QueryArm("arxiv_prompt_injection",
        'site:arxiv.org "prompt injection" after:{date}'))
    pool.append(QueryArm("arxiv_jailbreak_llm",
        'site:arxiv.org "jailbreak" "LLM" after:{date}'))
    pool.append(QueryArm("arxiv_adversarial_lm",
        'site:arxiv.org "adversarial" "language model" after:{date}'))
    pool.append(QueryArm("arxiv_red_team_llm",
        'site:arxiv.org "red team" "LLM" after:{date}'))
    pool.append(QueryArm("arxiv_indirect_pi",
        'site:arxiv.org "indirect prompt injection" after:{date}'))
    pool.append(QueryArm("arxiv_pi_agent",
        'site:arxiv.org "prompt injection" "agent" after:{date}'))
    pool.append(QueryArm("arxiv_tool_exploit",
        'site:arxiv.org "tool use" "exploit" OR "abuse" after:{date}'))
    # GitHub
    pool.append(QueryArm("github_pi_trending",
        'site:github.com prompt-injection updated:>{date}'))
    pool.append(QueryArm("github_jb_vendor",
        'site:github.com jailbreak (GPT OR "ChatGPT" OR Claude OR Anthropic OR Gemini '
        'OR Mistral OR Mixtral OR Llama OR Qwen OR DeepSeek OR Gemma OR Falcon) '
        'updated:>{date}'))
    pool.append(QueryArm("github_llm_attacks",
        'site:github.com "llm-attacks" OR "llm-security" updated:>{date}'))
    pool.append(QueryArm("github_sysprompt_leak",
        'site:github.com "system prompt" leak updated:>{date}'))
    pool.append(QueryArm("github_pliny_umbrella",
        'site:github.com/elder-plinius updated:>{date}'))
    # Blogs
    pool.append(QueryArm("blog_simonw_pi",
        'site:simonwillison.net "prompt injection" after:{date}'))
    pool.append(QueryArm("blog_simonw_indirect",
        'site:simonwillison.net "indirect injection" after:{date}'))
    pool.append(QueryArm("blog_etr_after",
        'site:embracethered.com after:{date}'))
    pool.append(QueryArm("blog_etr_mcp_tool",
        'site:embracethered.com "MCP" OR "tool" OR "exfiltration"'))
    pool.append(QueryArm("blog_lakera_attack",
        'site:lakera.ai "attack" OR "jailbreak" after:{date}'))
    # MITRE / OWASP
    pool.append(QueryArm("mitre_atlas_after",
        'site:atlas.mitre.org after:{date}'))
    pool.append(QueryArm("mitre_atlas_t1_technique",
        '"MITRE ATLAS" "new technique" OR "T1" after:{date}'))
    pool.append(QueryArm("owasp_llm10_after",
        'site:genai.owasp.org after:{date}'))
    pool.append(QueryArm("owasp_llm10_2026",
        '"OWASP" "LLM Top 10" "2026" OR "update"'))
    # Vendor safety blogs
    pool.append(QueryArm("vendor_anthropic_news",
        'site:anthropic.com/news "safety" OR "red team" after:{date}'))
    pool.append(QueryArm("vendor_openai_blog",
        'site:openai.com/blog "safety" OR "red team" after:{date}'))
    pool.append(QueryArm("vendor_deepmind_blog",
        'site:deepmind.google "safety" OR "red team" after:{date}'))
    # HuggingFace + LeakHub + Promptfoo + Jailbreakchat
    pool.append(QueryArm("hf_jb_discussion",
        'site:huggingface.co "jailbreak" OR "system prompt" discussion after:{date}'))
    pool.append(QueryArm("hf_obliteratus_org",
        'site:huggingface.co/OBLITERATUS after:{date}'))
    pool.append(QueryArm("leakhub_after",
        'site:leakhub.ai after:{date}'))
    pool.append(QueryArm("promptfoo_discord",
        '"discord" "promptfoo" jailbreak after:{date}'))
    pool.append(QueryArm("jailbreakchat_dan",
        '"jailbreakchat" OR "jailbreakchat.com" "DAN" OR "Sigma" OR "AIM"'))
    # AJAR multi-turn framework discovery (added 2026-05-27 per §4.2 row 15
    # + §4.4 multi-turn-coverage paragraph). Specifically targets the three
    # canonical multi-turn frameworks named in §4.2 family #6/#15 — surfaces
    # the academic + practitioner literature where new variants get disclosed.
    pool.append(QueryArm("arxiv_actorattack",
        'site:arxiv.org "ActorAttack" OR "multi-turn persona" after:{date}'))
    pool.append(QueryArm("arxiv_xteaming",
        'site:arxiv.org "X-Teaming" OR "multi-turn adversarial" after:{date}'))
    pool.append(QueryArm("github_multiturn_jb",
        'site:github.com (Crescendo OR ActorAttack OR "X-Teaming") jailbreak updated:>{date}'))
    # Multimodal / vision-language / audio attack discovery (added 2026-06-03 per
    # the #1b harvest-modality-bias finding: the pre-existing pool had ZERO
    # multimodal-targeted queries, so vision/VLM/audio attack papers entered only
    # incidentally via generic "adversarial"/"jailbreak" terms. A 5-query SERP
    # probe surfaced 21 unique multimodal-attack arXiv papers, 0 of them harvested.
    # These arms close that vocabulary gap; they feed the existing classify→
    # render-gate path unchanged. Vocabulary chosen from the probe's productive
    # queries (see scripts/confirm_multimodal_gap.py).
    pool.append(QueryArm("arxiv_vlm_jailbreak",
        'site:arxiv.org "vision-language" jailbreak after:{date}'))
    pool.append(QueryArm("arxiv_multimodal_jailbreak",
        'site:arxiv.org multimodal jailbreak (LLM OR VLM) after:{date}'))
    pool.append(QueryArm("arxiv_crossmodal_attack",
        'site:arxiv.org "cross-modal" jailbreak OR attack after:{date}'))
    pool.append(QueryArm("arxiv_typographic_vlm",
        'site:arxiv.org typographic attack (VLM OR "vision language") after:{date}'))
    pool.append(QueryArm("arxiv_audio_jailbreak",
        'site:arxiv.org audio jailbreak "language model" after:{date}'))
    pool.append(QueryArm("github_multimodal_jb",
        'site:github.com (multimodal OR VLM OR "vision-language") jailbreak updated:>{date}'))
    return pool


# The arm_ids of the multimodal block above — the subset `harvest_once.py
# --multimodal-only` restricts the SERP phase to (added 2026-06-03, #1b finding).
# Kept next to the arms so the two never drift.
MULTIMODAL_ARM_IDS: frozenset[str] = frozenset({
    "arxiv_vlm_jailbreak",
    "arxiv_multimodal_jailbreak",
    "arxiv_crossmodal_attack",
    "arxiv_typographic_vlm",
    "arxiv_audio_jailbreak",
    "github_multimodal_jb",
})


# --------------------------------------------------------------------------- #
# Plugin registry — the 10 plugins (7 original + 3 new 2026-05-25)
# --------------------------------------------------------------------------- #


def default_plugins() -> list[SourcePlugin]:
    """Return one instance of each of the 8 active source plugins (defaults-only).

    The 8 cover most of the 19 §5.1 sources (several plugins fan out across
    multiple sources internally — e.g. :class:`BlogStaticPlugin` handles 7
    blogs, :class:`RedditSubredditPlugin` handles 4 subreddits + 5 keyword
    searches). Order is loosely "cheapest fetch first" so that if a daily run
    hits a hard budget cap halfway through, the most expensive Scraping-
    Browser-backed plugins are the ones we drop — not the SERP-backed
    cheap ones.

    **Disabled 2026-05-26** (re-enable by passing ``plugins=[...]`` explicitly
    to :class:`DiscoveryAgent` or amending this list):

      * :class:`XUserTimelinePlugin` — BD's X discover-by-profile-url scraper
        averages 5-15+ min per /trigger snapshot. Even 1 handle exceeded a
        15-min ceiling during 2026-05-26 smoke tests. Until a faster X path
        is found (Collect-by-URL on SERP-discovered tweets, or BD lifts the
        scraper timeout), X is dropped from the daily harvest to keep
        wall-clock under 30 min.
      * :class:`LeakHubScrapePlugin` — auth-injection over BD's CDP-attached
        Scraping Browser doesn't reliably honor either ``new_context(
        storage_state=...)`` or ``add_init_script`` for the Convex
        localStorage flow (verified 2026-05-26: page still renders "Sign
        in" nav with 15 chars of text). Pliny CL4R1T4S (Source #7) covers
        much of the same system-prompt-leak content via direct GitHub
        fetches (no auth needed). Re-enable once a working auth path is
        identified (Convex direct-API approach, or a Playwright-stealth
        fork that defeats Google's OAuth automation block).
    """
    return [
        # --- Direct-fetch plugins (no SERP cost) ---
        ArxivListingPlugin(),
        BlogStaticPlugin(),
        RedditSubredditPlugin(),
        # XUserTimelinePlugin(),  # disabled 2026-05-26 — see docstring
        HuggingFaceDiscussionPlugin(),
        ObliteratusHfPlugin(),  # NEW 2026-05-25 (§5.1 #10)
        # --- SERP-discovery plugins ---
        GithubSearchPlugin(),
        PlinyGithubPlugin(),  # NEW 2026-05-25 (§5.1 #7); CL4R1T4S path
                              # rebuilt 2026-05-26 to use GitHub tree API
                              # (was silently returning 0 via the broken
                              # tree-page scrape).
        # --- Scraping Browser plugins (most expensive — run last) ---
        # LeakHubScrapePlugin(),  # disabled 2026-05-26 — see docstring
        CommunityArchivePlugin(),
    ]


# --------------------------------------------------------------------------- #
# Per-plugin run report (telemetry for the dashboard's freshness panel)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PluginRunReport:
    """Per-plugin outcome of one ``DiscoveryAgent.run`` invocation.

    Aggregated into ``DiscoveryAgent.last_run_reports`` so the dashboard
    freshness panel + Day-1 morning gate can render per-source status
    without re-parsing the docs list.

    Fields:

      * ``error`` — set when the plugin's ``fetch_since`` raised at the
        top level (anything other than :class:`NotImplementedError`, which
        is re-raised loudly so the Day-0 stubs still surface).
      * ``call_errors`` — per-call errors INSIDE ``fetch_since`` that the
        plugin caught + logged (e.g. one BD API call out of 12 timed out
        but the other 11 succeeded). Sourced from
        ``plugin.call_errors`` if the plugin maintains that list — fixes
        the 2026-05-26 "silent zero source" anti-pattern where
        ``except Exception: continue`` made every BD failure invisible.
    """

    plugin_name: str
    source_type: str
    bright_data_product: str
    n_docs: int
    error: Optional[str] = None
    call_errors: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# DiscoveryAgent
# --------------------------------------------------------------------------- #


QueryPicker = Callable[[datetime], list[str]]


class DiscoveryAgent:
    """Orchestrates the harvest layer.

    Day-1 behavior:
      1. Substitute ``{date}`` in each of the 10 hand-tuned queries.
      2. Fan out across every registered plugin's ``fetch_since(client, since)``
         via :func:`asyncio.gather`, isolating per-plugin failures.
      3. Return the flat ``list[RawDocument]`` for the extraction layer.
      4. Stash per-plugin reports on ``last_run_reports`` for telemetry.

    Day-2-evening upgrade (§11.6, wired 2026-05-26 PM): when a ``bandit``
    instance is passed at construction, ``run()`` calls
    ``bandit.select(k=10)`` to pick today's SERP queries and ``bandit.record()``
    to credit each arm with the post-dedup novel-primitive count. The bandit's
    state is persisted across runs by the caller (typically ``harvest_once.py``
    via ``bandit.to_disk(...)``); this class stays persistence-free.
    """

    def __init__(
        self,
        client: BrightDataClient,
        plugins: Iterable[SourcePlugin] | None = None,
        query_picker: QueryPicker | None = None,
        bandit: "EpsilonGreedyBandit | None" = None,  # noqa: UP037 - forward ref
        follow_links: bool = True,
    ) -> None:
        self.client = client
        self.plugins: list[SourcePlugin] = (
            list(plugins) if plugins is not None else default_plugins()
        )
        self.query_picker: QueryPicker = query_picker or self._day1_query_picker
        self.bandit = bandit  # if set, takes precedence over query_picker
        # Feature C: follow outbound links from post docs 1-hop (default on;
        # bounded by the phase's per-doc/total caps). Harvest_once flips it off
        # via HARVEST_FOLLOW_LINKS=0.
        self.follow_links = follow_links
        self.last_run_reports: list[PluginRunReport] = []
        # The most-recent select() result, exposed for the harvest script's
        # reward attribution call. Tuple of (arm_id, substituted_query).
        self.last_selected_arms: list[tuple[str, str]] = []
        # Per-arm BD spend from the §11.6 (c-serp) bandit-driven SERP phase.
        # {arm_id: serp_cost + per-fetched-URL unlocker cost}. Empty when no
        # bandit is wired OR no arms were picked OR the phase was skipped.
        # Consumed by ``scripts/harvest_once.py`` to pass real per-arm cost
        # to ``bandit.record(...)``.
        self.last_serp_phase_cost: dict[str, float] = {}
        self.last_serp_phase_errors: dict[str, list[str]] = {}
        # Feature C post→link-follow telemetry (mirrors the SERP-phase fields).
        self.last_link_follow_count: int = 0
        self.last_link_follow_cost: float = 0.0
        self.last_link_follow_errors: list[str] = []

    # ------------------------------------------------------------------
    # Query selection
    # ------------------------------------------------------------------

    @staticmethod
    def _day1_query_picker(since: datetime) -> list[str]:
        """Substitute ``{date}`` in the hand-tuned 10-query set (Day-1 default)."""
        # `since - 1 day` mirrors the per-plugin convention so SERP `after:`
        # bounds align with the per-plugin fetch_since window.
        from datetime import timedelta

        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [q.replace("{date}", date_str) for q in DAY1_HANDPICKED_QUERIES]

    def serp_queries(self, since: datetime) -> list[str]:
        """Return the queries this agent will issue today.

        Day 1: the hand-tuned 10-query set with ``{date}`` substituted.
        Day 2 evening: when a ``bandit`` is wired, ε-greedy ``select(k=10)``
        chooses 10 arms from the §5.2 query pool; otherwise we fall back to
        the hand-tuned set.
        """
        if self.bandit is not None:
            from datetime import timedelta as _td
            date_str = (since - _td(days=1)).strftime("%Y-%m-%d")
            picked = self.bandit.select(k=10)
            self.last_selected_arms = [
                (arm.arm_id, arm.query.replace("{date}", date_str))
                for arm in picked
            ]
            return [q for _, q in self.last_selected_arms]
        self.last_selected_arms = []
        return list(self.query_picker(since))

    # ------------------------------------------------------------------
    # Main harvest entry point
    # ------------------------------------------------------------------

    async def run(
        self, since: datetime, prefetched_urls: set[str] | None = None
    ) -> list[RawDocument]:
        """Run every registered plugin's ``fetch_since`` concurrently, then
        run the §11.6 (c-serp) bandit-driven SERP discovery phase if a bandit
        is wired.

        Per-plugin exceptions are caught + logged into ``last_run_reports``;
        the run never aborts on a single bad source (§9.3 source-level
        failure handling, ``No source blocks the pipeline``).

        The bandit SERP phase (when active) runs AFTER plugins so it can dedup
        its SERP-returned URLs against URLs the plugins already fetched —
        avoids paying Web Unlocker twice for the same content. SERP-phase
        RawDocuments are appended to the returned list with
        ``discovered_via=f"serp_arm:{arm_id}"`` tags so the per-arm
        attribution downstream can credit them causally.
        """
        # Materialize the picked queries on this run. Populates
        # ``self.last_selected_arms`` so the SERP phase + post-harvest
        # attribution can read them.
        _picked = self.serp_queries(since)

        coros = [self._safe_fetch(plugin, since) for plugin in self.plugins]
        results = await asyncio.gather(*coros)

        flat_docs: list[RawDocument] = []
        reports: list[PluginRunReport] = []
        for plugin, (docs, err) in zip(self.plugins, results, strict=True):
            flat_docs.extend(docs)
            # Pull per-call errors if the plugin maintains them (the new
            # error-visibility contract, 2026-05-26). Snapshot defensively.
            raw_call_errors = getattr(plugin, "call_errors", None) or ()
            call_errors = tuple(str(e) for e in raw_call_errors)
            reports.append(
                PluginRunReport(
                    plugin_name=plugin.name,
                    source_type=str(plugin.source_type),
                    bright_data_product=str(plugin.bright_data_product),
                    n_docs=len(docs),
                    error=err,
                    call_errors=call_errors,
                )
            )
        self.last_run_reports = reports

        # Snapshot the plugin/post docs BEFORE the discovery phases append to
        # `flat_docs`. The link-follow phase mines ONLY these (1-hop: never the
        # SERP phase's or its own fetched pages).
        plugin_docs = list(flat_docs)

        # --- §11.6 (c-serp) bandit-driven SERP discovery phase ---
        # Only fires when (a) a bandit is wired AND (b) select() actually
        # picked arms. URL dedup against plugin output prevents double-paying
        # for content the plugins already covered. Phase failures don't
        # abort the run — `last_serp_phase_errors` records what went wrong.
        self.last_serp_phase_cost = {}
        self.last_serp_phase_errors = {}
        if self.bandit is not None and self.last_selected_arms:
            from rogue.harvest.bandit_serp_phase import run_bandit_serp_phase

            # §11.7 Tier B — seed the SERP-phase skip set with BOTH this run's
            # plugin URLs (intra-run dedup, as before) AND the persistent
            # fetch_cache URLs (cross-run, passed in by harvest_once) so we
            # don't re-Web-Unlock a URL we already fetched on a prior day. Same
            # pure-URL skip semantics the SERP phase already uses intra-run,
            # extended across runs.
            plugin_urls = {str(d.url) for d in flat_docs}
            serp_seen = plugin_urls | (prefetched_urls or set())
            try:
                phase = await run_bandit_serp_phase(
                    client=self.client,
                    picked_arms=self.last_selected_arms,
                    seen_urls=serp_seen,
                )
                flat_docs.extend(phase.docs)
                self.last_serp_phase_cost = phase.per_arm_cost
                self.last_serp_phase_errors = phase.per_arm_errors
            except Exception as exc:  # noqa: BLE001 — phase failure must not abort harvest
                logger.warning(
                    "bandit SERP phase failed (%s) — proceeding with plugin docs only",
                    exc,
                )

        # --- Feature C: post→link following phase ---
        # Follows outbound links from the post docs 1-hop (e.g. an X post →
        # the GitHub repo it links to). Deduped against EVERYTHING already in
        # the pipeline (plugin docs + SERP docs + cross-run fetch_cache) so it
        # never re-fetches known content. Bounded by the phase's caps; failure
        # is logged, never fatal.
        self.last_link_follow_count = 0
        self.last_link_follow_cost = 0.0
        self.last_link_follow_errors = []
        if self.follow_links and plugin_docs:
            from rogue.harvest.link_follow_phase import run_link_follow_phase

            link_seen = {str(d.url) for d in flat_docs} | (prefetched_urls or set())
            try:
                lf = await run_link_follow_phase(
                    client=self.client,
                    source_docs=plugin_docs,
                    seen_urls=link_seen,
                )
                flat_docs.extend(lf.docs)
                self.last_link_follow_count = lf.followed
                self.last_link_follow_cost = lf.cost_usd
                self.last_link_follow_errors = lf.errors
            except Exception as exc:  # noqa: BLE001 — link-follow must not abort harvest
                logger.warning(
                    "post→link follow phase failed (%s) — proceeding without it",
                    exc,
                )

        return flat_docs

    async def _safe_fetch(
        self,
        plugin: SourcePlugin,
        since: datetime,
    ) -> tuple[list[RawDocument], Optional[str]]:
        """Run one plugin's ``fetch_since``; convert any non-stub exception
        into ``(<empty>, error_str)`` so :meth:`run` can keep going."""
        try:
            docs = await plugin.fetch_since(self.client, since)
        except NotImplementedError:
            # Day-0 stubs still surface loudly — never silently swallow.
            raise
        except Exception as exc:
            return ([], f"{type(exc).__name__}: {exc}")
        return (list(docs), None)
