"""Read/write the DiscoveryAgent bandit state in the DB.

The bandit's learned arm yields live in ``data/discovery_bandit.json`` (written
by the harvest). Mirroring that same dict into a single ``bandit_state`` row lets
``/api/bandit/stats`` serve it live from the database instead of a file baked into
the deploy — so the widget updates on each harvest, no redeploy needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from rogue.db.models import BanditState


def save_bandit_state(session: Session, state: dict[str, Any]) -> None:
    """Upsert the bandit state into the single ``bandit_state`` row (id=1)."""
    session.merge(
        BanditState(id=1, state=state, updated_at=datetime.now(timezone.utc))
    )
    session.commit()


def load_bandit_state(session: Session) -> dict[str, Any] | None:
    """Return the stored bandit state dict, or ``None`` if no row exists yet."""
    row = session.get(BanditState, 1)
    return row.state if row is not None else None
