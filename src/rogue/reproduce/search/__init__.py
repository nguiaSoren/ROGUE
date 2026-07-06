"""Escalation-search subsystem (AutoPT-inspired, black-box). A pluggable ``Searcher`` seam so the
bandit (prod baseline), MCTS, and future hierarchical/replace variants are interchangeable and
A/B-comparable, plus the continuous compliance signal (F1), the coverage/novelty reward (F3), and
the opt-in adversarial fix-hardening check (F4). Prototype-first: not wired into prod until the A/B
shows MCTS beats the bandit on real targets.
"""

from .ab import ABReport, ab_compare
from .actions import cheap_mutation_actions, default_actions, framing_mutation_actions, refine_action
from .bandit import BanditSearcher
from .compliance import COMPLIANCE_ANCHORS, compliance_score
from .coverage import NoveltyReward
from .goal_preservation import GoalPreservationResult, check_goal_preserved, make_goal_check
from .harden import HardenCheckResult, harden_check
from .mcts import MCTSSearcher
from .live import make_embed_fn, make_refine_action, make_rollout, make_seed_primitive
from .run import harden_from_remediation, search_escalate
from .searcher import Action, Budget, RolloutOutcome, SearchResult, default_reward

__all__ = [
    "compliance_score", "COMPLIANCE_ANCHORS",
    "Action", "Budget", "RolloutOutcome", "SearchResult", "default_reward",
    "MCTSSearcher", "BanditSearcher",
    "cheap_mutation_actions", "framing_mutation_actions", "refine_action", "default_actions",
    "NoveltyReward",
    "ab_compare", "ABReport",
    "harden_check", "HardenCheckResult",
    "check_goal_preserved", "make_goal_check", "GoalPreservationResult",
    "make_rollout", "make_refine_action", "make_embed_fn", "make_seed_primitive",
    "search_escalate", "harden_from_remediation",
]
