"""Epsilon-greedy bandit over the SERP query pool.

LOCKED-AS-COMMITTED per ROGUE_PLAN.md §1.6 hidden-depth manifest item 5 and
§11.6 (decommissioned from Day-3 scope-flex to Day-2-evening hard-commit).
Wired unconditionally into ``DiscoveryAgent.run()``; the dashboard's
``/feed`` widget surfaces top-3 / bottom-3 arms to the depth-pass judge.

Why this exists: with 39 SERP queries in the §5.2 pool, blindly running all
of them every day burns SERP credit on dead queries. Epsilon-greedy lets the
harvest learn — high-yield queries (lots of NEW canonical primitives per
dollar) get pulled more; dead queries get pulled occasionally for exploration
but mostly skipped.

Public surface:

    arm = QueryArm(arm_id, query)
    bandit = EpsilonGreedyBandit(arms, epsilon=0.1, seed=20260524)
    picked: list[QueryArm] = bandit.select(k=10)        # ε-greedy top-k
    bandit.record(arm_id, novel: int, cost_usd: float)  # post-run reward
    bandit.to_disk(Path("data/discovery_bandit.json"))   # persist state
    bandit = EpsilonGreedyBandit.from_disk(arms, Path("..."))   # resume

Reward signal: ``novel`` is the count of NEW canonical primitives surfaced
by that arm (downstream of dedup). ``mean_yield = novel / max(1, cost_usd)``
gives reward-per-dollar so cheap-but-high-yield queries win over expensive
ones. Cold-start: untested arms (pulls == 0) get pulled first regardless of
epsilon to bootstrap the table.

Persistence shape (gitignored at ``data/discovery_bandit.json``):

    {
      "epsilon": 0.1,
      "seed": 20260524,
      "updated_at": "2026-05-27T03:14:00+00:00",
      "arms": [
        {"arm_id": "reddit_jb_new_method", "pulls": 12,
         "total_novel": 47, "total_cost_usd": 0.018, "mean_yield": 2611.1},
        ...
      ]
    }
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

__all__ = ["QueryArm", "EpsilonGreedyBandit", "DEFAULT_EPSILON", "DEFAULT_SEED"]


DEFAULT_EPSILON: float = 0.10
DEFAULT_SEED: int = 20260524


@dataclass(frozen=True)
class QueryArm:
    """One immutable SERP query — the bandit chooses among instances of these."""

    arm_id: str  # stable hash-shaped id; the dict key in the persisted state
    query: str  # the actual SERP query template with `{date}` placeholder


@dataclass
class _ArmStats:
    """Mutable per-arm stats. Stored as a dict on the bandit instance."""

    pulls: int = 0
    total_novel: int = 0
    total_cost_usd: float = 0.0

    @property
    def mean_yield(self) -> float:
        """NEW canonical primitives per dollar spent on this arm.

        Cost denominator floored at $0.001 so a freshly-recorded arm with
        a free SERP call doesn't divide by zero. Free queries with novel
        hits get a huge but finite reward — the bandit will pull them.
        """
        return self.total_novel / max(0.001, self.total_cost_usd)

    def to_dict(self, arm_id: str) -> dict:
        return {
            "arm_id": arm_id,
            "pulls": self.pulls,
            "total_novel": self.total_novel,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "mean_yield": round(self.mean_yield, 4),
        }


@dataclass
class EpsilonGreedyBandit:
    """ε-greedy over a fixed arm pool with cold-start + persistence.

    Provenance fields (``seeded_from_corpus_at`` / ``last_live_pulled_at``)
    let the dashboard distinguish synthetic warm-prior state (set by
    ``scripts/seed_bandit_from_corpus.py``) from actual live-harvest pulls
    (set when ``record()`` fires during ``scripts/harvest_once.py``). Both
    are ISO-8601 UTC strings; ``None`` means "never happened."
    """

    arms: list[QueryArm]
    epsilon: float = DEFAULT_EPSILON
    seed: int = DEFAULT_SEED
    stats: dict[str, _ArmStats] = field(default_factory=dict)
    seeded_from_corpus_at: str | None = None
    last_live_pulled_at: str | None = None

    def __post_init__(self) -> None:
        # Ensure every arm has a stats row even if never pulled.
        for arm in self.arms:
            self.stats.setdefault(arm.arm_id, _ArmStats())
        self._rng = random.Random(self.seed)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def select(self, k: int) -> list[QueryArm]:
        """Return ``k`` arms ε-greedy with cold-start exploration first.

        Algorithm:

          1. **Cold-start phase**: every arm with ``pulls == 0`` is pulled
             first (in declaration order), up to ``k``. Ensures every query
             gets at least one observation before the greedy strategy locks
             in on the early winners.
          2. **Once all arms warm**: with probability ``epsilon``, pull a
             uniformly random arm (exploration); otherwise pull the arm
             with the highest ``mean_yield`` not yet picked this round
             (exploitation).
          3. ``k`` is clamped to ``len(arms)`` so requesting more arms than
             exist never deadlocks.
        """
        k = max(0, min(k, len(self.arms)))
        if k == 0:
            return []

        cold = [a for a in self.arms if self.stats[a.arm_id].pulls == 0]
        if cold:
            picked = cold[:k]
            # Fill remaining slots with greedy choices if cold pool short of k.
            if len(picked) < k:
                already = {a.arm_id for a in picked}
                picked.extend(self._greedy_select(k - len(picked), exclude=already))
            return picked

        # All arms warm — ε-greedy.
        return self._greedy_select(k, exclude=set())

    def _greedy_select(self, k: int, *, exclude: set[str]) -> list[QueryArm]:
        eligible = [a for a in self.arms if a.arm_id not in exclude]
        picked: list[QueryArm] = []
        for _ in range(min(k, len(eligible))):
            if self._rng.random() < self.epsilon:
                # Explore: uniform random over remaining eligible arms.
                chosen = self._rng.choice(eligible)
            else:
                # Exploit: arg-max on mean_yield. Python's ``max`` is
                # left-biased — on ties it returns the FIRST occurrence in
                # iteration order. Since ``eligible`` preserves declaration
                # order (declared alphabetical in the test fixture, by
                # convention in default_bandit_arms), ties resolve to the
                # alphabetically-first arm_id deterministically.
                chosen = max(
                    eligible,
                    key=lambda a: self.stats[a.arm_id].mean_yield,
                )
            picked.append(chosen)
            eligible.remove(chosen)
        return picked

    # ------------------------------------------------------------------
    # Reward recording
    # ------------------------------------------------------------------

    def record(self, arm_id: str, novel: int, cost_usd: float) -> None:
        """Update the arm's stats with one observation.

        Stamps ``last_live_pulled_at`` so the dashboard can surface "seeded
        prior decayed by N live runs" provenance instead of pretending the
        state is purely from live observation.

        Args:
            arm_id: which arm produced these results.
            novel: count of NEW canonical primitives surfaced (post-dedup).
            cost_usd: actual BD spend attributed to this arm (typically the
                cost of one SERP call + optional follow-on Web Unlocker fetches).
        """
        if arm_id not in self.stats:
            # Unknown arm — silently register it so future selects see it.
            self.stats[arm_id] = _ArmStats()
        s = self.stats[arm_id]
        s.pulls += 1
        s.total_novel += max(0, int(novel))
        s.total_cost_usd += max(0.0, float(cost_usd))
        self.last_live_pulled_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "epsilon": self.epsilon,
            "seed": self.seed,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "seeded_from_corpus_at": self.seeded_from_corpus_at,
            "last_live_pulled_at": self.last_live_pulled_at,
            "arms": [self.stats[arm.arm_id].to_dict(arm.arm_id) for arm in self.arms],
        }

    def to_disk(self, path: Path) -> None:
        """Atomically persist state. Writes to ``path.tmp`` first then renames
        so a crashed harvest doesn't leave a half-written JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)

    @classmethod
    def from_disk(
        cls,
        arms: Iterable[QueryArm],
        path: Path,
        *,
        epsilon: float = DEFAULT_EPSILON,
        seed: int = DEFAULT_SEED,
    ) -> "EpsilonGreedyBandit":
        """Restore a bandit from disk. If ``path`` doesn't exist, returns a
        fresh bandit with all arms cold (pulls=0). New arms not in the saved
        state get added cold-start; arms in the saved state but not in
        ``arms`` are dropped (orphan cleanup)."""
        arms_list = list(arms)
        bandit = cls(arms=arms_list, epsilon=epsilon, seed=seed)
        if not path.exists():
            return bandit
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return bandit
        # Preserve provenance fields across reload (None when absent in legacy
        # state files written before these fields existed).
        bandit.seeded_from_corpus_at = data.get("seeded_from_corpus_at")
        bandit.last_live_pulled_at = data.get("last_live_pulled_at")
        known_ids = {a.arm_id for a in arms_list}
        for entry in data.get("arms", []):
            arm_id = entry.get("arm_id")
            if not arm_id or arm_id not in known_ids:
                continue
            bandit.stats[arm_id] = _ArmStats(
                pulls=int(entry.get("pulls", 0)),
                total_novel=int(entry.get("total_novel", 0)),
                total_cost_usd=float(entry.get("total_cost_usd", 0.0)),
            )
        return bandit

    # ------------------------------------------------------------------
    # Inspection (for dashboard / debugging)
    # ------------------------------------------------------------------

    def top_arms(self, n: int = 3) -> list[QueryArm]:
        """Top-N arms by mean_yield, excluding cold (pulls=0) arms."""
        warm = [a for a in self.arms if self.stats[a.arm_id].pulls > 0]
        warm.sort(key=lambda a: self.stats[a.arm_id].mean_yield, reverse=True)
        return warm[:n]

    def bottom_arms(self, n: int = 3) -> list[QueryArm]:
        """Bottom-N arms by mean_yield, excluding cold arms."""
        warm = [a for a in self.arms if self.stats[a.arm_id].pulls > 0]
        warm.sort(key=lambda a: self.stats[a.arm_id].mean_yield)
        return warm[:n]
