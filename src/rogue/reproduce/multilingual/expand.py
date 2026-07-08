"""Expand one primitive into its language panel: the English original (untouched) plus one translated,
round-trip-gated variant per target language.

The base primitive is returned BYTE-FOR-BYTE unchanged so its (English) verdict never moves — the
variants are *added* alongside it. Each variant is a schema-valid derived primitive: same shape, a
distinct ``primitive_id`` (so it never collides with the base in a ``{primitive_id: …}`` map or a
``breach_results`` row), ``synthesized=True`` + ``derived_from_primitive_id=<base>`` (so the
schema's synthesized⇔derived invariant holds and the corpus stays separable), and a
``payload_slots["_ml_lang"]`` canonical marker used to group breaches by language for the delta.

A language is DROPPED (counted ``invalid``, never fired) when its translation is empty or fails the
round-trip semantic-preservation gate — so a broken translation is never mistaken for a breach or a
refusal. Non-text primitives (multimodal / procedural-generator) are left base-only: translating an
image payload or a generator spec is meaningless.

Pure module besides the injected async translator — no new dependency.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from rogue.reproduce.multilingual.languages import REFERENCE_LANG, Language
from rogue.reproduce.multilingual.translate import (
    MIN_TRANSLATION_CHARS,
    Translator,
    round_trip_ok,
)
from rogue.schemas import AttackPrimitive
from rogue.schemas.attack_primitive import AttackVector

_log = logging.getLogger(__name__)

__all__ = [
    "ExpandResult",
    "expand_primitive",
    "variant_id",
    "is_translatable",
    "variant_fire_identity",
    "fire_identity",
    "ML_LANG_SLOT",
    "ML_BASE_SLOT",
]

# Canonical per-variant markers. Underscore-prefixed so they are never a template placeholder that gets
# substituted, yet they ride along in payload_slots → resolved_slots so the fire/persist layers can
# recover (base primitive_id, language) from the RenderedAttack alone, with no primitive-object lookup.
ML_LANG_SLOT = "_ml_lang"   # ISO code of the target language
ML_BASE_SLOT = "_ml_base"   # the base (English) primitive_id this variant derives from

_PRIMITIVE_ID_MAX = 40  # ORM String(40) + schema derived_from_primitive_id max_length


def variant_id(base_id: str, lang_code: str) -> str:
    """A distinct, deterministic, ≤40-char primitive_id for a language variant. Uses a readable
    ``<base>__ml_<code>`` form when it fits, else a hashed fallback so long base ids stay in-bounds."""
    candidate = f"{base_id}__ml_{lang_code}"
    if len(candidate) <= _PRIMITIVE_ID_MAX:
        return candidate
    digest = hashlib.sha1(f"{base_id}:{lang_code}".encode()).hexdigest()[:10]
    return f"ml_{lang_code}_{digest}"  # e.g. ml_es_1a2b3c4d5e (short, unique)


def fire_identity(primitive_id: str, slots: dict) -> tuple[str, str | None]:
    """The (FK primitive_id, language) a persisted breach_results row should carry, derived from a
    slot dict (works off ``primitive.payload_slots`` OR ``rendered.resolved_slots`` — both carry the
    ``_ml_*`` markers). A translated variant persists against its BASE primitive_id (which exists in
    attack_primitives — the variant is an ephemeral render-time expansion, not a corpus row) with its
    language on the row; anything else → (its own id, None). Keeps the FK valid, avoids polluting the
    corpus with N× language rows, and is idempotent across re-runs. Byte-identical when multilingual is
    off (no row carries the ``_ml_*`` markers)."""
    lang = slots.get(ML_LANG_SLOT)
    base = slots.get(ML_BASE_SLOT)
    if lang and base:
        return base, lang
    return primitive_id, None


def variant_fire_identity(primitive: AttackPrimitive) -> tuple[str, str | None]:
    """``fire_identity`` for a primitive object (uses its ``payload_slots``)."""
    return fire_identity(primitive.primitive_id, primitive.payload_slots)


def is_translatable(primitive: AttackPrimitive) -> bool:
    """Text attacks only — an image/audio payload or a procedural-generator spec has no meaningful
    translation, so it is left base-only (fired in its original form)."""
    if primitive.requires_multimodal or primitive.generator is not None:
        return False
    return primitive.vector not in (AttackVector.MULTIMODAL_IMAGE, AttackVector.MULTIMODAL_AUDIO)


@dataclass
class ExpandResult:
    """Outcome of expanding ONE base primitive into its language panel."""

    variants: list[AttackPrimitive] = field(default_factory=list)  # translated variants (excludes base)
    invalid_langs: list[str] = field(default_factory=list)         # dropped (empty / failed round-trip)
    skipped: bool = False                                          # base was not translatable


async def _translate_field(text: str, target: Language, translator: Translator) -> str | None:
    """Translate one text field, round-trip-gate it, return the translation or ``None`` if invalid."""
    if not text or not text.strip():
        return text  # nothing to translate (e.g. empty turn) — pass through
    translated = await translator.translate(text, target)
    if not translated or len(translated.strip()) < MIN_TRANSLATION_CHARS:
        return None
    ok = await round_trip_ok(text, translated, translator, back_to=_english())
    return translated if ok else None


_EN: Language | None = None


def _english() -> Language:
    global _EN
    if _EN is None:
        from rogue.reproduce.multilingual.languages import LANGUAGES_BY_CODE  # noqa: PLC0415

        _EN = LANGUAGES_BY_CODE[REFERENCE_LANG]
    return _EN


async def expand_primitive(
    primitive: AttackPrimitive,
    languages: list[Language],
    translator: Translator,
) -> ExpandResult:
    """Return the translated variants (base excluded) for ``primitive`` across ``languages``.

    Translates ``payload_template`` and every ``multi_turn_sequence`` turn. If the payload translation
    is invalid, that whole language is dropped (``invalid_langs``). Individual turns that fail keep the
    original turn (so a partially-translatable multi-turn attack still fires, degraded — not lost). A
    variant whose translated payload would overflow the 20k schema cap is dropped for that language.
    """
    if not is_translatable(primitive):
        return ExpandResult(skipped=True)

    result = ExpandResult()
    for lang in languages:
        payload = await _translate_field(primitive.payload_template, lang, translator)
        if payload is None:
            result.invalid_langs.append(lang.code)
            continue
        if len(payload) > 20_000:
            result.invalid_langs.append(lang.code)
            continue

        turns = primitive.multi_turn_sequence
        new_turns = None
        if turns:
            new_turns = []
            for turn in turns:
                tr = await _translate_field(turn, lang, translator)
                new_turns.append(tr if tr is not None else turn)  # keep original on a per-turn miss

        slots = dict(primitive.payload_slots)
        slots[ML_LANG_SLOT] = lang.code
        slots[ML_BASE_SLOT] = primitive.primitive_id
        if "language" in slots or "{language}" in primitive.payload_template:
            slots["language"] = lang.name  # render nicely where a template names the language

        try:
            variant = primitive.model_copy(
                update={
                    "primitive_id": variant_id(primitive.primitive_id, lang.code),
                    "payload_template": payload,
                    "multi_turn_sequence": new_turns,
                    "payload_slots": slots,
                    "synthesized": True,
                    "derived_from_primitive_id": primitive.primitive_id,
                    # a translated variant is a fresh cluster member, not the canonical row
                    "cluster_id": None,
                    "canonical": False,
                },
            )
        except Exception as exc:  # noqa: BLE001 — a variant that won't validate is dropped, not fatal
            _log.warning("multilingual variant build failed (%s→%s): %s", primitive.primitive_id, lang.code, exc)
            result.invalid_langs.append(lang.code)
            continue
        result.variants.append(variant)

    return result
