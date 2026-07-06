"""Harvest-provenance signal: is a harvested attack text HUMAN-authored or LLM-GENERATED filler?

Inspired by XDAC (Go, Kim, Oh, Kim — ACL 2025), which separates human-written comments (HWC) from
LLM-generated comments (LGC) via stylometric features. XDAC trains a KcBERT detector on Korean
comments; ROGUE cannot reuse that model (English jailbreak text, no training), so this ports the
LANGUAGE-AGNOSTIC feature families XDAC found most discriminative and scores them heuristically:

    HUMAN signals (XDAC: HWC-heavy)          LLM signals (XDAC: LGC-heavy)
    - repeated characters (aaah, !!!, lol)   - assistant boilerplate ("as an AI", "Sure, here's")
    - informal markers (emoji, "...", CAPS)  - listicle/markdown structure ("Step 1:", "^# ", "1. ")
    - raw formatting artifacts (tabs, 2xsp)  - flat, formal, low-variance prose

Why ROGUE needs it: the harvest layer pulls "jailbreaks" from 19 open-web sources, and a real
fraction are LLM-generated spam / SEO listicles / karma-farm boilerplate, not human-authored novel
attacks. This is a cheap PRIOR — high score => likely synthetic filler => a collapse/quarantine
candidate; low score => human-authored => worth reproducing. It slots beside `function_word_divergence`
(same stdlib/no-API philosophy) and feeds the P5 provenance thread at the HARVEST layer.

HONESTY: a transparent HEURISTIC feature scorer, NOT a trained classifier. It returns the full feature
breakdown so a human can audit it; it is a signal for review/quarantine, never an auto-drop verdict.
Pure stdlib (re + unicodedata) — no model, no API, no new dependency.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

__all__ = ["LLMAuthoredScore", "llm_authored_score", "LLM_AUTHORED_THRESHOLD", "HUMAN_AUTHORED_THRESHOLD"]

# Label thresholds on the [0,1] LLM-likelihood score (higher = more LLM-generated).
# CALIBRATED on HC3 (human vs ChatGPT, 2026-07-07): the LLM threshold sits at the best-F1 operating
# point on the harvest-relevant forum/finance domains (AUC 0.84/0.90; F1 ~0.80/0.84 @ 0.55; the old
# 0.60 gave recall 0.27). Precision there is ~0.74 — a FLAG-FOR-REVIEW point, NOT an auto-drop gate;
# terse factual QA is a known blind spot (AUC 0.53). See docs/research/llm_authored_calibration.md.
LLM_AUTHORED_THRESHOLD = 0.55
HUMAN_AUTHORED_THRESHOLD = 0.35

# Assistant / generation boilerplate an LLM-authored jailbreak dump tends to carry (case-insensitive).
_BOILERPLATE = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bas an ai\b", r"\bas a language model\b", r"\bi cannot\b", r"\bi can ?not\b",
        r"\bi'?m sorry\b", r"\bi apologi[sz]e\b", r"\bsure,?\s+here'?s\b", r"\bcertainly[!.]",
        r"\bhere (?:are|is)\s+(?:a\s+few|some|\d+)\b", r"\bfirstly\b", r"\bin conclusion\b",
        r"\bit'?s important to (?:note|remember|understand)\b", r"\bdisclaimer\b",
        r"\bplease note\b", r"\bi hope this helps\b", r"\blet me know if\b",
    )
)
# Structure an LLM listicle tends to emit (per line).
_MD_HEADER = re.compile(r"^\s{0,3}#{1,6}\s", re.MULTILINE)
_NUM_LIST = re.compile(r"^\s{0,3}\d+[.)]\s", re.MULTILINE)
_BULLET = re.compile(r"^\s{0,3}[-*•]\s", re.MULTILINE)
_STEP = re.compile(r"\bstep\s*\d+\s*[:.]", re.IGNORECASE)

_RUN3 = re.compile(r"(.)\1{2,}")            # a char repeated >=3 (aaah, !!!, ....)
_ELONG = re.compile(r"[!?]{2,}")            # !!, ??, ?!
_ELLIPSIS = re.compile(r"\.{2,}")
_ALLCAPS = re.compile(r"\b[A-Z]{3,}\b")     # shouted words (excludes normal acronyms poorly, ok as signal)
_WORD = re.compile(r"\w+", re.UNICODE)
_SENT = re.compile(r"[.!?]+\s+")


def _is_emoji(ch: str) -> bool:
    # Symbol/pictographs + common emoji blocks; unicodedata category 'So' catches most.
    if unicodedata.category(ch) == "So":
        return True
    o = ord(ch)
    return 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF


@dataclass
class LLMAuthoredScore:
    """Result of :func:`llm_authored_score`. ``score`` in [0,1]: higher => more likely LLM-generated."""

    score: float
    label: str  # "llm_generated" | "human_authored" | "ambiguous"
    features: dict = field(default_factory=dict)

    @property
    def likely_synthetic(self) -> bool:
        return self.label == "llm_generated"


def llm_authored_score(text: str) -> LLMAuthoredScore:
    """Heuristic LLM-authored likelihood for a harvested attack text. Returns score + label + the
    per-feature breakdown (auditable). Empty/whitespace text is ``ambiguous`` (score 0.5)."""
    t = text or ""
    n = len(t)
    if n < 8 or not t.strip():
        return LLMAuthoredScore(0.5, "ambiguous", {"reason": "too_short"})

    words = _WORD.findall(t)
    n_words = max(1, len(words))
    n_sent = max(1, len(_SENT.findall(t)) + 1)

    # --- HUMAN signals (each normalized ~[0,1]) ---
    repetition = min(1.0, len(_RUN3.findall(t)) / max(3.0, n_words / 6))
    emoji = sum(1 for ch in t if _is_emoji(ch))
    # emoji/elongation/CAPS are strong human markers; ellipsis is weak+ambiguous (humans trail off,
    # but LLM output and truncations also use "...") so it counts half.
    informal = min(
        1.0,
        (emoji * 2 + len(_ELONG.findall(t)) + 0.5 * len(_ELLIPSIS.findall(t)) + len(_ALLCAPS.findall(t)))
        / max(4.0, n_words / 8),
    )
    fmt_artifacts = min(1.0, (t.count("  ") + t.count("\t") + t.count("\n\n")) / max(3.0, n_words / 12))
    human = 0.45 * repetition + 0.4 * informal + 0.15 * fmt_artifacts

    # --- LLM signals ---
    boiler = sum(1 for rx in _BOILERPLATE if rx.search(t)) + (1 if _STEP.search(t) else 0)
    boiler_norm = min(1.0, boiler / 2.0)
    structure = min(1.0, (len(_MD_HEADER.findall(t)) + len(_NUM_LIST.findall(t)) + len(_BULLET.findall(t))) / 3.0)
    avg_sent_words = n_words / n_sent
    formality = min(1.0, max(0.0, (avg_sent_words - 8) / 22)) * (1.0 - min(1.0, informal + repetition))
    llm = 0.5 * boiler_norm + 0.32 * structure + 0.18 * formality

    score = max(0.0, min(1.0, 0.5 + 0.55 * llm - 0.55 * human))
    if score >= LLM_AUTHORED_THRESHOLD:
        label = "llm_generated"
    elif score <= HUMAN_AUTHORED_THRESHOLD:
        label = "human_authored"
    else:
        label = "ambiguous"

    return LLMAuthoredScore(
        round(score, 4), label,
        {
            "repetition": round(repetition, 3), "informal": round(informal, 3),
            "fmt_artifacts": round(fmt_artifacts, 3), "boilerplate_hits": boiler,
            "structure": round(structure, 3), "formality": round(formality, 3),
            "human_signal": round(human, 3), "llm_signal": round(llm, 3),
        },
    )
