"""LeakHub.ai harvest plugin (source #8 in §5.1, new 2026-05-24 PM).

LeakHub.ai is a crowd-sourced system-prompt-leak verification platform
(Apache 2.0, GitHub OAuth, Convex backend). The site is a **Vite-built
React SPA** — the browse routes (``/prompts/<provider>``) are gated
behind GitHub OAuth, and an unauthenticated fetch returns only the
``Sign in`` nav (verified 2026-05-26 via Scraping Browser).

**Auth is in localStorage, not cookies.** Verified 2026-05-26: even when
signed in, leakhub.ai sets zero cookies — Convex's auth pattern stores the
JWT under a key like ``__convexAuthJWT_<deployment>`` in
``window.localStorage``. So the only durable auth-injection mechanism is
Playwright's native ``storage_state`` (cookies + per-origin localStorage in
one blob).

**Setup (one-time):**

  1. Sign in to https://leakhub.ai via GitHub in any normal browser.
  2. Capture the storage state. Easiest path:
     ``uv run python scripts/_capture_leakhub_storage.py`` — opens a
     local Playwright browser, lets you sign in, then writes
     ``leakhub_storage_state.json`` to the repo root.
  3. Set ``LEAKHUB_STORAGE_STATE`` in ``.env`` to either:
     * the JSON blob inline (single-line):
       ``LEAKHUB_STORAGE_STATE='{"cookies": [], "origins": [{"origin": "https://leakhub.ai", "localStorage": [...]}]}'``
     * OR the path to the JSON file:
       ``LEAKHUB_STORAGE_STATE=./leakhub_storage_state.json``

If ``LEAKHUB_STORAGE_STATE`` is unset, the plugin records a clear error in
``call_errors`` (visible in the harvest summary) and emits zero docs.

  * **Primary product:** Scraping Browser fetches each ``/prompts/<provider>``
    with the storage_state injected at context-creation time.
  * **Fallback:** none in-plugin. The Pliny CL4R1T4S plugin already
    covers the bulk of public system-prompt leaks via direct GitHub
    fetches (no auth needed), so a LeakHub stall doesn't bottom the
    harvest.

Spec: ROGUE_PLAN.md §5.1 Source #8, §5.2 Source #8, §9.3.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from rogue.harvest.fetchers import Capability, Fetcher
from rogue.schemas import RawDocument

from .base import SourcePlugin

__all__ = ["LeakHubScrapePlugin"]


logger = logging.getLogger(__name__)


# Panel-vendor slug list — drives the per-provider browse-route fan-out.
DEFAULT_PROVIDERS: tuple[str, ...] = (
    "openai",
    "anthropic",
    "google",
    "mistral",
    "meta",
    "deepseek",
)

LEAKHUB_BASE = "https://leakhub.ai"

# CSS selector to wait for before snapshotting. Verified 2026-05-26 against
# the unauthed shell: LeakHub does NOT render `<article>` tags (waiting on it
# hits the 30s timeout reliably). Set to None so we use the goto's default
# load wait — the SPA's JS bundle will have rendered its content by then.
# If a future probe identifies a stable "verified leaks loaded" CSS hook
# (e.g. `[data-verified]`, `[data-testid="leak-card"]`), swap it in here.
DEFAULT_WAIT_SELECTOR: str | None = None

# Filter the rendered text down to verified-only blocks.
VERIFIED_BADGE_RE = re.compile(r"\bverified\b", re.IGNORECASE)

# Anonymous-fetch text shape: when not logged in, LeakHub renders only the
# nav bar — total page text is `"LeakHub\nSign in"`. Use this as a positive
# sentinel: if the rendered text matches this shape, our cookies are stale
# (or missing) and we should report it as an auth error not just "empty".
_ANON_SENTINEL_RE = re.compile(r"^\s*LeakHub\s*Sign in\s*$", re.IGNORECASE)


def _load_storage_state() -> dict | None:
    """Resolve ``LEAKHUB_STORAGE_STATE`` env var into a Playwright storage_state dict.

    Accepts either:

      * an inline JSON object — e.g.
        ``{"cookies": [...], "origins": [{"origin": "...", "localStorage": [...]}]}``
      * a filesystem path to a JSON file in the same shape (Playwright's
        ``--save-storage`` output format).

    Returns ``None`` if the env var is unset or empty. Raises
    ``RuntimeError`` with a precise diagnostic if the value is set but
    unparseable — caller surfaces that into ``call_errors`` so the
    operator knows their export went wrong rather than silently getting
    zero results.
    """
    raw = os.environ.get("LEAKHUB_STORAGE_STATE", "").strip()
    if not raw:
        return None

    # Path-form first: if it looks like a path and the file exists, read it.
    candidate_path = raw
    if (
        not raw.startswith("{")
        and len(raw) < 2048
        and os.path.exists(candidate_path)
    ):
        try:
            with open(candidate_path, "r", encoding="utf-8") as f:
                parsed = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"LEAKHUB_STORAGE_STATE points to {candidate_path!r} but the "
                f"file could not be read as JSON: {exc}"
            ) from exc
    else:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"LEAKHUB_STORAGE_STATE must be a JSON object (Playwright "
                f"storage_state shape) or a path to such a file; got "
                f"malformed JSON: {exc}. See "
                f"src/rogue/harvest/sources/leakhub_scrape.py module "
                f"docstring for the capture procedure."
            ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(
            "LEAKHUB_STORAGE_STATE must decode to a JSON object "
            f"(Playwright storage_state shape); got {type(parsed).__name__}."
        )
    # Sanity-check the shape — both keys are optional individually but at
    # least one must be present, otherwise we're not actually injecting auth.
    if not parsed.get("cookies") and not parsed.get("origins"):
        raise RuntimeError(
            "LEAKHUB_STORAGE_STATE decoded to an object with neither "
            "`cookies` nor `origins` — nothing to inject. Re-run "
            "`uv run python scripts/_capture_leakhub_storage.py` after "
            "signing into LeakHub."
        )
    return parsed


class LeakHubScrapePlugin(SourcePlugin):
    """LeakHub.ai verified system-prompt-leak harvester (authed Scraping Browser)."""

    name = "leakhub_scrape"
    source_type = "other"  # no closer match in SourceType literal — locked Day 0
    bright_data_product = "scraping_browser"
    required_capabilities: frozenset[Capability] = frozenset({Capability.BROWSER})

    def __init__(
        self,
        providers: Iterable[str] | None = None,
        wait_for_selector: str | None = DEFAULT_WAIT_SELECTOR,
        scroll_pages: int = 2,
    ) -> None:
        self.providers: list[str] = (
            list(providers) if providers is not None else list(DEFAULT_PROVIDERS)
        )
        self.wait_for_selector = wait_for_selector
        self.scroll_pages = scroll_pages
        # Per-call telemetry surfaced into PluginRunReport.call_errors.
        self.call_errors: list[str] = []
        # Per-run telemetry: lets the orchestrator detect a stale-cookie / no-auth
        # run separately from a real-network failure.
        self.last_run_empty_providers: list[str] = []

    def serp_queries(self, since: datetime) -> list[str]:
        """SERP discovery for new verified-leak announcements (docs/sources.md §8-new)."""
        date_str = (since - timedelta(days=1)).strftime("%Y-%m-%d")
        return [f"site:leakhub.ai after:{date_str}"]

    async def fetch_since(
        self,
        fetcher: Fetcher,
        since: datetime,
    ) -> list[RawDocument]:
        """Per provider: render the browse route, keep verified-only content."""
        self.call_errors = []
        self.last_run_empty_providers = []
        docs: list[RawDocument] = []
        fetched_at = datetime.now(timezone.utc)

        try:
            storage_state = _load_storage_state()
        except RuntimeError as exc:
            self.call_errors.append(str(exc))
            logger.warning("leakhub: %s", exc)
            return []

        if storage_state is None:
            msg = (
                "LEAKHUB_STORAGE_STATE unset — LeakHub is a Convex/SPA app whose "
                "auth lives in localStorage (zero cookies, even when authed). "
                "Skipping all providers. Run "
                "`uv run python scripts/_capture_leakhub_storage.py` to capture "
                "your signed-in storage state."
            )
            self.call_errors.append(msg)
            logger.warning(msg)
            return []

        empty_providers: list[str] = []

        for provider in self.providers:
            url = f"{LEAKHUB_BASE}/prompts/{provider}"
            try:
                page = await fetcher.browser(
                    url,
                    wait_for_selector=self.wait_for_selector,
                    scroll_pages=self.scroll_pages,
                    storage_state=storage_state,
                )
            except NotImplementedError:
                raise
            except Exception as exc:
                msg = f"provider={provider}: {type(exc).__name__}: {exc}"
                self.call_errors.append(msg)
                logger.warning("leakhub fetch failed: %s", msg)
                empty_providers.append(provider)
                continue

            raw_content = page.rendered_text or page.html
            if not raw_content:
                empty_providers.append(provider)
                continue

            # Detect stale-cookie sentinel BEFORE the verified-badge check so
            # the operator sees "cookies expired" instead of the generic
            # "no verified leaks found".
            if _ANON_SENTINEL_RE.match(page.rendered_text or ""):
                msg = (
                    f"provider={provider}: LeakHub rendered the Sign-in nav only — "
                    "LEAKHUB_STORAGE_STATE appears stale or invalid "
                    "(Convex JWT may have expired; re-run "
                    "scripts/_capture_leakhub_storage.py)."
                )
                self.call_errors.append(msg)
                logger.warning(msg)
                empty_providers.append(provider)
                continue

            if not VERIFIED_BADGE_RE.search(raw_content):
                empty_providers.append(provider)
                continue

            content_format = "text" if page.rendered_text else "html"
            archive_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
            try:
                docs.append(
                    RawDocument(
                        url=url,
                        source_type=self.source_type,
                        bright_data_product=self.bright_data_product,
                        fetched_at=fetched_at,
                        raw_content=raw_content,
                        content_format=content_format,
                        archive_hash=archive_hash,
                        http_status=200,  # scrape_browser doesn't expose a code
                        metadata={
                            "provider": provider,
                            "site": "leakhub.ai",
                            "verified_filter": True,
                        },
                        discovered_via=None,
                    )
                )
            except Exception as exc:
                msg = f"provider={provider}: RawDocument build failed: {exc}"
                self.call_errors.append(msg)
                logger.debug(msg)
                empty_providers.append(provider)
                continue

        self.last_run_empty_providers = empty_providers
        _ = since  # site has no per-doc timestamp to filter on
        return docs
