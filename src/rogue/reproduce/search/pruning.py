"""Pre-fire prompt pruning (AutoPT Feature 5) — the search-budget saver.

Every expansion in the escalation search fires a paid rollout (target + judge). But an attacker
searching a mutation space re-visits near-identical prompts constantly: TAP (arXiv 2312.02119, §3.2
"Prompt Redundancy") observes that "the prompts generated from the first iteration follow
nearly-identical strategies in many repetitions"; EvoJail (arXiv 2605.02921) makes population
diversity a first-class objective for exactly this reason. Today ROGUE's only novelty signal is
``coverage.NoveltyReward``, which acts on *response* embeddings AFTER a rollout has already been paid
for — it steers the search but never SKIPS a paid call.

This module adds the missing pre-fire gate: before firing a candidate, embed its **prompt** and skip
the rollout if it is cosine ≥ threshold to any prompt already FIRED this search. Two grounded
mechanisms, one object:

  * **Hard near-duplicate skip** — the money saver. TAP's Phase-1 prune realised per-expansion (ROGUE
    expands one child at a time — a b=1 PAIR-shaped loop — so there is no width-w frontier for TAP's
    Phase-2 prune; the per-expansion cosine skip is ROGUE's equivalent query-saver). The near-dup
    criterion is ROGUE's own: it reuses ``dedupe.DEFAULT_COSINE_THRESHOLD`` (0.92) and
    ``coverage._cosine`` — no new constant, no new dependency, no duplicated cosine.

  * **Soft prompt-novelty reward** — EvoJail's ``F(p) = S(p) + λ·D(p|P)`` (their Eq. 6/8), where
    S(p) is the compliance the searcher already climbs and D(p|P) = 1 − sim(p, population). EvoJail
    uses *mean* TF-IDF cosine to the population; ROGUE uses ``1 − max`` neural-embedding cosine to the
    fired set (stricter; consistent with ``coverage.NoveltyReward``). Off by default (``lam=0``).

Design mirrors the ``goal_preservation`` gate: a stateful, injectable object the searcher consults
before the rollout, env-gated and **off by default** — with the flag unset, ``resolve_pruner``
returns ``None`` and both searchers are byte-identical to today (zero embedding calls, zero behaviour
change). ``embed_fn`` is pluggable (same shape as ``dedupe.embeddings.EmbedFn`` /
``coverage.EmbedFn``) so tests run offline and priced runs reuse ``live.make_embed_fn``.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from rogue.dedupe.embeddings import DEFAULT_COSINE_THRESHOLD

from .coverage import _cosine

EmbedFn = Callable[[str], "list[float]"]

# Env surface — off by default; unset ⇒ resolve_pruner returns None ⇒ byte-identical to today.
ENV_PRUNE = "ROGUE_SEARCH_PRUNE"                 # off (default) | on
ENV_THRESHOLD = "ROGUE_SEARCH_PRUNE_THRESHOLD"   # cosine cut for a near-dup skip (default 0.92)
ENV_LAMBDA = "ROGUE_SEARCH_PRUNE_LAMBDA"         # EvoJail λ for the soft prompt-novelty reward (default 0.0)

_TRUTHY = ("on", "1", "true", "yes")

__all__ = ["PromptPruner", "resolve_pruner", "EmbedFn", "ENV_PRUNE", "ENV_THRESHOLD", "ENV_LAMBDA"]


class PromptPruner:
    """A stateful, per-search pre-fire gate over PROMPT embeddings.

    ``admit(prompt)`` embeds the candidate, records its novelty (``1 − max`` cosine to already-fired
    prompts), and returns ``False`` — skip the rollout — when it is a near-duplicate (max cosine ≥
    ``threshold``) of something already fired this search; otherwise records it as fired and returns
    ``True``. The first candidate (the seed) is always admitted. Construct a fresh one per search:
    the fired set is the search's own history, not a global corpus.

    ``lam`` is the EvoJail soft-reward weight the searcher reads AFTER ``admit`` (``last_novelty`` is
    the just-admitted prompt's D(p|P)); ``lam=0`` (default) leaves the search's reward untouched.
    """

    def __init__(self, embed_fn: EmbedFn, threshold: float = DEFAULT_COSINE_THRESHOLD, lam: float = 0.0) -> None:
        self.embed_fn = embed_fn
        self.threshold = threshold
        self.lam = lam
        self._fired: list[list[float]] = []
        self.n_pruned = 0       # candidates skipped as near-duplicates
        self.n_admitted = 0     # candidates fired (incl. the seed)
        self.last_novelty = 1.0  # D(p|P) of the most recent admit — the EvoJail reward term

    def _max_sim(self, emb: "list[float]") -> float:
        return max((_cosine(emb, s) for s in self._fired), default=0.0)

    def admit(self, prompt: str) -> bool:
        """True ⇒ fire (novel enough, now recorded as fired); False ⇒ skip (near-duplicate).

        Fail-open: a flaky embedder must never crash the search (matches ``live``/``goal_preservation``);
        an embedding error admits the prompt without recording it (better to fire a possible duplicate
        than to abort, and an unembeddable prompt can't seed future dedups anyway)."""
        try:
            emb = self.embed_fn(prompt)
        except Exception:  # noqa: BLE001 — a flaky embedder degrades to fire-all, never crashes
            self.last_novelty = 1.0
            return True
        sim = self._max_sim(emb) if self._fired else 0.0
        self.last_novelty = max(0.0, 1.0 - sim)
        if self._fired and sim >= self.threshold:
            self.n_pruned += 1
            return False
        self._fired.append(emb)
        self.n_admitted += 1
        return True

    @property
    def stats(self) -> dict:
        return {"n_admitted": self.n_admitted, "n_pruned": self.n_pruned,
                "threshold": self.threshold, "lam": self.lam}


def resolve_pruner(
    embed_fn: Optional[EmbedFn] = None, *, override: Optional[PromptPruner] = None,
) -> Optional[PromptPruner]:
    """Build the pre-fire pruner from the environment, or ``None`` when disabled.

    Off unless ``ROGUE_SEARCH_PRUNE`` ∈ {on,1,true,yes}. When on, needs an ``embed_fn`` to embed
    prompts (returns ``None`` with a no-op if none is available — pruning without embeddings is
    impossible, and silently degrading to fire-all is the safe default). ``override`` short-circuits
    for tests. Reads the threshold (default 0.92) and the EvoJail λ (default 0.0) from the env.
    """
    if override is not None:
        return override
    if os.environ.get(ENV_PRUNE, "off").strip().lower() not in _TRUTHY:
        return None
    if embed_fn is None:
        return None
    threshold = float(os.environ.get(ENV_THRESHOLD, DEFAULT_COSINE_THRESHOLD))
    lam = float(os.environ.get(ENV_LAMBDA, 0.0))
    return PromptPruner(embed_fn, threshold=threshold, lam=lam)
