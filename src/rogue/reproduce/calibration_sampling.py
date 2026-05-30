"""Calibration sampling — pick a stratified, reproducible subset of real
``breach_results`` for human labeling.

The credibility number a security reviewer asks for ("judge agrees with the
human on N stratified cases at X%; FP-breach rate Y%") is only as good as the
sample it's measured on. Two failure modes this module exists to prevent:

* **Easy-case bias** — the live corpus is mostly clean ``refused`` rows, so a
  naive random draw would be ~40 refusals and almost no breaches, and the
  FP/FN-breach rates (conditioned on the rare verdicts) would have no support.
  :func:`stratified_sample` floors every present verdict so PARTIAL/FULL_BREACH
  always appear, then spreads each verdict across ``(model, family)`` so it is
  not all one target or one attack family.

* **Cherry-picking suspicion** — "you picked the 50 that made the judge look
  good." The draw is fully **deterministic** given ``(rows, target_n, seed)``:
  ordering is ``md5(seed:breach_id)``, no RNG, no wall-clock. Re-running
  reproduces the identical set, and the seed is recorded in the output, so the
  sample is defensible as unbiased rather than hand-curated.

This module is pure (no DB, no I/O) so it is unit-tested offline. The live-DB
query + worksheet emission live in ``scripts/sample_calibration_set.py``, which
builds :class:`CandidateRow` objects from a ``breach_results ⋈ deployment_configs
⋈ attack_primitives`` join and feeds them here.

ERROR rows are dropped: :class:`JudgeVerdict.ERROR` is a coverage failure, not
a gradable verdict, and ``CalibrationCase.from_dict`` rejects it as ground
truth — so it can never be a labeling candidate.

Spec: ROGUE_PLAN.md §10.2 + judge-calibration plan (Workstream A, items A1/A2).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass

__all__ = [
    "CandidateRow",
    "make_case_id",
    "stratified_sample",
]


@dataclass(frozen=True)
class CandidateRow:
    """One ``breach_results`` row, denormalized with the stratification keys.

    ``verdict`` and ``family`` are the string ``.value`` of their enums (the
    script lowers them at the query boundary) so this module stays free of
    schema imports and is trivially constructible in tests.
    """

    breach_id: str
    primitive_id: str
    verdict: str
    target_model: str
    family: str
    rendered_payload: str
    model_response: str


def _order_key(seed: str, breach_id: str) -> str:
    """Deterministic, RNG-free ordering hash for a row. Stable across runs and
    machines so the sampled set is reproducible from ``(seed, breach_id)``."""
    return hashlib.md5(f"{seed}:{breach_id}".encode()).hexdigest()


def make_case_id(row: CandidateRow) -> str:
    """Stable ``case_id`` traceable back to the source breach row.

    ``cal_<verdict>_<8 hex of breach_id>`` — encodes the verdict for at-a-glance
    stratification checks and stays unique/reproducible per source row.
    """
    short = hashlib.md5(row.breach_id.encode()).hexdigest()[:8]
    return f"cal_{row.verdict}_{short}"


def _spread(bucket: list[CandidateRow], k: int, seed: str) -> list[CandidateRow]:
    """Take ``k`` rows from one verdict bucket, round-robin across
    ``(target_model, family)`` groups so the draw is diverse, not all one cell.

    Each group is already in ``_order_key`` order (the caller sorts the bucket
    first). Groups are visited in a deterministic order; one row is taken from
    each per pass until ``k`` are collected.
    """
    if k >= len(bucket):
        return list(bucket)

    groups: dict[tuple[str, str], list[CandidateRow]] = defaultdict(list)
    for row in bucket:
        groups[(row.target_model, row.family)].append(row)

    # Deterministic group visit order: by the hash of each group's first row,
    # then the group key itself as a tie-break.
    group_keys = sorted(
        groups,
        key=lambda g: (_order_key(seed, groups[g][0].breach_id), g),
    )

    out: list[CandidateRow] = []
    cursor = {g: 0 for g in group_keys}
    while len(out) < k:
        progressed = False
        for g in group_keys:
            if len(out) >= k:
                break
            if cursor[g] < len(groups[g]):
                out.append(groups[g][cursor[g]])
                cursor[g] += 1
                progressed = True
        if not progressed:  # all groups exhausted (shouldn't happen: k < len)
            break
    return out


def stratified_sample(
    rows: list[CandidateRow],
    target_n: int,
    seed: str = "rogue",
) -> list[CandidateRow]:
    """Pick up to ``target_n`` rows, stratified by verdict and diversified
    within each verdict across ``(model, family)``. Deterministic given the
    inputs.

    Allocation:
      1. Drop ERROR rows (not gradable ground truth).
      2. Bucket by verdict; floor each present verdict at
         ``max(1, target // (2 · #verdicts))`` so rare breach verdicts always
         get representation (capped at that verdict's availability).
      3. Distribute the remaining slots to the verdicts with the most leftover
         capacity (deterministic tie-break by verdict name).
      4. Within each verdict, :func:`_spread` across ``(model, family)``.

    Returns fewer than ``target_n`` only when the corpus has fewer gradable
    rows than requested.
    """
    rows = [r for r in rows if r.verdict != "error"]
    if not rows or target_n <= 0:
        return []

    by_verdict: dict[str, list[CandidateRow]] = defaultdict(list)
    for row in rows:
        by_verdict[row.verdict].append(row)
    for verdict in by_verdict:
        by_verdict[verdict].sort(key=lambda r: _order_key(seed, r.breach_id))

    verdicts = sorted(by_verdict)
    avail = {v: len(by_verdict[v]) for v in verdicts}
    target = min(target_n, sum(avail.values()))

    base_floor = max(1, target // (2 * len(verdicts)))
    alloc = {v: min(avail[v], base_floor) for v in verdicts}

    remaining = target - sum(alloc.values())
    while remaining > 0:
        capacity = {v: avail[v] - alloc[v] for v in verdicts if avail[v] > alloc[v]}
        if not capacity:
            break
        # Give the next slot to the verdict with the most headroom; tie-break
        # by name keeps the choice deterministic.
        chosen = max(capacity, key=lambda k: (capacity[k], k))
        alloc[chosen] += 1
        remaining -= 1

    selected: list[CandidateRow] = []
    for verdict in verdicts:
        selected.extend(_spread(by_verdict[verdict], alloc[verdict], seed))

    selected.sort(key=lambda r: (r.verdict, _order_key(seed, r.breach_id)))
    return selected
