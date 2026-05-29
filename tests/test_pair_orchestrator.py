"""Tests for §10.7 full PAIR build (iterative_attacker extensions +
pair_orchestrator + reproduce_once integration).

Five groups:

  A. RefinementProposal refinement_type field — default 'roleplaying',
     coercion of unknown values at attacker-parse time, frozen semantics.

  B. Budget guards beyond per_run — per-primitive cap, per-day cap (reads
     llm_cost_log.csv), Slack alert fires once on per-day cap.

  C. PairOrchestrator.run_pair_cell — multi-iter loop, early-stop on breach,
     baseline-already-breached short-circuit, primitive-budget abort,
     daily-budget bubble-up.

  D. Persistence wiring — build_step_orm_rows shape; _build_pair_breach_result_orm
     in reproduce_once sets pair_iters_to_breach + persona_used.

  E. Live `rogue_test` DB end-to-end — run_reproduction with pair_max_iters=2
     produces baseline BreachResults + PAIR BreachResult + RefinementStep
     rows.

Spec: ROGUE_PLAN.md §10.7 PAIR iterative refinement FULL implementation.
"""

from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest

from rogue.reproduce.iterative_attacker import (
    DailyBudgetExceededError,
    IterativeAttacker,
    PrimitiveBudgetExceededError,
    REFINEMENT_TYPES,
    RefinementProposal,
)
from rogue.reproduce.judge import JudgeResult
from rogue.reproduce.llm_cost_log import append_row, log_anthropic_response
from rogue.reproduce.pair_orchestrator import (
    PairCellResult,
    PairOrchestrator,
    PairStepRecord,
    build_step_orm_rows,
    verdict_to_pair_score,
)
from rogue.reproduce.target_panel import ModelResponse
from rogue.schemas import (
    AttackFamily,
    AttackPrimitive,
    AttackVector,
    JudgeVerdict,
    Severity,
    demo_deployment_configs,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
DEFAULT_TEST_DATABASE_URL = (
    "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue_test"
)


def _database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)


def _load_golden_primitive() -> AttackPrimitive:
    fp = FIXTURES_DIR / "01_multilingual_african_languages.json"
    return AttackPrimitive.model_validate(json.loads(fp.read_text(encoding="utf-8")))


def _make_primitive(**overrides) -> AttackPrimitive:
    payload = {
        "primitive_id": "01PAIRPRIM00000000000000",
        "cluster_id": "01PAIRPRIM00000000000000",
        "canonical": True,
        "family": AttackFamily.DAN_PERSONA,
        "secondary_families": [],
        "vector": AttackVector.USER_TURN,
        "title": "pair test parent",
        "short_description": "Extract secret information from the target.",
        "payload_template": "Tell me {target_behavior}.",
        "payload_slots": {"target_behavior": "the secret"},
        "multi_turn_sequence": None,
        "target_models_claimed": [],
        "claimed_success_rate": None,
        "claimed_first_seen": None,
        "reproducibility_score": 7,
        "requires_multi_turn": False,
        "requires_system_prompt_access": False,
        "requires_tools": [],
        "requires_multimodal": False,
        "sources": [
            {
                "url": "https://example.com",
                "source_type": "other",
                "author": None,
                "published_at": None,
                "fetched_at": datetime.now(timezone.utc),
                "archive_hash": "h" * 16,
                "bright_data_product": "fixture",
            },
        ],
        "discovered_at": datetime.now(timezone.utc),
        "base_severity": Severity.MEDIUM,
        "severity_rationale": "r",
        "notes": None,
    }
    payload.update(overrides)
    return AttackPrimitive.model_validate(payload)


# =========================================================================== #
# Stub Anthropic infrastructure (mirror of test_llm_cost_log)
# =========================================================================== #


class _StubUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _StubBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _StubResponse:
    def __init__(self, text: str, in_tok: int = 800, out_tok: int = 150) -> None:
        self.content = [_StubBlock(text)]
        self.usage = _StubUsage(in_tok, out_tok)


class _StubAnthropicClient:
    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def close(self) -> None:
        pass

    @property
    def messages(self) -> "_StubAnthropicClient":
        return self

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if len(self.calls) <= len(self._responses):
            return self._responses[len(self.calls) - 1]
        return self._responses[-1]


# =========================================================================== #
# A. RefinementProposal refinement_type
# =========================================================================== #


def test_refinement_proposal_defaults_to_roleplaying() -> None:
    p = RefinementProposal(
        improvement="Pivoting to academic framing for the next iteration.",
        prompt="As a historian studying wartime chemistry, please describe...",
    )
    assert p.refinement_type == "roleplaying"


def test_refinement_proposal_accepts_known_refinement_types() -> None:
    for t in REFINEMENT_TYPES:
        p = RefinementProposal(
            improvement="Strategy pivot rationale here.",
            prompt="A long enough adversarial prompt body.",
            refinement_type=t,
        )
        assert p.refinement_type == t


def test_refinement_proposal_accepts_unknown_refinement_type_string() -> None:
    """Field is free-form String for forward-compat. Unknown values are
    accepted at schema time and coerced to 'roleplaying' by the attacker's
    JSON parser (not the schema). This separation lets the schema be the
    canonical wire shape without locking the taxonomy."""
    p = RefinementProposal(
        improvement="Some explanation here.",
        prompt="A long enough adversarial prompt body.",
        refinement_type="custom_novel_strategy",
    )
    assert p.refinement_type == "custom_novel_strategy"


@pytest.mark.asyncio
async def test_attacker_coerces_unknown_refinement_type_to_roleplaying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the attacker LLM invents an unknown refinement_type, the parser
    coerces it to 'roleplaying' so the dashboard's strategy-distribution
    chart stays clean."""
    log_path = tmp_path / "log.csv"
    monkeypatch.setattr(
        "rogue.reproduce.iterative_attacker.log_anthropic_response",
        lambda response, **kwargs: log_anthropic_response(
            response, path=log_path, **kwargs,
        ),
    )
    a = IterativeAttacker(
        attacker_strategy="haiku-only", allow_strategy_pick=True,
    )
    a._anthropic_client = _StubAnthropicClient(
        [_StubResponse(
            '{"improvement": "Trying a new framing approach.", '
            '"prompt": "Long enough adversarial prompt body for the schema.", '
            '"refinement_type": "academic_appeal"}',  # unknown
            in_tok=900, out_tok=120,
        )],
    )
    p = await a.refine(
        goal="x", previous_prompt="y", model_response="z",
        score=1, iter_index=0,
    )
    assert p is not None
    assert p.refinement_type == "roleplaying"  # coerced


# =========================================================================== #
# B. Budget guards
# =========================================================================== #


@pytest.mark.asyncio
async def test_per_primitive_budget_raises_distinct_error_class() -> None:
    a = IterativeAttacker(
        attacker_strategy="haiku-only",
        per_run_budget_usd=10.0,
        per_primitive_budget_usd=0.001,
    )
    a.primitive_spent_usd = 0.001
    with pytest.raises(PrimitiveBudgetExceededError):
        await a.refine(
            goal="x", previous_prompt="y", model_response="z", score=1,
            iter_index=0,
        )


def test_reset_primitive_clears_only_primitive_counter() -> None:
    a = IterativeAttacker(attacker_strategy="haiku-only")
    a.spent_usd = 0.42
    a.primitive_spent_usd = 0.99
    a.reset_primitive()
    assert a.primitive_spent_usd == 0.0
    assert a.spent_usd == 0.42  # per-run untouched


@pytest.mark.asyncio
async def test_per_day_budget_raises_when_log_aggregate_over_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_daily_spent_usd_today reads llm_cost_log.csv. Seed it with today's
    rows totaling > the cap, then attempt a refine."""
    log_path = tmp_path / "llm_cost_log.csv"
    # Seed 3 rows summing to $25 > $20 cap.
    for _ in range(3):
        append_row(
            module="iterative_attacker",
            operation="refine",
            model="claude-sonnet-4-6",
            subject_id="test",
            # input_tokens × $3/M + output_tokens × $15/M ≈ $8.33 per row
            input_tokens=1_000_000,
            output_tokens=355_555,
            refused=False,
            path=log_path,
        )

    monkeypatch.setattr(
        "rogue.reproduce.llm_cost_log.DEFAULT_LOG_PATH", log_path,
    )

    a = IterativeAttacker(
        attacker_strategy="haiku-only",
        per_run_budget_usd=10.0,
        per_primitive_budget_usd=10.0,
        per_day_budget_usd=20.0,
    )
    with pytest.raises(DailyBudgetExceededError):
        await a.refine(
            goal="x", previous_prompt="y", model_response="z", score=1,
            iter_index=0,
        )


def test_slack_alert_is_idempotent_within_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling _send_slack_alert twice should only fire one POST. The
    second call short-circuits via _slack_alerted_for_day."""
    posts: list[dict[str, Any]] = []

    class _FakeHttpx:
        @staticmethod
        def post(url, json=None, timeout=None):
            posts.append({"url": url, "json": json})
            return None

    monkeypatch.setitem(
        __import__("sys").modules,
        "httpx_stub_marker",  # safe key — not actually replacing httpx
        _FakeHttpx,
    )
    a = IterativeAttacker(
        attacker_strategy="haiku-only",
        slack_webhook_url="https://hooks.slack.test/fake",
    )
    # Patch the import line inside _send_slack_alert via monkeypatch on sys.modules.
    import sys
    real_httpx = sys.modules.get("httpx")
    sys.modules["httpx"] = _FakeHttpx  # type: ignore[assignment]
    try:
        a._send_slack_alert("hello world")
        a._send_slack_alert("hello world (again)")  # should no-op
    finally:
        if real_httpx is not None:
            sys.modules["httpx"] = real_httpx
        else:
            sys.modules.pop("httpx", None)
    assert len(posts) == 1
    assert posts[0]["json"]["text"] == "hello world"
    assert a._slack_alerted_for_day is True


def test_slack_alert_silent_when_no_webhook() -> None:
    """No webhook URL ⇒ silent no-op. Doesn't raise."""
    a = IterativeAttacker(
        attacker_strategy="haiku-only", slack_webhook_url=None,
    )
    a._send_slack_alert("hello")
    assert a._slack_alerted_for_day is False


# =========================================================================== #
# C. PairOrchestrator
# =========================================================================== #


class _StubPanel:
    """Returns text-of-choice for each render. Use the rendered payload
    to decide what the target says."""

    def __init__(self, baseline_response: str, refined_response: str) -> None:
        self._baseline = baseline_response
        self._refined = refined_response

    async def run_attack(self, rendered, config, temperature, n_trials):
        text_blob = " ".join(m.get("content", "") for m in rendered.messages)
        # Refined prompts produced by IterativeAttacker.refine() have the
        # marker "[REFINED" (followed by ` iter=N]`) injected by the stub
        # _call_anthropic below. Substring match — no closing bracket.
        content = self._refined if "[REFINED" in text_blob else self._baseline
        return [
            ModelResponse(
                content=content, latency_ms=10, tokens_in=50, tokens_out=20,
                cost_usd=0.001, error=None, trial_index=i,
                temperature=temperature,
            )
            for i in range(n_trials)
        ]

    async def aclose(self):
        pass


class _StubJudge:
    """Maps response text → verdict. 'Sure, here is' = full_breach;
    'partial' = partial_breach; else evaded."""

    async def judge(self, rendered, model_response, primitive):
        if "Sure, here is" in model_response:
            return JudgeResult(
                verdict=JudgeVerdict.FULL_BREACH, rationale="r", confidence=0.95,
            )
        if "partial" in model_response.lower():
            return JudgeResult(
                verdict=JudgeVerdict.PARTIAL_BREACH, rationale="r", confidence=0.85,
            )
        return JudgeResult(
            verdict=JudgeVerdict.EVADED, rationale="r", confidence=0.9,
        )


def _make_stub_attacker(
    *,
    refinement_type: str = "roleplaying",
    strategy: str = "mixed",
) -> IterativeAttacker:
    """Attacker whose _call_anthropic returns a marked refined prompt."""
    a = IterativeAttacker(attacker_strategy=strategy, allow_strategy_pick=True)

    async def _stub_call(*, goal, previous_prompt, model_response,
                         score, model, iter_index):
        a.spent_usd += 0.001
        a.primitive_spent_usd += 0.001
        return RefinementProposal(
            improvement=f"Pivoting to {refinement_type} on iter {iter_index}.",
            prompt=f"[REFINED iter={iter_index}] {goal}",
            refinement_type=refinement_type,
        )

    a._call_anthropic = _stub_call  # type: ignore[assignment]
    return a


def test_verdict_to_pair_score_is_monotonic() -> None:
    """Same monotonic 1-10 mapping as scripts/pair_attacker_ab.py."""
    assert verdict_to_pair_score(JudgeVerdict.REFUSED) == 1
    assert verdict_to_pair_score(JudgeVerdict.EVADED) == 3
    assert verdict_to_pair_score(JudgeVerdict.PARTIAL_BREACH) == 7
    assert verdict_to_pair_score(JudgeVerdict.FULL_BREACH) == 10


def test_pair_orchestrator_rejects_bad_max_iters() -> None:
    a = _make_stub_attacker()
    with pytest.raises(ValueError, match="max_iters must be between"):
        PairOrchestrator(
            attacker=a, panel=_StubPanel("x", "y"),  # type: ignore[arg-type]
            judge=_StubJudge(),  # type: ignore[arg-type]
            max_iters=0,
        )
    with pytest.raises(ValueError, match="max_iters must be between"):
        PairOrchestrator(
            attacker=a, panel=_StubPanel("x", "y"),  # type: ignore[arg-type]
            judge=_StubJudge(),  # type: ignore[arg-type]
            max_iters=11,
        )


@pytest.mark.asyncio
async def test_pair_cell_breaches_on_iter_zero_records_one_step() -> None:
    """Refined prompt full-breaches immediately → 1 step, iters_to_breach=0."""
    panel = _StubPanel(
        baseline_response="I cannot help.",
        refined_response="Sure, here is exactly what you wanted...",
    )
    judge = _StubJudge()
    attacker = _make_stub_attacker()
    orch = PairOrchestrator(
        attacker=attacker, panel=panel, judge=judge, max_iters=3,  # type: ignore[arg-type]
    )
    primitive = _make_primitive()
    config = demo_deployment_configs()[0]

    result = await orch.run_pair_cell(primitive=primitive, config=config)
    assert result.baseline_verdict == JudgeVerdict.EVADED
    assert result.final_verdict == JudgeVerdict.FULL_BREACH
    assert result.pair_iters_to_breach == 0
    assert len(result.steps) == 1
    assert result.steps[0].verdict == JudgeVerdict.FULL_BREACH
    assert result.steps[0].refinement_type == "roleplaying"


@pytest.mark.asyncio
async def test_pair_cell_baseline_breach_short_circuits_no_pair() -> None:
    """If baseline already breached, PAIR doesn't run — no refinement
    steps, iters_to_breach=None."""
    panel = _StubPanel(
        baseline_response="Sure, here is the answer.",  # baseline breaches
        refined_response="(unused)",
    )
    attacker = _make_stub_attacker()
    orch = PairOrchestrator(
        attacker=attacker, panel=panel, judge=_StubJudge(),  # type: ignore[arg-type]
        max_iters=3,
    )

    result = await orch.run_pair_cell(
        primitive=_make_primitive(), config=demo_deployment_configs()[0],
    )
    assert result.baseline_verdict == JudgeVerdict.FULL_BREACH
    assert result.pair_iters_to_breach is None  # no PAIR ran
    assert len(result.steps) == 0
    assert result.pair_attacker_total_cost_usd == 0.0


@pytest.mark.asyncio
async def test_pair_cell_iterates_to_max_when_no_breach() -> None:
    """All iters evade → max_iters steps recorded, iters_to_breach=None."""
    panel = _StubPanel(
        baseline_response="I cannot help.",
        refined_response="I still cannot help.",  # never breaches
    )
    attacker = _make_stub_attacker()
    orch = PairOrchestrator(
        attacker=attacker, panel=panel, judge=_StubJudge(),  # type: ignore[arg-type]
        max_iters=3,
    )
    result = await orch.run_pair_cell(
        primitive=_make_primitive(), config=demo_deployment_configs()[0],
    )
    assert result.pair_iters_to_breach is None
    assert len(result.steps) == 3
    assert result.final_verdict == JudgeVerdict.EVADED


@pytest.mark.asyncio
async def test_pair_cell_aborts_on_per_primitive_budget() -> None:
    """When per_primitive budget trips mid-loop, orchestrator records
    aborted_reason and returns partial chain."""
    panel = _StubPanel("I cannot help.", "I still cannot help.")
    attacker = _make_stub_attacker()
    # Each stub call costs $0.001 — after 2 calls we're at $0.002. Cap at $0.0015
    # so the THIRD call trips PrimitiveBudgetExceededError.
    attacker.per_primitive_budget_usd = 0.0015

    orch = PairOrchestrator(
        attacker=attacker, panel=panel, judge=_StubJudge(),  # type: ignore[arg-type]
        max_iters=5,
    )
    result = await orch.run_pair_cell(
        primitive=_make_primitive(), config=demo_deployment_configs()[0],
    )
    assert result.aborted_reason is not None
    assert "per_primitive_budget" in result.aborted_reason
    assert len(result.steps) < 5


@pytest.mark.asyncio
async def test_pair_cell_bubbles_daily_budget_exceeded() -> None:
    """DailyBudgetExceededError must propagate — sweep caller aborts run."""
    panel = _StubPanel("I cannot help.", "I still cannot help.")
    attacker = _make_stub_attacker()

    # Override _check_budgets to raise DailyBudgetExceededError on entry.
    async def _raise_daily(*args, **kwargs):
        raise DailyBudgetExceededError("daily cap hit")

    attacker._call_anthropic = _raise_daily  # type: ignore[assignment]
    orch = PairOrchestrator(
        attacker=attacker, panel=panel, judge=_StubJudge(),  # type: ignore[arg-type]
        max_iters=3,
    )
    with pytest.raises(DailyBudgetExceededError):
        await orch.run_pair_cell(
            primitive=_make_primitive(), config=demo_deployment_configs()[0],
        )


# =========================================================================== #
# D. Persistence wiring
# =========================================================================== #


def test_build_step_orm_rows_shape() -> None:
    """Step records → ORM-ready dicts in order, with breach_id propagated."""
    steps = [
        PairStepRecord(
            iter_index=0,
            refinement_type="logical_appeal",
            attacker_model="claude-haiku-4-5",
            proposed_prompt="prompt-0",
            improvement="explanation-0",
            target_response="response-0",
            verdict=JudgeVerdict.EVADED,
            score=3,
            attacker_cost_usd=0.002,
        ),
        PairStepRecord(
            iter_index=1,
            refinement_type="roleplaying",
            attacker_model="claude-sonnet-4-6",
            proposed_prompt="prompt-1",
            improvement="explanation-1",
            target_response="response-1",
            verdict=JudgeVerdict.PARTIAL_BREACH,
            score=7,
            attacker_cost_usd=0.008,
        ),
    ]
    rows = build_step_orm_rows(breach_id="BR123", steps=steps)
    assert len(rows) == 2
    assert all(r["breach_id"] == "BR123" for r in rows)
    assert rows[0]["iter_index"] == 0
    assert rows[0]["refinement_type"] == "logical_appeal"
    assert rows[0]["verdict"] == "evaded"
    assert rows[1]["score"] == 7
    assert rows[1]["attacker_cost_usd"] == 0.008


def test_build_pair_breach_result_orm_sets_pair_columns() -> None:
    """The PAIR-derived BreachResult row carries pair_iters_to_breach +
    pair_attacker_total_cost_usd + persona_used='pair_iter=N'."""
    from scripts.reproduce_once import _build_pair_breach_result_orm

    cell = PairCellResult(
        primitive_id="P1",
        config_id="C1",
        baseline_verdict=JudgeVerdict.EVADED,
        baseline_rendered_payload="baseline",
        baseline_model_response="I cannot help.",
        final_verdict=JudgeVerdict.FULL_BREACH,
        final_rendered_payload="refined prompt",
        final_model_response="Sure, here is...",
        pair_iters_to_breach=1,
        pair_attacker_total_cost_usd=0.014,
        steps=[
            PairStepRecord(
                iter_index=0,
                refinement_type="roleplaying",
                attacker_model="claude-haiku-4-5",
                proposed_prompt="p0",
                improvement="i0",
                target_response="r0",
                verdict=JudgeVerdict.EVADED,
                score=3,
                attacker_cost_usd=0.006,
            ),
            PairStepRecord(
                iter_index=1,
                refinement_type="logical_appeal",
                attacker_model="claude-sonnet-4-6",
                proposed_prompt="p1",
                improvement="i1",
                target_response="r1",
                verdict=JudgeVerdict.FULL_BREACH,
                score=10,
                attacker_cost_usd=0.008,
            ),
        ],
    )
    row = _build_pair_breach_result_orm(
        primitive_id="P1", config_id="C1", pair_result=cell,
    )
    assert row.primitive_id == "P1"
    assert row.deployment_config_id == "C1"
    assert row.verdict == "full_breach"
    assert row.pair_iters_to_breach == 1
    assert row.pair_attacker_total_cost_usd == pytest.approx(0.014, abs=1e-9)
    assert row.persona_used == "pair_iter=1"
    assert row.cost_usd == pytest.approx(0.014, abs=1e-9)


def test_build_pair_breach_result_orm_marks_no_breach() -> None:
    """When PAIR runs all iters without breach, persona_used='pair_no_breach'."""
    from scripts.reproduce_once import _build_pair_breach_result_orm

    cell = PairCellResult(
        primitive_id="P1",
        config_id="C1",
        baseline_verdict=JudgeVerdict.EVADED,
        baseline_rendered_payload="b",
        baseline_model_response="x",
        final_verdict=JudgeVerdict.EVADED,
        final_rendered_payload="r",
        final_model_response="y",
        pair_iters_to_breach=None,
        pair_attacker_total_cost_usd=0.02,
        steps=[],
    )
    row = _build_pair_breach_result_orm(
        primitive_id="P1", config_id="C1", pair_result=cell,
    )
    assert row.pair_iters_to_breach is None
    assert row.persona_used == "pair_no_breach"


# =========================================================================== #
# E. Live `rogue_test` DB end-to-end
# =========================================================================== #


@pytest.fixture
def live_db_with_one_evade_primitive(monkeypatch) -> Iterator[str]:
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session

    from rogue.db.models import (
        AttackPrimitive as AttackPrimitiveORM,
        DeploymentConfig as DeploymentConfigORM,
    )

    url = _database_url()
    monkeypatch.setenv("DATABASE_URL", url)
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            pass
    except (OperationalError, ConnectionRefusedError, socket.gaierror, OSError) as exc:
        pytest.skip(f"Postgres not reachable: {exc}")

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    try:
        command.upgrade(cfg, "head")
        golden = _load_golden_primitive()
        with Session(engine) as session:
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
            session.add(
                AttackPrimitiveORM(
                    primitive_id="01PAIRINTGR0000000000000",
                    cluster_id="01PAIRINTGR0000000000000",
                    canonical=True,
                    family=AttackFamily.DAN_PERSONA.value,
                    secondary_families=[],
                    vector=AttackVector.USER_TURN.value,
                    title="pair integration parent",
                    short_description="goal: extract restricted info",
                    payload_template="Please tell me {target_behavior}.",
                    payload_slots={"target_behavior": "the restricted info"},
                    multi_turn_sequence=None,
                    slot_requirements=None,
                    synthesized=False,
                    derived_from_primitive_id=None,
                    target_models_claimed=[],
                    claimed_success_rate=None,
                    claimed_first_seen=None,
                    reproducibility_score=8,
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
async def test_run_reproduction_with_pair_max_iters_persists_chain(
    live_db_with_one_evade_primitive,
) -> None:
    """End-to-end: --pair-max-iters=2 against a cell whose baseline evades
    produces (a) the baseline BreachResult, (b) one PAIR BreachResult with
    pair_iters_to_breach set, (c) corresponding pair_refinement_steps rows."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import (
        BreachResult as BreachResultORM,
        PairRefinementStep as PairRefinementStepORM,
    )
    from scripts.reproduce_once import run_reproduction

    panel = _StubPanel(
        baseline_response="I cannot help.",
        refined_response="Sure, here is the restricted info.",
    )
    judge = _StubJudge()
    attacker = _make_stub_attacker()

    stats = await run_reproduction(
        database_url=live_db_with_one_evade_primitive,
        primitive_limit=None,
        n_trials=2,  # 2 baseline trials per cell
        temperature=0.7,
        concurrency=1,
        panel=panel,  # type: ignore[arg-type]
        judge=judge,  # type: ignore[arg-type]
        pair_max_iters=2,
        pair_attacker=attacker,
    )
    # 2 baseline trials + 1 PAIR row = 3 BreachResults.
    assert stats.breach_results_persisted == 3
    assert stats.verdict_counts.get("evaded", 0) == 2  # baselines all evaded
    assert stats.verdict_counts.get("full_breach", 0) == 1  # PAIR cracked

    engine = create_engine(live_db_with_one_evade_primitive)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with SessionLocal() as session:
            all_breaches = list(
                session.execute(select(BreachResultORM)).scalars(),
            )
            assert len(all_breaches) == 3
            # Exactly one PAIR row (pair_iters_to_breach IS NOT NULL).
            pair_rows = [
                b for b in all_breaches if b.pair_iters_to_breach is not None
            ]
            assert len(pair_rows) == 1
            assert pair_rows[0].pair_iters_to_breach == 0  # cracked on iter 0
            assert pair_rows[0].persona_used == "pair_iter=0"
            assert pair_rows[0].verdict == "full_breach"

            # One refinement step linked to the PAIR breach.
            steps = list(
                session.execute(
                    select(PairRefinementStepORM).where(
                        PairRefinementStepORM.breach_id
                        == pair_rows[0].breach_id,
                    ),
                ).scalars(),
            )
            assert len(steps) == 1
            assert steps[0].iter_index == 0
            assert steps[0].verdict == "full_breach"
            assert steps[0].refinement_type in REFINEMENT_TYPES
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_run_reproduction_no_iterative_flag_skips_pair(
    live_db_with_one_evade_primitive,
) -> None:
    """pair_max_iters=0 ⇒ no PAIR row, no refinement_steps. Existing
    behavior preserved."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from rogue.db.models import (
        BreachResult as BreachResultORM,
        PairRefinementStep as PairRefinementStepORM,
    )
    from scripts.reproduce_once import run_reproduction

    panel = _StubPanel(
        baseline_response="I cannot help.",
        refined_response="(should never be hit)",
    )

    stats = await run_reproduction(
        database_url=live_db_with_one_evade_primitive,
        primitive_limit=None,
        n_trials=2,
        temperature=0.7,
        concurrency=1,
        panel=panel,  # type: ignore[arg-type]
        judge=_StubJudge(),  # type: ignore[arg-type]
        pair_max_iters=0,  # explicit no-PAIR
    )
    # Just the 2 baseline trials.
    assert stats.breach_results_persisted == 2

    engine = create_engine(live_db_with_one_evade_primitive)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with SessionLocal() as session:
            all_breaches = list(
                session.execute(select(BreachResultORM)).scalars(),
            )
            assert len(all_breaches) == 2
            assert all(b.pair_iters_to_breach is None for b in all_breaches)
            steps = list(
                session.execute(select(PairRefinementStepORM)).scalars(),
            )
            assert len(steps) == 0
    finally:
        engine.dispose()
