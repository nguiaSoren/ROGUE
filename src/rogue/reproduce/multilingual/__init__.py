"""Q20 multilingual reproduction — translate-then-reproduce across a language panel to measure the
per-deployment English-vs-non-English breach delta. Off by default (``ROGUE_MULTILINGUAL``).

See docs/research/multilingual_coverage.md for design + paper grounding + honest caveats.
"""

from __future__ import annotations

from rogue.reproduce.multilingual.gate import (
    ENV_LANGS,
    ENV_MULTILINGUAL,
    MultilingualConfig,
    MultilingualPlan,
    apply_multilingual,
    resolve_multilingual,
)
from rogue.reproduce.multilingual.languages import (
    DEFAULT_LANGUAGES,
    EXTENDED_LANGUAGES,
    Language,
    resolve_languages,
)
from rogue.reproduce.multilingual.translate import (
    EchoTranslator,
    LLMTranslator,
    Translator,
    build_translator,
)

__all__ = [
    "ENV_LANGS",
    "ENV_MULTILINGUAL",
    "MultilingualConfig",
    "MultilingualPlan",
    "apply_multilingual",
    "resolve_multilingual",
    "DEFAULT_LANGUAGES",
    "EXTENDED_LANGUAGES",
    "Language",
    "resolve_languages",
    "EchoTranslator",
    "LLMTranslator",
    "Translator",
    "build_translator",
]
