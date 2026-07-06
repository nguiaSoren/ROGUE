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
from scripts.reproduce.synthesize_escalations import (
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


# --------------------------------------------------------------------------- #
# §10.9 candidate-probe (instrumented-evaluation mode)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_normal_mode_image_breach_starves_the_candidate() -> None:
    """Baseline (the bias we're fixing): a Tier-1 image breach short-circuits, so a
    harvested candidate sitting in Tier 5 is NEVER attempted."""
    planner = _FakePlanner()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # image breaches immediately
    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge, configs=_ONE_CONFIG,
        n_trials=1, image_renderers=("mml:wr",), strategies=("crescendo", "cand1"),
    )
    assert res.attempts == [("image:mml:wr", "breach")]
    assert planner.planned == []  # candidate never reached


@pytest.mark.asyncio
async def test_candidate_probe_continues_past_image_breach_to_try_candidate() -> None:
    """Probe mode: the image breach is recorded but does NOT stop the ladder — it
    keeps going until the harvested candidate is attempted (and breaches here)."""
    planner = _FakePlanner()
    judge = _FakeJudge([
        JudgeVerdict.FULL_BREACH,  # image:mml:wr breaches (Tier 1)
        JudgeVerdict.REFUSED,      # crescendo (Tier 5) no breach
        JudgeVerdict.FULL_BREACH,  # cand1 (Tier 5 candidate) breaches
    ])
    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge, configs=_ONE_CONFIG,
        n_trials=1, image_renderers=("mml:wr",), strategies=("crescendo", "cand1"),
        candidate_attempt_quota=1, candidate_ids=frozenset({"cand1"}),
    )
    assert ("image:mml:wr", "breach") in res.attempts  # recorded...
    assert "cand1" in planner.planned                  # ...but candidate WAS tried
    assert ("cand1", "breach") in res.attempts         # and it breached
    assert res.winning_strategy == "image:mml:wr"      # first breach kept for stats


@pytest.mark.asyncio
async def test_candidate_quota_stops_once_met() -> None:
    """The quota stops once N candidates are attempted — it doesn't keep trying
    non-candidate strategies that sit after them."""
    planner = _FakePlanner()
    judge = _FakeJudge([JudgeVerdict.REFUSED, JudgeVerdict.REFUSED])
    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge, configs=_ONE_CONFIG,
        n_trials=1, strategies=("cand1", "crescendo"),
        candidate_attempt_quota=1, candidate_ids=frozenset({"cand1"}),
    )
    assert "cand1" in planner.planned
    assert "crescendo" not in planner.planned  # quota of 1 met after cand1 → stop
    assert res.winning_strategy is None  # nothing breached


@pytest.mark.asyncio
async def test_candidate_quota_reserves_exactly_n_attempts() -> None:
    """quota=1 with two candidates: only the first candidate is reserved/attempted,
    the second is left to the normal early-stop economy."""
    planner = _FakePlanner()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # image breaches at Tier 1
    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge, configs=_ONE_CONFIG,
        n_trials=1, image_renderers=("mml:wr",),
        strategies=("cand1", "cand2"),
        candidate_attempt_quota=1, candidate_ids=frozenset({"cand1", "cand2"}),
    )
    # Image breach didn't stop the ladder (quota unmet), one candidate was reserved...
    assert ("image:mml:wr", "breach") in res.attempts
    assert len(planner.planned) == 1  # exactly N=1 candidate attempted, not both
    assert res.winning_strategy == "image:mml:wr"


# --------------------------------------------------------------------------- #
# §10.10 Adaptive Technique Prioritization — cross-tier (contextual) ordering
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_default_no_cross_tier_order_preserves_fixed_tier_sequence() -> None:
    """REPRODUCIBILITY GUARD: with cross_tier_order=None (the default + every non-
    contextual mode), the ladder visits image → planner in the FIXED tier order, so a
    Tier-1 image breach short-circuits before the planner tier — byte-for-byte the
    legacy behavior. This is the safety net for the whole Phase-1 refactor."""
    planner = _FakePlanner()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # image breaches at Tier 1
    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge, configs=_ONE_CONFIG,
        n_trials=1, image_renderers=("mml:wr",), strategies=("crescendo",),
        cross_tier_order=None,
    )
    assert res.attempts == [("image:mml:wr", "breach")]  # fixed tier order, image first
    assert planner.planned == []  # planner tier never reached (image short-circuited)
    assert res.winning_strategy == "image:mml:wr"


@pytest.mark.asyncio
async def test_cross_tier_order_runs_planner_before_image() -> None:
    """CROSS-TIER PROMOTION: when cross_tier_order puts a planner strategy ahead of the
    image renderers, the ladder executes crescendo FIRST (the whole point of contextual
    mode — a strong planner prior rises above a tier-1 renderer)."""
    planner = _FakePlanner()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # whatever runs first breaches
    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge, configs=_ONE_CONFIG,
        n_trials=1, image_renderers=("mml:wr",), strategies=("crescendo",),
        cross_tier_order=("crescendo", "image:mml:wr"),
    )
    # crescendo ran first and breached → image renderer never reached.
    assert res.winning_strategy == "crescendo"
    assert planner.planned == ["crescendo"]
    assert res.attempts == [("crescendo", "breach")]
    assert not any(lbl.startswith("image:") for lbl, _ in res.attempts)


@pytest.mark.asyncio
async def test_cross_tier_order_advances_through_units_in_blend_order() -> None:
    """Contextual path advances unit-by-unit in the supplied order, preserving the
    first-breach-wins semantics across tiers (planner no_breach → image breach)."""
    planner = _FakePlanner()
    judge = _FakeJudge([JudgeVerdict.REFUSED, JudgeVerdict.FULL_BREACH])
    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge, configs=_ONE_CONFIG,
        n_trials=1, image_renderers=("mml:wr",), strategies=("crescendo",),
        cross_tier_order=("crescendo", "image:mml:wr"),
    )
    assert res.attempts == [("crescendo", "no_breach"), ("image:mml:wr", "breach")]
    assert res.winning_strategy == "image:mml:wr"


@pytest.mark.asyncio
async def test_cross_tier_order_audio_unit_skipped_without_audio_config() -> None:
    """An audio unit in the cross-tier order is silently skipped (no attempt) when no
    config accepts audio — same eligibility gate as the fixed Tier-4 block."""
    planner = _FakePlanner()
    judge = _FakeJudge([JudgeVerdict.FULL_BREACH])  # crescendo breaches
    res = await run_escalation_ladder_one(
        _parent(), planner=planner, panel=_FakePanel(), judge=judge, configs=_ONE_CONFIG,
        n_trials=1, strategies=("crescendo",),
        cross_tier_order=("audio:plain", "crescendo"),
    )
    assert not any(lbl.startswith("audio:") for lbl, _ in res.attempts)  # skipped
    assert res.winning_strategy == "crescendo"


def test_build_escalation_context_contextual_promotes_high_prior_planner(monkeypatch) -> None:
    """build_escalation_context under mode==contextual derives the target vendor/family
    from the single config and produces a CROSS-TIER blended order in which a planner
    strategy with a strong global prior outranks weak tier-1 renderers. Mocked at the
    DB-touching seams (rates + setup helpers) — no DB, no live LLM."""
    from rogue.reproduce import escalation_ladder as EL
    from rogue.reproduce import ladder_priors
    from rogue.reproduce import renderer_registry, strategy_library, strategy_lifecycle
    from rogue.reproduce.ladder_priors import VendorFamilyStat

    # Force contextual mode.
    monkeypatch.setenv("ROGUE_LADDER_ORDER", "contextual")

    # Stub the DB-touching setup helpers so no real session/schema is needed.
    monkeypatch.setattr(renderer_registry, "active_dynamic_strategies", lambda s, m: ())
    monkeypatch.setattr(strategy_library, "load_strategy_library", lambda *a, **k: {})
    monkeypatch.setattr(strategy_lifecycle, "ladder_config_from_env", lambda: ("run", 0))
    # Contextual falls into the breach-rate else-branch for the per-tier pre-sort.
    monkeypatch.setattr(ladder_priors, "strategy_breach_rates", lambda s, **k: {})

    class _Plan:
        rotation = ("crescendo", "actor_attack", "acronym")
        candidate_ids = ()
        harvested_ids = frozenset()

    monkeypatch.setattr(
        strategy_lifecycle, "build_rotation_plan", lambda *a, **k: _Plan()
    )
    monkeypatch.setattr(strategy_lifecycle, "format_rotation_plan", lambda p: "plan")

    captured = {}

    def _fake_rates(session, *, target_vendor, target_family, target_size_class=None):
        captured["vendor"] = target_vendor
        captured["family"] = target_family
        # crescendo: strong global prior; image renderers: proven weak (0 of many).
        return {
            "crescendo": VendorFamilyStat("crescendo", 20, 20, 0, 0, 0, 0),
            **{
                f"image:{r}": VendorFamilyStat(f"image:{r}", 0, 30, 0, 0, 0, 0)
                for r in EL.DEFAULT_IMAGE_RENDERERS
            },
        }

    monkeypatch.setattr(ladder_priors, "vendor_family_strategy_rates", _fake_rates)

    ctx = EL.build_escalation_context(
        session=object(),  # never used (all DB helpers stubbed)
        configs=_ONE_CONFIG,  # single claude-haiku config
        n_parents_est=1,
        n_trials=1,
        planner=_FakePlanner(),  # injected ⇒ no EscalationPlanner.from_env / API key
    )

    assert ctx.ladder_mode == "contextual"
    # vendor/family derived from the single claude config.
    assert captured == {"vendor": "anthropic", "family": "claude"}
    order = ctx.cross_tier_order
    assert order is not None
    # The strong-prior planner strategy is promoted ahead of EVERY weak image renderer.
    first_image = next(i for i, lbl in enumerate(order) if lbl.startswith("image:"))
    assert order.index("crescendo") < first_image
