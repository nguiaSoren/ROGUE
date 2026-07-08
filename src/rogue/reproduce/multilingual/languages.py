"""The ROGUE multilingual language panel — the default set of target languages for the
translate-then-reproduce path, chosen to span SCRIPT × RESOURCE because the safety gap reverses by
regime (Atil et al. 2511.00689): under *plain* queries low-resource languages are least safe, but under
*jailbreak* attacks the trend reverses and high-resource languages can be least safe (the model
understands the adversarial framing well enough to be steered by it). A panel that only sampled
low-resource languages would miss the jailbreak-transfer gap entirely.

Every entry is backed by a measured number from the literature (MM-ART 2504.03174, Atil 2511.00689,
Deng 2310.06474, Marx & Dunaiski 2605.18239). ``in_multijail`` marks languages that live in Deng's
public MultiJail parallel corpus (github.com/DAMO-NLP-SG/multilingual-safety-for-LLMs), which supplies
free human-reference translations for validating our own machine translation per language.

Pure data — no I/O, no new dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Language",
    "REFERENCE_LANG",
    "DEFAULT_LANGUAGES",
    "EXTENDED_LANGUAGES",
    "LANGUAGES_BY_CODE",
    "resolve_languages",
    "default_language_codes",
]

REFERENCE_LANG = "en"  # the untranslated baseline — its verdict must never move


@dataclass(frozen=True)
class Language:
    code: str            # ISO 639-1
    name: str            # English name (used in the translation instruction)
    script: str          # "latin" | "non_latin"
    resource: str        # "high" | "mid" | "low"
    in_multijail: bool    # has a human-reference parallel in Deng's public MultiJail corpus
    note: str            # the measured signal justifying inclusion


# Ordered: reference first, then the defensible default panel. Numbers are relative ASR deltas vs
# English from the cited papers (see docs/research/multilingual_coverage.md for the full table).
_REGISTRY: tuple[Language, ...] = (
    Language("en", "English", "latin", "high", True,
             "reference baseline; always fired untranslated."),
    Language("es", "Spanish", "latin", "high", True,
             "HRL-Latin negative control — near-English single-turn (MM-ART +9% @turn5, ~flat @turn1); "
             "a break here indicates the depth axis, not translation."),
    Language("de", "German", "latin", "high", False,
             "worst Latin-script language in MM-ART (+30% @turn5); vulnerable under Atil's Andrius25."),
    Language("ar", "Arabic", "non_latin", "mid", True,
             "mid-tier degradation consistent across MM-ART, Atil and Deng; robust non-Latin signal (+44% @turn5)."),
    Language("ja", "Japanese", "non_latin", "high", False,
             "MM-ART's single largest gap (+74% @turn5, +79% @turn1); the 'supported-but-degrades' case."),
    Language("bn", "Bengali", "non_latin", "low", True,
             "Deng + Atil canonical worst case (~3x unsafe under plain queries); in MultiJail."),
)

# The resource×script isolation extension (offer, not default).
_EXTENSION: tuple[Language, ...] = (
    Language("sw", "Swahili", "latin", "low", True,
             "LRL but Latin script — isolates resource level from script distance (Deng headline)."),
    Language("zh", "Chinese", "non_latin", "high", True,
             "HRL non-Latin — exposes Atil's reversal (high-resource yet script-distant)."),
)

LANGUAGES_BY_CODE: dict[str, Language] = {lang.code: lang for lang in (*_REGISTRY, *_EXTENSION)}
DEFAULT_LANGUAGES: tuple[Language, ...] = _REGISTRY
EXTENDED_LANGUAGES: tuple[Language, ...] = (*_REGISTRY, *_EXTENSION)


def default_language_codes(include_reference: bool = False) -> list[str]:
    """The default panel's language codes. ``include_reference=False`` drops ``en`` (the untranslated
    baseline fires from the original primitive, not a translation), which is what the expander wants."""
    return [
        lang.code
        for lang in DEFAULT_LANGUAGES
        if include_reference or lang.code != REFERENCE_LANG
    ]


def resolve_languages(codes: list[str] | None) -> list[Language]:
    """Resolve a list of ISO codes into :class:`Language` records, dropping the reference language and
    any unknown code (silently — an optimisation must never fail a scan). ``None`` → the default panel.
    """
    if codes is None:
        return [lang for lang in DEFAULT_LANGUAGES if lang.code != REFERENCE_LANG]
    out: list[Language] = []
    seen: set[str] = set()
    for raw in codes:
        code = (raw or "").strip().lower()
        if not code or code == REFERENCE_LANG or code in seen:
            continue
        lang = LANGUAGES_BY_CODE.get(code)
        if lang is not None:
            out.append(lang)
            seen.add(code)
    return out
