"""`/v1/slack/events` — the live Slack Events inbound endpoint (build-area 06 §8).

Slack POSTs every message in the agent's sandbox channel here. The handler is deliberately thin
and security-first:

1. Read the RAW body bytes BEFORE parsing — Slack's signature is over the exact raw body.
2. Verify the request signature (:func:`verify_slack_signature`) — 401 on failure, 503 if the
   signing secret isn't configured. Replay-guarded (±300s).
3. Answer the one-time ``url_verification`` handshake by echoing the ``challenge``.
4. For a user ``message`` event (NOT a bot / ``bot_id`` / ``subtype`` message — those would loop),
   schedule the advisory dispatch on a FastAPI ``BackgroundTasks`` and return ``{"ok": True}``
   IMMEDIATELY — Slack retries any request it can't ack in ~3s, so the heavy Tripwire/RedlineGuard
   work must never run in the request path.

ADR-0010 (load-bearing): advisory-only. This endpoint NEVER blocks, modifies, or replies to the
original message; the background task only posts to the agent's SECURITY channel, and only for a
registered SANDBOX channel. Services are pulled from the assembly-wired ``_PLATFORM`` dict at
dispatch time (the same dict the in-process worker reads) so this route stays a thin shell.

Side-effect-free import (no DB/engine/network at module load).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from rogue.config import get_settings
from rogue.integrations.slack.inbound import handle_inbound_message
from rogue.integrations.slack.signing import verify_slack_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["slack"])


async def _dispatch_advisory(text: str, channel_id: str) -> None:
    """Background advisory dispatch: pull services from `_PLATFORM`, build the channel sender, and
    delegate to the PURE :func:`handle_inbound_message`. Best-effort — never raises (it runs after
    the route has already acked Slack)."""
    from rogue.api.main import _PLATFORM
    from rogue.integrations.slack import (
        build_postgres_slack_agent_store,
        make_slack_channel_sender,
    )

    try:
        settings = get_settings()
        bot_token = settings.slack_bot_token
        if bot_token is None:
            logger.warning("slack inbound: SLACK_BOT_TOKEN unset — cannot post advisory")
            return
        sender = make_slack_channel_sender(bot_token.get_secret_value())
        await handle_inbound_message(
            text,
            channel_id,
            agent_store=build_postgres_slack_agent_store(_PLATFORM.get("secret_store")),
            attestation_service=_PLATFORM.get("attestation_service"),
            sender=sender,
        )
    except Exception as exc:  # noqa: BLE001 - background advisory is best-effort
        logger.warning("slack inbound: advisory dispatch failed for channel %s: %s", channel_id, exc)


@router.post("/slack/events")
async def slack_events(request: Request, background_tasks: BackgroundTasks) -> dict:
    # Raw bytes FIRST — the signature is computed over the exact raw body, not a re-serialized parse.
    raw = await request.body()

    secret = get_settings().slack_signing_secret
    if secret is None:
        raise HTTPException(status_code=503, detail="slack signing secret not configured")

    if not verify_slack_signature(
        signing_secret=secret.get_secret_value(),
        timestamp=request.headers.get("X-Slack-Request-Timestamp", ""),
        body=raw,
        signature=request.headers.get("X-Slack-Signature", ""),
    ):
        raise HTTPException(status_code=401, detail="bad slack signature")

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - a signed-but-unparseable body is quietly ignored
        return {"ok": True}

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    if payload.get("type") == "event_callback":
        event = payload.get("event") or {}
        # Only a plain user message triggers an advisory. Skip bot/own messages (`bot_id`) and any
        # message with a `subtype` (edits, joins, bot posts) to avoid an advisory→message loop.
        if (
            event.get("type") == "message"
            and not event.get("bot_id")
            and not event.get("subtype")
        ):
            text = event.get("text") or ""
            channel_id = event.get("channel") or ""
            if text and channel_id:
                # Schedule in the background so Slack gets a fast 200 (it retries after ~3s).
                background_tasks.add_task(_dispatch_advisory, text, channel_id)

    return {"ok": True}


__all__ = ["router"]
