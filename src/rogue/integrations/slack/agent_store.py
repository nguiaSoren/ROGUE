"""Persistence for `SlackAgentTarget` rows — the durable record behind a Slack self-registration.

Mirrors `rogue.platform.integration_store` in structure: an abc + `InMemory…` + `Postgres…` +
a `build_postgres_…` factory. The Postgres impl imports its ORM (`SlackRegisteredAgent`) LAZILY
inside methods, uses `self._sf()` session contexts, `_new_id("slackagent")` ids, and routes a
sensitive prompt through the `SecretStore` (yielding a `secref_…` handle persisted in
`system_prompt_ref` instead of the raw prompt).

Side-effect-free import: no engine is built and no DB connection is opened at module load.
"""

from __future__ import annotations

import abc
import os

from sqlalchemy import select

from rogue.platform.memory import _new_id

from .registration import SlackAgentTarget

_DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"


class SlackAgentStore(abc.ABC):
    @abc.abstractmethod
    def put(self, target: SlackAgentTarget) -> str: ...  # returns agent_id

    @abc.abstractmethod
    def get(self, org_id: str, agent_name: str) -> SlackAgentTarget | None: ...

    @abc.abstractmethod
    def list(self, org_id: str) -> list[dict]: ...  # [{agent_name, workspace}] — never the prompt

    @abc.abstractmethod
    def all_targets(self, org_id: str | None = None) -> list[SlackAgentTarget]: ...
    # Full reconstructed targets (prompt resolved). org_id=None ⇒ every org. Used by the
    # sandbox-cycle trigger to fan a reproduce run across all registered agents.

    @abc.abstractmethod
    def get_client_policy(self, org_id: str, agent_name: str) -> dict | None: ...
    # The cached, serialized `ClientPolicy` dict for an agent (or None if not yet derived /
    # the agent row is absent). The per-rule policy scan (build-06 §4 path A) reads this to
    # skip re-decomposing the policy every cycle.

    @abc.abstractmethod
    def set_client_policy(self, org_id: str, agent_name: str, policy: dict) -> None: ...
    # Cache a serialized `ClientPolicy` dict on the agent row (best-effort; a missing row is a
    # no-op for the Postgres impl).


class InMemorySlackAgentStore(SlackAgentStore):
    def __init__(self) -> None:
        self._d: dict[tuple[str, str], tuple[str, SlackAgentTarget]] = {}
        # Side map for cached, serialized ClientPolicy dicts — kept off the target tuple so the
        # existing put/get/list/all_targets behavior is unchanged.
        self._policies: dict[tuple[str, str], dict] = {}

    def put(self, target: SlackAgentTarget) -> str:
        key = (target.org_id, target.agent_name)
        existing = self._d.get(key)
        agent_id = existing[0] if existing is not None else _new_id("slackagent")
        self._d[key] = (agent_id, target)
        return agent_id

    def get(self, org_id: str, agent_name: str) -> SlackAgentTarget | None:
        v = self._d.get((org_id, agent_name))
        return v[1] if v else None

    def list(self, org_id: str) -> list[dict]:
        return [
            {"agent_name": t.agent_name, "workspace": t.workspace}
            for (o, _), (_, t) in self._d.items()
            if o == org_id
        ]

    def all_targets(self, org_id: str | None = None) -> list[SlackAgentTarget]:
        return [
            t for (o, _), (_, t) in self._d.items() if org_id is None or o == org_id
        ]

    def get_client_policy(self, org_id: str, agent_name: str) -> dict | None:
        return self._policies.get((org_id, agent_name))

    def set_client_policy(self, org_id: str, agent_name: str, policy: dict) -> None:
        self._policies[(org_id, agent_name)] = policy


class PostgresSlackAgentStore(SlackAgentStore):
    """Durable store. A sensitive system prompt is encrypted via the `SecretStore` and only its
    `secref_…` handle is persisted in `system_prompt_ref`; otherwise the prompt is stored inline."""

    def __init__(self, session_factory, secret_store=None) -> None:
        self._sf = session_factory
        self._secrets = secret_store

    def put(self, target: SlackAgentTarget) -> str:
        from datetime import datetime, timezone

        from rogue.platform.models import SlackRegisteredAgent

        if target.system_prompt_sensitive and self._secrets is not None:
            system_prompt_ref = self._secrets.put(target.system_prompt, org_id=target.org_id)
        else:
            system_prompt_ref = target.system_prompt

        with self._sf() as s:
            row = s.execute(
                select(SlackRegisteredAgent).where(
                    SlackRegisteredAgent.org_id == target.org_id,
                    SlackRegisteredAgent.agent_name == target.agent_name,
                )
            ).scalar_one_or_none()
            if row is not None:
                row.workspace = target.workspace
                row.base_url = target.base_url
                row.model = target.model
                row.system_prompt_ref = system_prompt_ref
                row.declared_tools = list(target.declared_tools)
                row.forbidden_topics = list(target.forbidden_topics)
                row.sandbox_channel_id = target.sandbox_channel_id
                row.security_channel_id = target.security_channel_id
                row.rule_pack_ref = target.rule_pack_ref
                agent_id = row.agent_id
            else:
                agent_id = _new_id("slackagent")
                s.add(
                    SlackRegisteredAgent(
                        agent_id=agent_id,
                        org_id=target.org_id,
                        agent_name=target.agent_name,
                        workspace=target.workspace,
                        base_url=target.base_url,
                        model=target.model,
                        system_prompt_ref=system_prompt_ref,
                        declared_tools=list(target.declared_tools),
                        forbidden_topics=list(target.forbidden_topics),
                        sandbox_channel_id=target.sandbox_channel_id,
                        security_channel_id=target.security_channel_id,
                        rule_pack_ref=target.rule_pack_ref,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            s.commit()
        return agent_id

    def _row_to_target(self, row) -> SlackAgentTarget:
        """Reconstruct a full `SlackAgentTarget` from a `slack_registered_agents` row,
        resolving a `secref_…` system_prompt_ref through the secret store. The single
        row→target path — used by both `get` and `all_targets`."""
        ref = row.system_prompt_ref or ""
        sensitive = isinstance(ref, str) and ref.startswith("secref_")
        if sensitive and self._secrets is not None:
            system_prompt = self._secrets.resolve(ref, org_id=row.org_id) or ""
        else:
            system_prompt = ref
            sensitive = False

        return SlackAgentTarget(
            org_id=row.org_id,
            agent_name=row.agent_name,
            workspace=row.workspace,
            base_url=row.base_url,
            model=row.model,
            system_prompt=system_prompt,
            declared_tools=tuple(row.declared_tools or ()),
            forbidden_topics=tuple(row.forbidden_topics or ()),
            sandbox_channel_id=row.sandbox_channel_id or "",
            security_channel_id=row.security_channel_id or "",
            rule_pack_ref=row.rule_pack_ref,
            system_prompt_sensitive=sensitive,
        )

    def get(self, org_id: str, agent_name: str) -> SlackAgentTarget | None:
        from rogue.platform.models import SlackRegisteredAgent

        with self._sf() as s:
            row = s.execute(
                select(SlackRegisteredAgent).where(
                    SlackRegisteredAgent.org_id == org_id,
                    SlackRegisteredAgent.agent_name == agent_name,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return self._row_to_target(row)

    def all_targets(self, org_id: str | None = None) -> list[SlackAgentTarget]:
        from rogue.platform.models import SlackRegisteredAgent

        stmt = select(SlackRegisteredAgent)
        if org_id is not None:
            stmt = stmt.where(SlackRegisteredAgent.org_id == org_id)
        with self._sf() as s:
            rows = s.execute(stmt).scalars().all()
            return [self._row_to_target(r) for r in rows]

    def list(self, org_id: str) -> list[dict]:
        from rogue.platform.models import SlackRegisteredAgent

        with self._sf() as s:
            rows = s.execute(
                select(SlackRegisteredAgent).where(SlackRegisteredAgent.org_id == org_id)
            ).scalars().all()
            return [{"agent_name": r.agent_name, "workspace": r.workspace} for r in rows]

    def get_client_policy(self, org_id: str, agent_name: str) -> dict | None:
        from rogue.platform.models import SlackRegisteredAgent

        with self._sf() as s:
            row = s.execute(
                select(SlackRegisteredAgent).where(
                    SlackRegisteredAgent.org_id == org_id,
                    SlackRegisteredAgent.agent_name == agent_name,
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return row.client_policy

    def set_client_policy(self, org_id: str, agent_name: str, policy: dict) -> None:
        """Cache a serialized ClientPolicy on the agent row. A missing row is a no-op (gentle):
        the policy cache is best-effort and the row is expected to exist from `put` first."""
        from rogue.platform.models import SlackRegisteredAgent

        with self._sf() as s:
            row = s.execute(
                select(SlackRegisteredAgent).where(
                    SlackRegisteredAgent.org_id == org_id,
                    SlackRegisteredAgent.agent_name == agent_name,
                )
            ).scalar_one_or_none()
            if row is None:
                return
            row.client_policy = policy
            s.commit()


def build_postgres_slack_agent_store(secret_store=None, database_url: str | None = None):
    """Build a `PostgresSlackAgentStore`. `secret_store` is optional: without it, a sensitive
    prompt simply falls back to inline storage (the in-memory secret path is not engaged)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    url = database_url or os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=300, pool_timeout=10)
    return PostgresSlackAgentStore(sessionmaker(bind=engine), secret_store)


__all__ = [
    "SlackAgentStore",
    "InMemorySlackAgentStore",
    "PostgresSlackAgentStore",
    "build_postgres_slack_agent_store",
]
