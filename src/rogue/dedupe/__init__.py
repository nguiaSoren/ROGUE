"""Dedup layer — pgvector cosine + function-word divergence. See ROGUE_PLAN.md §3.1 LAYER 3."""

from .embeddings import DEFAULT_COSINE_THRESHOLD, Deduplicator
from .function_word_divergence import (
    FUNCTION_WORDS,
    function_word_divergence,
    is_near_duplicate,
)
from .llm_authored import (
    HUMAN_AUTHORED_THRESHOLD,
    LLM_AUTHORED_THRESHOLD,
    LLMAuthoredScore,
    llm_authored_score,
)
from .quarantine import (
    QUARANTINE_BUDGET_THRESHOLD_USD,
    QUARANTINE_SCORE_FLOOR,
    should_quarantine,
)

__all__ = [
    "DEFAULT_COSINE_THRESHOLD",
    "Deduplicator",
    "FUNCTION_WORDS",
    "HUMAN_AUTHORED_THRESHOLD",
    "LLM_AUTHORED_THRESHOLD",
    "LLMAuthoredScore",
    "QUARANTINE_BUDGET_THRESHOLD_USD",
    "QUARANTINE_SCORE_FLOOR",
    "function_word_divergence",
    "is_near_duplicate",
    "llm_authored_score",
    "should_quarantine",
]
