"""Per-primitive analysis dataset: join ``attack_primitives`` → ``breach_matrix``.

Foundational slice of the grammar-component predictive-power study (see the package
docstring in ``rogue.grammar``). This module owns the *join*: it pairs every
``AttackPrimitive`` with its breach outcomes and emits one :class:`PrimitiveRecord`
per primitive, carrying per-target granularity (:class:`TargetOutcome`) so the
validation engineer can stratify by vendor / model family.

This is OBSERVATIONAL analysis over EXISTING rows only — SELECT-only, no generation,
no API calls, $0. Nothing here ever writes.

Aggregation contract
--------------------
``breach_matrix`` is a VIEW with one row per ``(primitive_id, deployment_config_id,
run_date)``. A single (primitive, config) pair can therefore appear across multiple
run_dates (re-runs). We collapse those into ONE :class:`TargetOutcome` per
deployment_config by:

* ``n_trials``     — summed across run_dates;
* ``any_breach_rate`` / ``full_breach_rate`` — trial-weighted means across run_dates
  (so a 100-trial run isn't outvoted by a 2-trial re-run). With a single run_date this
  is just that row's rate.

A primitive's aggregate ``breach_rate`` is the **max** ``any_breach_rate`` across its
targets (the headline "did this primitive ever break anything" signal), and
``breached`` is True iff *any* TargetOutcome breached (its ``any_breach_rate`` exceeds
``breach_threshold``).

CAVEAT (do not fix here — recorded for the validation engineer to surface):
``breach_matrix`` is graded by the OLD v1/v2 judge, not judge v3. It **over-reports
breaches** relative to v3 (the standing judge-v3 re-judge is deferred for cost). Every
breach signal in this dataset inherits that v1/v2 bias; treat absolute breach rates as
v1/v2-baseline, not v3.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.model_specs import extract_model_family, extract_vendor
from ..db.models import AttackPrimitive as AttackPrimitiveORM
from ..db.models import DeploymentConfig as DeploymentConfigORM


# --------------------------------------------------------------------------- #
# Frozen dataclasses — other engineers code against these field names.
# --------------------------------------------------------------------------- #
@dataclass
class TargetOutcome:
    """One (primitive × deployment_config) breach outcome, collapsed over run_dates."""

    deployment_config_id: str
    vendor: str
    model_family: str
    any_breach_rate: float
    full_breach_rate: float
    n_trials: int
    breached: bool  # any_breach_rate > breach_threshold


@dataclass
class PrimitiveRecord:
    """One ``AttackPrimitive`` joined to its aggregate + per-target breach outcomes."""

    primitive_id: str
    family: str  # primary AttackFamily value (string)
    secondary_families: list[str]
    payload_slots: dict  # raw slot dict (keys drive Engineer 3's labeler)
    requires_multi_turn: bool
    vector: str
    breached: bool  # ANY target breached (aggregate)
    breach_rate: float  # max any_breach_rate across targets (0.0 if no breach data)
    n_trials: int  # total trials across targets
    has_breach_data: bool  # True iff present in breach_matrix at all
    targets: list[TargetOutcome] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Pure aggregation helper — DB-free, unit-testable.
# --------------------------------------------------------------------------- #
def _enum_value(v: Any) -> str:
    """Return the wire string of an enum (or the value itself if already a str)."""
    return v.value if hasattr(v, "value") else str(v)


def _weighted_rate(rows: Iterable[Mapping[str, Any]], key: str) -> float:
    """Trial-weighted mean of ``rows[*][key]`` over ``rows[*]['n_trials']``.

    Rows whose rate is None (e.g. every trial errored → NULLIF made the view-rate NULL)
    contribute their trials to the denominator only if the rate is present; a None rate
    drops out of both numerator and weight so it can't poison the mean. Falls back to a
    plain mean if total weight is zero.
    """
    num = 0.0
    wt = 0
    for r in rows:
        rate = r.get(key)
        if rate is None:
            continue
        n = int(r.get("n_trials") or 0)
        num += float(rate) * n
        wt += n
    if wt > 0:
        return num / wt
    # No usable weights: fall back to a simple mean of present rates, else 0.0.
    present = [float(r[key]) for r in rows if r.get(key) is not None]
    return sum(present) / len(present) if present else 0.0


def aggregate_primitive(
    primitive_id: str,
    family: str,
    secondary_families: list[str],
    payload_slots: dict,
    requires_multi_turn: bool,
    vector: str,
    breach_rows: list[Mapping[str, Any]],
    *,
    target_meta: Mapping[str, tuple[str, str]],
    breach_threshold: float = 0.0,
) -> PrimitiveRecord:
    """Build one :class:`PrimitiveRecord` from raw breach_matrix rows for a primitive.

    Pure (no DB). ``breach_rows`` is the list of breach_matrix rows for THIS primitive,
    each a mapping with at least ``deployment_config_id``, ``n_trials``,
    ``any_breach_rate``, ``full_breach_rate`` (rates may be None). ``target_meta`` maps a
    ``deployment_config_id`` → ``(vendor, model_family)``.

    Rows are grouped by deployment_config_id (collapsing run_dates) into one
    :class:`TargetOutcome` each; the record's aggregate fields derive from those.
    """
    by_target: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in breach_rows:
        by_target[r["deployment_config_id"]].append(r)

    targets: list[TargetOutcome] = []
    for dc_id, rows in by_target.items():
        vendor, model_family = target_meta.get(dc_id, ("unknown", "unknown"))
        any_rate = _weighted_rate(rows, "any_breach_rate")
        full_rate = _weighted_rate(rows, "full_breach_rate")
        n_trials = sum(int(r.get("n_trials") or 0) for r in rows)
        targets.append(
            TargetOutcome(
                deployment_config_id=dc_id,
                vendor=vendor,
                model_family=model_family,
                any_breach_rate=any_rate,
                full_breach_rate=full_rate,
                n_trials=n_trials,
                breached=any_rate > breach_threshold,
            )
        )

    # Stable order for reproducibility (validation engineer iterates these).
    targets.sort(key=lambda t: t.deployment_config_id)

    has_breach_data = bool(breach_rows)
    breach_rate = max((t.any_breach_rate for t in targets), default=0.0)
    breached = any(t.breached for t in targets)
    total_trials = sum(t.n_trials for t in targets)

    return PrimitiveRecord(
        primitive_id=primitive_id,
        family=family,
        secondary_families=list(secondary_families or []),
        payload_slots=dict(payload_slots or {}),
        requires_multi_turn=bool(requires_multi_turn),
        vector=vector,
        breached=breached,
        breach_rate=breach_rate,
        n_trials=total_trials,
        has_breach_data=has_breach_data,
        targets=targets,
    )


# --------------------------------------------------------------------------- #
# DB entry point.
# --------------------------------------------------------------------------- #
def _fetch_target_meta(session: Session) -> dict[str, tuple[str, str]]:
    """deployment_config_id → (vendor, model_family) for every config (SELECT-only)."""
    rows = session.execute(
        select(DeploymentConfigORM.config_id, DeploymentConfigORM.target_model)
    ).all()
    return {
        cfg_id: (extract_vendor(model), extract_model_family(model))
        for cfg_id, model in rows
    }


def _fetch_breach_rows(session: Session) -> dict[str, list[dict[str, Any]]]:
    """primitive_id → list of breach_matrix rows (SELECT-only on the VIEW).

    Queried via raw SQL text because ``breach_matrix`` is a VIEW with no ORM model.
    """
    from sqlalchemy import text

    sql = text(
        "SELECT primitive_id, deployment_config_id, n_trials, "
        "full_breach_rate, any_breach_rate "
        "FROM breach_matrix"
    )
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in session.execute(sql).mappings():
        out[row["primitive_id"]].append(dict(row))
    return out


def build_grammar_analysis_dataset(
    session: Session,
    *,
    breach_threshold: float = 0.0,
    canonical_only: bool = True,
    include_synthesized: bool = False,
) -> list[PrimitiveRecord]:
    """One :class:`PrimitiveRecord` per primitive, joined to ``breach_matrix``.

    By default keeps canonical, non-synthesized primitives only. ``breached`` is True iff
    *any* :class:`TargetOutcome` breached. Primitives absent from ``breach_matrix`` are
    KEPT with ``has_breach_data=False``, ``breached=False``, ``breach_rate=0.0``,
    ``targets=[]`` — the analysis engineers filter on ``has_breach_data``.

    SELECT-only; never writes.
    """
    target_meta = _fetch_target_meta(session)
    breach_by_prim = _fetch_breach_rows(session)

    stmt = select(
        AttackPrimitiveORM.primitive_id,
        AttackPrimitiveORM.family,
        AttackPrimitiveORM.secondary_families,
        AttackPrimitiveORM.payload_slots,
        AttackPrimitiveORM.requires_multi_turn,
        AttackPrimitiveORM.vector,
    )
    if canonical_only:
        stmt = stmt.where(AttackPrimitiveORM.canonical.is_(True))
    if not include_synthesized:
        stmt = stmt.where(AttackPrimitiveORM.synthesized.is_(False))

    records: list[PrimitiveRecord] = []
    for pid, family, secondary, slots, multi_turn, vector in session.execute(stmt):
        records.append(
            aggregate_primitive(
                primitive_id=pid,
                family=_enum_value(family),
                secondary_families=list(secondary or []),
                payload_slots=dict(slots or {}),
                requires_multi_turn=bool(multi_turn),
                vector=_enum_value(vector),
                breach_rows=breach_by_prim.get(pid, []),
                target_meta=target_meta,
                breach_threshold=breach_threshold,
            )
        )

    records.sort(key=lambda r: r.primitive_id)
    return records


def dataset_summary(records: list[PrimitiveRecord]) -> dict:
    """Header stats for the report: counts + per-family breakdown.

    ``breach_base_rate`` is computed over records WITH breach data (the analyzable
    denominator) — a primitive never reproduced can't be a breach or a non-breach.
    """
    n_total = len(records)
    with_data = [r for r in records if r.has_breach_data]
    n_with_breach_data = len(with_data)
    n_breached = sum(1 for r in with_data if r.breached)
    breach_base_rate = (n_breached / n_with_breach_data) if n_with_breach_data else 0.0

    family_counts: dict[str, int] = defaultdict(int)
    family_breached: dict[str, int] = defaultdict(int)
    for r in records:
        family_counts[r.family] += 1
        if r.has_breach_data and r.breached:
            family_breached[r.family] += 1

    return {
        "n_total": n_total,
        "n_with_breach_data": n_with_breach_data,
        "n_breached": n_breached,
        "breach_base_rate": breach_base_rate,
        "family_counts": dict(family_counts),
        "family_breached": dict(family_breached),
    }
