"""Calibration adapters — bridge a real :class:`JudgeAgent` into the
synchronous ``judge_fn`` seam that :func:`judge_calibration.calibrate` expects.

``calibrate(cases, judge_fn)`` is deliberately decoupled from the judge: it
takes any ``Callable[[CalibrationCase], JudgeVerdict]``. Day-0 tests pass a
deterministic stub. This module supplies the *production* wiring promised in
``judge_calibration``'s docstring — the adapter that, for each hand-labeled
case, reconstructs the minimal :class:`RenderedAttack` + loads the source
:class:`AttackPrimitive`, runs the live judge, and unwraps
``JudgeResult.verdict``.

Two layers, separated so the core is testable with zero I/O:

* :func:`make_judge_fn` — pure dependency injection. Given a ``judge_sync_fn``
  (the grading call) and a ``primitive_loader`` (primitive_id → AttackPrimitive),
  returns a ``judge_fn``. No DB, no network — unit-tested with stubs.

* :func:`db_primitive_loader` / :func:`make_db_judge_fn` — the concrete
  live-DB wiring. The loader queries ``AttackPrimitiveORM`` by id and projects
  it to the Pydantic wire type. Only exercised by the paid calibration runs
  (Workstreams A3/B/C); requires Docker/Neon up.

Design choice (per the build plan): primitives are loaded from the **live DB**
at calibration time, not snapshotted into the fixture, so the rubric scores
against the real title / family / vector / goal of each primitive.

Spec: ROGUE_PLAN.md §10.2 + the judge-calibration plan (Phase 0, item 0c).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from rogue.reproduce.instantiator import RenderedAttack
from rogue.reproduce.judge_calibration import CalibrationCase, JudgeFn
from rogue.schemas import AttackPrimitive, JudgeVerdict

if TYPE_CHECKING:  # avoid importing heavy reproduce/db machinery at module load
    from rogue.reproduce.judge import JudgeResult
    from sqlalchemy.orm import Session


# A grading call: (rendered, model_response, primitive) -> JudgeResult.
# Matches the signature of ``JudgeAgent.judge_sync`` exactly so the bound
# method can be passed directly.
JudgeSyncFn = Callable[[RenderedAttack, str, AttackPrimitive], "JudgeResult"]

# primitive_id -> the source AttackPrimitive (Pydantic wire type).
PrimitiveLoader = Callable[[str], AttackPrimitive]

# The deployment_config_id we stamp on the reconstructed RenderedAttack. The
# judge never reads it (it scores against the attacker's goal, not the
# defender's config — see JudgeAgent._build_user_message), but RenderedAttack
# requires the field, so we use a sentinel that is obviously not a real config.
_CALIBRATION_CONFIG_ID = "calibration"


def _case_to_rendered(case: CalibrationCase) -> RenderedAttack:
    """Reconstruct the minimal single-turn :class:`RenderedAttack` the judge
    needs from a hand-labeled case.

    The judge only reads the *user-turn* contents of ``rendered.messages``
    (``JudgeAgent._build_user_message`` joins user turns and ignores the
    system prompt), so a one-message render carrying the stored payload
    excerpt reproduces exactly what the judge would have scored. Multi-turn
    primitives are flattened to their excerpt here — the calibration fixture
    stores a single ``rendered_payload_excerpt`` string by design.
    """
    return RenderedAttack(
        messages=[{"role": "user", "content": case.rendered_payload_excerpt}],
        is_multi_turn=False,
        resolved_slots={},
        primitive_id=case.primitive_id,
        deployment_config_id=_CALIBRATION_CONFIG_ID,
    )


def make_judge_fn(
    judge_sync_fn: JudgeSyncFn,
    primitive_loader: PrimitiveLoader,
) -> JudgeFn:
    """Build a ``judge_fn`` for :func:`judge_calibration.calibrate` from its
    two dependencies.

    Pure DI — no I/O of its own. ``judge_sync_fn`` is typically
    ``JudgeAgent(...).judge_sync``; ``primitive_loader`` is typically
    :func:`db_primitive_loader`. Both are injected so the returned closure can
    be exercised in unit tests with deterministic stubs.
    """

    def judge_fn(case: CalibrationCase) -> JudgeVerdict:
        primitive = primitive_loader(case.primitive_id)
        rendered = _case_to_rendered(case)
        result = judge_sync_fn(rendered, case.model_response, primitive)
        return result.verdict

    return judge_fn


def db_primitive_loader(session: "Session") -> PrimitiveLoader:
    """Return a :data:`PrimitiveLoader` backed by the live ``attack_primitives``
    table.

    Reuses the canonical ORM→Pydantic projection already maintained for the
    reproduction layer (``scripts.reproduce.reproduce_once._orm_to_pydantic_primitive``)
    so enum coercion and JSON-column defaults stay in one place. The import is
    lazy: the offline-testable :func:`make_judge_fn` core never triggers it,
    and only the paid live-DB runs pay the import cost.
    """
    from rogue.db.models import AttackPrimitive as AttackPrimitiveORM
    from scripts.reproduce.reproduce_once import _orm_to_pydantic_primitive

    def load(primitive_id: str) -> AttackPrimitive:
        orm = session.get(AttackPrimitiveORM, primitive_id)
        if orm is None:
            raise LookupError(
                f"primitive {primitive_id!r} referenced by a calibration case "
                "is not in the live DB — cannot reconstruct it for the judge. "
                "Re-sample the calibration set against the current DB."
            )
        return _orm_to_pydantic_primitive(orm)

    return load


def make_db_judge_fn(judge: object, session: "Session") -> JudgeFn:
    """Convenience: wire a live :class:`JudgeAgent` + DB ``session`` straight
    into a ``judge_fn``.

    ``judge`` is a :class:`rogue.reproduce.judge.JudgeAgent` (typed loosely to
    avoid importing the heavy module at load time). Equivalent to
    ``make_judge_fn(judge.judge_sync, db_primitive_loader(session))``.
    """
    return make_judge_fn(judge.judge_sync, db_primitive_loader(session))
