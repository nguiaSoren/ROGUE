"""Slack request-signature verification — the security gate for the §8 inbound endpoint.

Slack signs every request to a Request URL with an HMAC-SHA256 over
``f"v0:{timestamp}:{raw_body}"`` keyed by the app's signing secret, and ships it in the
``X-Slack-Signature`` (``v0=<hex>``) + ``X-Slack-Request-Timestamp`` headers. This module
implements that scheme exactly and nothing else: it is a PURE, dependency-free, unit-testable
predicate. The HTTP route (``rogue.api.v1.slack_events``) reads the raw bytes + headers and
calls :func:`verify_slack_signature`; this module never touches FastAPI, Slack, or the network.

Two non-negotiables (security-critical):

* **Replay guard** — reject when the request timestamp is more than ``max_age_seconds`` (300s,
  Slack's recommendation) away from now in either direction.
* **Constant-time compare** — the final comparison uses :func:`hmac.compare_digest` so a
  rejected signature leaks no timing information about how many leading bytes matched.

``now`` is injectable so the replay window is deterministically testable.

Side-effect-free import (stdlib only).
"""

from __future__ import annotations

import hashlib
import hmac
import time

__all__ = ["verify_slack_signature"]


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now: float | None = None,
    max_age_seconds: int = 300,
) -> bool:
    """Return ``True`` iff ``signature`` is Slack's valid v0 HMAC for ``body`` at ``timestamp``.

    Rejects (returns ``False``, never raises) when:

    * ``timestamp`` is missing / non-numeric;
    * the request is stale — ``abs(now - int(timestamp)) > max_age_seconds`` (replay guard);
    * ``signature`` is missing / not the ``v0=<hex>`` shape.

    Otherwise computes ``"v0=" + hmac_sha256(signing_secret, f"v0:{timestamp}:{body}")`` and
    compares it to ``signature`` with :func:`hmac.compare_digest` (constant-time). PURE — ``now``
    is injectable so the replay window can be exercised deterministically in tests.
    """
    if not signing_secret or not timestamp or not signature:
        return False

    # Replay guard: the timestamp must be numeric and within the freshness window.
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - ts) > max_age_seconds:
        return False

    # Slack signatures are exactly the "v0=<hex>" shape; anything else is malformed.
    if not signature.startswith("v0="):
        return False

    basestring = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}".encode()
    expected = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
