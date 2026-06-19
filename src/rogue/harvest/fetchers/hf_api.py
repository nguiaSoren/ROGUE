"""The ``hf_api`` fetcher backend — HuggingFace public REST API, no account required.

Uses the ``https://huggingface.co/api/`` surface that backs the HF web UI.  No BD
account, no API key: the endpoints are public.  If ``HF_TOKEN`` is present in the
environment it is sent as a ``Bearer`` token (raises the anonymous rate-limit from
~300 req/hr to ~1 000 req/hr), but the backend works and ``is_available()`` returns
``True`` even when the env var is absent.

Capabilities declared: :attr:`~rogue.harvest.fetchers.capabilities.Capability.HF`.

Two HuggingFace API endpoints are used:

  1. **List discussions** — ``GET /api/models/{model_id}/discussions``
     Returns a JSON object with a ``discussions`` key — a list of discussion
     summaries (``num``, ``title``, ``createdAt``, ``author.name``, ``status``
     ``isPullRequest``, …).  Paged via ``?p=0&limit=50``; we request up to 50
     per page and fetch pages until exhausted or the cap is reached.

  2. **Discussion detail** — ``GET /api/models/{model_id}/discussions/{num}``
     Returns the full discussion with its ``events`` array; events of
     ``type="comment"`` carry a ``data.latest.raw`` (Markdown) body plus
     embedded image URLs. We collect these to populate ``posts`` + ``media_urls``.

The :class:`HFDiscussion` shape returned is identical to what
:meth:`~rogue.harvest.bright_data_client.BrightDataClient.scrape_huggingface_discussion`
returns, so the :class:`~rogue.harvest.sources.huggingface_discussion.HuggingFaceDiscussionPlugin`
source can call this backend without any parsing changes.

Error handling: any ``httpx`` error, 404, or JSON parse failure is caught,
a warning is logged, and ``[]`` is returned — never raises to the caller.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from rogue.harvest.bright_data_client import HFDiscussion
from rogue.harvest.media_extract import extract_media_urls_from_json

from .base import Fetcher
from .capabilities import Capability

__all__ = ["HFApiFetcher"]

logger = logging.getLogger("rogue.harvest.fetchers.hf_api")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://huggingface.co/api"

# Discussions to fetch per model — keep reasonable to avoid hammering the
# public API without a token (rate-limit: ~300 req/hr anonymous).
_MAX_DISCUSSIONS = 50

# Per-discussion detail fetches — we only fetch detail for the first N
# discussions (to keep request count bounded for large models).
_MAX_DETAIL_FETCH = 20

# Markdown image pattern — ``![alt](url)``
_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)")

_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "ROGUE-fetcher/1.0 (open-web LLM red-team; +https://rogue-eosin.vercel.app)"
    ),
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(value: Any) -> datetime:
    """Parse an ISO-8601 string (HF uses ``2024-03-14T18:22:00.000Z``) to UTC datetime.

    Falls back to "now UTC" so :class:`HFDiscussion` always validates.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _extract_image_urls_from_text(text: str) -> list[str]:
    """Pull markdown-embedded image URLs from a post body string."""
    return _MD_IMG_RE.findall(text or "")


def _discussion_to_hf_discussion(
    summary: dict[str, Any],
    detail: dict[str, Any] | None,
    model_id: str,
) -> HFDiscussion:
    """Combine a discussion list-summary and optional detail into an :class:`HFDiscussion`.

    ``summary`` fields (from the list endpoint):
      - ``num`` (int) — discussion number within the model; used as ``thread_id``
      - ``title`` (str)
      - ``createdAt`` (ISO string)

    ``detail`` fields (from the per-discussion endpoint, optional):
      - ``events`` (list) — one per comment/commit/change; ``type=="comment"`` events
        carry ``data.latest.raw`` (Markdown body).

    Posts are the comment events (``type=="comment"``); we store each as a plain
    ``{"author": str, "body": str, "created_at": str}`` dict, matching the
    unprovisioned BD schema (``posts: list[dict]``).
    """
    num = summary.get("num") or ""
    thread_id = str(num)
    title = str(summary.get("title") or "")
    created_at = _parse_dt(summary.get("createdAt"))

    posts: list[dict] = []
    media_urls: list[str] = []

    if detail:
        events = detail.get("events") or []
        for event in events:
            if event.get("type") != "comment":
                continue
            data = event.get("data") or {}
            latest = data.get("latest") or {}
            body = str(latest.get("raw") or "")
            author_info = event.get("author") or {}
            author_name = str(author_info.get("name") or "")
            event_dt = _parse_dt(event.get("createdAt"))
            posts.append({
                "author": author_name,
                "body": body,
                "created_at": event_dt.isoformat(),
            })
            # Collect image URLs from markdown body
            for url in _extract_image_urls_from_text(body):
                if url not in media_urls:
                    media_urls.append(url)

        # Also walk the full detail dict for any image URLs the recursive
        # extractor can find (same field-name-agnostic walk as the BD adapter).
        for url in extract_media_urls_from_json(detail):
            if url not in media_urls:
                media_urls.append(url)

    return HFDiscussion(
        model_id=model_id,
        thread_id=thread_id,
        title=title,
        posts=posts,
        started_at=created_at,
        media_urls=media_urls,
    )


# ---------------------------------------------------------------------------
# HFApiFetcher
# ---------------------------------------------------------------------------

class HFApiFetcher(Fetcher):
    """HuggingFace public API backend — keyless, HF_TOKEN optional for higher rate limits.

    Declares capability: :attr:`~rogue.harvest.fetchers.capabilities.Capability.HF`.

    A single :class:`httpx.AsyncClient` is shared across calls (lazy-init on
    first use). Call :meth:`aclose` at shutdown to release the connection pool.
    """

    name = "hf_api"
    capabilities = frozenset({Capability.HF})

    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Availability — always True; HF_TOKEN is optional
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Always ``True`` — the HF public API requires no credentials."""
        return True

    # ------------------------------------------------------------------
    # Internal shared client
    # ------------------------------------------------------------------

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None:
            headers = dict(_DEFAULT_HEADERS)
            token = os.environ.get("HF_TOKEN", "").strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            self._http = httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, connect=10.0),
                headers=headers,
            )
        return self._http

    async def aclose(self) -> None:
        """Release the shared HTTP client. Idempotent."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # HF capability — structured discussion threads
    # ------------------------------------------------------------------

    async def hf_discussion(self, model_id: str) -> list[HFDiscussion]:
        """Fetch open model-card discussion threads for ``model_id``.

        Calls two HF API endpoints:

        1. ``GET /api/models/{model_id}/discussions?limit=50`` — discussion list.
        2. ``GET /api/models/{model_id}/discussions/{num}`` — per-discussion detail
           (up to :data:`_MAX_DETAIL_FETCH` discussions, to bound request count).

        Returns an empty list (never raises) on any network/parse error.
        """
        http = self._get_http()
        summaries: list[dict[str, Any]] = []

        # --- 1. Fetch the discussion list -----------------------------------
        list_url = f"{_BASE_URL}/models/{model_id}/discussions"
        try:
            resp = await http.get(list_url, params={"limit": _MAX_DISCUSSIONS, "p": 0})
            if resp.status_code == 404:
                logger.warning("hf_api: model %r not found (404)", model_id)
                return []
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "hf_api: HTTP %s fetching discussions for %r: %s",
                exc.response.status_code, model_id, exc,
            )
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning("hf_api: failed to fetch discussions for %r: %s", model_id, exc)
            return []

        # The list endpoint returns ``{"discussions": [...], "count": N}``
        raw_list = payload if isinstance(payload, list) else payload.get("discussions", [])
        if not isinstance(raw_list, list):
            logger.warning(
                "hf_api: unexpected discussions payload type %r for %r",
                type(raw_list).__name__, model_id,
            )
            return []

        summaries = raw_list[:_MAX_DISCUSSIONS]

        if not summaries:
            return []

        # --- 2. Fetch per-discussion detail (bounded) -----------------------
        results: list[HFDiscussion] = []
        for i, summary in enumerate(summaries):
            num = summary.get("num")
            detail: dict[str, Any] | None = None

            if i < _MAX_DETAIL_FETCH and num is not None:
                detail_url = f"{_BASE_URL}/models/{model_id}/discussions/{num}"
                try:
                    dresp = await http.get(detail_url)
                    if dresp.status_code == 200:
                        detail = dresp.json()
                    elif dresp.status_code == 404:
                        logger.debug(
                            "hf_api: discussion %s/%s not found (404)", model_id, num
                        )
                    else:
                        logger.debug(
                            "hf_api: discussion %s/%s returned HTTP %s",
                            model_id, num, dresp.status_code,
                        )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "hf_api: failed to fetch detail for %s/%s: %s", model_id, num, exc
                    )
                    # detail stays None; we still produce a discussion from the summary

            try:
                discussion = _discussion_to_hf_discussion(summary, detail, model_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "hf_api: could not map discussion %s/%s to HFDiscussion: %s",
                    model_id, num, exc,
                )
                continue

            results.append(discussion)

        return results
