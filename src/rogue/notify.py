"""Best-effort on-demand revalidation ping to the frontend.

The dashboard pages (/matrix, /brief, /feed, /) are statically prerendered with
~5-min ISR, so newly-written breaches otherwise surface within ~5 min. After a
harvest/reproduce run finishes (and auto-syncs to Neon), we POST the frontend's
`/api/revalidate` route so those pages regenerate immediately — latest data, no
polling, no wait.

Best-effort by design: never raises and never blocks the run. A failed ping just
logs a warning; the pages still refresh on the normal ISR cycle.

Env (both must be set, or the ping is skipped):
    FRONTEND_REVALIDATE_URL   e.g. https://rogue-eosin.vercel.app/api/revalidate
    REVALIDATE_TOKEN          shared secret (also set in the Vercel project env)
"""

from __future__ import annotations

import logging
import os
import urllib.request

logger = logging.getLogger(__name__)


def revalidate_frontend(timeout: float = 10.0) -> bool:
    """POST the frontend revalidate hook. Returns True on a 2xx, else False.

    No-op (returns False) when the env vars are unset — so local/dev runs and
    CI don't need them configured.
    """
    url = os.environ.get("FRONTEND_REVALIDATE_URL")
    token = os.environ.get("REVALIDATE_TOKEN")
    if not url or not token:
        logger.info(
            "revalidate: skipped (FRONTEND_REVALIDATE_URL / REVALIDATE_TOKEN unset)"
        )
        return False
    try:
        req = urllib.request.Request(
            url, data=b"", method="POST", headers={"x-revalidate-token": token}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            ok = 200 <= resp.status < 300
            logger.info("revalidate: POST %s -> %s", url, resp.status)
            return ok
    except Exception as exc:  # noqa: BLE001 - best-effort; must never fail a run
        logger.warning(
            "revalidate: ping failed (%s) — pages will refresh on the ~5-min ISR cycle",
            exc,
        )
        return False


def post_slack_webhook(text: str, *, webhook_url: str | None = None) -> bool:
    """Best-effort Slack post for agent-exec runner pings (start/breach/cap/done/crash).

    Mirrors ``diff.threat_brief._maybe_post_to_slack``: no-op when the webhook is unset,
    never raises (a Slack outage must never break or block a run). Fixes the cost-ops
    finding that the runner had no Slack surface — the ``notify-don't-babysit`` convention
    requires the SCRIPT to ping, so a hung/all-errored agent-exec sweep can't hide.

    Env: ``SLACK_WEBHOOK_URL`` (same var as the threat brief) unless ``webhook_url`` is passed.
    Returns True on a delivered 2xx, else False.
    """
    url = (webhook_url or os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    if not url or url.startswith("#"):
        return False
    try:
        import httpx  # noqa: PLC0415 — only needed on the ping path

        # follow_redirects=True is load-bearing: Slack webhooks answer a POST with a 302 that
        # httpx will NOT follow by default, so raise_for_status() then treated a LIVE webhook as a
        # failure — the real reason runner pings silently "never worked".
        resp = httpx.post(url, json={"text": text}, timeout=10.0, follow_redirects=True)
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — never let a Slack failure surface
        logger.warning("slack ping failed: %s", exc)
        return False
