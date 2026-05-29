"""Source provenance — one record per (raw document, fetch event).

A primitive can have multiple sources if it was independently disclosed in multiple
places (e.g. the same attack reported on Reddit, then in an arXiv preprint, then in a
vendor blog). Each source records *what we fetched, when, and via which Bright Data
product*, so the dashboard's "by Bright Data product" panel and the threat brief's
citations work without recomputation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

# Locked sets — keep in sync with §5.1 (source list) and §6.1 (Bright Data products).
SourceType = Literal[
    "reddit",
    "x",
    "arxiv",
    "github",
    "huggingface",
    "blog",
    "mitre",
    "owasp",
    "vendor_safety_blog",
    "discord_archive",
    "community_archive",
    "other",
]

BrightDataProduct = Literal[
    "web_scraper_api",
    "serp",
    "web_unlocker",
    "scraping_browser",
    "mcp_server",
    "fixture",  # for offline replays from tests/fixtures/ (demo fallback)
]


class SourceProvenance(BaseModel):
    """One record per fetched document. Immutable after creation."""

    url: HttpUrl = Field(..., description="canonical URL of the source document")
    source_type: SourceType = Field(..., description="see §5.1 mapping")
    author: Optional[str] = Field(
        None,
        description="byline if discoverable: redditor username, arXiv authors, blog author",
        max_length=200,
    )
    published_at: Optional[datetime] = Field(
        None, description="source-side publication timestamp if discoverable"
    )
    fetched_at: datetime = Field(..., description="UTC time ROGUE fetched the document")
    archive_hash: str = Field(
        ...,
        description="SHA-256 hex digest of the raw fetched content (HTML / PDF / JSON bytes)",
        min_length=7,  # accept short placeholder hashes in fixtures; production uses 64-char
        max_length=80,
    )
    bright_data_product: BrightDataProduct = Field(
        ..., description="which Bright Data product fetched this document"
    )

    model_config = {"frozen": True}  # immutable after creation
