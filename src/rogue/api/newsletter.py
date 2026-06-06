"""Newsletter-subscription endpoint (``POST /api/newsletter``).

A standalone, unauthenticated subscription route for the marketing site's
newsletter sign-up form. Inserts a ``NewsletterSubscriber`` row, idempotent on
the unique ``email`` column.

Frontend contract (do not deviate)::

    POST {API_BASE}/api/newsletter
      JSON {email, source}
    → 201 {"ok": true, "id": <int>}                      (new subscriber)
    → 200 {"ok": true, "id": <int>, "already": true}     (existing subscriber)
    → 422 on a bad email

Re-subscribing the same email is a no-op that returns the existing row's id with
``already: true`` — never a 409/500. The unique index on ``email`` is the
backstop; we pre-check by select and also catch the unique-violation in case of
a concurrent insert.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from rogue.api.main import get_session
from rogue.db.models import NewsletterSubscriber

logger = logging.getLogger("rogue.api.newsletter")

router = APIRouter(prefix="/api", tags=["newsletter"])


class NewsletterBody(BaseModel):
    """Wire body for ``POST /api/newsletter`` — storage twin is ``NewsletterSubscriber``."""

    email: str = Field(..., max_length=320)
    source: str | None = Field(default="site", max_length=60)

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


@router.post("/newsletter", status_code=201)
def subscribe_newsletter(
    body: NewsletterBody,
    response: Response,
    db: Session = Depends(get_session),
) -> dict[str, object]:
    """Subscribe an email to the newsletter, idempotent on the email column."""
    # Pre-check: a known email is a no-op returning the existing id (200).
    existing = db.execute(
        select(NewsletterSubscriber).where(NewsletterSubscriber.email == body.email)
    ).scalar_one_or_none()
    if existing is not None:
        response.status_code = 200
        return {"ok": True, "id": existing.id, "already": True}

    sub = NewsletterSubscriber(email=body.email, source=body.source)
    db.add(sub)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent insert beat us to it — fall back to the existing row.
        db.rollback()
        existing = db.execute(
            select(NewsletterSubscriber).where(
                NewsletterSubscriber.email == body.email
            )
        ).scalar_one()
        response.status_code = 200
        return {"ok": True, "id": existing.id, "already": True}

    db.refresh(sub)
    return {"ok": True, "id": sub.id}
