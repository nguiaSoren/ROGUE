"""Surface-1 auto-fire delivery — the worker-side glue that turns a finished policy scan into a
Slack security-channel breach diff (build-area 06 §4, auto-fire path).

Two pieces, both side-effect-free at import (no DB, no network at module load):

* :func:`make_slack_channel_sender` — the bot-token transport. Unlike the incoming-webhook
  ``SlackDestination`` (``rogue.platform.integrations.slack``), this posts to the Slack Web API
  ``chat.postMessage`` with a ``Bearer`` bot token, which is what lets us target a *channel id*
  (the agent's security channel) rather than a single pre-bound webhook URL. Mirrors
  ``_default_sender``'s posture exactly: lazy ``import httpx``, short timeout, and log-and-swallow
  on any transport error OR a non-``ok`` Slack response — a post failure never propagates.

* :class:`SlackSurface1Delivery` — the gate + dispatch the worker calls after a scan finalizes.
  It is a no-op for any scan that isn't a Surface-1 Slack policy scan (detected by the presence
  of ``report_payload["surface1_context"]``), looks the agent registration back up to find its
  security channel, and delegates the actual render+post to :func:`post_breach_diff`. Everything
  is best-effort: a missing registration, a render error, or a Slack outage is logged and turns
  into ``None`` — never an exception — because the scan it describes has already completed.

Remediation is intentionally left ``None`` on this hands-free path: the auto-fired post carries
"mitigation pending" (a paid remediation run is a separate, deliberate step — ADR-0010 / the
marketing-honesty filter: ROGUE never claims a fix it hasn't verified).
"""

from __future__ import annotations

import logging

from .diff_post import Sender, post_breach_diff

logger = logging.getLogger(__name__)

_CHAT_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"


def make_slack_channel_sender(bot_token: str) -> Sender:
    """Build the bot-token channel transport: an async ``(channel, payload) -> None`` that POSTs to
    the Slack Web API ``chat.postMessage``.

    ``httpx`` is imported lazily inside the sender so importing this module never requires it, and
    any transport error OR a non-``ok`` Slack response is logged + swallowed (mirroring
    ``_default_sender``) — a delivery failure must never propagate into the worker's finalize path.
    """

    async def _sender(channel: str, payload: dict) -> None:
        try:
            import httpx

            body = {
                "channel": channel,
                "text": payload.get("text", ""),
                "blocks": payload.get("blocks"),
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    _CHAT_POST_MESSAGE_URL,
                    headers={"Authorization": f"Bearer {bot_token}"},
                    json=body,
                )
                response.raise_for_status()
                data = response.json()
            if not data.get("ok"):
                logger.warning(
                    "slack: chat.postMessage returned not-ok (%s) — scan result still recorded",
                    data.get("error"),
                )
        except Exception as exc:  # noqa: BLE001 - a Slack outage must never break the cycle
            logger.warning("slack: chat.postMessage failed (%s) — scan result still recorded", exc)

    return _sender


class SlackSurface1Delivery:
    """Gate + dispatch for the worker's auto-fire: render a finished Surface-1 policy scan's breach
    diff and post it to the agent's security channel.

    Injected seams (no DB/network at construction): ``agent_store`` (looks a registration back up),
    ``sender`` (the channel transport), and an optional ``snapshot_store`` (content-addressed
    transcript capture). Remediation is fixed to ``None`` here — the auto-fired post is hands-free
    and says "mitigation pending" rather than claiming an unverified patch."""

    def __init__(self, *, agent_store, sender: Sender, snapshot_store=None) -> None:
        self._agent_store = agent_store
        self._sender = sender
        self._snapshot_store = snapshot_store

    async def deliver(self, report_payload: dict, *, org_id: str, scan_id: str) -> dict | None:
        """Post the breach diff for one finished scan, or no-op.

        Returns ``None`` (posts nothing) when this isn't a Surface-1 Slack scan (no
        ``surface1_context``), when the agent registration is gone, when there's no breach, or on
        any error — delivery is best-effort and never raises (the scan has already completed)."""
        surface1_context = report_payload.get("surface1_context")
        if not surface1_context:
            return None  # not a Surface-1 Slack scan — no-op

        try:
            agent = surface1_context["agent"]
            target = self._agent_store.get(org_id, agent["agent_name"])
            if target is None:
                logger.warning(
                    "slack auto-fire: registration gone for org=%s agent=%s (scan %s) — skipping post",
                    org_id,
                    agent.get("agent_name"),
                    scan_id,
                )
                return None
            return await post_breach_diff(
                report_payload,
                agent_target=target,
                org_id=org_id,
                sender=self._sender,
                snapshot_store=self._snapshot_store,
            )
        except Exception as exc:  # noqa: BLE001 - auto-fire is best-effort; never fail a completed scan
            logger.warning(
                "slack auto-fire: delivery failed for scan %s (scan result preserved): %s", scan_id, exc
            )
            return None


__all__ = ["make_slack_channel_sender", "SlackSurface1Delivery"]
