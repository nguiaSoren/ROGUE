"""Tests for ``rogue.reproduce.calibration_sampling`` — the stratified,
deterministic draw that feeds the human-labeling worksheet.

Pure logic, no DB. The properties that matter for the credibility of the
downstream agreement number: ERROR is excluded, rare breach verdicts get
representation (no easy-case bias), the draw is reproducible (no cherry-pick
suspicion), and within a verdict it spreads across models/families.

Spec: ROGUE_PLAN.md §10.2 + judge-calibration plan (Workstream A).
"""

from __future__ import annotations

from collections import Counter

from rogue.reproduce.calibration_sampling import (
    CandidateRow,
    make_case_id,
    stratified_sample,
)


def _row(
    i: int,
    verdict: str,
    model: str = "anthropic/claude-haiku-4-5",
    family: str = "jailbreak",
) -> CandidateRow:
    return CandidateRow(
        breach_id=f"breach_{verdict}_{i:04d}",
        primitive_id=f"prim_{i:04d}",
        verdict=verdict,
        target_model=model,
        family=family,
        rendered_payload=f"payload {i}",
        model_response=f"response {i}",
    )


def _corpus_mostly_refusals() -> list[CandidateRow]:
    """Realistic skew: a wall of refusals, a few breaches, some errors."""
    rows: list[CandidateRow] = []
    rows += [_row(i, "refused") for i in range(100)]
    rows += [_row(i, "evaded") for i in range(20)]
    rows += [_row(i, "partial_breach") for i in range(6)]
    rows += [_row(i, "full_breach") for i in range(3)]
    rows += [_row(i, "error") for i in range(15)]
    return rows


# --------------------------------------------------------------------------- #
# Exclusion + size
# --------------------------------------------------------------------------- #


def test_error_rows_are_never_sampled() -> None:
    rows = [_row(i, "error") for i in range(10)] + [_row(i, "refused") for i in range(10)]
    sample = stratified_sample(rows, target_n=20, seed="s")
    assert all(r.verdict != "error" for r in sample)


def test_sample_size_capped_by_available_gradable_rows() -> None:
    rows = [_row(i, "refused") for i in range(5)] + [_row(i, "error") for i in range(50)]
    sample = stratified_sample(rows, target_n=50, seed="s")
    assert len(sample) == 5  # only 5 gradable rows exist


def test_returns_target_n_when_corpus_is_large() -> None:
    sample = stratified_sample(_corpus_mostly_refusals(), target_n=50, seed="s")
    assert len(sample) == 50


def test_empty_and_zero_target_return_empty() -> None:
    assert stratified_sample([], target_n=50, seed="s") == []
    assert stratified_sample(_corpus_mostly_refusals(), target_n=0, seed="s") == []


# --------------------------------------------------------------------------- #
# Stratification — the anti-easy-case-bias property
# --------------------------------------------------------------------------- #


def test_rare_breach_verdicts_are_represented_despite_skew() -> None:
    """The whole point: a 100:3 refused:full_breach corpus must still surface
    the full_breach rows, or the FP/FN-breach rates have no support."""
    sample = stratified_sample(_corpus_mostly_refusals(), target_n=50, seed="s")
    counts = Counter(r.verdict for r in sample)
    assert counts["full_breach"] == 3  # all 3 available, floored in
    assert counts["partial_breach"] == 6  # all 6 available
    assert counts["evaded"] >= 1
    assert counts["refused"] >= 1
    # And refusals must not have swallowed the whole sample.
    assert counts["refused"] < 50


def test_floor_does_not_exceed_availability() -> None:
    """A verdict with only 2 rows contributes at most 2, never a padded floor."""
    rows = (
        [_row(i, "refused") for i in range(40)]
        + [_row(i, "full_breach") for i in range(2)]
    )
    sample = stratified_sample(rows, target_n=30, seed="s")
    assert Counter(r.verdict for r in sample)["full_breach"] == 2


# --------------------------------------------------------------------------- #
# Determinism — the anti-cherry-pick property
# --------------------------------------------------------------------------- #


def test_same_seed_same_sample() -> None:
    corpus = _corpus_mostly_refusals()
    a = stratified_sample(corpus, target_n=50, seed="rogue")
    b = stratified_sample(corpus, target_n=50, seed="rogue")
    assert [r.breach_id for r in a] == [r.breach_id for r in b]


def test_different_seed_can_change_selection_within_a_verdict() -> None:
    """Different seed reshuffles which refusals are picked (the over-supplied
    verdict), proving the draw isn't a fixed slice."""
    corpus = _corpus_mostly_refusals()
    a = {r.breach_id for r in stratified_sample(corpus, 50, seed="aaa")}
    b = {r.breach_id for r in stratified_sample(corpus, 50, seed="zzz")}
    assert a != b


# --------------------------------------------------------------------------- #
# Diversity within a verdict — spread across (model, family)
# --------------------------------------------------------------------------- #


def test_spread_across_models_within_a_verdict() -> None:
    """50 refusals across 5 models; a draw of 10 should touch multiple models,
    not pull all 10 from one cell."""
    models = ["m1", "m2", "m3", "m4", "m5"]
    rows = [
        _row(i, "refused", model=models[i % 5], family=f"fam{i % 3}")
        for i in range(50)
    ]
    sample = stratified_sample(rows, target_n=10, seed="s")
    distinct_models = {r.target_model for r in sample}
    assert len(distinct_models) >= 3


# --------------------------------------------------------------------------- #
# case_id
# --------------------------------------------------------------------------- #


def test_make_case_id_encodes_verdict_and_is_stable() -> None:
    row = _row(7, "partial_breach")
    cid = make_case_id(row)
    assert cid.startswith("cal_partial_breach_")
    assert make_case_id(row) == cid  # stable
    # distinct source rows → distinct ids
    assert make_case_id(_row(8, "partial_breach")) != cid
