"""Surface 2 human-decider harness — fire a gated case at a reviewer, capture the decision.

This is the human analogue of Surface 1's ``target_panel.run_attack``: step 1 (fire an
input — a ``GatedCase``) + step 2 (capture the decision — a ``GatedDecision``), pointed at
a *human* instead of a model.

A reviewer is "just another decider behind an interface" (the adapter philosophy, ADR-0004):
``HumanDecider.decide(case) -> GatedDecision`` is the same shape as a model target's
"present input, get a disposition". But a human answers *synchronously over a session*, not
through a provider SDK, so this is deliberately NOT a ``core.TargetAdapter`` — ADR-0004's
"no provider types above ``adapters/``" boundary is about provider SDKs and does not apply to
a human. The right shape is a thin **record-and-resume** ``ReviewSession``: assign an
un-decided case to a reviewer, let them answer over a session, record the decision, mark it
decided.

Two seams, one interface:

  * ``StubDecider`` — the OFFLINE / test seam. A decision *policy* (a dict ``{case_id: pole}``
    or a callable ``(GatedCase) -> pole``) answers instantly, so the whole harness + scorer
    run with no real human in the loop.
  * the durable path — ``ReviewSession`` backed by an injectable store. The default
    ``InMemorySessionStore`` keeps the scaffold unit-testable offline; the Postgres-backed
    ``PostgresSessionStore`` REUSES the platform queue's ``SELECT … FOR UPDATE SKIP LOCKED``
    pattern (``platform/queue.py``) to hand out un-decided cases to concurrent reviewers
    without ever assigning the same case twice, and attributes the decision to a real
    ``tenancy.Principal`` in a real org. The heavy lifting is the queue we reuse, not new logic.

Engagement ≠ breach: ``deliberation_notes`` and ``decision_latency_s`` are *engagement*
signals captured on the ``GatedDecision`` for the record; they are never inputs to the
disposition (see ``disposition_judge``). A reviewer who hesitated did not breach.
"""

from __future__ import annotations

import abc
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from rogue.oversight.case_corpus import GatedCase, GatedDecision
from rogue.platform.tenancy import Principal

__all__ = [
    "HumanDecider",
    "StubDecider",
    "ReviewSession",
    "SessionStore",
    "InMemorySessionStore",
    "PostgresSessionStore",
    "AssignedCase",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(18)}"


# --------------------------------------------------------------------------------------------------
# The decider interface + the offline stub
# --------------------------------------------------------------------------------------------------


class HumanDecider(abc.ABC):
    """A target that yields a ``GatedDecision`` for a presented ``GatedCase``.

    The reviewer-behind-an-interface (ADR-0004). Implementations capture a decision plus the
    engagement signals (notes, latency) and stamp it with the answering reviewer.
    """

    @abc.abstractmethod
    def decide(self, case: GatedCase, *, reviewer: str) -> GatedDecision:
        """Present ``case`` to the decider and capture a ``GatedDecision`` for ``reviewer``."""
        raise NotImplementedError


# A decision policy is either a static map case_id -> pole, or a callable case -> pole.
DecisionPolicy = dict[str, str] | Callable[[GatedCase], str]


class StubDecider(HumanDecider):
    """The OFFLINE / test seam — a deterministic decider driven by a fixed policy.

    Lets the full harness + scorer run with no real human. ``policy`` is either:

      * a dict ``{case_id: "APPROVE" | "DENY"}`` — looked up by case_id; or
      * a callable ``(GatedCase) -> "APPROVE" | "DENY"`` — computed per case.

    A case absent from a dict policy (or a pole the policy returns that is not APPROVE/DENY)
    raises loudly rather than silently defaulting — a stub that can't answer a case is a test
    wiring bug, not a disposition. ``latency_s`` and ``notes`` set the engagement signals
    recorded on the decision (they never affect the disposition; engagement ≠ breach).
    """

    def __init__(
        self,
        policy: DecisionPolicy,
        *,
        latency_s: float | None = None,
        notes: str | None = None,
    ) -> None:
        self._policy = policy
        self._latency_s = latency_s
        self._notes = notes

    def decide(self, case: GatedCase, *, reviewer: str) -> GatedDecision:
        if callable(self._policy):
            decision = self._policy(case)
        else:
            if case.case_id not in self._policy:
                raise KeyError(
                    f"StubDecider policy has no entry for case_id {case.case_id!r}"
                )
            decision = self._policy[case.case_id]
        if decision not in ("APPROVE", "DENY"):
            raise ValueError(
                f"StubDecider policy returned {decision!r} for case {case.case_id!r}; "
                "must be 'APPROVE' or 'DENY'"
            )
        return GatedDecision(
            case_id=case.case_id,
            reviewer=reviewer,
            decision=decision,  # type: ignore[arg-type]
            deliberation_notes=self._notes,
            decision_latency_s=self._latency_s,
            decided_at=_now(),
        )


# --------------------------------------------------------------------------------------------------
# Record-and-resume: the ReviewSession scaffold + its pluggable store
# --------------------------------------------------------------------------------------------------


class AssignedCase:
    """A case handed to a reviewer for a session — the in-flight unit of the harness.

    Thin value object (not a Pydantic model — it is internal scaffold state, not a wire shape):
    the assigned ``case``, the ``session_id`` the decision will reference, and the assigned-at
    stamp. ``org_id`` / ``reviewer`` are the tenancy attribution.
    """

    __slots__ = ("session_id", "case", "org_id", "reviewer", "assigned_at")

    def __init__(
        self,
        *,
        session_id: str,
        case: GatedCase,
        org_id: str,
        reviewer: str,
        assigned_at: datetime,
    ) -> None:
        self.session_id = session_id
        self.case = case
        self.org_id = org_id
        self.reviewer = reviewer
        self.assigned_at = assigned_at


class SessionStore(Protocol):
    """The persistence seam ``ReviewSession`` records through.

    Two impls: ``InMemorySessionStore`` (offline/test) and ``PostgresSessionStore`` (durable,
    SKIP-LOCKED hand-out). Keeping this a Protocol is what makes the harness unit-testable with
    no DB.
    """

    def assign_next(self, *, org_id: str, reviewer: str) -> AssignedCase | None:
        """Hand out the next un-decided case to ``reviewer`` in ``org_id`` (None if none left)."""
        ...

    def record(self, assigned: AssignedCase, decision: GatedDecision) -> None:
        """Persist ``decision`` for ``assigned`` and mark the session decided."""
        ...


class InMemorySessionStore:
    """Offline session store — an injectable, single-process substrate for tests.

    Seeded with the pool of cases to review; ``assign_next`` pops the next undecided one and
    creates a session, ``record`` files the decision and marks the session decided. No locking
    semantics (single-threaded) — it exercises the assign→decide state machine, the way the
    platform's in-memory queue mirrors its Postgres sibling.
    """

    def __init__(self, cases: list[GatedCase]) -> None:
        self._pending: list[GatedCase] = list(cases)
        self.sessions: dict[str, AssignedCase] = {}
        self.decisions: list[GatedDecision] = []

    def assign_next(self, *, org_id: str, reviewer: str) -> AssignedCase | None:
        if not self._pending:
            return None
        case = self._pending.pop(0)
        assigned = AssignedCase(
            session_id=_new_id("rs"),
            case=case,
            org_id=org_id,
            reviewer=reviewer,
            assigned_at=_now(),
        )
        self.sessions[assigned.session_id] = assigned
        return assigned

    def record(self, assigned: AssignedCase, decision: GatedDecision) -> None:
        if assigned.session_id not in self.sessions:
            raise KeyError(f"unknown session {assigned.session_id!r}")
        self.decisions.append(decision)


class PostgresSessionStore:
    """Durable session store — REUSES the platform queue's SKIP-LOCKED hand-out pattern.

    ``assign_next`` claims the next ``gated_cases`` row that has no ``review_sessions`` row for
    this org yet, using ``SELECT … FOR UPDATE SKIP LOCKED`` (the same Postgres-only concurrency
    guard as ``platform/queue.py``) so N concurrent reviewers never get the same case. The
    claim writes a ``review_sessions`` row (status ``assigned``); ``record`` writes the
    ``gated_decisions`` row and flips the session to ``decided``. Every write carries
    ``principal.org_id`` for tenant isolation (ADR-0006). Thin: the locking is reused, only the
    "next undecided case for this org" predicate is new.

    ``session_factory`` is a SQLAlchemy ``sessionmaker`` (or any zero-arg callable returning a
    ``Session`` usable as a context manager), exactly as ``platform/queue.py`` takes it.
    """

    def __init__(
        self, session_factory: Callable[[], Session], principal: Principal
    ) -> None:
        self._session_factory = session_factory
        self._principal = principal

    def assign_next(self, *, org_id: str, reviewer: str) -> AssignedCase | None:
        # ORM imported lazily so importing this module needs no DB/driver (mirrors tenancy.py).
        from rogue.platform.models import GatedCase as GatedCaseORM
        from rogue.platform.models import ReviewSession as ReviewSessionORM

        now = _now()
        with self._session_factory() as session:
            # Claim the next corpus case with no review_sessions row for this org. FOR UPDATE
            # SKIP LOCKED makes this safe for N concurrent reviewers on Postgres; SQLite ignores
            # the clause (single-threaded tests use the in-memory store instead).
            assigned_subq = (
                select(ReviewSessionORM.case_id)
                .where(ReviewSessionORM.org_id == org_id)
                .scalar_subquery()
            )
            stmt = (
                select(GatedCaseORM)
                .where(GatedCaseORM.case_id.not_in(assigned_subq))
                .order_by(GatedCaseORM.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = session.execute(stmt).scalar_one_or_none()
            if row is None:
                return None
            session_id = _new_id("rs")
            session.add(
                ReviewSessionORM(
                    session_id=session_id,
                    org_id=org_id,
                    reviewer_user_id=reviewer,
                    case_id=row.case_id,
                    status="assigned",
                    assigned_at=now,
                    decided_at=None,
                )
            )
            assigned = AssignedCase(
                session_id=session_id,
                case=GatedCase.from_dict(
                    {
                        "case_id": row.case_id,
                        "case_class": row.case_class,
                        "facts": row.facts,
                        "designed_label": row.designed_label,
                        "designed_rationale": row.designed_rationale,
                        "label_provenance": row.label_provenance,
                        "source_refs": row.source_refs,
                    }
                ),
                org_id=org_id,
                reviewer=reviewer,
                assigned_at=now,
            )
            session.commit()
        return assigned

    def record(self, assigned: AssignedCase, decision: GatedDecision) -> None:
        from rogue.platform.models import GatedDecision as GatedDecisionORM
        from rogue.platform.models import ReviewSession as ReviewSessionORM

        now = _now()
        with self._session_factory() as session:
            review = session.get(ReviewSessionORM, assigned.session_id)
            if review is None:
                raise KeyError(f"unknown review session {assigned.session_id!r}")
            review.status = "decided"
            review.decided_at = now
            session.add(
                GatedDecisionORM(
                    decision_id=_new_id("gd"),
                    org_id=assigned.org_id,
                    session_id=assigned.session_id,
                    case_id=decision.case_id,
                    reviewer_user_id=decision.reviewer,
                    decision=decision.decision,
                    deliberation_notes=decision.deliberation_notes,
                    decision_latency_s=decision.decision_latency_s,
                    snapshot_ref=None,
                    created_at=now,
                )
            )
            session.commit()


class ReviewSession:
    """Record-and-resume scaffold: assign an un-decided case, capture a decision, mark decided.

    Thin orchestration over a ``SessionStore`` + a ``HumanDecider``. ``run_one`` pulls the next
    case for ``reviewer`` (in ``org_id``), fires it at the decider, and records the resulting
    ``GatedDecision`` — returning it, or None when the pool is drained. ``run_all`` loops to
    exhaustion. The durable behavior (SKIP-LOCKED hand-out, tenant scoping) lives entirely in
    the store; this class adds no DB logic of its own.
    """

    def __init__(
        self,
        store: SessionStore,
        decider: HumanDecider,
        *,
        org_id: str,
        reviewer: str,
    ) -> None:
        self._store = store
        self._decider = decider
        self._org_id = org_id
        self._reviewer = reviewer

    def run_one(self) -> GatedDecision | None:
        """Assign the next case, capture and record one decision; None if the pool is empty."""
        assigned = self._store.assign_next(org_id=self._org_id, reviewer=self._reviewer)
        if assigned is None:
            return None
        decision = self._decider.decide(assigned.case, reviewer=self._reviewer)
        self._store.record(assigned, decision)
        return decision

    def run_all(self) -> list[GatedDecision]:
        """Drain the pool: decide every assignable case, returning all captured decisions."""
        decisions: list[GatedDecision] = []
        while (d := self.run_one()) is not None:
            decisions.append(d)
        return decisions
