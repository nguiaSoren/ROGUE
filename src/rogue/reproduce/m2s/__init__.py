"""M2S — Multi-turn-to-Single-turn consolidation of an EscalationPlan's turns.

Ha et al., *One-Shot is Enough: Consolidating Multi-Turn Attacks into Efficient
Single-Turn Prompts for LLMs* (arXiv 2503.04856). Three deterministic, rule-based
string formatters — Hyphenize, Numberize, Pythonize — fold an ordered multi-turn
jailbreak conversation into ONE structured single-turn prompt that preserves the
sequential context. In ROGUE this turns a `multi_turn_sequence` primitive (a
pre-baked Crescendo or an escalation-planner output) into a single-turn primitive
fired through the existing, fully-tested `render` → `run_attack` path at **1× trial**
(one victim call) instead of the K sequential victim calls a real `run_conversation`
spends — with zero attacker-LLM cost (the formatters are pure string templates).

Off by default (`ROGUE_M2S` unset). When off, every surface is byte-identical.
"""

from rogue.reproduce.m2s.consolidate import (
    M2S_METHODS,
    consolidate_primitive,
    consolidate_turns,
)
from rogue.reproduce.m2s.gate import (
    ENV_M2S,
    ENV_METHOD,
    M2SConfig,
    M2SPlan,
    apply_m2s,
    apply_m2s_pairs,
    resolve_m2s,
)

__all__ = [
    "M2S_METHODS",
    "consolidate_turns",
    "consolidate_primitive",
    "M2SConfig",
    "M2SPlan",
    "apply_m2s",
    "apply_m2s_pairs",
    "resolve_m2s",
    "ENV_M2S",
    "ENV_METHOD",
]
