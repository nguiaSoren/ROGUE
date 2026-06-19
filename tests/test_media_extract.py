"""Tests for generic image-URL extraction (Feature A — multimodal ingestion).

Pure, offline: no network, no DB. Covers ``rogue.harvest.media_extract`` —
``<img>`` / ``![]()`` parsing, relative→absolute resolution, junk filtering,
de-dupe + cap, and the structural+body merge.
"""

from __future__ import annotations

from rogue.harvest.media_extract import (
    extract_media_urls,
    extract_media_urls_from_json,
    media_urls_for_document,
)


def test_html_img_tags_resolved_to_absolute() -> None:
    html = (
        '<p>x</p><img src="/assets/jail.png" alt="a">'
        "<IMG SRC='https://cdn.example.com/screenshot.jpg'>"
    )
    out = extract_media_urls(html, "html", "https://blog.example.com/post/1")
    assert out == [
        "https://blog.example.com/assets/jail.png",
        "https://cdn.example.com/screenshot.jpg",
    ]


def test_markdown_images_and_data_uri_dropped() -> None:
    md = "![cap](https://i.imgur.com/a.png) and ![](data:image/png;base64,AAAA) end"
    out = extract_media_urls(md, "markdown", "https://x.example/p")
    assert out == ["https://i.imgur.com/a.png"]


def test_junk_and_non_image_filtered() -> None:
    html = (
        '<img src="https://t.example/spacer.gif">'      # spacer → junk
        '<img src="https://t.example/favicon.ico">'     # not raster + junk
        '<img src="https://t.example/avatar/u.png">'    # avatar → junk
        '<img src="https://t.example/real-photo.png">'  # keep
    )
    out = extract_media_urls(html, "html", "https://t.example/")
    assert out == ["https://t.example/real-photo.png"]


def test_extensionless_image_cdn_kept() -> None:
    # pbs.twimg.com/media URLs are extension-less but are real images.
    html = '<img src="https://pbs.twimg.com/media/Gabc123">'
    out = extract_media_urls(html, "html", "https://x.com/p")
    assert out == ["https://pbs.twimg.com/media/Gabc123"]


def test_json_and_text_are_noops() -> None:
    assert extract_media_urls('{"photos": ["x"]}', "json", "https://x") == []
    assert extract_media_urls("plain text ![nope](u.png)", "text", "https://x") == []


def test_dedupe_preserves_order_and_caps() -> None:
    html = "".join(f'<img src="https://c.example/img{i}.png">' for i in range(20))
    html += '<img src="https://c.example/img0.png">'  # dup of first
    out = extract_media_urls(html, "html", "https://c.example/", limit=5)
    assert out == [f"https://c.example/img{i}.png" for i in range(5)]


def test_media_urls_for_document_merges_structural_first() -> None:
    structural = ["https://pbs.twimg.com/media/STRUCT"]
    body = '<img src="https://blog.example/body.png">'
    out = media_urls_for_document(
        media_urls=structural,
        raw_content=body,
        content_format="html",
        base_url="https://blog.example/post",
    )
    # Structural URL leads; body-derived follows; no duplicates.
    assert out == [
        "https://pbs.twimg.com/media/STRUCT",
        "https://blog.example/body.png",
    ]


def test_media_urls_for_document_dedupes_across_sources() -> None:
    shared = "https://cdn.example/same.png"
    out = media_urls_for_document(
        media_urls=[shared],
        raw_content=f'<img src="{shared}">',
        content_format="html",
        base_url="https://cdn.example/",
    )
    assert out == [shared]


def test_json_walker_extracts_embedded_and_keyed_images() -> None:
    """For JSON sources without a clean `photos` array (HF discussions): images
    embedded as markdown / bare links in post bodies + image-keyed arrays."""
    obj = {
        "thread_id": "1",
        "posts": [
            {"author_avatar": "https://h/avatars/a.png",  # junk → dropped
             "content": "exploit ![poc](https://cdn.example/poc.png) here"},
            {"content": "also https://i.imgur.com/q.jpg and a clip https://x/v.mp4"},
            {"images": ["https://i.redd.it/keyed.png"]},
        ],
    }
    out = extract_media_urls_from_json(obj)
    assert out == [
        "https://cdn.example/poc.png",
        "https://i.imgur.com/q.jpg",
        "https://i.redd.it/keyed.png",
    ]


def test_json_walker_caps_and_dedupes() -> None:
    obj = {"a": [f"https://c/{i}.png" for i in range(10)] + ["https://c/0.png"]}
    # 'a' isn't an image key, but the strings are bare image URLs in a list.
    out = extract_media_urls_from_json(obj, limit=3)
    assert out == ["https://c/0.png", "https://c/1.png", "https://c/2.png"]


def test_media_urls_for_document_caps_total() -> None:
    structural = [f"https://cdn.example/s{i}.png" for i in range(3)]
    body = "".join(f'<img src="https://cdn.example/b{i}.png">' for i in range(10))
    out = media_urls_for_document(
        media_urls=structural,
        raw_content=body,
        content_format="html",
        base_url="https://cdn.example/",
        limit=4,
    )
    assert len(out) == 4
    assert out[:3] == structural  # structural always kept first
