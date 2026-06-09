"""Surface 1 → Slack security-channel diff post (build-area 06 §4).

When a per-rule policy scan finishes, this builds the Block Kit message that lands in the
agent's *security* channel — one section per **breaching** rule, with the trial-outcome CI,
the calibration status, a content-addressed transcript pointer, and (when wired) the inline
verified patch from Surface 1b's remediation loop.

Two seams keep this testable and honest:

* **Render from the per-rule report, never from findings.** We read each
  ``RuleVerdict`` out of ``report_payload["rule_breach_report"]["rule_verdicts"]``
  (a ``RuleBreachReport.model_dump()``), so the family / breach_type / N-of-M / CI shown
  are the judged per-rule numbers — not ``ScanReport.findings``' approximate rule→family map.
* **Never overclaim a fix.** The "Patch below" section appears ONLY when an injected
  ``RemediationResult`` is present AND ``accepted``; otherwise the post says mitigation is
  pending (marketing-honesty filter / ADR-0010 — ROGUE generates+verifies, never enforces).

Side-effect-free import (no DB, no network at module load). The transport (``sender``), the
capture store (``snapshot_store``), and remediation (``remediation``) are all injected; a send
failure is logged + swallowed, mirroring ``SlackDestination`` — a Slack outage must never crash
the red-team cycle. The post goes to ``security_channel_id`` and NOTHING ELSE; the sandbox
channel is where scans run, never where breach diffs are announced.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from rogue.integrations.slack.registration import SlackAgentTarget

logger = logging.getLogger(__name__)

# Mirror SlackDestination.Sender: (target_channel_or_url, payload) -> awaitable None.
Sender = Callable[[str, dict], Awaitable[None]]

# An injected async remediation hook: (report_payload, breaching_verdict_dict) -> RemediationResult|None.
# The live path wraps RemediationLoop.run; tests inject a fake returning a canned accepted result.
Remediation = Callable[[dict, dict], Awaitable[object]]

_MAX_PATCH_CHARS = 1200  # keep the inline patch section to a sane Block Kit length


def _verdict_summary(v: dict) -> str:
    """One human line for a breaching verdict: 'breaks 3/8 · [0.12–0.71] · uncalibrated'."""
    n_trials = int(v.get("n_trials") or 0)
    n_breaches = int(v.get("n_breaches") or 0)
    holds = n_trials - n_breaches
    parts = [f"breaks {n_breaches}/{n_trials}", f"holds {holds}/{n_trials}"]
    ci_low, ci_high = v.get("ci_low"), v.get("ci_high")
    if ci_low is not None and ci_high is not None:
        parts.append(f"CI [{ci_low:.2f}–{ci_high:.2f}]")
    parts.append(str(v.get("calibration_status") or "uncalibrated"))
    return " · ".join(parts)


def _transcript_pointer(v: dict, snapshot_refs: Optional[dict[str, str]]) -> Optional[str]:
    """Prefer the captured snapshot_ref for this rule; else the verdict's first raw marker."""
    rule_id = v.get("rule_id")
    if snapshot_refs and rule_id in snapshot_refs:
        return snapshot_refs[rule_id]
    refs = v.get("transcript_refs") or []
    return refs[0] if refs else None


def build_security_post(
    report_payload: dict,
    *,
    agent_target: SlackAgentTarget,
    snapshot_refs: dict[str, str] | None = None,
    mitigation=None,
) -> dict:
    """Pure Block Kit builder (no I/O) for the security-channel breach diff.

    Renders one section per breaching rule verdict (``n_breaches > 0``) read from
    ``report_payload["rule_breach_report"]["rule_verdicts"]``. The mitigation line reflects an
    injected ``RemediationResult`` only when it is ``accepted`` — never claiming a verified patch
    otherwise. Returns ``{"text": ..., "blocks": [...]}``; the headline also lives in ``text`` so
    notification-only clients see it (the SlackDestination contract).
    """
    report = report_payload.get("rule_breach_report") or {}
    verdicts = report.get("rule_verdicts") or []
    breaching = [v for v in verdicts if int(v.get("n_breaches") or 0) > 0]

    headline = f"🔴 New-corpus red-team — {agent_target.agent_name} ({agent_target.workspace})"

    if not breaching:
        text = f"✅ No new-corpus breaches this cycle — {agent_target.agent_name} ({agent_target.workspace})"
        return {
            "text": text,
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}}],
        }

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": headline, "emoji": True}}
    ]

    summary_rules: list[str] = []
    for v in breaching:
        rule_id = v.get("rule_id") or "?"
        breach_type = v.get("breach_type") or "?"
        family = v.get("attack_family") or "—"
        line = _verdict_summary(v)
        summary_rules.append(f"{rule_id} ({breach_type}): {line}")

        section_lines = [
            f"*{rule_id}* — `{breach_type}`",
            f"family: *{family}*",
            line,
        ]
        pointer = _transcript_pointer(v, snapshot_refs)
        if pointer:
            section_lines.append(f"transcript: `{pointer}`")
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(section_lines)}}
        )

    # Mitigation line — accepted patch (inline), else honest "pending".
    accepted = bool(mitigation is not None and getattr(mitigation, "accepted", False))
    if accepted:
        candidate = getattr(mitigation, "candidate", None)
        artifact = (getattr(candidate, "artifact", "") or "").strip()
        if len(artifact) > _MAX_PATCH_CHARS:
            artifact = artifact[:_MAX_PATCH_CHARS] + " …(truncated)"
        post_rate = getattr(mitigation, "post_breach_rate", None)
        post_ci = getattr(mitigation, "post_breach_ci", None)
        rate_bits = []
        if post_rate is not None:
            rate_bits.append(f"post-breach rate {post_rate:.2%}")
        if post_ci is not None:
            rate_bits.append(f"CI [{post_ci[0]:.2f}–{post_ci[1]:.2f}]")
        rate_line = (" · ".join(rate_bits)) if rate_bits else "verified by re-scan"
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🛠 *Patch below* ({rate_line}):\n```{artifact}```",
                },
            }
        )
        mitigation_text = f" — patch verified ({rate_line})"
    else:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "🛠 Mitigation pending (Surface 1b)"},
            }
        )
        mitigation_text = " — mitigation pending"

    text = (
        f"{headline} — {len(breaching)} breaching rule(s): "
        + "; ".join(summary_rules)
        + mitigation_text
    )
    return {"text": text, "blocks": blocks}


async def post_breach_diff(
    report_payload: dict,
    *,
    agent_target: SlackAgentTarget,
    org_id: str,
    sender: Sender,
    snapshot_store=None,
    remediation: Remediation | None = None,
    transcripts: dict[str, str] | None = None,
) -> dict | None:
    """Capture evidence, run remediation, build the post, and send it to the security channel.

    Steps (all seams injectable, no network in tests):
      1. Pull ``rule_breach_report``; if absent or no breaching rules → return ``None`` (post nothing).
      2. For each breaching rule capture transcript evidence into ``snapshot_store`` (org-scoped),
         keyed by rule_id; when no store is given, refs fall back to the verdict's raw markers.
      3. If ``remediation`` is given, run it against the first breaching verdict to get an inline
         ``RemediationResult`` (only an *accepted* one renders a patch).
      4. Build the payload from the per-rule report.
      5. Send ONLY to ``agent_target.security_channel_id`` (never the sandbox channel); a send
         failure is logged + swallowed.
      6. Return the payload (so callers/tests can assert it).
    """
    report = report_payload.get("rule_breach_report") or {}
    verdicts = report.get("rule_verdicts") or []
    breaching = [v for v in verdicts if int(v.get("n_breaches") or 0) > 0]
    if not breaching:
        return None

    # 2. Capture transcript evidence → content-addressed refs (real capture lives here: we have org_id).
    snapshot_refs: dict[str, str] = {}
    if snapshot_store is not None:
        for v in breaching:
            rule_id = v.get("rule_id")
            if not rule_id:
                continue
            text: str | None = None
            if transcripts:
                text = transcripts.get(rule_id)
                if text is None:
                    for marker in v.get("transcript_refs") or []:
                        if marker in transcripts:
                            text = transcripts[marker]
                            break
            if text is None:
                # No supplied transcript text — serialize the verdict's markers as the evidence blob.
                markers = v.get("transcript_refs") or []
                text = "\n".join(markers) if markers else f"{rule_id}: no transcript markers"
            try:
                ref = snapshot_store.put(text, org_id=org_id, content_type="transcript")
                snapshot_refs[rule_id] = ref
            except Exception as exc:  # noqa: BLE001 - capture failure must not crash the cycle
                logger.warning("slack diff: snapshot capture failed for %s (%s)", rule_id, exc)

    # 3. Inline remediation (optional) — run against the first breaching verdict.
    result = None
    if remediation is not None:
        try:
            result = await remediation(report_payload, breaching[0])
        except Exception as exc:  # noqa: BLE001 - a remediation failure must not block the alert
            logger.warning("slack diff: remediation hook failed (%s) — posting without patch", exc)
            result = None

    # 4. Build the payload.
    payload = build_security_post(
        report_payload,
        agent_target=agent_target,
        snapshot_refs=snapshot_refs or None,
        mitigation=result,
    )

    # 5. Post ONLY to the security channel; log + swallow failures.
    try:
        await sender(agent_target.security_channel_id, payload)
    except Exception as exc:  # noqa: BLE001 - a Slack outage must never break the cycle
        logger.warning("slack diff: security-channel post failed (%s) — scan still recorded", exc)

    # 6. Return the payload for callers/tests.
    return payload


__all__ = ["build_security_post", "post_breach_diff"]
