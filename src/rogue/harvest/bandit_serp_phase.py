"""Bandit-driven SERP discovery phase (§11.6 (c-serp), 2026-05-27).

Closes the causal-attribution gap left by (c-runtime). After
:meth:`DiscoveryAgent.run` collects RawDocuments from the 8 plugins, this
module runs the bandit's 10 picked SERP queries via :meth:`Fetcher.serp`,
dedupes the returned URLs against what plugins already produced, fetches
the new URLs via :meth:`Fetcher.unlock`, and emits them as additional
RawDocuments tagged ``discovered_via=f"serp_arm:{arm_id}"``.

Net effect: the bandit becomes a *discovery controller* whose picks drive
which extra URLs enter the pipeline, not just a telemetry sidecar that gets
post-hoc credit for whatever plugins happened to fetch.

Per-arm cost is tracked precisely: one SERP call + one Web Unlocker fetch per
non-deduped URL. The harvest orchestrator passes this real cost to
``bandit.record(...)`` so ``mean_yield = novel / cost_usd`` reflects actual
BD spend per arm, not the prior flat $0.0015 estimate.

Exception isolation is per-arm: a SERP timeout on one arm doesn't block the
others; a Web Unlocker failure on one URL doesn't kill the whole arm. All
failures land in a per-arm error list returned alongside the docs+cost so
the dashboard can surface "arm X had 3/10 URL failures" if useful later.

SERP bandit cost caveat (spec §SERP-bandit-caveat):
  The ε-greedy bandit optimises novel-attacks-per-dollar of SERP spend.
  A free SERP backend (DDG etc.) has cost≈0, making that ratio undefined.
  When the active SERP backend is NOT ``brightdata``, bandit cost-tracking is
  bypassed: all arms run (no spend-weighted selection pruning), and
  ``per_arm_cost`` is zeroed so the caller does NOT feed cost≈0 into the
  bandit's reward math. Pass the :class:`~rogue.harvest.fetchers.FetcherRegistry`
  as ``registry`` to enable this detection; omit it (or pass ``None``) if cost
  tracking is explicitly not needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from typing import TYPE_CHECKING

from rogue.harvest.fetchers.base import Fetcher
from rogue.harvest.fetchers.capabilities import Capability
from rogue.schemas.raw_document import RawDocument

if TYPE_CHECKING:
    from rogue.harvest.fetchers.registry import FetcherRegistry

__all__ = [
    "BanditSerpPhaseResult",
    "run_bandit_serp_phase",
]

logger = logging.getLogger(__name__)


# Per-§6.1 BD pricing
_SERP_COST_PER_CALL = 0.0015
_UNLOCKER_COST_PER_PAGE = 0.0025

# Bound on URLs per arm to keep per-harvest spend predictable. 10 matches the
# `serp_search(count=10)` default; tunable via `max_urls_per_arm` kwarg.
DEFAULT_MAX_URLS_PER_ARM = 10

# Bound on wall-clock per arm so a slow SERP can't stall the whole phase. A
# pathological arm dropped here just gets `pulls += 1, novel = 0` later; the
# bandit will deprioritize it.
DEFAULT_ARM_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class BanditSerpPhaseResult:
    """What the phase produces — consumed by DiscoveryAgent.run + harvest_once."""

    docs: list[RawDocument]
    """RawDocuments emitted by the phase, tagged with discovered_via=serp_arm:{id}."""

    per_arm_cost: dict[str, float]
    """{arm_id: total BD spend attributed to this arm (serp + per-URL fetches)}.

    Includes the SERP call cost even for arms that returned 0 new URLs — so
    arms get debited for the discovery query even if dedup killed all
    follow-ons. The bandit.record() loop uses this verbatim.
    """

    per_arm_errors: dict[str, list[str]] = field(default_factory=dict)
    """{arm_id: ["serp_failed: ...", "fetch_failed: ..."]} for observability."""


def _serp_is_brightdata(registry: "FetcherRegistry | None") -> bool:
    """True iff the active SERP backend is the Bright Data backend.

    When ``registry`` is absent or no SERP backend is registered, returns
    ``False`` (unknown/free path → skip bandit cost tracking to be safe).
    """
    if registry is None:
        return False
    serp_backend = registry.for_capability(Capability.SERP)
    return serp_backend is not None and serp_backend.name == "brightdata"


async def run_bandit_serp_phase(
    fetcher: Fetcher,
    picked_arms: list[tuple[str, str]],
    *,
    registry: "FetcherRegistry | None" = None,
    seen_urls: set[str] | None = None,
    max_urls_per_arm: int = DEFAULT_MAX_URLS_PER_ARM,
    arm_timeout_s: float = DEFAULT_ARM_TIMEOUT_S,
) -> BanditSerpPhaseResult:
    """For each picked arm, SERP-search → URL dedup → unlock fetch.

    Args:
        fetcher: a :class:`~rogue.harvest.fetchers.base.Fetcher` (typically a
            :class:`~rogue.harvest.fetchers.routing.RoutingFetcher`); uses
            :meth:`Fetcher.serp` and :meth:`Fetcher.unlock`.
        picked_arms: ``[(arm_id, substituted_query), ...]`` — typically
            ``agent.last_selected_arms`` after :meth:`DiscoveryAgent.serp_queries`
            populates it.
        registry: the :class:`~rogue.harvest.fetchers.registry.FetcherRegistry` in
            use. Used to detect whether the active SERP backend is Bright Data —
            only then does cost-tracking engage (per SERP bandit caveat). Pass
            ``None`` to unconditionally skip cost tracking (free-backend or test path).
        seen_urls: URLs to skip (don't fetch). Caller pre-populates with URLs
            the plugin phase has already produced so we don't double-spend on
            content the plugins covered. ``None`` means "skip nothing."
        max_urls_per_arm: cap on per-arm fetches so a noisy SERP can't blow
            the budget. Default 10.
        arm_timeout_s: wall-clock cap per arm. Slow SERPs get dropped; the arm
            is debited the SERP cost only (no fetches happened).

    Returns:
        :class:`BanditSerpPhaseResult` — never raises. Per-arm failures land
        in ``per_arm_errors`` so harvest_once can log them without aborting.
        When the SERP backend is not Bright Data, ``per_arm_cost`` values are
        all ``0.0`` so the caller must NOT feed them into the bandit's reward math.

    Empty ``picked_arms`` is a fast no-op: returns empty result, makes zero
    network calls.
    """
    if not picked_arms:
        return BanditSerpPhaseResult(docs=[], per_arm_cost={})

    # SERP bandit cost caveat: only engage cost-tracking when BD is the SERP
    # backend. A free backend (DDG etc.) has cost≈0, making yield-per-dollar
    # undefined. When not BD, log once and run all queries without spend tracking.
    use_cost_tracking = _serp_is_brightdata(registry)
    if not use_cost_tracking:
        logger.info(
            "bandit_serp_phase: SERP backend is not brightdata (or registry absent) — "
            "cost tracking disabled; running all %d arms without spend-weighted pruning",
            len(picked_arms),
        )

    seen: set[str] = set(seen_urls) if seen_urls is not None else set()

    # Run all arms concurrently. Per-arm timeouts prevent a single hung arm
    # from holding the entire phase.
    coros = [
        _run_one_arm(
            fetcher=fetcher,
            arm_id=arm_id,
            query=query,
            seen_urls=seen,
            max_urls=max_urls_per_arm,
            timeout_s=arm_timeout_s,
        )
        for arm_id, query in picked_arms
    ]
    per_arm_results = await asyncio.gather(*coros, return_exceptions=False)

    all_docs: list[RawDocument] = []
    per_arm_cost: dict[str, float] = {}
    per_arm_errors: dict[str, list[str]] = {}
    for arm_id, docs, cost, errors in per_arm_results:
        all_docs.extend(docs)
        # Zero out cost when not on the BD path so callers can't accidentally
        # feed it into the bandit (cost≈0 makes yield-per-dollar meaningless).
        per_arm_cost[arm_id] = cost if use_cost_tracking else 0.0
        if errors:
            per_arm_errors[arm_id] = errors

    logger.info(
        "bandit_serp_phase: %d arms ran, %d total RawDocuments, $%.4f total spend%s",
        len(picked_arms),
        len(all_docs),
        sum(per_arm_cost.values()),
        "" if use_cost_tracking else " (cost zeroed — free SERP backend)",
    )
    return BanditSerpPhaseResult(
        docs=all_docs,
        per_arm_cost=per_arm_cost,
        per_arm_errors=per_arm_errors,
    )


async def _run_one_arm(
    *,
    fetcher: Fetcher,
    arm_id: str,
    query: str,
    seen_urls: set[str],
    max_urls: int,
    timeout_s: float,
) -> tuple[str, list[RawDocument], float, list[str]]:
    """Run SERP + fetches for one arm. Returns (arm_id, docs, cost, errors).

    Mutates ``seen_urls`` (adds URLs we fetched) so a later arm in the same
    batch can't re-fetch the same URL. Conceptually a small race — two arms
    could pick the same URL concurrently — but the dedup engine downstream
    catches duplicate primitives, so the worst case is one wasted fetch.
    """
    errors: list[str] = []
    cost = _SERP_COST_PER_CALL  # debit the SERP regardless of outcome

    try:
        serp = await asyncio.wait_for(
            fetcher.serp(query, count=max_urls),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        errors.append(f"serp_timeout: {timeout_s}s")
        return (arm_id, [], cost, errors)
    except Exception as exc:  # noqa: BLE001 — never let one arm kill the phase
        errors.append(f"serp_failed: {type(exc).__name__}: {exc}")
        return (arm_id, [], cost, errors)

    # Pull URLs out of organic_results. SerpResponse uses BD's parsed_light
    # shape — field is usually `link` but some engines emit `url`/`href`.
    # Mirrors github_search.py's existing tolerant extraction.
    candidate_urls: list[str] = []
    for result in serp.organic_results or []:
        link = (
            result.get("link")
            or result.get("url")
            or result.get("href")
            or ""
        )
        if not link or not link.startswith(("http://", "https://")):
            continue
        if link in seen_urls:
            continue
        candidate_urls.append(link)
        seen_urls.add(link)
        if len(candidate_urls) >= max_urls:
            break

    if not candidate_urls:
        return (arm_id, [], cost, errors)

    # Fetch each candidate via unlock. Per-URL failures stay isolated;
    # the arm still gets credit for the URLs that DID land.
    docs: list[RawDocument] = []
    for url in candidate_urls:
        try:
            page = await fetcher.unlock(url, format="markdown")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"fetch_failed {url}: {type(exc).__name__}: {exc}")
            continue
        cost += _UNLOCKER_COST_PER_PAGE
        try:
            doc = _page_to_raw_document(page=page, url=url, arm_id=arm_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"raw_doc_build_failed {url}: {type(exc).__name__}: {exc}")
            continue
        docs.append(doc)

    return (arm_id, docs, cost, errors)


def _page_to_raw_document(
    *,
    page,  # UnlockedPage; typed loosely to avoid an import cycle in tests
    url: str,
    arm_id: str,
) -> RawDocument:
    """Convert one Web Unlocker response to a RawDocument tagged with arm_id.

    The `source_type` is set to "blog" as a conservative default — the
    extraction LLM doesn't depend on this beyond the prompt context, and the
    extracted AttackPrimitive's SourceProvenance carries the more precise
    `bright_data_product=web_unlocker` field. Future improvement: infer
    source_type from the URL domain (reddit.com → "reddit", arxiv.org →
    "arxiv", github.com → "github", else "blog").
    """
    raw = page.content or ""
    archive_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return RawDocument(
        url=url,
        source_type=_infer_source_type(url),
        bright_data_product="web_unlocker",
        fetched_at=page.fetched_at or datetime.now(timezone.utc),
        raw_content=raw,
        content_format=page.content_format,
        archive_hash=archive_hash,
        http_status=page.status_code,
        metadata={"bandit_arm_id": arm_id},
        discovered_via=f"serp_arm:{arm_id}",
    )


# URL → SourceType heuristic. Conservative — the extraction LLM tolerates a
# wrong label here (it has its own classification logic). The vocabulary
# tracks rogue.schemas.SourceType.
def _infer_source_type(url: str) -> str:
    lo = url.lower()
    if "arxiv.org" in lo:
        return "arxiv"
    # github.com + raw.githubusercontent.com + *.github.io project/user pages
    # (the post→link follower's canonical example, giovannigatti.github.io).
    if "github.com" in lo or "githubusercontent.com" in lo or "github.io" in lo:
        return "github"
    if "reddit.com" in lo:
        return "reddit"
    if "huggingface.co" in lo:
        return "huggingface"
    if "x.com" in lo or "twitter.com" in lo:
        return "x"
    if "atlas.mitre.org" in lo:
        return "mitre"
    if "genai.owasp.org" in lo or "owasp.org" in lo:
        return "owasp"
    return "blog"
