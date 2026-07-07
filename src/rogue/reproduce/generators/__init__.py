"""Procedural attack generators — build a payload from params instead of a static template.

The registry seam: a generator is a pure ``build(params, target_query, seed) -> str``. Two techniques
that ROGUE could not represent as a static ``payload_template`` ship here — ``many_shot`` and
``shot_repetition`` — plus whatever future algorithmic/scaling attack (token-budget padding,
crescendo-by-length) plugs in. The sweep runner (``rogue.reproduce.generator_sweep``) calls ``build``
once per swept value to trace an ASR curve.

Content policy: generators default to BENIGN filler shots (the MSJ paper found dummy/benign shots work
as well as harmful ones), so the long-context vulnerability is testable without a harmful corpus.
``shot_source='corpus'`` is an explicit opt-in for higher fidelity.
"""

from __future__ import annotations

from typing import Any, Callable

# (params, target_query, seed) -> the assembled payload string
GeneratorFn = Callable[[dict[str, Any], str, int], str]

_REGISTRY: dict[str, GeneratorFn] = {}


def register(kind: str) -> Callable[[GeneratorFn], GeneratorFn]:
    def _wrap(fn: GeneratorFn) -> GeneratorFn:
        if kind in _REGISTRY:
            raise ValueError(f"generator {kind!r} already registered")
        _REGISTRY[kind] = fn
        return fn

    return _wrap


def available() -> list[str]:
    return sorted(_REGISTRY)


def build(kind: str, params: dict[str, Any], target_query: str, seed: int = 0) -> str:
    """Assemble a payload for ``kind``. Raises KeyError for an unknown generator."""
    if kind not in _REGISTRY:
        raise KeyError(f"unknown generator {kind!r}; available: {available()}")
    return _REGISTRY[kind](dict(params), target_query, seed)


# Register built-in generators on import.
from . import many_shot as _many_shot  # noqa: E402,F401
from . import shot_repetition as _shot_repetition  # noqa: E402,F401
from . import domain_terminology as _domain_terminology  # noqa: E402,F401

__all__ = ["GeneratorFn", "register", "available", "build"]
