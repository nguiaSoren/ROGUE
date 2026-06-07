"""Tests for `rogue.harvest.bandit_attribution`.

The (c-full) per-arm attribution shipped 2026-05-27 replaces the prior
even-split heuristic in `scripts/harvest/harvest_once.py`. These tests lock the
behavior so it can't silently regress:

  * Most-specific-wins: a Pliny URL routes to `github_pliny_umbrella` (specific)
    rather than the generic `github_pi_trending` (which also matches `github.com`).
  * Tie semantics: arms with the *same* site pattern (e.g. `reddit_gptjb_new_method`
    and `reddit_gptjb_after` both at `site:reddit.com/r/GPT_jailbreaks`) both get credit.
  * `restrict_to_arms`: only picked arms can receive credit; an unpicked arm with
    a matching URL gets nothing (preserves bandit "I picked, this is what they
    returned" semantics).
  * Picked-but-no-match arms: omitted from the count dict (caller defaults to 0
    when calling `bandit.record`).
  * URL normalization: `raw.githubusercontent.com/USER/REPO/...` folds to
    `github.com/USER/REPO/...` for pattern matching.
  * Cold (no-`site:`) arms: dropped from the pattern map; never receive credit.
"""

from __future__ import annotations

from rogue.harvest.bandit import QueryArm
from rogue.harvest.bandit_attribution import (
    attribute_urls_to_arms,
    build_arm_pattern_map,
    extract_site_pattern,
    normalize_url_for_matching,
    url_matches_arm,
)


# ---------------------------------------------------------------------------
# extract_site_pattern
# ---------------------------------------------------------------------------


def test_extract_site_pattern_basic() -> None:
    assert (
        extract_site_pattern('site:reddit.com/r/GPT_jailbreaks "x" after:{date}')
        == "reddit.com/r/gpt_jailbreaks"
    )


def test_extract_site_pattern_lowercased_and_no_trailing_slash() -> None:
    assert extract_site_pattern("site:Arxiv.Org/ after:2026-05-01") == "arxiv.org"


def test_extract_site_pattern_none_when_no_site_operator() -> None:
    assert extract_site_pattern('"OWASP" "LLM Top 10" "2026"') is None


def test_extract_site_pattern_picks_first_operator_if_multiple() -> None:
    # Pathological — two site: operators. We take the first.
    got = extract_site_pattern("site:foo.com site:bar.com")
    assert got == "foo.com"


# ---------------------------------------------------------------------------
# normalize_url_for_matching
# ---------------------------------------------------------------------------


def test_normalize_strips_scheme_and_www() -> None:
    assert (
        normalize_url_for_matching("https://www.reddit.com/r/x/comments/abc")
        == "reddit.com/r/x/comments/abc"
    )


def test_normalize_folds_raw_githubusercontent_to_github() -> None:
    # Pliny raw URL → discoverable github.com form so the
    # `site:github.com/elder-plinius` arm matches it.
    assert (
        normalize_url_for_matching(
            "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/META.mkd"
        )
        == "github.com/elder-plinius/l1b3rt4s/meta.mkd"
    )


def test_normalize_leaves_non_raw_github_untouched() -> None:
    # `gist.githubusercontent.com` is a different host; should NOT be folded.
    got = normalize_url_for_matching(
        "https://gist.githubusercontent.com/someone/abc/raw/file.txt"
    )
    assert got.startswith("gist.githubusercontent.com/")


# ---------------------------------------------------------------------------
# url_matches_arm
# ---------------------------------------------------------------------------


def test_url_matches_arm_prefix_match() -> None:
    assert url_matches_arm("reddit.com/r/gpt_jailbreaks/comments/x", "reddit.com/r/gpt_jailbreaks")


def test_url_matches_arm_no_match_on_different_subreddit() -> None:
    assert not url_matches_arm(
        "reddit.com/r/claudeaijailbreak/comments/x", "reddit.com/r/gpt_jailbreaks"
    )


# ---------------------------------------------------------------------------
# build_arm_pattern_map
# ---------------------------------------------------------------------------


def test_build_arm_pattern_map_drops_no_site_arms() -> None:
    arms = [
        QueryArm(arm_id="has_site", query="site:reddit.com/r/X after:{date}"),
        QueryArm(arm_id="no_site", query='"OWASP" "LLM Top 10"'),
    ]
    got = build_arm_pattern_map(arms)
    assert "has_site" in got
    assert "no_site" not in got
    assert got["has_site"] == "reddit.com/r/x"


# ---------------------------------------------------------------------------
# attribute_urls_to_arms — most-specific-wins
# ---------------------------------------------------------------------------


def _build_test_arms() -> dict[str, str]:
    """Realistic miniature arm pool covering the most-specific-wins case."""
    return build_arm_pattern_map(
        [
            # Generic + specific GitHub arms (same root, different specificity)
            QueryArm(arm_id="github_pliny_umbrella", query="site:github.com/elder-plinius updated:>{date}"),
            QueryArm(arm_id="github_pi_trending", query="site:github.com prompt-injection updated:>{date}"),
            QueryArm(arm_id="github_jb_vendor", query="site:github.com jailbreak GPT updated:>{date}"),
            # Tied arms (same site path, different keywords)
            QueryArm(arm_id="reddit_gptjb_new_method", query='site:reddit.com/r/GPT_jailbreaks "new method" after:{date}'),
            QueryArm(arm_id="reddit_gptjb_after", query="site:reddit.com/r/GPT_jailbreaks after:{date}"),
            # Unrelated arm — should never match
            QueryArm(arm_id="arxiv_pi", query='site:arxiv.org "prompt injection" after:{date}'),
        ]
    )


def test_most_specific_wins_pliny_url_routes_to_pliny_arm() -> None:
    arms = _build_test_arms()
    pliny_url = "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/META.mkd"

    got = attribute_urls_to_arms([pliny_url], arms)

    # github.com/elder-plinius (longest match) wins; generic github.com arms get nothing.
    assert got == {"github_pliny_umbrella": 1}


def test_tied_arms_both_get_credit() -> None:
    arms = _build_test_arms()
    # A reddit URL in r/GPT_jailbreaks matches BOTH gptjb arms (same site pattern)
    reddit_url = "https://www.reddit.com/r/GPT_jailbreaks/comments/x"

    got = attribute_urls_to_arms([reddit_url], arms)

    assert got == {"reddit_gptjb_new_method": 1, "reddit_gptjb_after": 1}


def test_url_with_no_matching_arm_silently_dropped() -> None:
    arms = _build_test_arms()
    # leakhub.ai isn't in our test arm pool
    got = attribute_urls_to_arms(["https://leakhub.ai/prompts/openai"], arms)
    assert got == {}


def test_multiple_urls_accumulate_counts() -> None:
    arms = _build_test_arms()
    urls = [
        "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/A.mkd",
        "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/B.mkd",
        "https://raw.githubusercontent.com/elder-plinius/CL4R1T4S/main/C.md",
    ]
    got = attribute_urls_to_arms(urls, arms)
    assert got == {"github_pliny_umbrella": 3}


# ---------------------------------------------------------------------------
# attribute_urls_to_arms — restrict_to_arms (live-harvest "credit picked only")
# ---------------------------------------------------------------------------


def test_restrict_to_arms_excludes_unpicked_matching_arms() -> None:
    """An unpicked arm with a matching URL gets NO credit — bandit only learns
    from arms it actually selected this run."""
    arms = _build_test_arms()
    pliny_url = "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/META.mkd"

    # github_pliny_umbrella was NOT picked this run
    got = attribute_urls_to_arms(
        [pliny_url], arms, restrict_to_arms={"reddit_gptjb_new_method", "arxiv_pi"}
    )

    assert got == {}, "no picked arm matches the Pliny URL → no credit awarded"


def test_restrict_to_arms_credits_only_picked_arm_within_tie() -> None:
    """When two arms share a site pattern but only one was picked, only the
    picked one gets credit — even though both would match in the unrestricted
    seed-script call."""
    arms = _build_test_arms()
    reddit_url = "https://www.reddit.com/r/GPT_jailbreaks/comments/x"

    got = attribute_urls_to_arms(
        [reddit_url], arms, restrict_to_arms={"reddit_gptjb_new_method"}
    )

    assert got == {"reddit_gptjb_new_method": 1}


def test_restrict_to_arms_picked_no_match_returns_empty() -> None:
    """Picked arm that matches no URLs is omitted from the count dict — caller
    falls back to novel=0 when calling bandit.record."""
    arms = _build_test_arms()
    got = attribute_urls_to_arms(
        ["https://leakhub.ai/prompts/openai"],
        arms,
        restrict_to_arms={"github_pliny_umbrella"},
    )
    assert got == {}


def test_restrict_to_empty_set_attributes_nothing() -> None:
    arms = _build_test_arms()
    urls = ["https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/X.mkd"]
    assert attribute_urls_to_arms(urls, arms, restrict_to_arms=set()) == {}


def test_restrict_none_falls_back_to_seed_semantics() -> None:
    """restrict_to_arms=None means seed-script semantics: all arms eligible."""
    arms = _build_test_arms()
    pliny_url = "https://raw.githubusercontent.com/elder-plinius/L1B3RT4S/main/X.mkd"
    got = attribute_urls_to_arms([pliny_url], arms, restrict_to_arms=None)
    assert got == {"github_pliny_umbrella": 1}
