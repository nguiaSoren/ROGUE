"""Pairwise grammar-node interactions — the combination-analysis layer.

This is THE gold of the grammar-component study: per-node lift (Engineer 4) only tells
us whether a node *alone* tracks breaches; pairwise interactions tell us whether
COMPOSING two nodes does something the two nodes do not do separately. A positive
interaction (synergy) is the empirical fact that would justify grammar *composition*
(a Technique-AST that combines nodes) over a flat per-node model.

OBSERVATIONAL, $0, read-only. Analysis unit = one ``(primitive × target)`` pair:
for every ``record`` we emit one observation per ``record.targets`` entry, with
``breach = target.breached``. We deliberately do NOT aggregate to the per-primitive
level — the per-primitive ANY-breach base rate is ~0.79 (a ceiling that washes out all
contrast); the per-(primitive × target) rate has real spread and is the correct unit.

No-interaction baseline (stated explicitly)
-------------------------------------------
For each unordered node pair (A, B) we partition every observation by node presence into
four cells: ``both`` (A and B), ``a_only`` (A, not B), ``b_only`` (B, not A), and
``neither``. Each cell has an empirical breach probability.

The expected breach probability of the ``both`` cell *under no interaction* is computed
on the **odds (log-odds) scale** — i.e. the standard logistic no-interaction model, where
the two nodes' effects are ADDITIVE in log-odds (equivalently MULTIPLICATIVE in odds):

    OR(both vs neither) == OR(a_only vs neither) * OR(b_only vs neither)

Each cell's odds use a Haldane-Anscombe 0.5 continuity correction
(``odds = (k + 0.5) / (n - k + 0.5)``) — NOT the raw ``p / (1 - p)`` — so a thin
single-node cell with 0 breaches (e.g. n=6, common in the corpus) can't collapse the
baseline to a degenerate ``expected_p_both ≈ 0`` and manufacture a fake "synergy". The
same correction is used for the OR/CI, so baseline and effect-size are consistent:

    odds_neither = (k_neither + .5) / (n_neither - k_neither + .5)
    OR_a = odds_a_only / odds_neither
    OR_b = odds_b_only / odds_neither
    expected_odds_both = odds_neither * OR_a * OR_b
    expected_p_both    = expected_odds_both / (1 + expected_odds_both)

``interaction_delta = p_both - expected_p_both`` (> 0 = synergy on the probability scale,
i.e. the combination breaches MORE than the multiplicative-odds model predicts). We report
the delta on the probability scale because that's the directly interpretable quantity
("how many more breaches than expected"), while the *baseline* that defines "expected" is
the odds-scale no-interaction model (the right null for binary outcomes — it can't predict
p > 1, unlike a naive additive-on-probability null).

Why odds-scale rather than additive-on-probability: with a high background rate, an
additive-probability null routinely predicts expected p_both > 1 (nonsensical) and
manufactures fake "antagonism". The logistic null is bounded in [0, 1] and is the model an
actual Technique-AST composition would be fit under, so the delta against it is the
honest test of "does composing beat the no-interaction assumption".

Significance
------------
``p_value`` is the Fisher exact p of the interaction term, computed on the 2×2 table of
(node B present/absent) × (breach/no-breach) *within the rows where node A is present vs
absent*, collapsed to the both-vs-neither contrast that the OR measures. Concretely we run
Fisher's exact test on the both-vs-neither 2×2 (the same table the OR is read from). This
is a conservative, distribution-free test that needs no scipy. ``synergy`` is
``interaction_delta > 0 AND p_value < 0.05`` — PRE-FDR; Engineer 6 applies the
multiple-comparison correction across the returned pairs.

Small-n is the trap
-------------------
Any pair where ANY of the four cells has fewer than ``min_cell_n`` observations is
SKIPPED (its OR/CI/p would be unstable). Skips are counted, never silent:
:func:`suppressed_pair_count` reports the drop count and the CLI surfaces it.

NO scipy / statsmodels. Pure Python + (optional) numpy. Engineer 4's helpers
(``fisher_exact_2x2``, ``odds_ratio_ci``, ``wilson_ci``) are imported lazily with a local
fallback so this module + its tests run standalone before Engineer 4 lands.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

from ..schemas import GrammarNode
from .dataset import PrimitiveRecord


# --------------------------------------------------------------------------- #
# Engineer 4 helpers — import lazily, fall back to local pure-Python copies.
# --------------------------------------------------------------------------- #
def _import_stats_helpers():
    """Return (fisher_exact_2x2, odds_ratio_ci, wilson_ci).

    Prefer Engineer 4's ``rogue.grammar.stats``; if it doesn't exist yet (parallel
    build) fall back to local copies so this module is importable standalone.
    """
    try:  # pragma: no cover - exercised only once Engineer 4 lands
        from .stats import fisher_exact_2x2, odds_ratio_ci, wilson_ci

        return fisher_exact_2x2, odds_ratio_ci, wilson_ci
    except Exception:
        return _fisher_exact_2x2_local, _odds_ratio_ci_local, _wilson_ci_local


def _log_factorial(n: int) -> float:
    return math.lgamma(n + 1)


def _hypergeom_logpmf(a: int, b: int, c: int, d: int) -> float:
    """log P of one 2x2 table [[a, b], [c, d]] under the hypergeometric null."""
    row1, row2 = a + b, c + d
    col1, col2 = a + c, b + d
    n = a + b + c + d
    return (
        _log_factorial(row1)
        + _log_factorial(row2)
        + _log_factorial(col1)
        + _log_factorial(col2)
        - _log_factorial(n)
        - _log_factorial(a)
        - _log_factorial(b)
        - _log_factorial(c)
        - _log_factorial(d)
    )


def _fisher_exact_2x2_local(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for table [[a, b], [c, d]]. Pure Python.

    Sums the hypergeometric probability of every table at least as extreme (<= the
    observed table's probability, with a small epsilon for float wobble) holding all
    margins fixed.
    """
    row1 = a + b
    row2 = c + d
    col1 = a + c
    n = a + b + c + d
    if n == 0:
        return 1.0
    p_obs = math.exp(_hypergeom_logpmf(a, b, c, d))
    # Range of the top-left cell holding all margins fixed.
    lo = max(0, col1 - row2)
    hi = min(row1, col1)
    total = 0.0
    eps = 1e-9
    for a_i in range(lo, hi + 1):
        b_i = row1 - a_i
        c_i = col1 - a_i
        d_i = n - a_i - b_i - c_i
        if b_i < 0 or c_i < 0 or d_i < 0:
            continue
        p_i = math.exp(_hypergeom_logpmf(a_i, b_i, c_i, d_i))
        if p_i <= p_obs * (1 + eps):
            total += p_i
    return min(1.0, total)


def _odds_ratio_ci_local(
    a: int, b: int, c: int, d: int, *, z: float = 1.96
) -> tuple[float, float, float]:
    """(odds_ratio, lo, hi) with Woolf's log-OR CI and Haldane-Anscombe 0.5 correction."""
    aa, bb, cc, dd = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    or_ = (aa * dd) / (bb * cc)
    se = math.sqrt(1 / aa + 1 / bb + 1 / cc + 1 / dd)
    log_or = math.log(or_)
    return or_, math.exp(log_or - z * se), math.exp(log_or + z * se)


def _wilson_ci_local(k: int, n: int, *, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion k/n."""
    if n == 0:
        return 0.0, 1.0
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


# --------------------------------------------------------------------------- #
# Deliverable dataclass.
# --------------------------------------------------------------------------- #
@dataclass
class Interaction:
    """One unordered grammar-node pair's interaction on the per-(primitive × target) unit.

    See the module docstring for the no-interaction baseline (odds-scale / logistic null).
    """

    node_a: GrammarNode
    node_b: GrammarNode
    n_both: int
    n_a_only: int
    n_b_only: int
    n_neither: int
    p_both: float
    p_a_only: float
    p_b_only: float
    p_neither: float
    expected_p_both: float  # odds-scale (multiplicative-on-odds) no-interaction baseline
    interaction_delta: float  # p_both - expected_p_both  (>0 = synergy)
    odds_ratio_both: float  # OR of (A&B present) vs (neither) on breach
    p_value: float  # Fisher exact p of the both-vs-neither table (interaction term)
    synergy: bool  # interaction_delta > 0 AND p_value < 0.05 (pre-FDR)
    both_ci: tuple[float, float]  # Wilson CI on p_both


# --------------------------------------------------------------------------- #
# Observation expansion: per-(primitive × target).
# --------------------------------------------------------------------------- #
def _observations(
    records: list[PrimitiveRecord],
    labels: dict[str, set[GrammarNode]],
) -> list[tuple[frozenset[GrammarNode], bool]]:
    """Expand records into per-(primitive × target) observations.

    One observation per target on a record that HAS breach data; carries the record's
    grammar-node set (labels) and that target's ``breached`` flag. Records absent from
    ``labels`` contribute the empty node set (they still count toward 'neither').
    """
    obs: list[tuple[frozenset[GrammarNode], bool]] = []
    for rec in records:
        if not rec.has_breach_data:
            continue
        nodes = frozenset(labels.get(rec.primitive_id, set()))
        for tgt in rec.targets:
            obs.append((nodes, bool(tgt.breached)))
    return obs


def _cell_odds(k: int, n: int) -> float:
    """Breach odds of a cell with a Haldane-Anscombe 0.5 continuity correction.

    odds = (k + 0.5) / (n - k + 0.5). The +0.5 is essential here, not cosmetic: an
    empirical odds of exactly 0 (a cell with 0 breaches — common in THIN single-node
    cells like n=6) collapses the multiplicative-odds baseline to expected_p_both ≈ 0 and
    manufactures a huge fake "synergy". The continuity correction keeps a thin all-no
    cell from poisoning the baseline, matching the same correction used for the OR/CI.
    """
    return (k + 0.5) / (n - k + 0.5)


def _expected_p_both_logodds(
    k_neither: int,
    n_neither: int,
    k_a_only: int,
    n_a_only: int,
    k_b_only: int,
    n_b_only: int,
) -> float:
    """No-interaction expected p(both) on the odds scale (see module docstring).

    OR_both = OR_a * OR_b  ⇒  odds_both = odds_neither * OR_a * OR_b
                            = odds_a_only * odds_b_only / odds_neither.

    Cell odds use the Haldane-Anscombe 0.5 correction so a thin all-no single cell can't
    drive the baseline to a degenerate 0 (the small-cell trap).
    """
    o_n = _cell_odds(k_neither, n_neither)
    o_a = _cell_odds(k_a_only, n_a_only)
    o_b = _cell_odds(k_b_only, n_b_only)
    expected_odds = (o_a * o_b) / o_n
    return expected_odds / (1 + expected_odds)


# --------------------------------------------------------------------------- #
# Public API.
# --------------------------------------------------------------------------- #
def pairwise_interactions(
    records: list[PrimitiveRecord],
    labels: dict[str, set[GrammarNode]],
    *,
    min_cell_n: int = 5,
) -> list[Interaction]:
    """Pairwise grammar-node interactions on the per-(primitive × target) unit.

    For each unordered node pair that co-occurs in >= ``min_cell_n`` observations, partition
    all observations into both / a_only / b_only / neither, compute the four empirical breach
    probabilities, the odds-scale no-interaction baseline ``expected_p_both`` and
    ``interaction_delta = p_both - expected_p_both``, the both-vs-neither odds ratio + Fisher
    exact p, and a Wilson CI on p_both.

    SKIPS any pair where ANY of the four cells has n < ``min_cell_n`` (unstable). Use
    :func:`suppressed_pair_count` for the drop count.

    Returns ``Interaction``s sorted by ``interaction_delta`` descending.
    """
    fisher_exact_2x2, odds_ratio_ci, wilson_ci = _import_stats_helpers()
    obs = _observations(records, labels)

    # Per-pair cell tallies: (n, breaches) for each of the 4 cells.
    nodes_present = sorted({n for ns, _ in obs for n in ns}, key=lambda n: n.value)
    out: list[Interaction] = []

    for node_a, node_b in itertools.combinations(nodes_present, 2):
        # 4 cells: keys = (has_a, has_b) -> [n, breaches]
        cells: dict[tuple[bool, bool], list[int]] = {
            (True, True): [0, 0],
            (True, False): [0, 0],
            (False, True): [0, 0],
            (False, False): [0, 0],
        }
        for ns, breached in obs:
            ha = node_a in ns
            hb = node_b in ns
            cell = cells[(ha, hb)]
            cell[0] += 1
            if breached:
                cell[1] += 1

        n_both, k_both = cells[(True, True)]
        n_a_only, k_a_only = cells[(True, False)]
        n_b_only, k_b_only = cells[(False, True)]
        n_neither, k_neither = cells[(False, False)]

        # Co-occurrence gate + small-n suppression (any cell < min_cell_n -> skip).
        if n_both < min_cell_n:
            continue
        if min(n_both, n_a_only, n_b_only, n_neither) < min_cell_n:
            continue

        p_both = k_both / n_both
        p_a_only = k_a_only / n_a_only
        p_b_only = k_b_only / n_b_only
        p_neither = k_neither / n_neither

        expected_p_both = _expected_p_both_logodds(
            k_neither, n_neither, k_a_only, n_a_only, k_b_only, n_b_only
        )
        interaction_delta = p_both - expected_p_both

        # OR + Fisher p for both-vs-neither: 2x2 = [[k_both, n_both-k_both],
        #                                           [k_neither, n_neither-k_neither]]
        a = k_both
        b = n_both - k_both
        c = k_neither
        d = n_neither - k_neither
        or_both, *_ = odds_ratio_ci(a, b, c, d)
        p_value = fisher_exact_2x2(a, b, c, d)
        both_ci = wilson_ci(k_both, n_both)

        synergy = interaction_delta > 0 and p_value < 0.05

        out.append(
            Interaction(
                node_a=node_a,
                node_b=node_b,
                n_both=n_both,
                n_a_only=n_a_only,
                n_b_only=n_b_only,
                n_neither=n_neither,
                p_both=p_both,
                p_a_only=p_a_only,
                p_b_only=p_b_only,
                p_neither=p_neither,
                expected_p_both=expected_p_both,
                interaction_delta=interaction_delta,
                odds_ratio_both=or_both,
                p_value=p_value,
                synergy=synergy,
                both_ci=both_ci,
            )
        )

    out.sort(key=lambda i: i.interaction_delta, reverse=True)
    return out


def suppressed_pair_count(
    records: list[PrimitiveRecord],
    labels: dict[str, set[GrammarNode]],
    *,
    min_cell_n: int = 5,
) -> int:
    """Count node pairs DROPPED for small-n (any of the 4 cells < ``min_cell_n``).

    Counts only pairs that actually CO-OCCUR (n_both >= 1) — pairs that never appear
    together aren't candidate interactions, so they don't count as "suppressed". This is
    the honest denominator: of the pairs we *could* have tested, how many were too thin.
    """
    obs = _observations(records, labels)
    nodes_present = sorted({n for ns, _ in obs for n in ns}, key=lambda n: n.value)

    suppressed = 0
    for node_a, node_b in itertools.combinations(nodes_present, 2):
        cells = {
            (True, True): 0,
            (True, False): 0,
            (False, True): 0,
            (False, False): 0,
        }
        for ns, _breached in obs:
            cells[(node_a in ns, node_b in ns)] += 1

        n_both = cells[(True, True)]
        if n_both < 1:
            continue  # never co-occur -> not a candidate, not "suppressed"
        n_a_only = cells[(True, False)]
        n_b_only = cells[(False, True)]
        n_neither = cells[(False, False)]
        if min(n_both, n_a_only, n_b_only, n_neither) < min_cell_n:
            suppressed += 1
    return suppressed
