"""RawDocument — the transient wire type between LAYER 1 (HARVEST) and LAYER 2 (EXTRACT).

Position in the pipeline (see ROGUE_PLAN.md §3.1):
    BrightDataClient / harvest source plugins  ──►  RawDocument  ──►  ExtractionAgent.extract()

Every source plugin under `harvest/sources/` returns `list[RawDocument]` from its
`async def fetch_since(client, since_dt)` entrypoint (plan §9.3), and the extraction
agent consumes RawDocument instances one-at-a-time to materialize AttackPrimitive
records.

RawDocument is transient by design: we do NOT persist the document body. The persistent
record is `SourceProvenance` (URL, fetched_at, archive_hash, product) attached to the
extracted `AttackPrimitive`. The body itself is hashed (SHA-256) and only the hash
travels onward via `SourceProvenance.archive_hash`, so re-fetching the same content
later can be detected without storing megabytes of HTML.

The `metadata` field is an open-ended per-source dict — e.g. Reddit upvotes/subreddit/
comment count, X retweet counts, arXiv abstract fields, GitHub stargazers. The extraction
agent may peek at it for stronger heuristics but doesn't depend on any particular keys.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

from .source_provenance import BrightDataProduct, SourceType


class RawDocument(BaseModel):
    """One fetched document, ready for the extraction agent. Immutable after creation."""

    url: HttpUrl = Field(..., description="canonical URL of the source document")
    source_type: SourceType = Field(
        ..., description="same vocabulary as SourceProvenance.source_type"
    )
    bright_data_product: BrightDataProduct = Field(
        ..., description="same vocabulary as SourceProvenance.bright_data_product"
    )
    fetched_at: datetime = Field(..., description="UTC time of fetch (timezone-aware)")
    raw_content: str = Field(
        ...,
        description="document body — HTML / markdown / serialized JSON / extracted PDF text",
        max_length=2_000_000,  # 2 MB cap; long Reddit threads via Web Scraper API can be large
    )
    content_format: Literal["html", "markdown", "json", "text", "pdf_text"] = Field(
        ...,
        description=(
            "what raw_content actually is, so the extraction agent knows whether to "
            "strip tags, parse JSON, etc."
        ),
    )
    archive_hash: str = Field(
        ...,
        description="SHA-256 hex digest of raw_content.encode('utf-8'); mirrors SourceProvenance.archive_hash",
        min_length=7,  # accept shortened fixture hashes; production uses full 64-char
        max_length=64,
    )
    http_status: int = Field(
        ...,
        ge=100,
        le=599,
        description="HTTP status code returned by the fetch; powers the cost-log failure tracking",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "per-source extras — e.g. {'score': 42, 'subreddit': 'ChatGPTJailbreak', "
            "'comments_n': 17} for Reddit; arXiv abstract fields; X retweet counts"
        ),
    )
    discovered_via: Optional[str] = Field(
        default=None,
        max_length=500,
        description=(
            "how this URL was found — e.g. 'serp_query: site:reddit.com/r/ChatGPTJailbreak "
            "after:2026-05-23' for SERP-discovered docs; None for direct-source-listing fetches "
            "like an arXiv RSS feed"
        ),
    )
    media_urls: list[str] = Field(
        default_factory=list,
        max_length=64,
        description=(
            "Image URLs attached to this document (multimodal ingestion — Feature A). "
            "Populated by source plugins from structured JSON (X `photos`, Reddit "
            "`images`) or derived from HTML/markdown `<img>` tags via "
            "`rogue.harvest.media_extract.extract_media_urls`. The harvest "
            "media-download step (`rogue.harvest.media_ingest`) fetches each one "
            "so the extraction agent can vision-read it. Distinct from "
            "`payload_slots['media_query']` (§11.8): media_urls are the document's "
            "OWN images (a candidate payload), not a generic carrier to composite a "
            "text attack onto. Empty for text-only documents."
        ),
    )

    model_config = {"frozen": True}  # immutable after creation

    def compute_archive_hash(self) -> str:
        """Return the SHA-256 hex digest of raw_content.

        Doesn't validate against `self.archive_hash` — the caller decides whether to
        compare. Useful for source plugins that need to compute the hash before
        constructing the model.
        """
        return hashlib.sha256(self.raw_content.encode("utf-8")).hexdigest()


__all__ = ["RawDocument"]
