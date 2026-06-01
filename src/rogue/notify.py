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
