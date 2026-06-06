"""Embedding function factory for the Technique Retrieval System.

Public API
----------
EmbedFn
    Type alias: Callable[[str], list[float]].

default_embed_fn(model=None) -> EmbedFn
    Returns a live OpenAI embedding callable. The OpenAI client is constructed
    *inside* the returned closure (lazy), so importing this module requires no
    OPENAI_API_KEY and makes no network calls. Reads the model from the ``model``
    argument or the ``EMBEDDING_MODEL`` env var (default: "text-embedding-3-small").
    Mirrors the pattern in scripts/harvest_url.py:57.

deterministic_embed_fn(dim=1536) -> EmbedFn
    Returns an offline, reproducible embedding callable. Same text always yields
    the same unit-normalised float vector of length ``dim``; different text yields
    a different vector. No network, no API key. Used by tests and offline eval.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Callable

EmbedFn = Callable[[str], list[float]]

_DEFAULT_MODEL = "text-embedding-3-small"


def default_embed_fn(model: str | None = None) -> EmbedFn:
    """Return an OpenAI embedding callable (live, costs money when called).

    The OpenAI client is constructed lazily inside the returned closure — this
    function itself makes no network requests and requires no OPENAI_API_KEY at
    construction time.

    Parameters
    ----------
    model:
        Embedding model name.  Falls back to the ``EMBEDDING_MODEL`` env var,
        then to "text-embedding-3-small".
    """
    resolved_model = model or os.environ.get("EMBEDDING_MODEL", _DEFAULT_MODEL)

    def embed_fn(text: str) -> list[float]:
        from openai import OpenAI  # imported lazily — no key needed at module load

        client = OpenAI()
        response = client.embeddings.create(model=resolved_model, input=text)
        return list(response.data[0].embedding)

    return embed_fn


def deterministic_embed_fn(dim: int = 1536) -> EmbedFn:
    """Return an offline, reproducible embedding callable.

    Properties
    ----------
    - Deterministic: same text → identical vector across calls and processes.
    - Unit-normalised: cosine similarity of a vector with itself is ≈ 1.0.
    - Collision-resistant: different texts produce different vectors with high
      probability (backed by SHA-256).
    - No network, no API key, no external dependencies.

    Implementation
    --------------
    SHA-256 of the UTF-8 text seeds a simple LCG-style expansion to fill ``dim``
    floats, then the vector is L2-normalised.  Using the hash digest bytes as a
    seed (rather than Python's random module) guarantees cross-process stability.
    """

    def embed_fn(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()  # 32 bytes

        # Expand the 32-byte digest into `dim` pseudo-random floats by hashing
        # successive chunks: sha256(digest || chunk_index).
        raw: list[float] = []
        chunk_index = 0
        while len(raw) < dim:
            chunk_digest = hashlib.sha256(
                digest + chunk_index.to_bytes(4, "big")
            ).digest()
            # Each digest byte contributes one float in [-1, 1).
            for byte in chunk_digest:
                raw.append((byte / 127.5) - 1.0)
                if len(raw) == dim:
                    break
            chunk_index += 1

        # L2-normalise so cosine similarity is well-behaved.
        magnitude = math.sqrt(sum(x * x for x in raw))
        if magnitude == 0.0:
            # Degenerate edge case: return a unit vector along the first axis.
            normalised = [0.0] * dim
            normalised[0] = 1.0
            return normalised
        return [x / magnitude for x in raw]

    return embed_fn
