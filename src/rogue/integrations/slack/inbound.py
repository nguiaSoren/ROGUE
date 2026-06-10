"""Inbound advisory dispatch — the §8 glue between a live Slack message and a security-channel
ADVISORY (build-area 06 §8). No HTTP here: the FastAPI route (``rogue.api.v1.slack_events``)
verifies the signature + acks Slack fast, then hands the message text + channel to this module
on a background task.

ADR-0010 (load-bearing): advisory-ONLY. This NEVER blocks, modifies, or replies to the original
message; it only posts to the agent's SECURITY channel. And it ONLY acts on a registered SANDBOX
channel — a message in any other channel (including production) is a no-op. The actual prediction
is the existing PURE §6 :func:`tripwire.predict_breach` + §7 :func:`redline_guard.score_inbound`;
this module just routes a sandbox message into them and posts the composed advisory.

Best-effort: a missing prediction input or a Slack outage is logged and turns into ``None`` — a
dispatch failure never propagates (the route has already acked Slack).

Side-effect-free import (no DB/engine/network at module load).
"""

from __future__ import annotations

import logging

from .redline_guard import score_inbound
from .tripwire import predict_breach

logger = logging.getLogger(__name__)

__all__ = ["handle_inbound_message"]


async def handle_inbound_message(
    text: str,
    channel_id: str,
    *,
    agent_store,
    attestation_service,
    sender,
    org_id: str | None = None,
) -> dict | None:
    """Run Tripwire + RedlineGuard on a sandbox-channel message and post an ADVISORY, or no-op.

    ADR-0010: advisory-only. Steps:

    1. Find the registered agent whose ``sandbox_channel_id == channel_id`` (scan
       ``agent_store.all_targets(org_id)``). None → return ``None`` (we only act on consented
       sandbox channels we watch; never production).
    2. Run the PURE §6 :func:`predict_breach` (empirical-prior predictor) and §7
       :func:`score_inbound` (calibrated gate-rule emitter) on the message.
    3. If neither flags risk (Tripwire matched no family / RedlineGuard ``no-match``) → ``None``
       (nothing to advise).
    4. Else compose a short ADVISORY payload (prefixed "⚠️ Tripwire/RedlineGuard (advisory —
       not a block)") and ``await sender(target.security_channel_id, payload)`` — posting to the
       SECURITY channel ONLY, never the sandbox/production channel. Returns the payload (for tests).

    Best-effort: any error is logged and returns ``None`` — never raises.
    """
    try:
        target = next(
            (
                t
                for t in agent_store.all_targets(org_id)
                if t.sandbox_channel_id == channel_id
            ),
            None,
        )
        if target is None:
            # Not a sandbox channel we watch — ADR-0010: never act outside consented sandboxes.
            return None

        prediction = predict_breach(
            target.org_id, target.agent_name, text, attestation_service=attestation_service
        )
        score = score_inbound(
            target.org_id, target.agent_name, text, attestation_service=attestation_service
        )

        # Nothing flagged risk on either path → nothing worth advising the security channel about.
        if prediction.matched_family is None and score.risk == "no-match":
            return None

        lines = [
            "⚠️ Tripwire/RedlineGuard (advisory — not a block)",
            f"*Agent:* {target.agent_name}  *Sandbox:* {channel_id}",
            f"*Inbound:* {prediction.inbound_excerpt}",
            f"*Tripwire:* {prediction.recommendation}",
            f"*RedlineGuard:* {score.recommendation}",
        ]
        if score.rule is not None:
            lines.append(f"*Gate rule:* {score.rule.artifact}")
        payload = {"text": "\n".join(lines)}

        await sender(target.security_channel_id, payload)
        return payload
    except Exception as exc:  # noqa: BLE001 - advisory is best-effort; a failure never propagates
        logger.warning(
            "slack inbound advisory: dispatch failed for channel %s (advisory only, no enforcement): %s",
            channel_id,
            exc,
        )
        return None
