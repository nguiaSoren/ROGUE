"""HuggingFace community-discussion harvest plugin (source #6 in docs/sources.md).

  * **Primary product:** Web Scraper API — *if* an HF dataset is provisioned
    on the Bright Data side (``BRIGHTDATA_HUGGINGFACE_DATASET_ID``). Wrapped
    by :meth:`BrightDataClient.scrape_huggingface_discussion`, returning typed
    :class:`HFDiscussion` records.
  * **Fallback:** Web Unlocker — fetch ``huggingface.co/<model>/discussions``
    and the per-thread pages as raw HTML for the extraction layer.
    See ``website/WEB-UNLOCKER/send-your-first-request.md``.

We don't ship a default model list — model IDs are populated on Day 1 once
the HF dataset ID + the model-of-interest list (likely surfaced from a SERP
``"jailbreak" OR "system prompt" discussion`` sweep) is confirmed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["HuggingFaceDiscussionPlugin"]


class HuggingFaceDiscussionPlugin(SourcePlugin):
    """HuggingFace model-card discussions harvester."""

    name = "huggingface_discussion"
    source_type = "huggingface"
    bright_data_product = "web_scraper_api"
    required_capabilities: frozenset[Capability] = frozenset({Capability.HF, Capability.UNLOCK})

    def __init__(self, model_ids: Optional[list[str]] = None) -> None:
        # Empty by default — Day-1 populates from a SERP sweep + confirmed
        # HF dataset availability. See `docs/sources.md` §6 + ROGUE_PLAN.md
        # §9.2 (Day-1 dataset-id discovery).
        # REVIEW Day 1: scan `website/WEB SCRAPER API/` again after Bright
        # Data ships the rumored HF prebuilt; if still absent, *all* fetches
        # will go through the Web Unlocker fallback below.
        self.model_ids = model_ids if model_ids is not None else []
        self.call_errors: list[str] = []

    def serp_queries(self, since: datetime) -> list[str]:
        """HuggingFace SERP queries (docs/sources.md §6).

        The second query has a ``<model>`` placeholder per the spec; we
        emit one expanded query per configured ``model_id`` plus the
        site-wide discovery query.
        """
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        queries = [
            f'site:huggingface.co "jailbreak" OR "system prompt" discussion '
            f"after:{date_str}",
        ]
        for model_id in self.model_ids:
            queries.append(
                f'site:huggingface.co/{model_id}/discussions '
                f'"exploit" OR "bypass" after:{date_str}'
            )
        return queries

    async def fetch_since(
        self,
        fetcher: Fetcher,
        since: datetime,
    ) -> list[RawDocument]:
        """Fetch each model's discussions. Try Web Scraper API first; on
        ``RuntimeError`` (no HF dataset provisioned) fall back per-model to
        Web Unlocker."""
        self.call_errors = []
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)

        if not self.model_ids:
            # Common config: HF dataset isn't provisioned AND no model_ids
            # passed. Surface explicitly rather than silently returning [].
            self.call_errors.append(
                "no model_ids configured — pass models=[...] to the plugin "
                "or set BRIGHTDATA_HUGGINGFACE_DATASET_ID + populate via SERP "
                "sweep (Day-1 task)."
            )
            return docs

        for model_id in self.model_ids:
            # --- Try the structured Web Scraper API path first ---
            primary_failed = False
            try:
                threads = await fetcher.hf_discussion(model_id)
            except NotImplementedError:
                raise
            except RuntimeError:
                # The client raises RuntimeError when hf_dataset_id is None
                # per `bright_data_client.py` docstring.
                primary_failed = True
                threads = []
            except Exception as exc:
                # Other transient errors — skip this model for this run, but
                # surface the cause so silent zeros are diagnosable.
                self.call_errors.append(
                    f"model={model_id} primary: {type(exc).__name__}: {exc}"
                )
                continue

            if not primary_failed:
                for thread in threads:
                    if thread.started_at <= since:
                        continue
                    raw_content = json.dumps(
                        thread.model_dump(mode="json"), sort_keys=True
                    )
                    archive_hash = hashlib.sha256(
                        raw_content.encode("utf-8")
                    ).hexdigest()
                    thread_url = (
                        f"https://huggingface.co/{model_id}/discussions/"
                        f"{thread.thread_id}"
                    )
                    try:
                        docs.append(
                            RawDocument(
                                url=thread_url,
                                source_type=self.source_type,
                                bright_data_product="web_scraper_api",
                                fetched_at=fetched_at,
                                raw_content=raw_content,
                                content_format="json",
                                archive_hash=archive_hash,
                                http_status=200,
                                metadata={
                                    "model_id": model_id,
                                    "thread_id": thread.thread_id,
                                    "title": thread.title,
                                    "n_posts": len(thread.posts),
                                },
                                discovered_via=None,
                                # Multimodal ingestion (Feature A): images
                                # embedded in the thread's posts (JSON source —
                                # the body-img extractor can't see into JSON).
                                media_urls=list(thread.media_urls),
                            )
                        )
                    except Exception:
                        continue
                continue

            # --- Web Unlocker fallback ---
            # REVIEW Day 1: the discussions index page is rendered via Next.js
            # SSR — Web Unlocker handles SSR'd HTML fine, but per-thread
            # pages may need an extra fetch each. For Day-0 we emit just the
            # index page as a single doc per model and let the extraction
            # layer pull URLs/IDs from the raw HTML. Day 1: parse out thread
            # IDs and follow through.
            discussions_url = f"https://huggingface.co/{model_id}/discussions"
            try:
                page = await fetcher.unlock(discussions_url, format="html")
            except NotImplementedError:
                raise
            except Exception as exc:
                self.call_errors.append(
                    f"model={model_id} fallback: {type(exc).__name__}: {exc}"
                )
                continue

            raw_content = page.content
            archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
            try:
                docs.append(
                    RawDocument(
                        url=discussions_url,
                        source_type=self.source_type,
                        bright_data_product="web_unlocker",
                        fetched_at=fetched_at,
                        raw_content=raw_content,
                        content_format="html",
                        archive_hash=archive_hash,
                        http_status=page.status_code,
                        metadata={
                            "model_id": model_id,
                            "fallback_path": "web_unlocker",
                        },
                        discovered_via=None,
                    )
                )
            except Exception:
                continue

        return docs
