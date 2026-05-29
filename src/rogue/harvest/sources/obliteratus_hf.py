"""OBLITERATUS HuggingFace org harvest plugin (source #10 in §5.1, new 2026-05-24 PM).

Pliny-affiliated HF org publishing "abliterated" model variants
(``Qwen3.6-27B-OBLITERATED``, ``DeepSeek-R1-Distill-Llama-8B-OBLITERATED``,
``gpt2-xl-OBLITERATED``, ``Qwen3-4B-OBLITERATED``, ``gemma-4-E4B-it-OBLITERATED``,
``Qwen2.5-Coder-7B-Instruct-OBLITERATED``). Each model card's README
describes the weight-abliteration technique — that text IS the attack
primitive (``family=weight_abliteration``; new family per §4.2 amendment,
extraction-layer concern).

  * **Primary product:** Web Unlocker — README markdown for each model card,
    plus the org's ``/activity`` page once daily to surface new publishes
    by ``pliny-the-prompter`` (§5.2 Source #10 cadence).
  * **Fallback:** none — if Web Unlocker fails on a README, the model goes
    stale per §9.3 and the next daily run retries.

Spec: ROGUE_PLAN.md §5.1 Source #10, §5.2 Source #10, §9.3 (Day-1 source
plugin checklist).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from rogue.harvest.bright_data_client import BrightDataClient
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["ObliteratusHfPlugin"]


# Locked model list per §5.2 Source #10 (2026-05-24 PM verification).
# Refresh via the `/activity` page every daily run — when new models appear
# under pliny-the-prompter, add them to this tuple and ship the change.
DEFAULT_MODELS: tuple[str, ...] = (
    "Qwen3.6-27B-OBLITERATED",
    "Qwen2.5-Coder-7B-Instruct-OBLITERATED",
    "gpt2-xl-OBLITERATED",
    "DeepSeek-R1-Distill-Llama-8B-OBLITERATED",
    "Qwen3-4B-OBLITERATED",
    "gemma-4-E4B-it-OBLITERATED",
)

HF_ORG_SLUG = "OBLITERATUS"
HF_ACTIVITY_URL = f"https://huggingface.co/{HF_ORG_SLUG}/activity"


def _readme_url(model: str) -> str:
    """Canonical raw README URL for one OBLITERATUS model card.

    HF serves model-card READMEs at ``/<org>/<model>/raw/main/README.md``;
    that's a plain-markdown response that Web Unlocker passes through
    unchanged. The ``/blob/main/README.md`` HTML view is also valid but
    requires HTML→markdown stripping, so we prefer ``/raw/``.
    """
    return f"https://huggingface.co/{HF_ORG_SLUG}/{model}/raw/main/README.md"


class ObliteratusHfPlugin(SourcePlugin):
    """OBLITERATUS HF org model-card READMEs harvester (Web Unlocker)."""

    name = "obliteratus_hf"
    source_type = "huggingface"
    bright_data_product = "web_unlocker"

    def __init__(
        self,
        models: Iterable[str] | None = None,
        include_activity_page: bool = True,
    ) -> None:
        self.models: list[str] = (
            list(models) if models is not None else list(DEFAULT_MODELS)
        )
        self.include_activity_page = include_activity_page

    def serp_queries(self, since: datetime) -> list[str]:
        """OBLITERATUS SERP query (docs/sources.md §10-new)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [f"site:huggingface.co/{HF_ORG_SLUG} after:{date_str}"]

    async def fetch_since(
        self,
        client: BrightDataClient,
        since: datetime,
    ) -> list[RawDocument]:
        """Per model: fetch README via Web Unlocker. Plus the org activity page once."""
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)

        # --- 1. Per-model README fetches ---
        for model in self.models:
            url = _readme_url(model)
            try:
                page = await client.web_unlock(url, format="markdown")
            except NotImplementedError:
                raise
            except Exception:
                continue
            if not page.content or len(page.content) < 50:
                # Empty / stub README — skip rather than feed the extraction
                # LLM noise. HF occasionally serves a 200 with an empty body
                # when a model card hasn't been migrated to a README yet.
                continue

            raw_content = page.content
            archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
            try:
                docs.append(
                    RawDocument(
                        url=url,
                        source_type=self.source_type,
                        bright_data_product=self.bright_data_product,
                        fetched_at=fetched_at,
                        raw_content=raw_content,
                        content_format="markdown",
                        archive_hash=archive_hash,
                        http_status=page.status_code,
                        metadata={
                            "org": HF_ORG_SLUG,
                            "model": model,
                            "fetch_path": "readme",
                        },
                        discovered_via=None,
                    )
                )
            except Exception:
                continue

        # --- 2. /activity page (daily delta of new publishes) ---
        if self.include_activity_page:
            try:
                activity = await client.web_unlock(HF_ACTIVITY_URL, format="markdown")
            except NotImplementedError:
                raise
            except Exception:
                activity = None
            if activity is not None and activity.content and len(activity.content) >= 50:
                raw_content = activity.content
                archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
                try:
                    docs.append(
                        RawDocument(
                            url=HF_ACTIVITY_URL,
                            source_type=self.source_type,
                            bright_data_product=self.bright_data_product,
                            fetched_at=fetched_at,
                            raw_content=raw_content,
                            content_format="markdown",
                            archive_hash=archive_hash,
                            http_status=activity.status_code,
                            metadata={
                                "org": HF_ORG_SLUG,
                                "fetch_path": "activity",
                            },
                            discovered_via=None,
                        )
                    )
                except Exception:
                    pass

        # ``since`` filtering is best handled at the dedup layer via
        # archive_hash — HF model-card READMEs change in place; a timestamp
        # filter on the raw URL would drop active content.
        _ = since
        return docs
