"""Shared breach-result persistence — the single writer of `breach_results` rows + deployment-config upsert. Imported by both the research sweep (reproduce_once) and the endpoint scan, so the persistence logic lives in exactly one place."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import ulid
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from rogue.db.models import (
    BreachResult as BreachResultORM,
    DeploymentConfig as DeploymentConfigORM,
)
from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.judge import JudgeResult
from rogue.reproduce.target_panel import ModelResponse
from rogue.schemas import DeploymentConfig

logger = logging.getLogger("rogue.reproduce.persistence")


def build_breach_result_orm(
    *,
    primitive_id: str,
    config_id: str,
    rendered: RenderedAttack,
    response: ModelResponse,
    judge_result: JudgeResult,
) -> BreachResultORM:
    """Compose one BreachResult ORM row from (rendered, response, verdict).

    `rendered_payload` is the concatenated user-turn content of
    `rendered.messages` (system prompt excluded; it's already on
    `deployment_configs.system_prompt`). Truncated at 50K chars to keep
    row size sane.

    `persona_used` mirrors `rendered.persona_used` (set when --persona is
    passed; NULL otherwise) so the §10.7 A/B query GROUP BY persona_used
    can compare wrapped-vs-unwrapped breach rates per (primitive, config).
    """
    user_turns = [
        m["content"] for m in rendered.messages if m.get("role") == "user"
    ]
    rendered_payload = "\n\n---NEXT TURN---\n\n".join(user_turns)[:50_000]

    return BreachResultORM(
        breach_id=ulid.new().str,
        primitive_id=primitive_id,
        deployment_config_id=config_id,
        trial_index=response.trial_index,
        temperature=response.temperature,
        rendered_payload=rendered_payload,
        model_response=(response.content or "")[:50_000],
        verdict=judge_result.verdict.value,
        judge_rationale=judge_result.rationale[:2_000],
        judge_confidence=judge_result.confidence,
        latency_ms=response.latency_ms,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        cost_usd=response.cost_usd,
        ran_at=datetime.now(timezone.utc),
        persona_used=rendered.persona_used,
    )


def persist_breach_rows(
    database_url: str,
    orm_rows: list[BreachResultORM],
    *,
    chunk: int = 200,
    retries: int = 3,
) -> tuple[int, int]:
    """Persist breach-result rows on a FRESH connection, in chunks, with retry.

    The batch path holds no DB connection during the long panel+batch wait, so
    this opens a brand-new engine (``pool_pre_ping`` so a stale pooled conn is
    detected + replaced) and commits in small chunks — a dropped connection
    loses at most one chunk, not the whole sweep, and each chunk reconnects and
    retries. Returns ``(persisted, failed)``.
    """
    if not orm_rows:
        return 0, 0
    cols = [c.name for c in BreachResultORM.__table__.columns]
    dicts = [{c: getattr(r, c) for c in cols} for r in orm_rows]

    engine = create_engine(database_url, pool_pre_ping=True)
    persisted = failed = 0
    try:
        for i in range(0, len(dicts), chunk):
            part = dicts[i : i + chunk]
            for attempt in range(retries):
                try:
                    with engine.begin() as conn:
                        conn.execute(insert(BreachResultORM.__table__), part)
                    persisted += len(part)
                    break
                except OperationalError as exc:
                    logger.warning(
                        "persist chunk %d retry %d/%d (%s) — reconnecting",
                        i // chunk, attempt + 1, retries, type(exc).__name__,
                    )
                    engine.dispose()
                    engine = create_engine(database_url, pool_pre_ping=True)
                    if attempt == retries - 1:
                        failed += len(part)
                        logger.error("persist chunk %d FAILED after %d retries", i // chunk, retries)
    finally:
        engine.dispose()
    logger.info("batch persist: %d rows committed, %d failed", persisted, failed)
    return persisted, failed


def persist_agent_exec_rows(database_url: str, rows: list) -> tuple[int, int]:
    """Persist agent-exec results — ``[(BreachResultORM, AgentTranscriptORM, [TraceFindingORM])]``
    from ``reproduce.agent.tier.to_persistence_rows`` — with the FK chain intact (breach → 1:1
    transcript → N findings, per CRIT-2). Relational ``add`` (not bulk insert) so the CASCADE FKs
    resolve. Best-effort: logs + returns ``(persisted, failed)``; NEVER raises — a persistence
    failure must not break the customer's scan. Returns row-SETS committed/failed."""
    if not rows:
        return 0, 0
    engine = create_engine(database_url, pool_pre_ping=True)
    persisted = failed = 0
    try:
        with Session(engine) as session:
            for breach, transcript, findings in rows:
                try:
                    session.add(breach)
                    session.add(transcript)
                    session.add_all(findings)
                    session.commit()
                    persisted += 1
                except Exception as exc:  # noqa: BLE001 — one bad row-set must not sink the rest
                    session.rollback()
                    failed += 1
                    logger.warning("agent-exec persist failed for %s: %s", getattr(breach, "breach_id", "?"), exc)
    finally:
        engine.dispose()
    logger.info("agent-exec persist: %d row-set(s) committed, %d failed", persisted, failed)
    return persisted, failed


def upsert_deployment_config(config: DeploymentConfig, database_url: str) -> None:
    """Insert-or-update the deployment-config row so the dashboard can show this target as a
    /matrix column. `base_url` is excluded — it has no ORM column (ephemeral scan-time routing
    field), mirroring scripts/ops/seed_demo_data.py::_to_orm_deployment."""
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine) as session:
            existing = (
                session.query(DeploymentConfigORM)
                .filter_by(config_id=config.config_id)
                .first()
            )
            # base_url + live_tool_target are ephemeral scan-time routing/target fields with no
            # (or intentionally no) ORM column — live_tool_target carries auth-header secrets we do
            # not persist. tool_specs (Level 1 BYO schema, no secrets) DOES persist.
            fields = config.model_dump(exclude={"base_url", "live_tool_target"})
            if existing is None:
                session.add(DeploymentConfigORM(**fields))
            else:
                for key, value in fields.items():
                    setattr(existing, key, value)
            session.commit()
    finally:
        engine.dispose()
