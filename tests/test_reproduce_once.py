"""Smoke tests for ``scripts/reproduce_once.py``.

Pure-Python helpers (always run) cover the ORM↔Pydantic projections, the
BreachResult builder, and the stats summary. The end-to-end mocked test
runs against the live `rogue_test` DB with TargetPanel + JudgeAgent
substituted by simple stubs — verifies the (instantiate → fire → judge
→ persist) loop is wired correctly without paying real API costs.

Spec: ROGUE_PLAN.md §A.13, §10.1-§10.4.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import pytest

from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.judge import JudgeResult
from rogue.reproduce.target_panel import ModelResponse
from rogue.schemas import (
    AttackPrimitive,
    JudgeVerdict,
    demo_deployment_configs,
)
from scripts.reproduce_once import (
    ReproductionRunStats,
    _build_breach_result_orm,
    _orm_to_pydantic_config,
    _orm_to_pydantic_primitive,
    run_reproduction,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _database_url() -> str:
    # Test-isolation contract — use TEST_DATABASE_URL (rogue_test), NOT
    # the dev DB. Same pattern as test_smoke.py / test_dedupe.py /
    # test_harvest_once.py.
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_DATABASE_URL)


def _load_golden_primitive() -> AttackPrimitive:
    fp = FIXTURES_DIR / "01_multilingual_african_languages.json"
    return AttackPrimitive.model_validate(json.loads(fp.read_text(encoding="utf-8")))


# --------------------------------------------------------------------------- #
# A. Stats summary
# --------------------------------------------------------------------------- #


def test_stats_summary_line_includes_all_counters() -> None:
    stats = ReproductionRunStats(
        primitives_processed=20,
        configs_per_primitive=5,
        trials_per_pair=5,
        breach_results_persisted=480,
        target_call_errors=15,
        judge_call_errors=5,
        persist_errors=0,
        estimated_cost_usd=9.87,
    )
    stats.add_verdict(JudgeVerdict.REFUSED)
    stats.add_verdict(JudgeVerdict.REFUSED)
    stats.add_verdict(JudgeVerdict.FULL_BREACH)

    line = stats.summary_line()
    for token in (
        "primitives=20", "configs=5", "trials=5",
        "breach_results=480", "target_errors=15", "judge_errors=5",
        "persist_errors=0", "est_cost=$9.87",
        "refused=2", "full_breach=1",
    ):
        assert token in line


def test_stats_add_verdict_accumulates() -> None:
    stats = ReproductionRunStats()
    for _ in range(3):
        stats.add_verdict(JudgeVerdict.REFUSED)
    stats.add_verdict(JudgeVerdict.FULL_BREACH)
    assert stats.verdict_counts == {"refused": 3, "full_breach": 1}


# --------------------------------------------------------------------------- #
# B. ORM → Pydantic projection helpers
# --------------------------------------------------------------------------- #


def test_orm_to_pydantic_primitive_coerces_string_enums() -> None:
    """ORM stores enums as strings (per `values_callable=`); projection must
    coerce back to the enum types Pydantic + downstream code expects."""
    from rogue.db.models import AttackPrimitive as AttackPrimitiveORM

    orm = AttackPrimitiveORM(
        primitive_id="01TEST" + "0" * 20,
        cluster_id="01TEST" + "0" * 20,
        canonical=True,
        family="direct_instruction_override",  # string, not enum
        secondary_families=["role_hijack"],
        vector="user_turn",
        title="t",
        short_description="d",
        payload_template="Ignore previous and {target}",
        payload_slots={"target": "x"},
        multi_turn_sequence=None,
        target_models_claimed=[],
        claimed_success_rate=None,
        claimed_first_seen=None,
        reproducibility_score=5,
        requires_multi_turn=False,
        requires_system_prompt_access=False,
        requires_tools=[],
        requires_multimodal=False,
        discovered_at=datetime.now(timezone.utc),
        base_severity="high",
        severity_rationale="r",
        notes=None,
    )
    pyd = _orm_to_pydantic_primitive(orm)
    # Enum-typed fields are real enums now.
    assert pyd.family.value == "direct_instruction_override"
    assert pyd.vector.value == "user_turn"
    assert pyd.base_severity.value == "high"
    # Sources gets a single placeholder (the wire type requires ≥1 entry
    # but the reproduction layer doesn't read it; the dashboard re-joins
    # source_provenances directly for breach cards).
    assert len(pyd.sources) == 1
    assert "rogue.internal/replay/" in str(pyd.sources[0].url)
    assert pyd.sources[0].bright_data_product == "fixture"


def test_orm_to_pydantic_config_round_trips() -> None:
    from rogue.db.models import DeploymentConfig as DeploymentConfigORM

    orm = DeploymentConfigORM(
        config_id="cfg-test-1234567890",  # min_length=10
        customer_id="acme",
        name="Test config",
        target_model="openai/gpt-5.4-nano",
        system_prompt="You are a helpful bot.",
        declared_tools=[],
        forbidden_topics=["weapons"],
    )
    pyd = _orm_to_pydantic_config(orm)
    assert pyd.config_id == "cfg-test-1234567890"
    assert pyd.target_model == "openai/gpt-5.4-nano"
    assert pyd.forbidden_topics == ["weapons"]


# --------------------------------------------------------------------------- #
# C. BreachResult ORM builder
# --------------------------------------------------------------------------- #


def test_build_breach_result_orm_populates_required_fields() -> None:
    rendered = RenderedAttack(
        messages=[
            {"role": "system", "content": "You are X."},
            {"role": "user", "content": "Turn 1 payload"},
            {"role": "user", "content": "Turn 2 payload"},
        ],
        is_multi_turn=True,
        resolved_slots={"target": "x"},
        primitive_id="PID_TEST",
        deployment_config_id="CFG_TEST",
    )
    response = ModelResponse(
        content="model said no",
        latency_ms=300,
        tokens_in=100,
        tokens_out=20,
        cost_usd=0.001,
        error=None,
        trial_index=0,
        temperature=0.7,
    )
    judge_result = JudgeResult(
        verdict=JudgeVerdict.REFUSED,
        rationale="model declined cleanly",
        confidence=0.95,
    )
    row = _build_breach_result_orm(
        primitive_id="PID_TEST",
        config_id="CFG_TEST",
        rendered=rendered,
        response=response,
        judge_result=judge_result,
    )

    # Identity
    assert row.primitive_id == "PID_TEST"
    assert row.deployment_config_id == "CFG_TEST"
    assert len(row.breach_id) == 26  # ULID

    # Trial metadata
    assert row.trial_index == 0
    assert row.temperature == 0.7

    # rendered_payload = user-turn concat (system message excluded)
    assert "Turn 1 payload" in row.rendered_payload
    assert "Turn 2 payload" in row.rendered_payload
    assert "You are X." not in row.rendered_payload
    assert "---NEXT TURN---" in row.rendered_payload

    # Verdict shape
    assert row.verdict == "refused"
    assert row.judge_confidence == 0.95

    # Cost/latency captured
    assert row.latency_ms == 300
    assert row.cost_usd == 0.001


def test_build_breach_result_orm_truncates_oversized_response() -> None:
    """50K-char ceiling per docstring — guards against runaway model_response
    blowing up row size when a target model has a verbose meltdown."""
    rendered = RenderedAttack(
        messages=[{"role": "user", "content": "x"}],
        is_multi_turn=False,
        resolved_slots={},
        primitive_id="P",
        deployment_config_id="C",
    )
    huge_response = "A" * 100_000
    response = ModelResponse(
        content=huge_response,
        latency_ms=1,
        tokens_in=1,
        tokens_out=1,
        cost_usd=0.0,
        error=None,
        trial_index=0,
        temperature=0.5,
    )
    judge_result = JudgeResult(
        verdict=JudgeVerdict.FULL_BREACH, rationale="r", confidence=1.0,
    )
    row = _build_breach_result_orm(
        primitive_id="P", config_id="C", rendered=rendered,
        response=response, judge_result=judge_result,
    )
    assert len(row.model_response) == 50_000


# --------------------------------------------------------------------------- #
# D. End-to-end against live `rogue_test` DB
# --------------------------------------------------------------------------- #


@pytest.fixture
def live_db_with_seeded_data(monkeypatch) -> Iterator[str]:
    """Migrate `rogue_test`, seed 2 primitives + 1 config, yield URL.

    Same monkeypatch trick as test_harvest_once.live_db to defeat alembic
    env.py's DATABASE_URL override. After the test, downgrade to clean up.
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    url = _database_url()
    monkeypatch.setenv("DATABASE_URL", url)

    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(
            f"Postgres not reachable at {url}: {exc.__class__.__name__}: {exc} "
            "— run `docker compose up -d` + `CREATE DATABASE rogue_test;`"
        )

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)

    try:
        command.upgrade(cfg, "head")

        # Seed 2 canonical primitives + 1 demo deployment config.
        from rogue.db.models import (
            AttackPrimitive as AttackPrimitiveORM,
            DeploymentConfig as DeploymentConfigORM,
        )
        golden = _load_golden_primitive()
        with Session(engine) as session:
            # Seed a known DeploymentConfig.
            cfg_pyd = demo_deployment_configs()[0]
            session.add(
                DeploymentConfigORM(
                    config_id=cfg_pyd.config_id,
                    customer_id=cfg_pyd.customer_id,
                    name=cfg_pyd.name,
                    target_model=cfg_pyd.target_model,
                    system_prompt=cfg_pyd.system_prompt,
                    declared_tools=cfg_pyd.declared_tools,
                    forbidden_topics=cfg_pyd.forbidden_topics,
                ),
            )
            # 2 primitives with descending reproducibility scores so the
            # --primitive-limit ordering can be asserted.
            for i, score in enumerate([9, 6]):
                session.add(
                    AttackPrimitiveORM(
                        primitive_id=f"01TESTPRIM{i}{'0' * 16}",
                        cluster_id=f"01TESTPRIM{i}{'0' * 16}",
                        canonical=True,
                        family=golden.family.value,
                        secondary_families=[],
                        vector=golden.vector.value,
                        title=f"Test primitive {i} (score={score})",
                        short_description="seeded for reproduce_once tests",
                        payload_template=golden.payload_template,
                        payload_slots=golden.payload_slots,
                        multi_turn_sequence=None,  # avoid cross-field validator: requires_multi_turn=False ⇒ multi_turn_sequence must be None
                        target_models_claimed=[],
                        claimed_success_rate=None,
                        claimed_first_seen=None,
                        reproducibility_score=score,
                        requires_multi_turn=False,
                        requires_system_prompt_access=False,
                        requires_tools=[],
                        requires_multimodal=False,
                        discovered_at=datetime.now(timezone.utc),
                        base_severity=golden.base_severity.value,
                        severity_rationale="r",
                        notes=None,
                    ),
                )
            session.commit()
        yield url
    finally:
        command.downgrade(cfg, "base")
        engine.dispose()


@pytest.mark.asyncio
async def test_run_reproduction_end_to_end_with_mocked_panel_and_judge(
    live_db_with_seeded_data,
) -> None:
    """Full pipeline against the live DB with stubbed network components.

    Verifies: (1) primitives are loaded + ordered by reproducibility_score,
    (2) every (primitive × config × trial) produces a BreachResult row,
    (3) stats counters tally correctly, (4) target-call errors get the
    synth ERROR verdict, (5) the BreachResult rows persist + can be
    re-queried.
    """
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import BreachResult as BreachResultORM

    # --- Mock TargetPanel: returns N=2 ModelResponses per `run_attack` call,
    # one OK and one errored (so we exercise the ERROR-verdict synth path).
    class _StubPanel:
        async def run_attack(self, rendered, config, temperature, n_trials):
            results = []
            for i in range(n_trials):
                if i == 0:
                    results.append(
                        ModelResponse(
                            content="model complied: here's the answer.",
                            latency_ms=120,
                            tokens_in=300,
                            tokens_out=50,
                            cost_usd=0.0012,
                            error=None,
                            trial_index=i,
                            temperature=temperature,
                        ),
                    )
                else:
                    results.append(
                        ModelResponse(
                            content="",
                            latency_ms=20,
                            tokens_in=0,
                            tokens_out=0,
                            cost_usd=0.0,
                            error="rate_limit_exhausted: sim",
                            trial_index=i,
                            temperature=temperature,
                        ),
                    )
            return results

        async def aclose(self):
            pass

    # --- Mock JudgeAgent: every successful target call → FULL_BREACH verdict
    class _StubJudge:
        async def judge(self, rendered, model_response, primitive):
            return JudgeResult(
                verdict=JudgeVerdict.FULL_BREACH,
                rationale="stub: model complied",
                confidence=0.9,
            )

    stats = await run_reproduction(
        database_url=live_db_with_seeded_data,
        primitive_limit=None,   # both primitives
        n_trials=2,             # 2 trials each — half OK, half errored
        temperature=0.7,
        concurrency=2,
        panel=_StubPanel(),     # type: ignore[arg-type]
        judge=_StubJudge(),     # type: ignore[arg-type]
    )

    # --- Stats assertions ---
    assert stats.primitives_processed == 2
    assert stats.configs_per_primitive == 1
    assert stats.trials_per_pair == 2
    # 2 primitives × 1 config × 2 trials = 4 BreachResults
    assert stats.breach_results_persisted == 4
    assert stats.target_call_errors == 2  # half of trials errored
    assert stats.judge_call_errors == 0
    assert stats.persist_errors == 0
    # 2 FULL_BREACH (from the OK trials) + 2 ERROR (from the synthesized
    # ERROR verdicts on the errored trials).
    assert stats.verdict_counts.get("full_breach") == 2
    assert stats.verdict_counts.get("error") == 2

    # --- DB-level: rows persisted ---
    engine = create_engine(live_db_with_seeded_data)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        count = session.execute(
            select(func.count()).select_from(BreachResultORM),
        ).scalar_one()
        assert count == 4
        # Verdict distribution matches stats.
        full_count = session.execute(
            select(func.count())
            .select_from(BreachResultORM)
            .where(BreachResultORM.verdict == "full_breach"),
        ).scalar_one()
        assert full_count == 2
    engine.dispose()


@pytest.mark.asyncio
async def test_run_reproduction_primitive_limit_picks_highest_score(
    live_db_with_seeded_data,
) -> None:
    """--primitive-limit 1 must select the higher-reproducibility-score
    primitive (we seeded scores 9 and 6 → expect only score=9)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import (
        AttackPrimitive as AttackPrimitiveORM,
        BreachResult as BreachResultORM,
    )

    class _StubPanel:
        async def run_attack(self, rendered, config, temperature, n_trials):
            return [
                ModelResponse(
                    content="x", latency_ms=1, tokens_in=1, tokens_out=1,
                    cost_usd=0.0, error=None,
                    trial_index=i, temperature=temperature,
                )
                for i in range(n_trials)
            ]
        async def aclose(self):
            pass

    class _StubJudge:
        async def judge(self, rendered, model_response, primitive):
            return JudgeResult(
                verdict=JudgeVerdict.EVADED, rationale="r", confidence=0.5,
            )

    stats = await run_reproduction(
        database_url=live_db_with_seeded_data,
        primitive_limit=1,
        n_trials=1,
        temperature=0.5,
        concurrency=1,
        panel=_StubPanel(),     # type: ignore[arg-type]
        judge=_StubJudge(),     # type: ignore[arg-type]
    )

    # 1 primitive × 1 config × 1 trial = 1 BreachResult.
    assert stats.breach_results_persisted == 1
    assert stats.primitives_processed == 1

    # The selected primitive must be the score=9 one.
    engine = create_engine(live_db_with_seeded_data)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        breach = session.execute(select(BreachResultORM)).scalar_one()
        # Look up the source primitive and confirm score=9.
        prim = session.execute(
            select(AttackPrimitiveORM).where(
                AttackPrimitiveORM.primitive_id == breach.primitive_id,
            ),
        ).scalar_one()
        assert prim.reproducibility_score == 9
    engine.dispose()
