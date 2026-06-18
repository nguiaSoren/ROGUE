"""Tests for `rogue.harvest.bandit` — epsilon-greedy SERP query bandit.

Per ROGUE_PLAN.md §11.6 acceptance cases:
  - Cold-start: untested arms (pulls == 0) are explored in priority
  - Exploitation: high-yield arms get picked first at epsilon=0
  - Tie-handling: arms with equal yield don't deadlock the picker
  - Persistence: to_disk / from_disk round-trip preserves state
  - Defensive: unknown arm_id on `record()` registers it on the fly
"""

from __future__ import annotations

import json

import pytest

from rogue.harvest.bandit import (
    DEFAULT_SEED,
    EpsilonGreedyBandit,
    QueryArm,
)


@pytest.fixture
def small_arm_pool() -> list[QueryArm]:
    """A 5-arm pool for fast tests."""
    return [
        QueryArm("arm_a", "site:a.com after:{date}"),
        QueryArm("arm_b", "site:b.com after:{date}"),
        QueryArm("arm_c", "site:c.com after:{date}"),
        QueryArm("arm_d", "site:d.com after:{date}"),
        QueryArm("arm_e", "site:e.com after:{date}"),
    ]


# --------------------------------------------------------------------------- #
# Cold-start exploration
# --------------------------------------------------------------------------- #


def test_cold_start_explores_every_arm_before_repeating(small_arm_pool) -> None:
    """First N pulls should hit each of N arms exactly once (cold-start)."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool, epsilon=0.0)
    picked = bandit.select(k=5)
    picked_ids = {a.arm_id for a in picked}
    assert picked_ids == {"arm_a", "arm_b", "arm_c", "arm_d", "arm_e"}


def test_cold_start_uses_declaration_order(small_arm_pool) -> None:
    """Cold-start picks happen in declaration order so the operator can
    predict the first day's harvest."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool, epsilon=0.0)
    picked = bandit.select(k=3)
    assert [a.arm_id for a in picked] == ["arm_a", "arm_b", "arm_c"]


def test_select_clamps_k_to_pool_size(small_arm_pool) -> None:
    """Requesting more arms than exist returns the full pool, not a hang."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool, epsilon=0.0)
    picked = bandit.select(k=999)
    assert len(picked) == 5


def test_select_k_zero_returns_empty(small_arm_pool) -> None:
    bandit = EpsilonGreedyBandit(arms=small_arm_pool)
    assert bandit.select(k=0) == []


# --------------------------------------------------------------------------- #
# Exploitation
# --------------------------------------------------------------------------- #


def test_high_yield_arm_wins_at_epsilon_zero(small_arm_pool) -> None:
    """After warming all arms, epsilon=0 picks the highest-yield first."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool, epsilon=0.0)
    bandit.record("arm_a", novel=1, cost_usd=0.10)   # yield 10
    bandit.record("arm_b", novel=10, cost_usd=0.10)  # yield 100 — winner
    bandit.record("arm_c", novel=5, cost_usd=0.10)   # yield 50
    bandit.record("arm_d", novel=0, cost_usd=0.10)   # yield 0
    bandit.record("arm_e", novel=2, cost_usd=0.10)   # yield 20

    # All warm now; first pick should be the high-yield arm.
    first = bandit.select(k=1)[0]
    assert first.arm_id == "arm_b"


def test_tied_zero_yield_arms_do_not_deadlock(small_arm_pool) -> None:
    """If every arm has 0 yield (or tied), the picker still returns k arms
    deterministically — never raises or returns fewer than k."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool, epsilon=0.0)
    for arm in small_arm_pool:
        bandit.record(arm.arm_id, novel=0, cost_usd=0.01)
    picked = bandit.select(k=3)
    assert len(picked) == 3
    # Determinism: ties broken by arm_id lexicographic order.
    assert [a.arm_id for a in picked] == ["arm_a", "arm_b", "arm_c"]


def test_top_arms_excludes_cold_arms(small_arm_pool) -> None:
    """`top_arms()` should only return warm (pulls > 0) arms."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool)
    bandit.record("arm_a", novel=10, cost_usd=0.01)
    bandit.record("arm_b", novel=5, cost_usd=0.01)
    # arm_c, arm_d, arm_e stay cold.
    top = bandit.top_arms(n=10)
    assert {a.arm_id for a in top} == {"arm_a", "arm_b"}


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #


def test_persistence_round_trips(small_arm_pool, tmp_path) -> None:
    """to_disk → from_disk preserves per-arm stats."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool, epsilon=0.15)
    bandit.record("arm_a", novel=7, cost_usd=0.10)
    bandit.record("arm_b", novel=3, cost_usd=0.05)
    bandit.record("arm_a", novel=2, cost_usd=0.10)  # second pull

    state_path = tmp_path / "discovery_bandit.json"
    bandit.to_disk(state_path)
    assert state_path.exists()

    restored = EpsilonGreedyBandit.from_disk(small_arm_pool, state_path)
    assert restored.stats["arm_a"].pulls == 2
    assert restored.stats["arm_a"].total_novel == 9
    assert abs(restored.stats["arm_a"].total_cost_usd - 0.20) < 1e-9
    assert restored.stats["arm_b"].pulls == 1
    assert restored.stats["arm_b"].total_novel == 3
    # Untouched arms should be cold-init.
    assert restored.stats["arm_c"].pulls == 0


def test_from_disk_returns_fresh_when_file_missing(small_arm_pool, tmp_path) -> None:
    """Missing state file → fresh bandit, no crash."""
    state_path = tmp_path / "does_not_exist.json"
    bandit = EpsilonGreedyBandit.from_disk(small_arm_pool, state_path)
    assert all(bandit.stats[a.arm_id].pulls == 0 for a in small_arm_pool)


def test_from_disk_drops_orphan_arms_not_in_pool(small_arm_pool, tmp_path) -> None:
    """Saved state for arms removed from the pool gets dropped on load."""
    state_path = tmp_path / "discovery_bandit.json"
    blob = {
        "epsilon": 0.1,
        "seed": DEFAULT_SEED,
        "updated_at": "2026-05-26T00:00:00+00:00",
        "arms": [
            {"arm_id": "arm_a", "pulls": 3, "total_novel": 9, "total_cost_usd": 0.05},
            {"arm_id": "arm_removed", "pulls": 99, "total_novel": 0, "total_cost_usd": 1.0},
        ],
    }
    state_path.write_text(json.dumps(blob))
    restored = EpsilonGreedyBandit.from_disk(small_arm_pool, state_path)
    assert restored.stats["arm_a"].pulls == 3
    assert "arm_removed" not in restored.stats


def test_to_disk_atomic_write(small_arm_pool, tmp_path) -> None:
    """`to_disk` writes via a `.tmp` then renames — no partial-file artifact."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool)
    state_path = tmp_path / "discovery_bandit.json"
    bandit.to_disk(state_path)
    assert state_path.exists()
    # No leftover .tmp file.
    assert not (tmp_path / "discovery_bandit.json.tmp").exists()


# --------------------------------------------------------------------------- #
# Defensive `record()` behavior
# --------------------------------------------------------------------------- #


def test_record_on_unknown_arm_id_registers_it(small_arm_pool) -> None:
    """Recording for an arm_id not in the pool registers it (defensive — the
    pool can grow between runs)."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool)
    bandit.record("arm_brand_new", novel=4, cost_usd=0.02)
    assert "arm_brand_new" in bandit.stats
    assert bandit.stats["arm_brand_new"].pulls == 1


def test_record_clamps_negative_inputs(small_arm_pool) -> None:
    """Negative novel/cost values get clamped to 0 — bookkeeping must never go negative."""
    bandit = EpsilonGreedyBandit(arms=small_arm_pool)
    bandit.record("arm_a", novel=-5, cost_usd=-0.10)
    assert bandit.stats["arm_a"].pulls == 1
    assert bandit.stats["arm_a"].total_novel == 0
    assert bandit.stats["arm_a"].total_cost_usd == 0.0


def test_default_bandit_arms_returns_expected_pool() -> None:
    """`default_bandit_arms()` should match the §5.2 SERP query inventory."""
    from rogue.harvest.discovery_agent import default_bandit_arms

    arms = default_bandit_arms()
    # All arm_ids must be unique.
    assert len(set(a.arm_id for a in arms)) == len(arms)
    # Pool must include the canonical sources we built.
    arm_ids = {a.arm_id for a in arms}
    assert "arxiv_prompt_injection" in arm_ids
    assert "github_pliny_umbrella" in arm_ids
    assert "blog_etr_after" in arm_ids
    # Approximate pool size: 39 original §5.2 arms + 6 multimodal (§1b, 2026-06-03)
    # + 7 source-expansion (2026-06-04, OpenReview/ACL/garak/HF/advisory/huntr) = 52.
    # Bound stays loose so a future arm or two doesn't trip it; a halving or a
    # runaway doubling still does.
    assert 28 <= len(arms) <= 60, f"unexpected pool size {len(arms)}"


def test_discovery_agent_with_bandit_calls_select(small_arm_pool, monkeypatch) -> None:
    """DiscoveryAgent with a bandit calls `bandit.select(k=10)` for `serp_queries()`."""
    from datetime import datetime, timezone
    from rogue.harvest.discovery_agent import DiscoveryAgent

    bandit = EpsilonGreedyBandit(arms=small_arm_pool, epsilon=0.0)
    # Fake BD client — never actually called by `serp_queries` (no plugin run).

    class _NoopClient:
        async def aclose(self): pass

    agent = DiscoveryAgent(fetcher=_NoopClient(), plugins=[], bandit=bandit)
    queries = agent.serp_queries(datetime.now(timezone.utc))
    # 5-arm pool clamps k=10 down to 5.
    assert len(queries) == 5
    assert len(agent.last_selected_arms) == 5
    # `{date}` got substituted.
    for q in queries:
        assert "{date}" not in q
