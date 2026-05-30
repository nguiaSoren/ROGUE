"""Tests for outbound-link extraction (Feature C — post→link following).

Pure, offline. Covers ``rogue.harvest.link_extract``: per-format URL extraction,
shortener detection, the asset/image/social-noise + same-site filters, and
order-preserving de-dupe + cap.
"""

from __future__ import annotations

import json

from rogue.harvest.link_extract import (
    SHORTENER_HOSTS,
    extract_outbound_urls,
    is_shortener,
)


def test_x_post_json_yields_tco_and_external_url() -> None:
    body = json.dumps(
        {
            "url": "https://x.com/akaclandestine/status/1",
            "description": "new CVE bench dropped https://t.co/abc see thread",
            "external_url": "https://giovannigatti.github.io/cve-bench/",
            "quoted_post": "https://x.com/someoneelse/status/9",  # same-site → skip
        }
    )
    out = extract_outbound_urls(body, "json", "https://x.com/akaclandestine/status/1", limit=5)
    assert "https://t.co/abc" in out
    assert "https://giovannigatti.github.io/cve-bench/" in out
    # The quoted x.com link is same registrable domain as the source → excluded.
    assert not any("someoneelse" in u for u in out)


def test_markdown_link_excludes_image_and_keeps_repo() -> None:
    md = "See [the repo](https://github.com/x/y) but not ![pic](https://i.imgur.com/a.png)."
    out = extract_outbound_urls(md, "markdown", "https://blog.example.com/p", limit=5)
    assert out == ["https://github.com/x/y"]


def test_html_anchor_hrefs_extracted() -> None:
    html = '<a href="https://arxiv.org/abs/2605.1">paper</a> <a href="/local">x</a>'
    out = extract_outbound_urls(html, "html", "https://news.example.org/post", limit=5)
    assert out == ["https://arxiv.org/abs/2605.1"]  # relative /local dropped (not http)


def test_same_site_links_excluded() -> None:
    # A reddit post linking within reddit isn't "following out".
    body = "discussion at https://www.reddit.com/r/x/comments/abc and https://github.com/a/b"
    out = extract_outbound_urls(body, "text", "https://reddit.com/r/x/comments/zzz", limit=5)
    assert out == ["https://github.com/a/b"]


def test_asset_and_noise_links_filtered() -> None:
    body = (
        "https://example.com/styles.css "        # asset
        "https://pbs.twimg.com/media/x.jpg "      # noise host + image
        "https://youtube.com/watch?v=1 "          # noise host
        "https://realsite.org/writeup"            # keep
    )
    out = extract_outbound_urls(body, "text", "https://x.com/u/status/1", limit=5)
    assert out == ["https://realsite.org/writeup"]


def test_dedupe_and_cap() -> None:
    body = " ".join(f"https://site{i}.com/p" for i in range(10)) + " https://site0.com/p"
    out = extract_outbound_urls(body, "text", "https://x.com/u/status/1", limit=3)
    assert out == ["https://site0.com/p", "https://site1.com/p", "https://site2.com/p"]


def test_trailing_punctuation_trimmed() -> None:
    body = "great write-up at https://giovannigatti.github.io/cve-bench/."
    out = extract_outbound_urls(body, "text", "https://x.com/u/status/1", limit=5)
    assert out == ["https://giovannigatti.github.io/cve-bench/"]


def test_is_shortener() -> None:
    assert is_shortener("https://t.co/abcDEF")
    assert is_shortener("https://www.bit.ly/x")
    assert not is_shortener("https://github.com/x/y")
    assert "t.co" in SHORTENER_HOSTS


def test_empty_when_no_outbound_links() -> None:
    assert extract_outbound_urls("just some text, no links", "text", "https://x.com/u/1") == []
    assert extract_outbound_urls('{"score": 42}', "json", "https://x.com/u/1") == []
