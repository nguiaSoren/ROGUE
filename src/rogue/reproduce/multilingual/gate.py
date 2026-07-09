"""Env-gated multilingual expansion surface — the one call each fire path makes.

Off by default (``ROGUE_MULTILINGUAL`` unset) → the primitive list is returned unchanged, so every
surface is byte-for-byte identical to today. When on (``ROGUE_MULTILINGUAL=on``), each text primitive is
expanded into itself (the untouched English baseline) PLUS one translated, round-trip-gated variant per
target language (``ROGUE_MULTILINGUAL_LANGS`` csv, default the 6-language panel). The base's verdict
never moves; the variants are added, so the scan measures the per-deployment English-vs-non-English
breach delta without disturbing the existing English number.

The production translator is a real (paid) Anthropic call built lazily; tests inject an ``EchoTranslator``
so the whole pipeline runs at $0. Mirrors the ``m2s.gate`` shape (resolve-from-env-or-injected → a plan
that is a pure identity when off).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from rogue.reproduce.multilingual.expand import expand_primitive
from rogue.reproduce.multilingual.languages import Language, resolve_languages
from rogue.reproduce.multilingual.translate import Translator, build_translator
from rogue.schemas import AttackPrimitive

_log = logging.getLogger(__name__)

ENV_MULTILINGUAL = "ROGUE_MULTILINGUAL"      # off (default) | on
ENV_LANGS = "ROGUE_MULTILINGUAL_LANGS"        # csv of ISO codes; default = the 6-language panel

__all__ = [
    "MultilingualConfig",
    "MultilingualPlan",
    "resolve_multilingual",
    "apply_multilingual",
    "ENV_MULTILINGUAL",
    "ENV_LANGS",
]


@dataclass
class MultilingualConfig:
    languages: list[Language]
    translator: Translator


@dataclass
class MultilingualPlan:
    """Outcome of one expansion: the (possibly grown) primitive list + telemetry."""

    primitives: list[AttackPrimitive]
    n_variants: int = 0
    n_invalid: int = 0
    languages: list[str] = field(default_factory=list)
    enabled: bool = True

    def summary(self) -> str:
        return (
            f"multilingual expansion ({'/'.join(self.languages)}): +{self.n_variants} translated "
            f"variant(s), {self.n_invalid} dropped (empty / failed round-trip)"
        )


def resolve_multilingual(
    config: MultilingualConfig | None = None,
    *,
    translator: Translator | None = None,
) -> MultilingualConfig | None:
    """Build a ``MultilingualConfig`` from the environment, or ``None`` when multilingual is off.

    Off unless ``ROGUE_MULTILINGUAL`` ∈ {on,1,true,yes}. Languages come from ``ROGUE_MULTILINGUAL_LANGS``
    (csv) or the default panel; an empty/all-unknown set → ``None`` (nothing to do). An injected
    ``translator`` wins over the lazily-built production one (tests pass ``EchoTranslator``)."""
    if config is not None:
        return config
    mode = os.environ.get(ENV_MULTILINGUAL, "off").strip().lower()
    if mode not in ("on", "1", "true", "yes"):
        return None
    raw = os.environ.get(ENV_LANGS, "").strip()
    codes = [c.strip() for c in raw.split(",") if c.strip()] if raw else None
    langs = resolve_languages(codes)
    if not langs:
        _log.warning("%s on but no valid target languages resolved — multilingual inert", ENV_MULTILINGUAL)
        return None
    return MultilingualConfig(languages=langs, translator=translator or build_translator())


async def apply_multilingual(
    primitives: list[AttackPrimitive],
    *,
    config: MultilingualConfig | None = None,
    translator: Translator | None = None,
) -> MultilingualPlan:
    """The one call a scan makes before its fire loop. Returns a disabled plan (list unchanged) when
    multilingual is off — a single uniform surface, byte-identical when off. When on, the output is
    ``[base, *variants]`` per base, preserving base order so the existing English verdicts are intact.
    """
    cfg = resolve_multilingual(config, translator=translator)
    if cfg is None or not primitives:
        return MultilingualPlan(primitives=list(primitives), enabled=False)

    out: list[AttackPrimitive] = []
    n_variants = 0
    n_invalid = 0
    for base in primitives:
        out.append(base)  # the untouched English baseline — its verdict must not move
        res = await expand_primitive(base, cfg.languages, cfg.translator)
        out.extend(res.variants)
        n_variants += len(res.variants)
        n_invalid += len(res.invalid_langs)

    plan = MultilingualPlan(
        primitives=out,
        n_variants=n_variants,
        n_invalid=n_invalid,
        languages=[lang.code for lang in cfg.languages],
        enabled=True,
    )
    # A systemic translator failure (no credit / bad key / provider down) shows up as EVERY translation
    # invalid → 0 variants. Distinguish that from a few legitimately-garbled prompts with a loud warning,
    # so a paid multilingual run can't silently produce an English-only result that looks like "no gap".
    if n_variants == 0 and n_invalid > 0:
        _log.warning(
            "multilingual ON but produced 0 variants (%d dropped) — likely a translator failure "
            "(credit/auth/provider), not garbled prompts. Check the translator (%s) before trusting "
            "an English-vs-non-English result.",
            n_invalid, type(cfg.translator).__name__,
        )
    else:
        _log.info("%s", plan.summary())
    return plan
