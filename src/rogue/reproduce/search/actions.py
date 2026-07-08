"""The mixed expansion action set (AutoPT Feature 2) — cheap deterministic obfuscation mutations
(~$0 each) plus an optional pluggable LLM-refine (PAIR-style). MCTS/bandit choose among these to
expand a node; keeping refine pluggable lets the A/B run offline (no LLM) and priced runs share code.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from rogue.obfuscation.operators import active_operators, apply_operator
from rogue.reproduce.structured_data import STRUCTURED_FORMATS, wrap_structured_data

from .searcher import Action, RolloutOutcome

# (prompt, parent_outcome) -> (refined_prompt, cost_usd). parent carries the target's last behaviour
# (response + compliance) so a PAIR refine can condition on it.
RefineFn = Callable[[str, Optional[RolloutOutcome]], Awaitable["tuple[str, float]"]]


def cheap_mutation_actions() -> list[Action]:
    """One $0 Action per deterministic obfuscation operator (leetspeak, homoglyph, base64_wrap, …)."""

    def _mk(name: str) -> Action:
        async def _apply(prompt: str, parent: Optional[RolloutOutcome] = None) -> tuple[str, float]:
            return apply_operator(name, prompt), 0.0

        return Action(name=f"obf:{name}", apply=_apply, kind="mutation")

    # active_operators() = baseline 10, plus the Q16 extended set only when
    # ROGUE_OBF_EXTENDED is on — so the search action space is byte-identical
    # to today unless the flag is flipped.
    return [_mk(op.name) for op in active_operators()]


def framing_mutation_actions() -> list[Action]:
    """$0 SEMANTIC-framing mutations (XDAC-diversity-inspired) — richer than the character-level
    obfuscation set. Reuses the existing, tested `structured_data` machinery to re-frame the payload as
    an authoritative directive inside a JSON/CSV/YAML/XML document (the data/instruction-confusion
    vector). Deterministic and $0, so the offline A/B still runs; gives the searcher a semantic axis to
    explore alongside byte-level obfuscation. Full XDAC-style reference-augmented / persona-styled
    generation is the LLM-costed domain of `refine_action` (parallel to PAIR), not these $0 templates."""

    def _mk(fmt: str) -> Action:
        async def _apply(prompt: str, parent: Optional[RolloutOutcome] = None) -> tuple[str, float]:
            return wrap_structured_data(prompt, fmt), 0.0

        return Action(name=f"frame:structured_{fmt}", apply=_apply, kind="mutation")

    return [_mk(fmt) for fmt in STRUCTURED_FORMATS]


def refine_action(refine_fn: RefineFn, *, name: str = "llm_refine") -> Action:
    """An LLM-refine expansion (the 'smart', costed action). ``refine_fn`` wraps a PAIR attacker and
    conditions on the parent outcome (the target's last response + compliance)."""

    async def _apply(prompt: str, parent: Optional[RolloutOutcome] = None) -> tuple[str, float]:
        return await refine_fn(prompt, parent)

    return Action(name=name, apply=_apply, kind="refine")


def default_actions(refine_fn: Optional[RefineFn] = None, *, richer: bool = False) -> list[Action]:
    """The mixed set: cheap obfuscation mutations (+ ``richer`` semantic-framing mutations) + the
    LLM-refine when a ``refine_fn`` is supplied. ``richer`` stays OFF by default so the settled
    breach/$ A/B baseline is unchanged; opt in to widen the $0 action space with the framing set."""
    actions = cheap_mutation_actions()
    if richer:
        actions += framing_mutation_actions()
    if refine_fn is not None:
        actions.append(refine_action(refine_fn))
    return actions


__all__ = [
    "cheap_mutation_actions", "framing_mutation_actions", "refine_action", "default_actions", "RefineFn",
]
