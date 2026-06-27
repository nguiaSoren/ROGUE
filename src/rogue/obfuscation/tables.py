"""Shared obfuscation/normalization tables.

Single source of truth for the character-level transforms used in two
complementary places:

  * ``rogue.obfuscation.operators`` — runs them **forward** (plain → obfuscated)
    as deterministic augmentation operators for the §10.7/§10.9 sweep.
  * ``rogue.obfuscation.canonical`` — runs them **backward** (obfuscated →
    plain) to fold near-duplicate surface variants together before embedding
    in the harvest dedup path.

The two directions share these tables so an operator and its inverse can
never drift — a payload obfuscated by ``leetspeak`` collapses back under
``canonicalize`` to (approximately) the same text, which is exactly the
property the dedup pipeline relies on.

Provenance: the leet map, the Cyrillic homoglyph map, and the
invisible/direction-control ranges mirror StackOne Defender's
de-obfuscation sanitizers (`@stackone/defender`, Apache-2.0:
``src/sanitizers/{leet-normalizer,normalizer}.ts`` and
``src/classifiers/patterns.ts``). Defender runs them as a *defender* to
decode-and-catch; ROGUE runs the same table set as a *red-team* to
generate-and-measure. Independently-useful, opposite direction.
"""

from __future__ import annotations

# ----- Leetspeak ------------------------------------------------------------

# Plain letter -> the leet glyph an obfuscator most commonly substitutes in.
# Used forward by the ``leetspeak`` operator.
LEET_ENCODE: dict[str, str] = {
    "a": "4",
    "b": "8",
    "e": "3",
    "i": "1",
    "o": "0",
    "s": "5",
    "t": "7",
}

# Leet glyph -> plain letter, for canonicalization. Mirrors Defender's
# LEET_MAP (`@`/`$` aliases included) so we fold the broader attack
# distribution, not just the glyphs we emit.
LEET_DECODE: dict[str, str] = {
    "4": "a",
    "@": "a",
    "8": "b",
    "3": "e",
    "1": "i",
    "0": "o",
    "5": "s",
    "$": "s",
    "7": "t",
}


# ----- Homoglyphs (Cyrillic look-alikes) ------------------------------------

# ASCII letter -> a confusable Cyrillic codepoint (forward, ``homoglyph``
# operator). Subset chosen for the letters with a faithful Cyrillic twin.
HOMOGLYPH_ENCODE: dict[str, str] = {
    "a": "а",  # Cyrillic а
    "e": "е",  # Cyrillic е
    "o": "о",  # Cyrillic о
    "p": "р",  # Cyrillic р
    "c": "с",  # Cyrillic с
    "y": "у",  # Cyrillic у
    "x": "х",  # Cyrillic х
    "i": "і",  # Cyrillic і
}

# Confusable codepoint -> ASCII (canonicalization). Mirrors Defender's
# normalizer.ts replacement table.
HOMOGLYPH_DECODE: dict[str, str] = {v: k for k, v in HOMOGLYPH_ENCODE.items()}


# ----- Invisible / direction-control characters -----------------------------

# Zero-width and BOM characters — inserted forward to split trigger words,
# stripped on canonicalization. Range mirrors patterns.ts ``invisible_unicode``
# plus the word-joiner block.
ZERO_WIDTH_CHARS: tuple[str, ...] = (
    "​",  # zero-width space
    "‌",  # zero-width non-joiner
    "‍",  # zero-width joiner
    "﻿",  # BOM / zero-width no-break space
    "⁠",  # word joiner
)

# Bidirectional / text-direction override controls (patterns.ts
# ``text_direction_override``). Stripped on canonicalization.
DIRECTION_CONTROL_CHARS: tuple[str, ...] = (
    "‪",
    "‫",
    "‬",
    "‭",
    "‮",
    "⁦",
    "⁧",
    "⁨",
    "⁩",
)

# Combining-diacritic ranges used in Zalgo / diacritic-stacking. Stripped on
# canonicalization (mirrors normalizer.ts ``stripCombiningMarks``). Stored as
# (low, high) inclusive codepoint bounds.
COMBINING_MARK_RANGES: tuple[tuple[int, int], ...] = (
    (0x0300, 0x036F),
    (0x1AB0, 0x1AFF),
    (0x1DC0, 0x1DFF),
    (0x20D0, 0x20FF),
    (0xFE20, 0xFE2F),
)

# A small pool of combining marks to *apply* forward in the zalgo operator.
ZALGO_MARKS: tuple[str, ...] = (
    "́",
    "̈",
    "̧",
    "ͤ",
    "҉",
)
