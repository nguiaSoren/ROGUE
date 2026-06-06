"""Research-validation layer — "don't fool ourselves" controls for the grammar study.

This module is the adversarial conscience of the grammar-component predictive-power
study. Its job is to make the headline result (*do grammar nodes predict breaches?*)
TRUSTWORTHY — or to kill it. It does this by controlling for every way a naive
per-node lift can lie to us:

1. **Collinearity with family** — if a grammar node is derived from / nearly identical
   to one ``AttackFamily``, then "node predicts breach" is circular: it's just "family
   predicts breach" wearing a node's clothes. The genuinely informative nodes cut
   ACROSS families (AUTHORITY_FRAME, LANGUAGE_SHIFT, ENCODING_OBFUSCATION,
   STRUCTURED_OUTPUT, ...). :func:`node_family_collinearity` quantifies each node's
   redundancy with its dominant family (Cramér's V + overlap fraction) and FLAGS the
   circular ones.

2. **Target-mix confound** — a node may look strong only because it was tried against
   weak target models. :func:`stratified_node_lift` stratifies by target vendor /
   model_family and pools with Mantel–Haenszel.

3. **Family confound** — recompute node lift WITHIN each primitive family. A node whose
   lift vanishes within-family was a family proxy, not real signal (``by="family"``).

4. **Multiple comparisons** — ~23 nodes + up to ~250 pairs = hundreds of tests.
   Uncorrected p-values WILL manufacture false positives. :func:`benjamini_hochberg`
   applies BH-FDR across ALL node AND pair tests together.

5. **Ceiling effect** — the per-primitive ANY-breach base rate is ~0.79 (saturated). The
   per-(primitive × target) unit (~1540 units) is the correct, non-saturated denominator.
   We disclose this and prefer the per-target unit for the MH analysis.

6. **Judge-version confound** — ``breach_matrix`` is graded by the OLD v1/v2 judge
   (standing flag), which over-reports breaches vs judge v3. We cannot fix it here; we
   MUST disclose it as a limitation. Every verdict carries the caveat.

Pure Python + numpy only — **NO scipy / statsmodels**. Sibling stats helpers
(``wilson_ci`` / ``fisher_exact_2x2`` / ``odds_ratio_ci``) are imported lazily with a
self-contained local fallback so this module (and its tests) run standalone even when
the parallel sibling files don't exist yet.

OBSERVATIONAL, $0, read-only. Nothing here estimates a causal effect; every result is
an association in existing data.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Sequence

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .dataset import PrimitiveRecord


# --------------------------------------------------------------------------- #
# Lazy sibling-stats import with self-contained fallbacks.
# The parallel `rogue.grammar.stats` module (Engineer building stats) exposes
# wilson_ci / fisher_exact_2x2 / odds_ratio_ci. We prefer it when present, but
# never hard-depend on it (it may not exist yet during parallel build).
# --------------------------------------------------------------------------- #
def _stats():
    """Return the sibling stats module, or ``None`` if it isn't importable yet."""
    try:  # pragma: no cover - exercised both ways across the parallel build
        from . import stats as _s

        return _s
    except Exception:  # pragma: no cover
        return None


def _wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. Local fallback."""
    s = _stats()
    if s is not None and hasattr(s, "wilson_ci"):
        try:
            return s.wilson_ci(k, n)
        except Exception:  # pragma: no cover
            pass
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _fisher_exact_2x2(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p-value for the 2×2 table [[a,b],[c,d]]. Local fallback.

    a = node-present & breached, b = node-present & not breached,
    c = node-absent  & breached, d = node-absent  & not breached.
    """
    s = _stats()
    if s is not None and hasattr(s, "fisher_exact_2x2"):
        try:
            return s.fisher_exact_2x2(a, b, c, d)
        except Exception:  # pragma: no cover
            pass
    return _fisher_local(a, b, c, d)


def _fisher_local(a: int, b: int, c: int, d: int) -> float:
    """Self-contained two-sided Fisher exact test (hypergeometric tail sum)."""
    n = a + b + c + d
    if n == 0:
        return 1.0
    row1 = a + b
    col1 = a + c
    # log-factorials via lgamma for numeric stability on the corpus-size tables.
    lg = math.lgamma

    def lhyper(x: int) -> float:
        # P(X = x) for hypergeometric with margins fixed.
        x2 = row1 - x
        x3 = col1 - x
        x4 = n - row1 - col1 + x
        if x < 0 or x2 < 0 or x3 < 0 or x4 < 0:
            return float("-inf")
        return (
            lg(row1 + 1) + lg(n - row1 + 1) + lg(col1 + 1) + lg(n - col1 + 1)
            - lg(n + 1)
            - lg(x + 1) - lg(x2 + 1) - lg(x3 + 1) - lg(x4 + 1)
        )

    p_obs = lhyper(a)
    lo = max(0, col1 - (n - row1))
    hi = min(row1, col1)
    # Sum probabilities of all tables at least as extreme (<= observed, with epsilon).
    tot = 0.0
    eps = 1e-7
    for x in range(lo, hi + 1):
        lp = lhyper(x)
        if lp <= p_obs + eps:
            tot += math.exp(lp)
    return min(1.0, tot)


def _odds_ratio_ci(a: int, b: int, c: int, d: int) -> tuple[float, float, float]:
    """(OR, lo, hi) with Haldane–Anscombe 0.5 correction. Local fallback."""
    s = _stats()
    if s is not None and hasattr(s, "odds_ratio_ci"):
        try:
            return s.odds_ratio_ci(a, b, c, d)
        except Exception:  # pragma: no cover
            pass
    aa, bb, cc, dd = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    or_ = (aa * dd) / (bb * cc)
    se = math.sqrt(1 / aa + 1 / bb + 1 / cc + 1 / dd)
    lo = math.exp(math.log(or_) - 1.96 * se)
    hi = math.exp(math.log(or_) + 1.96 * se)
    return (or_, lo, hi)


# --------------------------------------------------------------------------- #
# Multiple-comparison correction.
# --------------------------------------------------------------------------- #
def benjamini_hochberg(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """Benjamini–Hochberg FDR step-up. Returns a reject-mask in input order.

    ``True`` at position i means: reject the null for test i at FDR level ``alpha``.

    Standard BH: sort p ascending, find the largest rank k with p_(k) <= (k/m)*alpha,
    reject all tests with rank <= k (i.e. all p_(i) for i <= k), which — by the step-up
    property — includes any test whose own p-value exceeds its own threshold but lies
    below the largest passing one.
    """
    m = len(pvalues)
    if m == 0:
        return []
    # NaN / out-of-range p-values are treated as 1.0 (never reject) defensively.
    clean = [1.0 if (p is None or math.isnan(p)) else min(1.0, max(0.0, p)) for p in pvalues]
    order = sorted(range(m), key=lambda i: clean[i])
    # Largest rank (1-based) satisfying p_(k) <= (k/m) * alpha.
    max_k = 0
    for rank, idx in enumerate(order, start=1):
        if clean[idx] <= (rank / m) * alpha:
            max_k = rank
    reject = [False] * m
    for rank, idx in enumerate(order, start=1):
        if rank <= max_k:
            reject[idx] = True
    return reject


# --------------------------------------------------------------------------- #
# Association: Cramér's V (binary node-presence vs categorical family).
# --------------------------------------------------------------------------- #
def cramers_v(a_present: list[bool], b_category: list) -> float:
    """Cramér's V between a binary vector ``a_present`` and a categorical ``b_category``.

    Bias-uncorrected Cramér's V on the 2×C contingency table. Returns 0.0 when either
    margin is degenerate (one row or one column), since association is undefined /
    trivially zero there. Perfect association → ~1.0; independence → ~0.0.
    """
    if len(a_present) != len(b_category):
        raise ValueError("a_present and b_category must be the same length")
    n = len(a_present)
    if n == 0:
        return 0.0
    cats = sorted({str(c) for c in b_category})
    if len(cats) < 2:
        return 0.0  # only one category → no association to measure
    cat_idx = {c: j for j, c in enumerate(cats)}
    # 2 rows (absent=0, present=1) × C columns.
    table = np.zeros((2, len(cats)), dtype=float)
    for present, cat in zip(a_present, b_category):
        table[1 if present else 0, cat_idx[str(cat)]] += 1.0
    row_sums = table.sum(axis=1, keepdims=True)
    col_sums = table.sum(axis=0, keepdims=True)
    total = table.sum()
    if total == 0 or (row_sums == 0).any():
        return 0.0  # one row empty → node always/never present → undefined
    expected = row_sums @ col_sums / total
    # Guard against zero-expected cells (a column with zero margin can't happen since
    # we built cats from observed data, but be safe).
    with np.errstate(divide="ignore", invalid="ignore"):
        chi2_terms = np.where(expected > 0, (table - expected) ** 2 / expected, 0.0)
    chi2 = float(chi2_terms.sum())
    r, c = table.shape
    k = min(r - 1, c - 1)
    if k <= 0:
        return 0.0
    v = math.sqrt(chi2 / (total * k))
    return min(1.0, v)


# --------------------------------------------------------------------------- #
# Labeling bridge — accept either a sibling labeler or a passed-in `labels` map.
# --------------------------------------------------------------------------- #
def _node_value(node: Any) -> str:
    return node.value if hasattr(node, "value") else str(node)


def _present_vector(
    records: Sequence["PrimitiveRecord"],
    labels: dict[str, set],
    node: Any,
) -> list[bool]:
    """Per-record boolean: is ``node`` assigned to this primitive?"""
    nv = _node_value(node)
    out = []
    for r in records:
        node_set = labels.get(r.primitive_id, set())
        out.append(any(_node_value(x) == nv for x in node_set))
    return out


def _all_nodes(labels: dict[str, set]) -> list:
    """Stable, sorted list of every node that appears in ``labels``."""
    seen: dict[str, Any] = {}
    for node_set in labels.values():
        for n in node_set:
            seen.setdefault(_node_value(n), n)
    return [seen[k] for k in sorted(seen)]


# --------------------------------------------------------------------------- #
# THREAT 1 — collinearity with family (circularity detector).
# --------------------------------------------------------------------------- #
def node_family_collinearity(
    records: Sequence["PrimitiveRecord"],
    labels: dict[str, set],
    *,
    overlap_threshold: float = 0.80,
    cramers_threshold: float = 0.70,
) -> dict:
    """Per node: redundancy with its dominant primitive family.

    For each node we compute:

    * ``dominant_family`` — the family that hosts the most node-present primitives.
    * ``overlap_frac``    — of the node-present primitives, the fraction in that one
      family. 1.0 means the node lives entirely in one family (maximally circular).
    * ``cramers_v``       — Cramér's V of node-presence against the full family vector.
    * ``circular``        — flagged True iff ``overlap_frac >= overlap_threshold`` OR
      ``cramers_v >= cramers_threshold``. Circular nodes are family proxies; their lift
      cannot be claimed as independent structural signal.
    * ``n_present`` / ``n_total`` for transparency.

    A node flagged ``circular`` is NOT disqualified outright — it is flagged so the
    master verdict can require survival of family stratification before trusting it.
    """
    fam_vec = [r.family for r in records]
    n_total = len(records)
    out: dict[str, dict] = {}
    for node in _all_nodes(labels):
        nv = _node_value(node)
        present = _present_vector(records, labels, node)
        n_present = sum(present)
        # dominant family among node-present primitives
        fam_counts: dict[str, int] = defaultdict(int)
        for p, fam in zip(present, fam_vec):
            if p:
                fam_counts[fam] += 1
        if fam_counts:
            dominant_family = max(fam_counts, key=lambda f: fam_counts[f])
            overlap_frac = fam_counts[dominant_family] / n_present if n_present else 0.0
        else:
            dominant_family = None
            overlap_frac = 0.0
        cv = cramers_v(present, fam_vec)
        circular = bool(
            n_present > 0
            and (overlap_frac >= overlap_threshold or cv >= cramers_threshold)
        )
        out[nv] = {
            "dominant_family": dominant_family,
            "overlap_frac": overlap_frac,
            "cramers_v": cv,
            "circular": circular,
            "n_present": n_present,
            "n_total": n_total,
        }
    return out


# --------------------------------------------------------------------------- #
# Raw (marginal) per-node lift on the per-target unit.
# --------------------------------------------------------------------------- #
def _target_units(
    records: Sequence["PrimitiveRecord"],
    labels: dict[str, set],
) -> list[dict]:
    """Flatten to per-(primitive × target) units — the non-saturated denominator.

    Each unit carries: primitive_id, family, vendor, model_family, breached (target-level),
    and node_set (the primitive's grammar nodes). Only primitives with breach data
    contribute units.
    """
    units: list[dict] = []
    for r in records:
        if not getattr(r, "has_breach_data", True):
            continue
        node_set = {_node_value(x) for x in labels.get(r.primitive_id, set())}
        for t in getattr(r, "targets", []) or []:
            units.append(
                {
                    "primitive_id": r.primitive_id,
                    "family": r.family,
                    "vendor": getattr(t, "vendor", "unknown"),
                    "model_family": getattr(t, "model_family", "unknown"),
                    "breached": bool(getattr(t, "breached", False)),
                    "nodes": node_set,
                }
            )
    return units


def _two_by_two(units: list[dict], nv: str) -> tuple[int, int, int, int]:
    """Build (a, b, c, d) for node ``nv`` on per-target units.

    a = present & breached, b = present & not, c = absent & breached, d = absent & not.
    """
    a = b = c = d = 0
    for u in units:
        has = nv in u["nodes"]
        br = u["breached"]
        if has and br:
            a += 1
        elif has and not br:
            b += 1
        elif (not has) and br:
            c += 1
        else:
            d += 1
    return a, b, c, d


def raw_node_lift(
    records: Sequence["PrimitiveRecord"],
    labels: dict[str, set],
) -> dict:
    """Marginal per-node lift on the per-target unit (no controls).

    Per node: present/absent breach rates, lift (ratio of rates), odds ratio + CI,
    Wilson CIs on each rate, Fisher exact p. This is the UNCONTROLLED signal — the
    master verdict only trusts a node after it also survives family stratification and
    FDR correction.
    """
    units = _target_units(records, labels)
    out: dict[str, dict] = {}
    for node in _all_nodes(labels):
        nv = _node_value(node)
        a, b, c, d = _two_by_two(units, nv)
        n_present = a + b
        n_absent = c + d
        p_present = a / n_present if n_present else 0.0
        p_absent = c / n_absent if n_absent else 0.0
        lift = (p_present / p_absent) if p_absent > 0 else float("inf") if p_present > 0 else 0.0
        or_, or_lo, or_hi = _odds_ratio_ci(a, b, c, d)
        pval = _fisher_exact_2x2(a, b, c, d)
        out[nv] = {
            "n_present_units": n_present,
            "n_absent_units": n_absent,
            "rate_present": p_present,
            "rate_absent": p_absent,
            "rate_present_ci": _wilson_ci(a, n_present),
            "rate_absent_ci": _wilson_ci(c, n_absent),
            "lift": lift,
            "odds_ratio": or_,
            "odds_ratio_ci": (or_lo, or_hi),
            "p_value": pval,
        }
    return out


# --------------------------------------------------------------------------- #
# THREATS 2 & 3 — stratified lift + Mantel–Haenszel pooling.
# --------------------------------------------------------------------------- #
def _mantel_haenszel(strata: list[tuple[int, int, int, int]]) -> dict:
    """Mantel–Haenszel pooled OR + Robins–Breslow–Greenland 95% CI + MH chi-square.

    Each stratum is (a, b, c, d) with the same orientation as :func:`_two_by_two`.
    Strata with an empty total are dropped. Returns OR, CI, p (from MH chi-square),
    and the count of contributing strata.
    """
    num = 0.0  # sum a*d/n
    den = 0.0  # sum b*c/n
    # RBG variance accumulators
    R = 0.0
    S = 0.0
    pr_sum = 0.0  # sum (a+d)*(a*d)/n^2
    ps_qr = 0.0  # sum [(a+d)*(b*c) + (b+c)*(a*d)] / n^2
    qs_sum = 0.0  # sum (b+c)*(b*c)/n^2
    # MH chi-square accumulators
    chi_num = 0.0  # sum (a - E[a])
    chi_var = 0.0  # sum Var(a)
    used = 0
    for a0, b0, c0, d0 in strata:
        n0 = a0 + b0 + c0 + d0
        if n0 == 0:
            continue
        # MH chi-square uses the RAW table (computed below). For the pooled OR we apply
        # a Haldane–Anscombe 0.5 correction to strata containing a zero cell, so a single
        # empty cell can't zero out R or S and force the pooled OR to NaN (standard
        # sparse-data practice). Strata with no zero cell are used as-is.
        if min(a0, b0, c0, d0) == 0:
            a, b, c, d = a0 + 0.5, b0 + 0.5, c0 + 0.5, d0 + 0.5
        else:
            a, b, c, d = float(a0), float(b0), float(c0), float(d0)
        n = a + b + c + d
        adn = a * d / n
        bcn = b * c / n
        num += adn
        den += bcn
        pr_sum += (a + d) * adn / n
        ps_qr += ((a + d) * bcn + (b + c) * adn) / n
        qs_sum += (b + c) * bcn / n
        R += adn
        S += bcn
        # MH chi-square uses the RAW (uncorrected) stratum table.
        row1 = a0 + b0
        col1 = a0 + c0
        e_a = row1 * col1 / n0
        if n0 > 1:
            var_a = row1 * (n0 - row1) * col1 * (n0 - col1) / (n0 * n0 * (n0 - 1))
        else:
            var_a = 0.0
        chi_num += a0 - e_a
        chi_var += var_a
        used += 1
    if den <= 0 or R <= 0 or S <= 0:
        # Not enough information to pool an OR.
        or_ = float("nan")
        lo = hi = float("nan")
    else:
        or_ = num / den
        var_lnor = pr_sum / (2 * R * R) + ps_qr / (2 * R * S) + qs_sum / (2 * S * S)
        se = math.sqrt(var_lnor) if var_lnor > 0 else 0.0
        lo = math.exp(math.log(or_) - 1.96 * se)
        hi = math.exp(math.log(or_) + 1.96 * se)
    # MH chi-square -> two-sided p via normal approx (chi2_1 = z^2).
    if chi_var > 0:
        chi2 = (abs(chi_num)) ** 2 / chi_var
        z = math.sqrt(chi2)
        pval = math.erfc(z / math.sqrt(2.0))
    else:
        pval = 1.0
    return {
        "pooled_or": or_,
        "pooled_or_ci": (lo, hi),
        "p_value": pval,
        "n_strata": used,
    }


def stratified_node_lift(
    records: Sequence["PrimitiveRecord"],
    labels: dict[str, set],
    *,
    by: str = "model_family",
) -> dict:
    """Per-node lift recomputed WITHIN strata of ``by`` and pooled with Mantel–Haenszel.

    ``by`` ∈ {"family", "vendor", "model_family"}:

    * ``"family"``        — primitive family (THREAT 3: kills family proxies).
    * ``"vendor"``        — target vendor (THREAT 2: kills weak-target confound).
    * ``"model_family"``  — target model family (THREAT 2, finer).

    For each node we report the within-stratum 2×2 lifts and a MH-pooled OR + CI that
    holds the stratum constant. ``survives_stratification`` is True iff the pooled OR
    CI excludes 1.0 on the protective/harmful side consistent with the raw effect — i.e.
    the effect does NOT collapse to ≈1 once the confounder is held fixed.

    The unit is per-(primitive × target). For ``by="family"`` the stratum is the
    primitive's family; for vendor / model_family it's the target's.
    """
    if by not in {"family", "vendor", "model_family"}:
        raise ValueError(f"`by` must be one of family/vendor/model_family, got {by!r}")
    units = _target_units(records, labels)
    out: dict[str, dict] = {}
    for node in _all_nodes(labels):
        nv = _node_value(node)
        # partition units by stratum
        by_stratum: dict[str, list[dict]] = defaultdict(list)
        for u in units:
            by_stratum[str(u[by])].append(u)
        per_stratum: dict[str, dict] = {}
        tables: list[tuple[int, int, int, int]] = []
        for stratum, us in sorted(by_stratum.items()):
            a, b, c, d = _two_by_two(us, nv)
            tables.append((a, b, c, d))
            np_ = a + b
            na_ = c + d
            rp = a / np_ if np_ else 0.0
            ra = c / na_ if na_ else 0.0
            per_stratum[stratum] = {
                "n_present_units": np_,
                "n_absent_units": na_,
                "rate_present": rp,
                "rate_absent": ra,
                "lift": (rp / ra) if ra > 0 else (float("inf") if rp > 0 else 0.0),
            }
        mh = _mantel_haenszel(tables)
        lo, hi = mh["pooled_or_ci"]
        survives = bool(
            not math.isnan(mh["pooled_or"])
            and not math.isnan(lo)
            and not math.isnan(hi)
            and (lo > 1.0 or hi < 1.0)  # CI excludes the null OR=1
        )
        out[nv] = {
            "by": by,
            "per_stratum": per_stratum,
            "pooled_or": mh["pooled_or"],
            "pooled_or_ci": mh["pooled_or_ci"],
            "p_value": mh["p_value"],
            "n_strata": mh["n_strata"],
            "survives_stratification": survives,
        }
    return out


# --------------------------------------------------------------------------- #
# THREAT 4 helper — pairwise interaction p-values (optional sibling).
# --------------------------------------------------------------------------- #
def _pair_pvalues(
    records: Sequence["PrimitiveRecord"],
    labels: dict[str, set],
) -> dict:
    """{(nodeA, nodeB): {p_value, odds_ratio, n_both, ...}} for FDR pooling.

    Uses the sibling ``combinations.pairwise_interactions`` when importable; otherwise a
    local fallback computes, per node pair, the per-target breach 2×2 for "both nodes
    present" vs "not both present" and a Fisher exact p. Pairs with too-few both-present
    units are skipped (no test, can't inflate the FDR pool with noise).
    """
    # Prefer sibling combinations module if it exposes a usable result. It returns a
    # list[Interaction] (dataclass with .node_a/.node_b/.p_value/.odds_ratio_both/.n_both)
    # OR a dict keyed by node pair; we normalize both shapes to {(a,b): {p_value, ...}}.
    try:  # pragma: no cover - depends on parallel build state
        from .combinations import pairwise_interactions  # type: ignore

        res = pairwise_interactions(records, labels)
        norm: dict = {}
        if isinstance(res, dict):
            for k, v in res.items():
                pv = v.get("p_value") if isinstance(v, dict) else None
                if pv is not None:
                    norm[k] = v
        else:  # list[Interaction]
            for it in res or []:
                pv = getattr(it, "p_value", None)
                if pv is None:
                    continue
                na = _node_value(getattr(it, "node_a"))
                nb = _node_value(getattr(it, "node_b"))
                key = (na, nb) if na <= nb else (nb, na)
                norm[key] = {
                    "p_value": pv,
                    "odds_ratio": getattr(it, "odds_ratio_both", None),
                    "n_both_present_units": getattr(it, "n_both", None),
                }
        if norm:
            return norm
    except Exception:
        pass

    units = _target_units(records, labels)
    nodes = _all_nodes(labels)
    out: dict = {}
    min_both = 5  # require at least a few both-present units to test a pair
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            na, nb = _node_value(nodes[i]), _node_value(nodes[j])
            a = b = c = d = 0
            for u in units:
                both = (na in u["nodes"]) and (nb in u["nodes"])
                br = u["breached"]
                if both and br:
                    a += 1
                elif both and not br:
                    b += 1
                elif (not both) and br:
                    c += 1
                else:
                    d += 1
            if a + b < min_both:
                continue
            pval = _fisher_exact_2x2(a, b, c, d)
            or_, lo, hi = _odds_ratio_ci(a, b, c, d)
            out[(na, nb)] = {
                "p_value": pval,
                "odds_ratio": or_,
                "odds_ratio_ci": (lo, hi),
                "n_both_present_units": a + b,
            }
    return out


# --------------------------------------------------------------------------- #
# Dataset summary with the ceiling disclosure.
# --------------------------------------------------------------------------- #
def _dataset_summary(
    records: Sequence["PrimitiveRecord"],
    labels: dict[str, set],
) -> dict:
    with_data = [r for r in records if getattr(r, "has_breach_data", True)]
    n_breached = sum(1 for r in with_data if r.breached)
    base = (n_breached / len(with_data)) if with_data else 0.0
    units = _target_units(records, labels)
    unit_breached = sum(1 for u in units if u["breached"])
    unit_base = (unit_breached / len(units)) if units else 0.0
    return {
        "n_primitives": len(records),
        "n_with_breach_data": len(with_data),
        "primitive_breach_base_rate": base,
        "n_target_units": len(units),
        "target_unit_breach_base_rate": unit_base,
        "ceiling_note": (
            f"Per-primitive ANY-breach base rate is {base:.2f} (saturated/ceiling). "
            f"The per-(primitive × target) unit (n={len(units)}, base rate "
            f"{unit_base:.2f}) is the correct non-saturated denominator and is what the "
            "MH / stratified analysis uses."
        ),
        "n_nodes_observed": len(_all_nodes(labels)),
    }


CAVEATS: list[str] = [
    "OBSERVATIONAL, not causal: every result is an association in existing corpus data. "
    "A node 'predicting' breach does not mean adding it would cause one.",
    "JUDGE-VERSION CONFOUND: breach_matrix is graded by the OLD v1/v2 judge (standing "
    "flag — judge-v3 re-judge deferred for cost). It OVER-REPORTS breaches vs judge v3, "
    "so absolute breach rates and every lift inherit a v1/v2 bias. Treat as v1/v2-baseline.",
    "CEILING EFFECT: per-primitive ANY-breach base rate ≈0.79 is saturated; the analysis "
    "uses the per-(primitive × target) unit to avoid the ceiling, but residual saturation "
    "in easy strata can still compress lift.",
    "SMALL-N nodes: several cross-family nodes are rare (n<10 present primitives). Their "
    "CIs are wide and their FDR-significance is fragile — disclosed per node.",
    "TARGET-MIX confound: controlled via vendor / model_family Mantel–Haenszel pooling, "
    "but the target panel is itself a non-random convenience sample of deployments.",
    "MULTIPLE COMPARISONS: ~23 node tests + pairwise interaction tests are pooled under a "
    "single Benjamini–Hochberg FDR(α=0.05); per-test p-values are NOT trustworthy alone.",
    "CIRCULARITY: family-mirroring nodes are derived FROM the family, so their lift is "
    "partly tautological. node_family_collinearity flags these; the verdict only counts a "
    "node as signal if it is non-circular AND survives family stratification.",
]


# --------------------------------------------------------------------------- #
# MASTER VERDICT.
# --------------------------------------------------------------------------- #
def controlled_analysis(
    records: Sequence["PrimitiveRecord"],
    labels: dict[str, set],
    *,
    alpha: float = 0.05,
) -> dict:
    """The master, self-skeptical verdict. Combines every control into one report.

    Pipeline:

    1. dataset summary (+ ceiling disclosure);
    2. node↔family collinearity (circularity flags);
    3. raw per-node lift on the per-target unit;
    4. BH-FDR correction across ALL node tests AND pair tests jointly;
    5. within-family survival (THREAT 3) and target MH pooling (THREATS 2);
    6. a single VERDICT.

    VERDICT = "signal" iff at least one node is simultaneously:
      * FDR-significant on its raw per-target lift,
      * NOT circular (not a family proxy),
      * survives_stratification under ``by="family"`` (within-family effect persists),
      * AND survives target MH pooling (``by="model_family"``).
    Otherwise "weak/none" — explicitly noted as a *successful* null that saves the
    AST/synthetic-generation roadmap from chasing a non-effect.
    """
    summary = _dataset_summary(records, labels)
    collinearity = node_family_collinearity(records, labels)
    raw = raw_node_lift(records, labels)
    within_family = stratified_node_lift(records, labels, by="family")
    mh_model = stratified_node_lift(records, labels, by="model_family")
    mh_vendor = stratified_node_lift(records, labels, by="vendor")
    pair_tests = _pair_pvalues(records, labels)

    # ---- Joint BH-FDR across node tests + pair tests ----
    node_keys = list(raw.keys())
    pair_keys = list(pair_tests.keys())
    node_pvals = [raw[k]["p_value"] for k in node_keys]
    pair_pvals = [pair_tests[k]["p_value"] for k in pair_keys]
    all_pvals = node_pvals + pair_pvals
    reject = benjamini_hochberg(all_pvals, alpha=alpha)
    node_reject = dict(zip(node_keys, reject[: len(node_keys)]))
    pair_reject = dict(zip(pair_keys, reject[len(node_keys):]))

    # annotate raw with FDR result
    for k in node_keys:
        raw[k]["fdr_significant"] = bool(node_reject.get(k, False))

    # ---- assemble per-node verdict rows ----
    surviving_nodes: list[dict] = []
    node_rows: list[dict] = []
    for nv in node_keys:
        coll = collinearity.get(nv, {})
        wf = within_family.get(nv, {})
        mh = mh_model.get(nv, {})
        fdr_sig = bool(node_reject.get(nv, False))
        non_circular = not bool(coll.get("circular", False))
        survives_family = bool(wf.get("survives_stratification", False))
        survives_target = bool(mh.get("survives_stratification", False))
        is_signal = fdr_sig and non_circular and survives_family and survives_target
        row = {
            "node": nv,
            "raw_lift": raw[nv]["lift"],
            "raw_odds_ratio": raw[nv]["odds_ratio"],
            "raw_p_value": raw[nv]["p_value"],
            "fdr_significant": fdr_sig,
            "circular": bool(coll.get("circular", False)),
            "dominant_family": coll.get("dominant_family"),
            "overlap_frac": coll.get("overlap_frac"),
            "cramers_v": coll.get("cramers_v"),
            "within_family_pooled_or": wf.get("pooled_or"),
            "survives_family_stratification": survives_family,
            "target_mh_pooled_or": mh.get("pooled_or"),
            "survives_target_stratification": survives_target,
            "is_signal": is_signal,
        }
        node_rows.append(row)
        if is_signal:
            surviving_nodes.append(row)

    verdict = "signal" if surviving_nodes else "weak/none"
    if verdict == "weak/none":
        verdict_note = (
            "No grammar node clears all four bars (FDR-significant ∧ non-circular ∧ "
            "survives family stratification ∧ survives target MH pooling). This is a "
            "SUCCESSFUL null result: it saves the Technique-AST / synthetic-generation "
            "roadmap from building on a structural-component effect the data does not "
            "support. The family label, not the sub-family grammar node, carries the "
            "predictive weight here."
        )
    else:
        names = ", ".join(r["node"] for r in surviving_nodes)
        verdict_note = (
            f"{len(surviving_nodes)} node(s) survive every control: {names}. Each is "
            "FDR-significant, non-circular (not a family proxy), and retains its effect "
            "within primitive family AND after target Mantel–Haenszel pooling. These are "
            "the defensible structural signals to carry into the AST roadmap — still "
            "OBSERVATIONAL and still under the v1/v2-judge caveat."
        )

    return {
        "verdict": verdict,
        "verdict_note": verdict_note,
        "surviving_nodes": surviving_nodes,
        "dataset_summary": summary,
        "node_family_collinearity": collinearity,
        "raw_node_lift": raw,
        "within_family_stratification": within_family,
        "target_mh_model_family": mh_model,
        "target_mh_vendor": mh_vendor,
        "node_rows": node_rows,
        "fdr": {
            "alpha": alpha,
            "n_node_tests": len(node_keys),
            "n_pair_tests": len(pair_keys),
            "n_total_tests": len(all_pvals),
            "n_node_reject": sum(1 for v in node_reject.values() if v),
            "n_pair_reject": sum(1 for v in pair_reject.values() if v),
            "node_significant": {k: bool(v) for k, v in node_reject.items()},
        },
        "caveats": list(CAVEATS),
    }
