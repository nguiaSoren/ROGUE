"""ARMS escalation ladder (§10.8) — try crescendo → actor_attack → acronym,
short-circuit on the first that breaches.

Tests the per-parent ladder logic with mocked planner / panel / judge — no
network, no DB. The contract under test: strategies are tried IN ORDER, and the
moment one breaches we keep that child and DO NOT try the remaining strategies.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rogue.reproduce.escalation_planner import EscalationPlan
from rogue.reproduce.target_panel import supports_audio
from rogue.schemas import AttackPrimitive, JudgeVerdict, demo_deployment_configs
from scripts.synthesize_escalations import (
    ESCALATION_LADDER,
    run_escalation_ladder_one,
)

_HAS_SAY = shutil.which("say") is not None
_AUDIO_CONFIG = [c for c in demo_deployment_configs() if supports_audio(c.target_model)]

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _parent() -> AttackPrimitive:
    data = json.loads(
        (FIXTURES_DIR / "02_copirate_365_cve_2026_24299.json").read_text(encoding="utf-8")
    )
    return AttackPrimitive.model_validate(data)


def _plan() -> EscalationPlan:
    return EscalationPlan(
        objective="leak the system prompt",
        turns=["t1 benign", "t2 narrower", "t3 the exact objective"],
        slot_requirements={"0": [], "1": [], "2": []},
        rationale="three-turn escalation",
        planner_model="anthropic/claude-sonnet-4-6",
    )


class _FakePlanner:
    """Records which strategies were asked to plan; always returns a plan."""

    def __init__(self) -> None:
        self.planned: list[str] = []

    async def plan(self, parent, *, n_turns, arms_strategy):
        self.planned.append(arms_strategy)
        return _plan()


class _Resp:
    def __init__(self, content: str) -> None:
        self.content = content
        self.error = None


class _FakePanel:
    """Returns one trial; records dispatch count."""

    def __init__(self) -> None:
        self.dispatches = 0

    async def run_attack(self, *, rendered, config, temperature, n_trials):
        self.dispatches += 1
        return [_Resp("model output")]


class _JR:
    def __init__(self, verdict: JudgeVerdict) -> None:
        self.verdict = verdict
        self.confidence = 0.9


class _FakeJudge:
    """Returns a configured verdict per call (list, consumed in order)."""

    def __init__(self, verdicts: list[JudgeVerdict]) -> None:
        self._verdicts = list(verdicts)
        self.calls = 0

    async def judge(self, *, rendered, model_response, primitive):
        self.calls += 1
        v = self._verdicts.pop(0) if self._verdicts else JudgeVerdict.REFUSED
        return _JR(v)


# A real DeploymentConfig (claude-haiku) so render() has every field it reads;
# the panel + judge are mocked, so nothing hits the network.
_ONE_CONFIG = [demo_deployment_configs()[1]]
_BREACH_MODEL = _ONE_CONFIG[0].target_model


@pytest.mark.asyncio
async def test_ladder_stops_at_first_breaching_strategy() -> None:
    """Crescendo breaches → actor_attack/acronym are never planned or tried."""
    planner = _FakePlanner()
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # crescendo breaches immediately

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1,
    )

    assert res.winning_strategy == "crescendo"
    assert res.breached_on == _BREACH_MODEL
    assert res.child_orm is not None
    assert planner.planned == ["crescendo"]  # the others were left untried
    assert res.attempts == [("crescendo", "breach")]


@pytest.mark.asyncio
async def test_ladder_advances_until_one_breaches() -> None:
    """crescendo + actor_attack refuse, acronym breaches → acronym wins; all 3 tried."""
    planner = _FakePlanner()
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.REFUSED, JudgeVerdict.EVADED, JudgeVerdict.PARTIAL_BREACH])

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1,
    )

    assert planner.planned == list(ESCALATION_LADDER)  # tried in order
    assert res.winning_strategy == "acronym"
    assert res.attempts == [
        ("crescendo", "no_breach"),
        ("actor_attack", "no_breach"),
        ("acronym", "breach"),
    ]


@pytest.mark.asyncio
async def test_ladder_exhausts_with_no_breach() -> None:
    """No strategy breaches → no child produced, all 3 attempted."""
    planner = _FakePlanner()
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.REFUSED, JudgeVerdict.REFUSED, JudgeVerdict.EVADED])

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1,
    )

    assert res.winning_strategy is None
    assert res.child_orm is None
    assert planner.planned == list(ESCALATION_LADDER)
    assert [o for _, o in res.attempts] == ["no_breach", "no_breach", "no_breach"]


@pytest.mark.asyncio
async def test_ladder_skips_refused_plan_strategy() -> None:
    """A refused plan counts as 'refused' and the ladder moves to the next strategy."""

    class _RefuseFirstPlanner(_FakePlanner):
        async def plan(self, parent, *, n_turns, arms_strategy):
            self.planned.append(arms_strategy)
            return None if arms_strategy == "crescendo" else _plan()

    planner = _RefuseFirstPlanner()
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # actor_attack breaches

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1,
    )

    assert res.winning_strategy == "actor_attack"
    assert res.attempts[0] == ("crescendo", "refused")
    assert res.attempts[1] == ("actor_attack", "breach")


@pytest.mark.asyncio
async def test_autoladder_tier1_image_breach_short_circuits_before_planner() -> None:
    """Tier-1: the refused payload rendered as an image breaches → planner never runs."""
    planner = _FakePlanner()
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # first image renderer breaches

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1, image_renderers=("mml:wr", "vpi:lowcontrast"),
    )

    assert res.winning_strategy == "image:mml:wr"
    assert res.child_orm is None  # image-tier win → no new primitive persisted
    assert planner.planned == []  # escalation tier never reached
    assert res.attempts == [("image:mml:wr", "breach")]


@pytest.mark.asyncio
async def test_autoladder_falls_through_image_tier_to_escalation() -> None:
    """Image renderers refuse → ladder advances to the escalation tier."""
    planner = _FakePlanner()
    panel = _FakePanel()
    # 1 image attempt refuses, then crescendo escalation breaches.
    judge = _FakeJudge([JudgeVerdict.REFUSED, JudgeVerdict.FULL_BREACH])

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1, image_renderers=("mml:wr",),
    )

    assert res.attempts[0] == ("image:mml:wr", "no_breach")
    assert res.winning_strategy == "crescendo"
    assert planner.planned == ["crescendo"]  # reached the escalation tier


@pytest.mark.asyncio
async def test_autoladder_coj_tier_is_planner_free() -> None:
    """Tier-2 CoJ breaches with NO planner call (deterministic decomposition)."""
    planner = _FakePlanner()
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # first CoJ op breaches

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1, coj_operations=("delete_then_insert", "insert_then_delete"),
    )

    assert res.winning_strategy == "coj:delete_then_insert"
    assert res.child_orm is not None  # CoJ winner IS persisted (a real multi-turn child)
    assert res.child_orm.requires_multi_turn is True
    assert planner.planned == []  # CoJ needs no planner
    assert res.attempts == [("coj:delete_then_insert", "breach")]


@pytest.mark.asyncio
async def test_autoladder_structured_tier_is_planner_free() -> None:
    """Tier-3 structured-data (#12) breaches with NO planner call; slot variant,
    so no child is persisted (like the image tier)."""
    planner = _FakePlanner()
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # first format breaches

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1, structured_formats=("json", "csv"),
    )

    assert res.winning_strategy == "structured:json"
    assert res.child_orm is None  # slot variant of the parent — not persisted
    assert planner.planned == []  # structured-data needs no planner
    assert res.attempts == [("structured:json", "breach")]


@pytest.mark.asyncio
async def test_autoladder_structured_advances_then_breaches() -> None:
    """Tier-3 tries formats in order; first no-breach, second breaches."""
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.REFUSED, JudgeVerdict.FULL_BREACH])

    res = await run_escalation_ladder_one(
        _parent(), planner=_FakePlanner(), panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1, structured_formats=("json", "csv"),
    )

    assert res.attempts == [("structured:json", "no_breach"), ("structured:csv", "breach")]
    assert res.winning_strategy == "structured:csv"


@pytest.mark.asyncio
async def test_autoladder_audio_tier_skipped_without_audio_config() -> None:
    """Tier-4 audio is skipped entirely when no config accepts audio (claude-haiku
    is not audio-capable) — no `say` invoked, no attempts recorded."""
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])
    res = await run_escalation_ladder_one(
        _parent(), planner=_FakePlanner(), panel=_FakePanel(), judge=judge,
        configs=_ONE_CONFIG, n_trials=1, audio_styles=("plain", "fast"),
    )
    # no audio config ⇒ no audio attempts; falls through to the planner tier
    assert not any(a.startswith("audio:") for a, _ in res.attempts)


@pytest.mark.asyncio
@pytest.mark.skipif(not _HAS_SAY, reason="macOS `say` not available")
async def test_autoladder_audio_tier_breaches_on_audio_config() -> None:
    """Tier-4 audio (#6) breaches against the audio-capable config, planner-free."""
    planner = _FakePlanner()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge,
        configs=_AUDIO_CONFIG, n_trials=1, audio_styles=("plain", "fast"),
    )

    assert res.winning_strategy == "audio:plain"
    assert res.child_orm is None  # slot variant — not persisted
    assert planner.planned == []  # audio needs no planner
    assert res.attempts == [("audio:plain", "breach")]


@pytest.mark.asyncio
async def test_ladder_survives_unrenderable_plan() -> None:
    """A plan whose turns reference unpopulated slots raises at render time —
    the ladder records 'render_error' and moves on instead of crashing."""

    class _BadFirstPlanner(_FakePlanner):
        async def plan(self, parent, *, n_turns, arms_strategy):
            self.planned.append(arms_strategy)
            if arms_strategy == "crescendo":
                # turn 2 needs a slot that isn't in the parent's slots/defaults.
                return EscalationPlan(
                    objective="leak the system prompt",
                    turns=["benign t1", "follow-up {nonexistent_slot}", "objective t3"],
                    slot_requirements={"1": ["nonexistent_slot"]},
                    rationale="r",
                    planner_model="anthropic/claude-sonnet-4-6",
                )
            return _plan()

    planner = _BadFirstPlanner()
    panel = _FakePanel()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # actor_attack breaches

    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=panel, judge=judge, configs=_ONE_CONFIG,
        n_trials=1,
    )

    assert res.attempts[0] == ("crescendo", "render_error")  # caught, not crashed
    assert res.winning_strategy == "actor_attack"  # ladder advanced
