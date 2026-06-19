"""Pure-Python statistics for the grammar-component predictive-power study.

NO scipy / statsmodels (not installed, do not add). Everything here is implemented
in pure Python + ``math``; numpy is allowed but not required. These helpers are
deterministic and unit-tested against hand-computed / textbook reference values.

The headline question: *does the presence of a given* :class:`GrammarNode` *raise the
breach rate?* We answer it with a 2×2 contingency table per node — (node present /
absent) × (breach / no-breach) — and report effect size (absolute & relative lift,
odds ratio with a Wald CI) plus a Fisher exact two-sided p-value.

ANALYSIS UNIT (critical, see study spec / CLAUDE.md data finding): the per-primitive
ANY-breach base rate is ~0.79 (a ceiling — 8 targets saturate "any breached"). So the
PRIMARY unit is the per-(primitive × target) outcome (~1540 units), NOT the
per-primitive aggregate. ``unit="per_target"`` is the default and the headline;
``unit="per_primitive"`` is supported for comparison only.

P-values produced here are UNCORRECTED. Multiple-comparison (FDR) correction is applied
downstream by Engineer 6 across the full node table.

OBSERVATIONAL, $0, read-only. Nothing here touches the DB or the network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..schemas import GrammarNode

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .dataset import PrimitiveRecord


# --------------------------------------------------------------------------- #
# Low-level stat helpers — pure, hand-verifiable.
# --------------------------------------------------------------------------- #
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial proportion k/n.

    Returns ``(lo, hi)`` clamped to [0, 1]. For ``n == 0`` returns ``(0.0, 1.0)``
    (maximally uninformative). The Wilson interval is preferred over the normal
    approximation because it behaves sensibly near p=0 and p=1, which matters here
    where many node cells are small.

    Reference: Wilson(8, 10) ≈ (0.49, 0.94).
    """
    if n <= 0:
        return (0.0, 1.0)
    if k < 0 or k > n:
        raise ValueError(f"k={k} must be in [0, n={n}]")
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = (z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n)) / denom
    lo = center - margin
    hi = center + margin
    return (max(0.0, lo), min(1.0, hi))


def _hypergeom_pmf(a: int, row1: int, col1: int, total: int) -> float:
    """P(X = a) for a 2×2 table under fixed margins (Fisher's hypergeometric).

    ``row1`` = a+b (row total for the first row), ``col1`` = a+c (column total for the
    first column), ``total`` = a+b+c+d. Returns 0.0 when ``a`` is outside its support.
    """
    # Support: max(0, col1+row1-total) <= a <= min(row1, col1)
    lo = max(0, col1 + row1 - total)
    hi = min(row1, col1)
    if a < lo or a > hi:
        return 0.0
    return (
        math.comb(col1, a)
        * math.comb(total - col1, row1 - a)
        / math.comb(total, row1)
    )


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact test p-value for the 2×2 table [[a, b], [c, d]].

    Uses the hypergeometric distribution over the table's fixed margins via
    ``math.comb`` (exact integer binomials, no floating-point factorials). The two-sided
    p-value sums the probabilities of every table (with the same margins) whose
    probability is <= that of the observed table, using a small epsilon to keep
    equally-likely tables in the sum.

    Reference: the classic "lady tasting tea" table [[1, 9], [11, 3]] → p ≈ 0.00137.
    A balanced table [[10, 10], [10, 10]] → p = 1.0.
    """
    if min(a, b, c, d) < 0:
        raise ValueError("cell counts must be non-negative")
    total = a + b + c + d
    if total == 0:
        return 1.0
    row1 = a + b
    col1 = a + c
    lo = max(0, col1 + row1 - total)
    hi = min(row1, col1)
    p_obs = _hypergeom_pmf(a, row1, col1, total)
    if p_obs <= 0.0:
        return 1.0
    eps = p_obs * 1e-7
    p_sum = 0.0
    for x in range(lo, hi + 1):
        px = _hypergeom_pmf(x, row1, col1, total)
        if px <= p_obs + eps:
            p_sum += px
    return min(1.0, p_sum)


def odds_ratio_ci(
    a: int, b: int, c: int, d: int, z: float = 1.96
) -> tuple[float, float, float]:
    """Odds ratio and log-OR Wald confidence interval for [[a, b], [c, d]].

    Returns ``(OR, lo, hi)``. The OR is (a*d) / (b*c). When any cell is zero the
    Haldane–Anscombe correction adds +0.5 to *all four* cells (the standard remedy for
    undefined / infinite ORs); the CI is then the Wald interval on log(OR):

        log(OR) ± z * sqrt(1/a + 1/b + 1/c + 1/d)

    For the balanced table [[10, 10], [10, 10]] the OR is 1.0 and the CI straddles 1.
    """
    if min(a, b, c, d) < 0:
        raise ValueError("cell counts must be non-negative")
    if a == 0 or b == 0 or c == 0 or d == 0:
        a_, b_, c_, d_ = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    else:
        a_, b_, c_, d_ = float(a), float(b), float(c), float(d)
    orat = (a_ * d_) / (b_ * c_)
    log_or = math.log(orat)
    se = math.sqrt(1.0 / a_ + 1.0 / b_ + 1.0 / c_ + 1.0 / d_)
    lo = math.exp(log_or - z * se)
    hi = math.exp(log_or + z * se)
    return (orat, lo, hi)


# --------------------------------------------------------------------------- #
# Node lift table.
# --------------------------------------------------------------------------- #
@dataclass
class NodeLift:
    """Effect of one :class:`GrammarNode`'s presence on the breach rate.

    Cells of the 2×2: with-breach ``k_with`` / ``n_with``; without-breach ``k_without``
    / ``n_without``. ``baseline`` is the marginal breach rate over *all* units (the
    grand mean), so ``lift_abs`` / ``lift_rel`` are measured against the corpus base
    rate rather than against the node-absent group. ``flagged`` is True when
    ``n_with < min_n`` (under-powered — reported but not to be trusted).
    """

    node: GrammarNode
    n_with: int
    n_without: int
    k_with: int
    k_without: int
    p_with: float
    p_without: float
    baseline: float
    lift_abs: float  # p_with - baseline
    lift_rel: float  # p_with / baseline
    odds_ratio: float
    or_ci_low: float
    or_ci_high: float
    p_value: float  # Fisher exact two-sided, UNCORRECTED
    with_ci: tuple[float, float]
    without_ci: tuple[float, float]
    flagged: bool = False


def _iter_units(records: list["PrimitiveRecord"], unit: str):
    """Yield ``(primitive_id, breached_bool)`` per analysis unit.

    ``per_target`` → one unit per (record, target); ``per_primitive`` → one unit per
    record (aggregate ``record.breached``). Records with no targets contribute nothing
    in ``per_target`` mode (they have no per-target outcomes).
    """
    if unit == "per_target":
        for rec in records:
            for tgt in rec.targets:
                yield (rec.primitive_id, bool(tgt.breached))
    elif unit == "per_primitive":
        for rec in records:
            yield (rec.primitive_id, bool(rec.breached))
    else:
        raise ValueError(f"unknown unit {unit!r}; expected 'per_target'|'per_primitive'")


def _target_breach(tgt, breach_threshold: float) -> bool:
    """Breach decision for a target under an optional rate threshold.

    ``breach_threshold == 0.0`` defers to the dataset's own ``breached`` flag (which is
    ``any_breach_rate > breach_threshold`` as computed at build time). A positive
    threshold re-decides from ``any_breach_rate`` so callers can tighten the bar without
    rebuilding the dataset.
    """
    if breach_threshold > 0.0:
        return float(tgt.any_breach_rate) > breach_threshold
    return bool(tgt.breached)


def node_lift_table(
    records: list["PrimitiveRecord"],
    labels: dict[str, "set[GrammarNode]"],
    *,
    unit: str = "per_target",
    min_n: int = 5,
    breach_threshold: float = 0.0,
) -> list[NodeLift]:
    """Per-node 2×2 lift / odds-ratio / Fisher table over the chosen analysis units.

    For every :class:`GrammarNode` that appears in ``labels``, partition the units into
    node-present vs node-absent (a unit's node-set is ``labels[primitive_id]``), count
    breaches in each, and compute p_with / p_without / baseline, absolute & relative
    lift (vs the grand baseline), the Haldane-corrected odds ratio + Wald CI, and a
    Fisher exact two-sided p-value.

    Nodes with ``n_with < min_n`` are kept but ``flagged=True`` (under-powered). The
    table is sorted by ``lift_rel`` descending (flagged rows sort with everyone else;
    callers/Engineer 6 decide how to treat them). p-values are UNCORRECTED.

    Args:
        records: dataset rows.
        labels: ``primitive_id -> set[GrammarNode]`` from the labeler.
        unit: ``"per_target"`` (default, headline) or ``"per_primitive"`` (comparison).
        min_n: minimum node-present unit count below which a node is flagged.
        breach_threshold: optional per-target ``any_breach_rate`` cutoff (per_target
            only); ``0.0`` uses the dataset's precomputed ``breached`` flag.
    """
    # Materialise units once. For per_target we need the target object to honour
    # breach_threshold; for per_primitive the aggregate flag is fixed.
    units: list[tuple[str, bool]] = []
    if unit == "per_target":
        for rec in records:
            for tgt in rec.targets:
                units.append((rec.primitive_id, _target_breach(tgt, breach_threshold)))
    elif unit == "per_primitive":
        units = list(_iter_units(records, unit))
    else:
        raise ValueError(f"unknown unit {unit!r}; expected 'per_target'|'per_primitive'")

    total_n = len(units)
    total_k = sum(1 for _, br in units if br)
    baseline = (total_k / total_n) if total_n else 0.0

    # Every node observed in the label map (across all primitives present in records).
    present_ids = {rec.primitive_id for rec in records}
    observed_nodes: set[GrammarNode] = set()
    for pid in present_ids:
        observed_nodes.update(labels.get(pid, set()))

    out: list[NodeLift] = []
    for node in observed_nodes:
        # 2×2: a = node present & breach; b = node present & no-breach;
        #      c = node absent  & breach; d = node absent  & no-breach.
        a = b = c = d = 0
        for pid, breached in units:
            has = node in labels.get(pid, set())
            if has and breached:
                a += 1
            elif has and not breached:
                b += 1
            elif (not has) and breached:
                c += 1
            else:
                d += 1
        n_with = a + b
        n_without = c + d
        p_with = (a / n_with) if n_with else 0.0
        p_without = (c / n_without) if n_without else 0.0
        orat, or_lo, or_hi = odds_ratio_ci(a, b, c, d, z=1.96)
        pval = fisher_exact_2x2(a, b, c, d)
        lift_rel = (p_with / baseline) if baseline > 0 else float("inf") if p_with > 0 else 0.0
        out.append(
            NodeLift(
                node=node,
                n_with=n_with,
                n_without=n_without,
                k_with=a,
                k_without=c,
                p_with=p_with,
                p_without=p_without,
                baseline=baseline,
                lift_abs=p_with - baseline,
                lift_rel=lift_rel,
                odds_ratio=orat,
                or_ci_low=or_lo,
                or_ci_high=or_hi,
                p_value=pval,
                with_ci=wilson_ci(a, n_with),
                without_ci=wilson_ci(c, n_without),
                flagged=n_with < min_n,
            )
        )

    out.sort(key=lambda nl: nl.lift_rel, reverse=True)
    return out
