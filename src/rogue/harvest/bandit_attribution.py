"""URL → bandit-arm attribution helpers (shared by seed script + live harvest).

Per ROGUE_PLAN.md §11.6, the bandit arms are SERP query templates like
``site:reddit.com/r/GPT_jailbreaks "new method" after:{date}``. This module
maps a CONCRETE URL (e.g. ``https://www.reddit.com/r/GPT_jailbreaks/comments/...``)
back to the arm(s) whose query template could have surfaced it via the
``site:DOMAIN/path`` operator.

Two callers use these helpers:

  * ``scripts/harvest/seed_bandit_from_corpus.py`` — one-shot offline attribution
    over the full corpus to bootstrap a warm-prior bandit state.
  * ``scripts/harvest/harvest_once.py`` — per-harvest attribution of THIS RUN's
    newly-canonical primitives to the arms picked by ``bandit.select(k=10)``.

Both share the same matching logic so seed and live-pull state are mutually
consistent — the seed's per-arm yields are extended (not replaced) by each
live harvest's incremental attribution.

**Most-specific-wins**: a URL like ``github.com/elder-plinius/L1B3RT4S/META.mkd``
matches both ``site:github.com`` (generic) and ``site:github.com/elder-plinius``
(specific). We attribute ONLY to arms tied on the LONGEST matching pattern
— mirrors how a real SERP would route that URL to the targeted Pliny query,
not the generic GitHub-prompt-injection query (which would also require a
keyword filter we don't track here). Ties (arms with the same site pattern
but different keyword filters) all get credit.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from rogue.harvest.bandit import QueryArm

__all__ = [
    "extract_site_pattern",
    "normalize_url_for_matching",
    "url_matches_arm",
    "build_arm_pattern_map",
    "attribute_urls_to_arms",
]


# Match `site:DOMAIN[/PATH]` from a SERP query template. Captures the
# domain+path token up to the next whitespace.
_SITE_OPERATOR_RE = re.compile(r"site:(\S+)")

# raw.githubusercontent.com/USER/REPO/BRANCH/PATH → github.com/USER/REPO/PATH
# Used to fold post-fetch raw-content URLs back to the discoverable github.com
# form, since the Pliny plugin rewrites blob URLs to raw URLs for content
# fetch but the bandit arm queries use `site:github.com/elder-plinius`.
_RAW_GITHUB_RE = re.compile(
    r"^raw\.githubusercontent\.com/([^/]+)/([^/]+)/[^/]+/(.*)$"
)


def extract_site_pattern(query: str) -> str | None:
    """Return the ``site:DOMAIN/path`` operator value as a normalized prefix.

    Returns ``None`` when the query has no ``site:`` operator (pure keyword
    queries like ``"OWASP" "LLM Top 10" "2026"`` — those arms can't be
    URL-attributed and stay cold until the bandit picks them).

    Examples:
        >>> extract_site_pattern('site:reddit.com/r/GPT_jailbreaks "x" after:{date}')
        'reddit.com/r/gpt_jailbreaks'
        >>> extract_site_pattern('site:arxiv.org "jailbreak" after:{date}')
        'arxiv.org'
        >>> extract_site_pattern('"OWASP" "LLM Top 10"') is None
        True
    """
    m = _SITE_OPERATOR_RE.search(query)
    if not m:
        return None
    return m.group(1).rstrip("/").lower()


def normalize_url_for_matching(url: str) -> str:
    """Strip scheme + www, fold raw.githubusercontent.com → github.com/USER/REPO.

    Pliny URLs are stored as raw.githubusercontent.com paths (because the
    Pliny plugin rewrites GitHub blob URLs to raw URLs for content fetch).
    The bandit arm ``site:github.com/elder-plinius`` would have surfaced
    those originally via the regular github.com URL. To match them, we
    rewrite the raw URL back to the github.com form.
    """
    u = url.lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    m = _RAW_GITHUB_RE.match(u)
    if m:
        user, repo, rest = m.group(1), m.group(2), m.group(3)
        u = f"github.com/{user}/{repo}/{rest}"
    return u


def url_matches_arm(normalized_url: str, site_pattern: str) -> bool:
    """True when the normalized URL begins with the arm's site pattern."""
    return normalized_url.startswith(site_pattern)


def build_arm_pattern_map(arms: Iterable[QueryArm]) -> dict[str, str]:
    """Return ``{arm_id: site_pattern}`` for every arm with a ``site:`` operator.

    Arms whose query has no ``site:`` operator (pure keyword queries) are
    DROPPED from the map — they can't be URL-attributed. Callers handle
    those as the "always-cold" pool that depends on `select()` cold-start
    preference for any pulls.
    """
    out: dict[str, str] = {}
    for arm in arms:
        pattern = extract_site_pattern(arm.query)
        if pattern is not None:
            out[arm.arm_id] = pattern
    return out


def attribute_urls_to_arms(
    urls: Iterable[str],
    arm_id_to_pattern: dict[str, str],
    *,
    restrict_to_arms: set[str] | None = None,
) -> dict[str, int]:
    """Return ``{arm_id: count}`` of URLs whose pattern is the most-specific match.

    Args:
        urls: iterable of source URLs (one per attributable observation).
            Duplicates are NOT deduplicated — pass an already-deduplicated
            iterable if you want one count per primitive.
        arm_id_to_pattern: output of :func:`build_arm_pattern_map`.
        restrict_to_arms: if given, only arms in this set are eligible for
            attribution. This is the live-harvest path's "credit only picked
            arms" semantics: an arm that wasn't selected by ``bandit.select()``
            this run gets no credit even if its pattern matches today's URLs.
            ``None`` means "all arms eligible" (the seed-script path).

    For each URL, find every matching arm pattern, then credit ONLY arms
    tied on the longest pattern length. URLs with no matching arm are
    silently ignored.
    """
    counts: dict[str, int] = defaultdict(int)
    eligible_patterns = (
        {aid: p for aid, p in arm_id_to_pattern.items() if aid in restrict_to_arms}
        if restrict_to_arms is not None
        else arm_id_to_pattern
    )
    for url in urls:
        normalized = normalize_url_for_matching(url)
        matches: list[tuple[str, int]] = [
            (arm_id, len(pattern))
            for arm_id, pattern in eligible_patterns.items()
            if url_matches_arm(normalized, pattern)
        ]
        if not matches:
            continue
        max_len = max(length for _, length in matches)
        for arm_id, length in matches:
            if length == max_len:
                counts[arm_id] += 1
    return dict(counts)
