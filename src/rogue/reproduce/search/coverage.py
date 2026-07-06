"""Coverage / behavioral-diversity reward (AutoPT Feature 3) — reward = compliance + λ·novelty.

ROGUE optimizing breach alone can mode-collapse onto one breach class. AutoPT rewards behavioral
COVERAGE, not just breaches. Black-box, we approximate coverage via RESPONSE-embedding diversity:
a rollout whose response is far from every response seen this search is novel. novelty = 1 − max
cosine-sim to seen responses (distance to the nearest neighbor). λ tunes explore vs exploit; λ=0
recovers pure compliance (Feature 2). Stateful + per-search — construct a fresh one per search.

``embed_fn`` is pluggable (``Callable[[str], list[float]]`` — the same shape as
``dedupe.embeddings.Deduplicator.embed_fn``), so tests run offline and priced runs share the code.
Every rollout embeds its response, so on a paid run this adds one embedding call per rollout.
"""

from __future__ import annotations

import math
from typing import Callable

from .searcher import RolloutOutcome

EmbedFn = Callable[[str], "list[float]"]


class NoveltyReward:
    """A stateful reward: compliance + λ · (1 − max cosine-sim to responses seen this search)."""

    def __init__(self, embed_fn: EmbedFn, lam: float = 0.3) -> None:
        self.embed_fn = embed_fn
        self.lam = lam
        self._seen: list[list[float]] = []

    def __call__(self, outcome: RolloutOutcome) -> float:
        comp = outcome.compliance or 0.0
        if self.lam <= 0.0 or not outcome.response:
            return comp
        emb = self.embed_fn(outcome.response)
        nov = self._novelty(emb)
        self._seen.append(emb)
        return comp + self.lam * nov

    def _novelty(self, emb: list[float]) -> float:
        if not self._seen:
            return 1.0  # the first response is maximally novel
        best_sim = max(_cosine(emb, s) for s in self._seen)
        return max(0.0, 1.0 - best_sim)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


__all__ = ["NoveltyReward", "EmbedFn"]
