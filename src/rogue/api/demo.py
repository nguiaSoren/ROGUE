"""Demo-request lead-capture endpoint (``POST /api/demo-request``).

A standalone, unauthenticated lead-capture route for the marketing site's
"request a demo" form. Inserts a ``DemoRequest`` row and best-effort pings Slack
(reusing the ``SLACK_WEBHOOK_URL`` pattern from ``rogue.diff.threat_brief``).

Frontend contract (do not deviate)::

    POST {API_BASE}/api/demo-request
      JSON {name, company, email, deployment_type, message}
    → 201 {"ok": true, "id": <int>}
    → 422 on a bad email

The Slack ping is non-fatal: a webhook outage (or an unset env var) must never
turn a successful lead capture into a 500.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from rogue.api.main import get_session
from rogue.db.models import DemoRequest

logger = logging.getLogger("rogue.api.demo")

router = APIRouter(prefix="/api", tags=["leads"])


class DemoRequestBody(BaseModel):
    """Wire body for ``POST /api/demo-request`` — storage twin is ``DemoRequest``."""

    email: str = Field(..., max_length=320)
    name: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    deployment_type: str | None = Field(default=None, max_length=60)
    message: str | None = Field(default=None, max_length=4000)
    source: str | None = Field(default="request-demo", max_length=60)

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip()
        at = v.find("@")
        # Plausible-email check: exactly the contract — an "@" with a "." after it,
        # and non-empty local/domain parts. Reject anything else with 422.
        if at <= 0 or "." not in v[at + 1 :] or v.endswith("."):
            raise ValueError("email must be a plausible address (e.g. you@company.com)")
        return v


def _maybe_post_to_slack(req: DemoRequest) -> None:
    """Best-effort Slack ping for a new demo request.

    No-op when ``SLACK_WEBHOOK_URL`` is unset/empty/commented. Network failure
    logs a WARNING but never raises — a Slack outage must not fail the request.
    Mirrors the synchronous ``httpx`` pattern in ``rogue.diff.threat_brief``.
    """
    webhook_url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    if not webhook_url or webhook_url.startswith("#"):
        return

    who = req.company or req.email
    lines = [f":wave: *New ROGUE demo request* from *{who}*", f"• email: {req.email}"]
    if req.name:
        lines.append(f"• name: {req.name}")
    if req.deployment_type:
        lines.append(f"• deployment: {req.deployment_type}")
    if req.message:
        snippet = req.message if len(req.message) <= 300 else req.message[:297] + "..."
        lines.append(f"• message: {snippet}")

    try:
        import httpx

        response = httpx.post(webhook_url, json={"text": "\n".join(lines)}, timeout=10.0)
        response.raise_for_status()
        logger.info("slack: posted demo-request ping (id=%s)", req.id)
    except Exception as exc:  # noqa: BLE001 - never let Slack crash a lead capture
        logger.warning("slack: demo-request ping failed (non-fatal): %s", exc)


@router.post("/demo-request", status_code=201)
def create_demo_request(
    body: DemoRequestBody,
    db: Session = Depends(get_session),
) -> dict[str, object]:
    """Persist a demo-request lead and best-effort notify Slack."""
    req = DemoRequest(
        email=body.email,
        name=body.name,
        company=body.company,
        deployment_type=body.deployment_type,
        message=body.message,
        source=body.source,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    _maybe_post_to_slack(req)

    return {"ok": True, "id": req.id}
