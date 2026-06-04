"""Slack destination — a per-tenant incoming-webhook notification on scan completion.

Generalizes ``threat_brief._maybe_post_to_slack`` (one process-wide ``SLACK_WEBHOOK_URL``) into a
per-tenant ``SlackDestination(webhook_url)`` that an org configures once and the dispatcher fans
events to. Builds a small Block Kit message — headline + score/breaches/top-attack, with a button
linking to the full report — and POSTs it via an injectable async ``sender``.

The default sender is a lazy ``httpx`` POST (5s timeout, errors logged + swallowed). Tests inject a
fake sender that records the payload, so no real HTTP is involved.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from rogue.platform.integrations.dispatcher import ScanCompletedEvent

logger = logging.getLogger(__name__)

# An injectable transport: given the webhook URL and the JSON-able payload, deliver it. Async so it
# composes with the dispatcher's concurrent fan-out; returns None (Slack's response body is unused).
Sender = Callable[[str, dict], Awaitable[None]]


async def _default_sender(url: str, payload: dict) -> None:
    """The real transport: a lazy ``httpx`` POST with a short timeout that never raises.

    ``httpx`` is imported inside the function so merely importing this module (e.g. for tests with a
    fake sender) doesn't require the dependency, and a network failure logs a WARNING instead of
    crashing the dispatch — the same contract as the threat-brief webhook.
    """
    try:
        import httpx

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - a Slack outage must never break dispatch
        logger.warning("slack: webhook post failed (%s) — scan result still recorded", exc)


class SlackDestination:
    """Posts a Block Kit scan summary to one org's incoming webhook."""

    name = "slack"

    def __init__(self, webhook_url: str, *, sender: Sender | None = None) -> None:
        self.webhook_url = webhook_url
        self._sender: Sender = sender or _default_sender

    def build_payload(self, event: ScanCompletedEvent) -> dict:
        """Compose the Slack message — Block Kit ``blocks`` plus a ``text`` summary fallback.

        The fallback ``text`` is what clients without Block Kit support (and notifications) show, so
        the score / breach ratio / top attack all live there too — not only inside the blocks.
        """
        score = round(event.score)
        top = event.top_attack or "none"
        summary = (
            f"ROGUE scan complete — score {score}/100, "
            f"{event.n_breaches}/{event.n_tests} breached, top: {top}"
        )

        blocks: list[dict] = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f":shield: *{summary}*"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Target:*\n{event.target}"},
                    {"type": "mrkdwn", "text": f"*Status:*\n{event.status}"},
                    {"type": "mrkdwn", "text": f"*Score:*\n{score}/100"},
                    {"type": "mrkdwn", "text": f"*Breaches:*\n{event.n_breaches}/{event.n_tests}"},
                    {"type": "mrkdwn", "text": f"*Top attack:*\n{top}"},
                ],
            },
        ]
        if event.report_url:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View report"},
                            "url": event.report_url,
                        }
                    ],
                }
            )

        return {"text": summary, "blocks": blocks}

    async def notify(self, event: ScanCompletedEvent) -> None:
        """Build the payload and hand it to the injected sender (which owns failure handling)."""
        payload = self.build_payload(event)
        await self._sender(self.webhook_url, payload)


__all__ = ["SlackDestination", "Sender"]
