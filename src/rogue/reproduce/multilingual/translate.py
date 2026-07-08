"""Translator seam for the translate-then-reproduce path.

Design constraints (from the research + ROGUE conventions):
  * **Injectable** — production builds an :class:`LLMTranslator` (a real paid Anthropic call, no new
    dependency: reuses the same ``anthropic`` client + ``llm_cost_log`` pattern as ``persona_wrap``);
    tests inject an :class:`EchoTranslator` so the whole expand→round-trip→fire→record pipeline runs at
    $0 (it does NOT translate — it marks the language — so it proves the plumbing, not translation
    quality, which is stated honestly wherever the $0 number is reported).
  * **Reason in English, translate the prompt** (MM-ART 2504.03174) — we translate the outgoing attack
    text only; generation/judging stay in their own layers.
  * **Round-trip gate** (control against the translation-artifact confound): before a translated variant
    is fired, translate it back to English and require it to preserve the original meaning, so a
    "breach" or "refusal" is never attributed to a prompt the translator mangled. Garbled / empty
    output is routed to an ``invalid`` outcome — NOT counted as safe or as a breach (Deng, Atil).

MT artifacts *deflate* the low-resource signal (MM-ART Fig 3), so an MT-driven multilingual breach is a
conservative lower bound — which is the honest, defensible direction for the bias to run.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol, runtime_checkable

from rogue.reproduce.multilingual.languages import Language

_log = logging.getLogger(__name__)

__all__ = [
    "Translator",
    "EchoTranslator",
    "LLMTranslator",
    "build_translator",
    "round_trip_ok",
    "ROUND_TRIP_MIN_CONTAINMENT",
    "MIN_TRANSLATION_CHARS",
]

# A translated variant whose back-translation shares fewer than this fraction of the original's content
# tokens is treated as mangled (invalid) and dropped, not fired. Tolerant by design — the goal is to
# catch garbled/empty output, not to demand a perfect round-trip.
ROUND_TRIP_MIN_CONTAINMENT = 0.35
MIN_TRANSLATION_CHARS = 3  # shorter than this = the translator returned nothing usable

_WORD = re.compile(r"\w+", re.UNICODE)
_STOP = frozenset(
    "a an the of to and or in on for with as at by is are be this that it you your i we".split()
)


@runtime_checkable
class Translator(Protocol):
    """Text→text async translator. ``name`` labels it in logs/reports."""

    name: str

    async def translate(self, text: str, target: Language) -> str: ...


def _content_tokens(text: str) -> set[str]:
    return {w for w in (m.lower() for m in _WORD.findall(text or "")) if w not in _STOP and len(w) > 2}


async def round_trip_ok(
    original_en: str, translated: str, translator: "Translator", *, back_to: Language,
) -> bool:
    """True iff ``translated`` back-translated to English preserves enough of the original's content
    tokens (containment ≥ :data:`ROUND_TRIP_MIN_CONTAINMENT`). Fail-open on a back-translation error
    (we don't want the QC step itself to silently drop a valid variant); fail-closed on empty text."""
    if not translated or len(translated.strip()) < MIN_TRANSLATION_CHARS:
        return False
    orig = _content_tokens(original_en)
    if not orig:
        return True  # nothing to preserve (all stopwords / slots) — don't block
    try:
        back = await translator.translate(translated, back_to)
    except Exception as exc:  # noqa: BLE001 — QC must never crash a scan
        _log.warning("round-trip back-translation failed (%s); admitting variant: %s", translator.name, exc)
        return True
    got = _content_tokens(back)
    if not got:
        return False
    containment = len(orig & got) / len(orig)
    return containment >= ROUND_TRIP_MIN_CONTAINMENT


class EchoTranslator:
    """$0 test double: marks the target language but does NOT translate. It lets the full pipeline
    (expand → round-trip → fire → record per language) run without any paid call. It cannot and does
    not measure translation quality or a real breach delta — always name that gap when reporting a
    number produced with it."""

    name = "echo"

    async def translate(self, text: str, target: Language) -> str:  # noqa: D401
        # Reference language (back-translation) → return as-is so round-trip trivially preserves content.
        if target.code == "en":
            return text
        return f"[{target.code}] {text}"


class LLMTranslator:
    """Production translator: a real Anthropic call (paid), reusing persona_wrap's client + cost-log
    conventions — no new dependency. Caches by (text, target) so re-firing the same variant is free.
    On an API content-policy refusal or short reply it returns ``""`` → the caller routes it to
    ``invalid`` (never a false breach)."""

    name = "llm"
    _MAX_TOKENS = 2000

    def __init__(self, model: str = "claude-haiku-4-5", temperature: float = 0.0) -> None:
        self.model = model
        self.temperature = temperature
        self._client = None
        self._cache: dict[tuple[str, str], str] = {}

    async def translate(self, text: str, target: Language) -> str:
        if not text or not text.strip():
            return ""
        key = (text, target.code)
        if key in self._cache:
            return self._cache[key]
        from anthropic import APIStatusError, AsyncAnthropic, BadRequestError  # noqa: PLC0415

        if self._client is None:
            self._client = AsyncAnthropic()
        instruction = (
            f"Translate the following text into {target.name}. Preserve meaning, tone, and any "
            f"{{placeholder}} tokens EXACTLY (do not translate text inside curly braces). Output ONLY "
            f"the translation, no preamble.\n\n---\n{text}"
        )
        try:
            resp = await self._client.messages.create(
                model=self.model,
                max_tokens=self._MAX_TOKENS,
                temperature=self.temperature,
                messages=[{"role": "user", "content": instruction}],
            )
        except (BadRequestError, APIStatusError) as exc:
            _log.warning("translation refused/failed (%s→%s): %s", self.model, target.code, exc)
            return ""
        parts = [
            getattr(b, "text", "")
            for b in (getattr(resp, "content", []) or [])
            if getattr(b, "type", None) == "text"
        ]
        out = "".join(parts).strip()
        try:
            from rogue.reproduce.llm_cost_log import log_anthropic_response  # noqa: PLC0415

            log_anthropic_response(
                resp, module="multilingual", operation="translate", model=self.model,
                subject_id=target.code, refused=(len(out) < MIN_TRANSLATION_CHARS),
                notes=f"chars={len(text)}",
            )
        except Exception:  # noqa: BLE001 — accounting must never crash a run
            pass
        self._cache[key] = out
        return out


def build_translator(model: str | None = None) -> "Translator":
    """The production translator built when the gate is on and none was injected. Env
    ``ROGUE_MULTILINGUAL_TRANSLATOR=echo`` forces the $0 double (useful for a dry-run)."""
    import os  # noqa: PLC0415

    if os.environ.get("ROGUE_MULTILINGUAL_TRANSLATOR", "").strip().lower() == "echo":
        return EchoTranslator()
    return LLMTranslator(model=model or os.environ.get("ROGUE_MULTILINGUAL_MODEL", "claude-haiku-4-5"))
