"""Surface-obfuscation transforms, shared by the augmentation sweep and dedup.

Two directions over one shared table set (``rogue.obfuscation.tables``):

  * ``operators`` — forward (plain → obfuscated): deterministic, zero-cost
    augmentation operators for §10.7/§10.9, each labelled so the sweep yields
    a flip-rate-per-transform table.
  * ``canonical`` — inverse (obfuscated → plain): fold surface skins before
    embedding so the harvest dedup clusters by technique, not by spelling.
"""

from __future__ import annotations

from rogue.obfuscation.canonical import canonicalize
from rogue.obfuscation.operators import (
    ENCODING_FAMILY_COVERAGE,
    EXTENDED_OBFUSCATION_OPERATORS,
    OBFUSCATION_OPERATORS,
    ObfuscationOperator,
    active_operators,
    apply_operator,
    obfuscate,
    try_decode_nested_cipher,
)

__all__ = [
    "ENCODING_FAMILY_COVERAGE",
    "EXTENDED_OBFUSCATION_OPERATORS",
    "OBFUSCATION_OPERATORS",
    "ObfuscationOperator",
    "active_operators",
    "apply_operator",
    "canonicalize",
    "obfuscate",
    "try_decode_nested_cipher",
]
