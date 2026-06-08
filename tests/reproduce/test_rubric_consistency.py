"""Cross-rubric consistency check (ROGUE v2 Phase 1, §2 of
``docs/v2/build/02_judge_generalization.md``).

The judge generalizes from a single *harm* classifier to a family of per-type
*consummation* rubrics — one per breach type. Each rubric (``judge_v3.md``,
``infodisc_v1.md``, ``unauthorized_action_v2.md``) inherits the v3 skeleton and
swaps **only** the consummation gate. For that family to stay coherent, every
rubric must speak the *same* verdict vocabulary and carry the *same*
"always classify, never refuse" directive — otherwise ``verdict_projection``'s
4-way → binary collapse (``{PARTIAL,FULL}=breach``, ``{REFUSED,EVADED}=clean``)
would not be valid for some type, and the binary breach axis would silently
break for that breach type.

These are file-level assertions over the rubric markdown: they guard the
*invariant* (shared taxonomy + never-refuse clause) without touching judge code
or making any model call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Resolve the prompts dir the same way ``JudgeAgent`` does: relative to the
# installed ``rogue.reproduce`` package, so the test is cwd-independent.
import rogue.reproduce  # noqa: E402

PROMPTS_DIR = Path(rogue.reproduce.__file__).parent / "prompts"

# Every rubric in the consummation family. Keep in lockstep with the
# ``BreachType`` registry (§1) as new breach types are added.
RUBRIC_FILES = [
    "judge_v3.md",  # capability_transfer — the reference instance
    "infodisc_v1.md",  # information_disclosure — Phase 1 primary target
    "unauthorized_action_v2.md",  # unauthorized_action — Phase 1 stretch target
]

# The exact verdict tokens ``judge_v3.md`` uses (and that
# ``verdict_projection.py`` / ``JudgeVerdict`` enumerate). Every rubric must
# contain all four so the binary projection is valid for every type.
VERDICT_TOKENS = ["REFUSED", "EVADED", "PARTIAL_BREACH", "FULL_BREACH"]

# The "always classify, never refuse" directive, present verbatim in every
# rubric so a non-harm judge never declines to label.
NEVER_REFUSE_PHRASES = ["always classify, never refuse"]


def _read_rubric(name: str) -> str:
    path = PROMPTS_DIR / name
    assert path.is_file(), f"rubric file missing: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("rubric", RUBRIC_FILES)
def test_rubric_exists(rubric: str) -> None:
    """Each rubric in the family is present on disk."""
    assert (PROMPTS_DIR / rubric).is_file(), f"missing rubric: {rubric}"


@pytest.mark.parametrize("rubric", RUBRIC_FILES)
@pytest.mark.parametrize("token", VERDICT_TOKENS)
def test_rubric_contains_all_verdict_tokens(rubric: str, token: str) -> None:
    """Every rubric carries all four verdict tokens, so the 4-way → binary
    projection in ``verdict_projection.py`` is valid for every breach type."""
    text = _read_rubric(rubric)
    assert token in text, (
        f"{rubric} is missing verdict token {token!r}; the binary breach "
        f"projection would be invalid for this breach type."
    )


@pytest.mark.parametrize("rubric", RUBRIC_FILES)
def test_rubric_contains_never_refuse_directive(rubric: str) -> None:
    """Every rubric carries the 'always classify, never refuse' directive so a
    per-type judge always emits a verdict (never declines)."""
    text = _read_rubric(rubric).lower()
    assert any(phrase.lower() in text for phrase in NEVER_REFUSE_PHRASES), (
        f"{rubric} is missing the 'always classify, never refuse' directive; a "
        f"judge loading it could decline to label."
    )


def test_partial_full_token_spelling_matches_judge_v3() -> None:
    """Guard the exact token spellings: PARTIAL_BREACH / FULL_BREACH (not
    PARTIAL / FULL alone), matching ``judge_v3.md`` and ``JudgeVerdict``.

    A rubric that wrote a bare 'PARTIAL'/'FULL' would silently fail to map onto
    the verdict enum, so assert the underscored form appears in each rubric.
    """
    for rubric in RUBRIC_FILES:
        text = _read_rubric(rubric)
        assert "PARTIAL_BREACH" in text, f"{rubric}: expected PARTIAL_BREACH token"
        assert "FULL_BREACH" in text, f"{rubric}: expected FULL_BREACH token"
