"""Technique Retrieval System (Team B).

Candidate-generator layer that sits in front of the contextual scheduler:

    target -> TechniqueRetriever (top-K) -> contextual scheduler (rank) -> ladder

The retriever embeds every technique *label* (the ladder strategy label, e.g.
``crescendo`` / ``image:mml:wr``) and every target (TargetFingerprint), then
returns the top-K most similar techniques for a given target via pgvector cosine
similarity. The scheduler remains the ranker; retrieval is the candidate set.

Public surface is populated by the retrieval submodules (embedding_text, embed,
target_fingerprint, technique_profile_builder, retriever, evaluation).

Public API (importable from ``rogue.retrieval``)
------------------------------------------------
Schemas (re-exported from ``rogue.schemas``):
  TechniqueProfile, TargetFingerprint

Embedding helpers:
  build_technique_embedding_text, build_target_embedding_text
  default_embed_fn, deterministic_embed_fn

Target / profile builders:
  build_target_fingerprint, build_technique_profiles

Retrieval:
  TechniqueRetriever, RetrievalResult

Evaluation:
  evaluate_recall
"""

from __future__ import annotations

# --- Schemas (owned by rogue.schemas, re-exported for convenience) ---
from rogue.schemas import TargetFingerprint, TechniqueProfile

# --- Embedding text builders ---
from rogue.retrieval.embedding_text import (
    build_target_embedding_text,
    build_technique_embedding_text,
)

# --- Embedding function factories ---
from rogue.retrieval.embed import default_embed_fn, deterministic_embed_fn

# --- Target fingerprint builder ---
from rogue.retrieval.target_fingerprint import build_target_fingerprint

# --- Technique profile builder ---
from rogue.retrieval.technique_profile_builder import build_technique_profiles

# --- Retriever ---
from rogue.retrieval.retriever import RetrievalResult, TechniqueRetriever

# --- Evaluation ---
# Guarded: evaluation.py is owned by a parallel sibling and may not yet be
# present during early integration.  When the orchestrator lands the full build
# all sibling files will exist and this guard becomes a no-op branch.
try:
    from rogue.retrieval.evaluation import evaluate_recall
except ImportError:  # pragma: no cover
    evaluate_recall = None  # type: ignore[assignment]

__all__ = [
    # schemas
    "TechniqueProfile",
    "TargetFingerprint",
    # embedding text
    "build_technique_embedding_text",
    "build_target_embedding_text",
    # embed factories
    "default_embed_fn",
    "deterministic_embed_fn",
    # builders
    "build_target_fingerprint",
    "build_technique_profiles",
    # retriever
    "TechniqueRetriever",
    "RetrievalResult",
    # evaluation
    "evaluate_recall",
]
