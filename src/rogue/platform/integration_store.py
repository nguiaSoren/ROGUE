"""Per-org stored integrations (Slack / Jira) — so a tool references an integration by NAME and the
agent never handles the raw credential.

The enterprise model the tool-args approach was a placeholder for:

    Organization → stored Integration (config + secret_ref → SecretStore) → MCP tool references by name

An ops/admin path (`scripts/add_integration.py`) registers an org's integration once (the secret is
encrypted into the `secrets` table via the `SecretStore`); thereafter `send_slack_alert(scan_id,
integration="slack-sec")` / `create_jira_ticket(scan_id, integration="jira-prod")` resolve the config +
decrypt the secret server-side. The LLM only ever sees the integration's NAME.
"""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass

from sqlalchemy import select

from .memory import _new_id

_DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


@dataclass
class ResolvedIntegration:
    kind: str  # "slack" | "jira"
    name: str
    config: dict  # non-secret (e.g. jira base_url / project_key / email)
    secret: str | None  # the decrypted credential (slack webhook url / jira api_token)


class IntegrationStore(abc.ABC):
    @abc.abstractmethod
    def put(self, *, org_id: str, kind: str, name: str, config: dict, secret: str | None) -> str: ...

    @abc.abstractmethod
    def get(self, org_id: str, name: str) -> ResolvedIntegration | None: ...

    @abc.abstractmethod
    def list(self, org_id: str) -> list[dict]: ...  # [{kind, name}] — never secrets


class InMemoryIntegrationStore(IntegrationStore):
    def __init__(self) -> None:
        self._d: dict[tuple[str, str], tuple[str, str, dict, str | None]] = {}

    def put(self, *, org_id, kind, name, config, secret) -> str:
        iid = _new_id("intg")
        self._d[(org_id, name)] = (iid, kind, dict(config or {}), secret)
        return iid

    def get(self, org_id, name) -> ResolvedIntegration | None:
        v = self._d.get((org_id, name))
        return ResolvedIntegration(kind=v[1], name=name, config=v[2], secret=v[3]) if v else None

    def list(self, org_id) -> list[dict]:
        return [{"kind": v[1], "name": n} for (o, n), v in self._d.items() if o == org_id]


class PostgresIntegrationStore(IntegrationStore):
    """Durable store; the credential is encrypted into the `secrets` table via the `SecretStore`."""

    def __init__(self, session_factory, secret_store) -> None:
        self._sf = session_factory
        self._secrets = secret_store

    def put(self, *, org_id, kind, name, config, secret) -> str:
        from datetime import datetime, timezone

        from .models import Integration

        secref = self._secrets.put(secret, org_id=org_id) if secret is not None else None
        with self._sf() as s:
            row = s.execute(
                select(Integration).where(Integration.org_id == org_id, Integration.name == name)
            ).scalar_one_or_none()
            if row is not None:
                row.kind = kind
                row.config = dict(config or {})
                row.secret_ref = secref
                iid = row.integration_id
            else:
                iid = _new_id("intg")
                s.add(
                    Integration(
                        integration_id=iid, org_id=org_id, kind=kind, name=name,
                        config=dict(config or {}), secret_ref=secref, created_at=datetime.now(timezone.utc),
                    )
                )
            s.commit()
        return iid

    def get(self, org_id, name) -> ResolvedIntegration | None:
        from .models import Integration

        with self._sf() as s:
            row = s.execute(
                select(Integration).where(Integration.org_id == org_id, Integration.name == name)
            ).scalar_one_or_none()
            if row is None:
                return None
            secret = self._secrets.resolve(row.secret_ref, org_id=org_id) if row.secret_ref else None
            return ResolvedIntegration(kind=row.kind, name=row.name, config=dict(row.config or {}), secret=secret)

    def list(self, org_id) -> list[dict]:
        from .models import Integration

        with self._sf() as s:
            rows = s.execute(select(Integration).where(Integration.org_id == org_id)).scalars().all()
            return [{"kind": r.kind, "name": r.name} for r in rows]


def build_postgres_integration_store(secret_store, database_url: str | None = None):
    """Build a `PostgresIntegrationStore`, or None if no `secret_store` (can't store secrets without
    encryption — falls back to the raw-args tool path)."""
    if secret_store is None:
        return None
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = database_url or os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
    return PostgresIntegrationStore(sessionmaker(bind=engine), secret_store)


__all__ = [
    "ResolvedIntegration", "IntegrationStore", "InMemoryIntegrationStore",
    "PostgresIntegrationStore", "build_postgres_integration_store",
]
