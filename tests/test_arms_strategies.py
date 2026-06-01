"""Tests for the ARMS strategy library (#9) and its EscalationPlanner seeding.

ARMS (arXiv 2510.02677) is borrowed as a strategy-prompt library — we do NOT
rebuild its agent. These tests lock the taxonomy (5 patterns × 17 strategies) and
verify the multi-turn strategies seed the planner without breaking the default
Crescendo behaviour. No network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rogue.reproduce.arms_strategies import (
    ADVERSARIAL_PATTERNS,
    ARMS_STRATEGIES,
    multi_turn_strategies,
    strategies_for_pattern,
)
from rogue.reproduce.escalation_planner import (
    EscalationPlanner,
    _build_planner_messages,
    _cache_key,
)
from rogue.schemas import AttackPrimitive

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _primitive() -> AttackPrimitive:
    data = json.loads(
        (FIXTURES_DIR / "02_copirate_365_cve_2026_24299.json").read_text(encoding="utf-8")
    )
    return AttackPrimitive.model_validate(data)


# --------------------------------------------------------------------------- #
# Taxonomy
# --------------------------------------------------------------------------- #


def test_taxonomy_has_five_patterns_and_seventeen_strategies() -> None:
    assert len(ADVERSARIAL_PATTERNS) == 5
    assert len(ARMS_STRATEGIES) == 17  # 17 strategies total (11 novel per paper)
    # every strategy's pattern is a known pattern
    assert {s.pattern for s in ARMS_STRATEGIES.values()} == set(ADVERSARIAL_PATTERNS)


def test_every_strategy_has_principle_and_directive() -> None:
    for s in ARMS_STRATEGIES.values():
        assert s.principle.strip(), f"{s.id} missing principle"
        assert s.directive.strip(), f"{s.id} missing directive"
        assert s.realized_by.strip()


def test_pattern_partition_covers_all_strategies() -> None:
    counted = sum(len(strategies_for_pattern(p)) for p in ADVERSARIAL_PATTERNS)
    assert counted == len(ARMS_STRATEGIES)
    # documented per-pattern counts (D.2): 6 / 2 / 3 / 3 / 3
    assert len(strategies_for_pattern("visual_context_cloaking")) == 6
    assert len(strategies_for_pattern("typographic_transformation")) == 2
    assert len(strategies_for_pattern("visual_reasoning_hijacking")) == 3
    assert len(strategies_for_pattern("visual_perturbation")) == 3


def test_strategies_for_pattern_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown pattern"):
        strategies_for_pattern("telepathy")


def test_multi_turn_strategies_are_the_planner_ones() -> None:
    ids = {s.id for s in multi_turn_strategies()}
    assert ids == {"crescendo", "actor_attack", "acronym"}


# --------------------------------------------------------------------------- #
# EscalationPlanner seeding
# --------------------------------------------------------------------------- #


def test_planner_messages_inject_arms_directive() -> None:
    primitive = _primitive()
    base_system, _ = _build_planner_messages(primitive, 3)
    actor_system, _ = _build_planner_messages(primitive, 3, arms_strategy="actor_attack")

    assert "ARMS STRATEGY OVERRIDE" not in base_system  # default crescendo untouched
    assert "ARMS STRATEGY OVERRIDE" in actor_system
    assert "Actor attack" in actor_system
    assert ARMS_STRATEGIES["actor_attack"].directive[:30] in actor_system


def test_planner_crescendo_is_noop_override() -> None:
    primitive = _primitive()
    base_system, _ = _build_planner_messages(primitive, 3)
    cres_system, _ = _build_planner_messages(primitive, 3, arms_strategy="crescendo")
    assert base_system == cres_system  # crescendo == the built-in default


def test_cache_key_differs_per_arms_strategy() -> None:
    base = _cache_key("p1", 3, "anthropic/x", "v1")
    actor = _cache_key("p1", 3, "anthropic/x", "v1", "actor_attack")
    acronym = _cache_key("p1", 3, "anthropic/x", "v1", "acronym")
    assert base != actor != acronym
    # crescendo == default (None) so they share a cache slot
    assert base == _cache_key("p1", 3, "anthropic/x", "v1", "crescendo")


@pytest.mark.asyncio
async def test_plan_rejects_non_multiturn_strategy(tmp_path: Path) -> None:
    """Selecting a renderer-only ARMS strategy (e.g. rule_based) on the planner errors."""
    planner = EscalationPlanner(cache_dir=tmp_path)
    # §10.9 Phase 3a generalized the drivable set (ARMS multi-turn ∪ harvested
    # text/multi_turn techniques), so the error now says "planner-drivable".
    with pytest.raises(ValueError, match="planner-drivable"):
        await planner.plan(_primitive(), n_turns=3, arms_strategy="rule_based")
