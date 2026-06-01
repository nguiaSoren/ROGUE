"""Strategy library — the single source the EscalationPlanner reads from (§10.9 Phase 3a).

ROGUE's attack *strategies* come from two places that must be interchangeable
(§10.9 risk-note 3):
  - **hand-written** — the ARMS seed library (`arms_strategies.ARMS_STRATEGIES`),
    static code authored from the ARMS paper;
  - **harvested** — `attack_strategies` rows produced by the §10.9 technique
    pipeline (`ExtractionAgent.extract_any` → `TechniqueSpec` → DB).

This module unifies both behind one flat ``dict[str, StrategyView]`` so the
planner doesn't care where a strategy came from. A harvested *text* or
*multi_turn* technique needs no new code — its `directive` is synthesized
deterministically from its principle + steps (no LLM call) and the planner can
drive it on the very next run.

`image`/`audio` techniques are NOT planner-drivable (they need a renderer, §10.9
Phase 3b) and are excluded from the library the planner sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from rogue.reproduce.arms_strategies import ARMS_STRATEGIES
from rogue.schemas import (
    AUTO_INTEGRABLE_MODALITIES,
    StrategyStatus,
    TechniqueSpec,
)

if TYPE_CHECKING:  # avoid a hard import cycle at module load
    from sqlalchemy.orm import Session

__all__ = [
    "StrategyView",
    "technique_to_directive",
    "arms_views",
    "load_strategy_library",
    "persist_technique",
    "planner_drivable_ids",
]

# The ARMS pattern whose strategies the EscalationPlanner can actually drive
# (crescendo / actor_attack / acronym). Mirrors arms_strategies.multi_turn_strategies().
_PLANNER_DRIVABLE_ARMS_PATTERN = "visual_multi_turn_escalation"


@dataclass(frozen=True)
class StrategyView:
    """A planner's-eye view of a strategy, agnostic to hand-written vs harvested.

    Carries exactly what `_build_planner_messages` needs: a display ``name``, the
    one-line ``principle``, the operational ``directive`` to inject, whether the
    planner can drive it, and ``origin`` (so the override header cites the ARMS
    paper for ARMS entries and stays neutral for harvested ones).
    """

    id: str
    name: str
    principle: str
    directive: str
    planner_drivable: bool
    origin: str  # "arms" | "harvested"

    @property
    def override_header(self) -> str:
        """The planner's strategy-override header line.

        ARMS entries reproduce the exact legacy string (so cached ARMS plans and
        their wording are byte-for-byte unchanged); harvested entries get a
        neutral header.
        """
        if self.origin == "arms":
            return f"ARMS STRATEGY OVERRIDE — {self.name} (arXiv 2510.02677):"
        return f"HARVESTED STRATEGY OVERRIDE — {self.name}:"


def technique_to_directive(spec: TechniqueSpec) -> Optional[str]:
    """Deterministically synthesize a planner directive from a text/multi_turn technique.

    No LLM call — the directive is an operational prompt fragment built from the
    technique's ``principle`` + ``steps`` (the same shape as the hand-written ARMS
    directives). Returns the technique's own ``directive`` if it already carries
    one; ``None`` for image/audio techniques (renderer methods — Phase 3b), which
    the planner cannot drive.
    """
    if spec.modality not in AUTO_INTEGRABLE_MODALITIES:
        return None
    if spec.directive:
        return spec.directive
    principle = spec.principle.strip().rstrip(".")
    parts = [f"{principle}." if principle else ""]
    steps = [s.strip().rstrip(".") for s in (spec.steps or []) if s.strip()]
    if steps:
        parts.append("Procedure: " + "; ".join(steps) + ".")
    directive = " ".join(p for p in parts if p).strip()
    return directive or None


def arms_views() -> dict[str, StrategyView]:
    """The hand-written ARMS strategies as `StrategyView`s."""
    return {
        s.id: StrategyView(
            id=s.id,
            name=s.name,
            principle=s.principle,
            directive=s.directive,
            planner_drivable=s.pattern == _PLANNER_DRIVABLE_ARMS_PATTERN,
            origin="arms",
        )
        for s in ARMS_STRATEGIES.values()
    }


def _view_from_row(row) -> StrategyView:  # row: rogue.db.models.AttackStrategy
    """Adapt a harvested ``attack_strategies`` row into a `StrategyView`."""
    directive = row.directive or ""
    return StrategyView(
        id=row.technique_id,
        name=row.name,
        principle=row.principle,
        directive=directive,
        planner_drivable=True,  # only text/multi_turn rows reach here (see loader)
        origin="harvested",
    )


def load_strategy_library(
    session: "Session | None" = None,
    *,
    statuses: tuple[StrategyStatus, ...] = (
        StrategyStatus.ACTIVE,
        StrategyStatus.CANDIDATE,
    ),
) -> dict[str, StrategyView]:
    """The union the planner reads from: ARMS seeds ∪ harvested techniques.

    Without a ``session`` (or when the table is empty/unreachable) this is just
    the ARMS seed library — the legacy behaviour. With a session, planner-drivable
    harvested techniques (``modality`` in {text, multi_turn}) whose ``status`` is
    in ``statuses`` are merged in.

    Default ``statuses`` includes ``candidate`` so a freshly-harvested technique is
    usable on the next run — it has to be *tried* before it can breach and graduate
    to ``active`` (Phase 4). Pass ``statuses=(ACTIVE,)`` to gate candidates behind a
    human review (§10.9 risk-note 2).
    """
    library = arms_views()
    if session is None:
        return library

    from rogue.db.models import AttackStrategy

    try:
        rows = (
            session.query(AttackStrategy)
            .filter(
                AttackStrategy.status.in_(statuses),
                AttackStrategy.modality.in_(tuple(AUTO_INTEGRABLE_MODALITIES)),
            )
            .all()
        )
    except Exception:  # pragma: no cover — a missing table must not break reproduce
        return library

    for row in rows:
        if not (row.directive and row.directive.strip()):
            # A planner-drivable row with no directive is unusable; skip it
            # rather than inject an empty override.
            continue
        library[row.technique_id] = _view_from_row(row)
    return library


def planner_drivable_ids(library: dict[str, StrategyView]) -> set[str]:
    """The subset of strategy ids the EscalationPlanner can drive."""
    return {sid for sid, view in library.items() if view.planner_drivable}


def persist_technique(
    session: "Session",
    spec: TechniqueSpec,
    *,
    synthesize_directive: bool = True,
):
    """Insert a harvested `TechniqueSpec` as an ``attack_strategies`` row.

    For text/multi_turn techniques, the planner directive is synthesized
    (deterministically) and stored so the technique is immediately planner-usable
    (§10.9 Phase 3a). Image/audio techniques are stored as-is (``status`` already
    ``needs_implementation`` from extraction) with no directive — their renderer is
    Phase 3b work. Returns the persisted ORM row.
    """
    from rogue.db.models import AttackStrategy

    directive = spec.directive
    if synthesize_directive and not directive:
        directive = technique_to_directive(spec)

    row = AttackStrategy(
        technique_id=spec.technique_id,
        name=spec.name,
        modality=spec.modality,
        principle=spec.principle,
        steps=list(spec.steps),
        params=dict(spec.params),
        example=spec.example,
        directive=directive,
        source_url=spec.source_url,
        status=spec.status,
        claimed_first_seen=spec.claimed_first_seen,
    )
    session.add(row)
    return row
