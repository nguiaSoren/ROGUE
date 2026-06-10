"""Cohort + trust-boundary scoping for the assured skill pool (Surface 3, Sections B + G).

Framed as **leakage-containment, not personalization** (spec
``docs/v2/surface3_memory_spec.md`` §2.4, build plan §8 Section G): a skill is
retrievable/promotable ONLY within the ``cohort_id`` / ``trust_domain`` it was
ingested under. A skill verified net-positive for team A must never cross into
team B — that crossing is leakage of A's content into B's domain, so cross-
``trust_domain`` access is **denied**, not silently filtered.

This module REUSES ``rogue.platform.tenancy`` for org plumbing (the ``Principal``
is the org identity; ``cohort_id`` / ``trust_domain`` narrow *within* an org).
It is the single place isolation is decided: ``scope_query`` is the one helper
the pool / promotion / leakage paths call, so trust-boundary enforcement is one
decision, not N (mirroring ``tenancy.query_scope``).

Built out (Section G is NOT a dormant no-op): given skills across ≥2 trust
domains, a request scoped to domain X must never return or promote a domain-Y
skill, and a *direct* cross-domain access raises ``TrustBoundaryViolation``.
Single-trust-domain is the special case — when every skill is in one domain the
scope filter is a tautology and nothing is excluded (build-seq Phase 4: "a
single trust domain doesn't trigger the hardest gates").

Import-safe: no DB, no credentials at import.
"""

from __future__ import annotations

from dataclasses import dataclass

from rogue.platform.tenancy import Principal

__all__ = [
    "TrustBoundaryViolation",
    "CohortScope",
    "resolve_scope",
    "scope_query",
    "enforce_scope",
]


class TrustBoundaryViolation(Exception):
    """Raised when an access crosses a trust boundary it is not scoped to.

    The skill pool's containment invariant (Section G): a skill belongs to
    exactly one ``(org_id, cohort_id, trust_domain)`` and may only be
    read/promoted from within that triple. An attempted cross-``trust_domain``
    (or cross-``org``/cohort) read or promote is leakage to the skill's origin
    domain and is denied here rather than served.
    """

    def __init__(
        self,
        *,
        requested_org: str,
        requested_cohort: str,
        requested_trust_domain: str,
        skill_org: str | None = None,
        skill_cohort: str | None = None,
        skill_trust_domain: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.requested_org = requested_org
        self.requested_cohort = requested_cohort
        self.requested_trust_domain = requested_trust_domain
        self.skill_org = skill_org
        self.skill_cohort = skill_cohort
        self.skill_trust_domain = skill_trust_domain
        msg = detail or (
            "trust-boundary violation: request scoped to "
            f"org={requested_org!r} cohort={requested_cohort!r} "
            f"trust_domain={requested_trust_domain!r} may not access skill in "
            f"org={skill_org!r} cohort={skill_cohort!r} "
            f"trust_domain={skill_trust_domain!r}"
        )
        super().__init__(msg)


@dataclass(frozen=True)
class CohortScope:
    """A resolved ``(org_id, cohort_id, trust_domain)`` access scope.

    The unit every pool/promotion/leakage path is scoped to. ``org_id`` comes
    from the authenticated ``Principal`` (tenancy); ``cohort_id`` /
    ``trust_domain`` narrow within the org. ``contains`` answers the central
    isolation question: is a skill carrying ``(org, cohort, trust_domain)``
    inside this scope?
    """

    org_id: str
    cohort_id: str
    trust_domain: str

    def contains(
        self, *, org_id: str, cohort_id: str, trust_domain: str
    ) -> bool:
        """True iff a skill at ``(org_id, cohort_id, trust_domain)`` is in-scope.

        All three must match — the trust_domain match is the trust-boundary
        check (Section G), the org/cohort match is the tenancy/cohort scope.
        """
        return (
            self.org_id == org_id
            and self.cohort_id == cohort_id
            and self.trust_domain == trust_domain
        )


def resolve_scope(
    *,
    cohort_id: str,
    trust_domain: str,
    org_id: str | None = None,
    principal: Principal | None = None,
) -> CohortScope:
    """Resolve an access ``CohortScope`` from an org identity + cohort/trust-domain.

    ``org_id`` is taken from ``principal`` (REUSE ``tenancy.Principal`` — the org
    is the outer tenant boundary) or passed explicitly; exactly one of the two
    must be supplied. ``cohort_id`` / ``trust_domain`` narrow within the org.

    This does not touch the DB — it is the pure resolution step the pool calls
    before any scoped query.
    """
    if principal is not None:
        resolved_org = principal.org_id
        if org_id is not None and org_id != resolved_org:
            raise TrustBoundaryViolation(
                requested_org=org_id,
                requested_cohort=cohort_id,
                requested_trust_domain=trust_domain,
                skill_org=resolved_org,
                detail=(
                    f"org_id={org_id!r} does not match principal org "
                    f"{resolved_org!r}"
                ),
            )
    elif org_id is not None:
        resolved_org = org_id
    else:
        raise ValueError("resolve_scope: pass either org_id or principal")
    return CohortScope(
        org_id=resolved_org, cohort_id=cohort_id, trust_domain=trust_domain
    )


def scope_query(stmt, scope: CohortScope):
    """Apply ``scope`` to a ``select(Skill)`` — the one central isolation filter.

    Appends ``WHERE org_id=:org AND cohort_id=:cohort AND trust_domain=:td`` to
    the statement, using the first FROM entity (mirrors ``tenancy.query_scope``).
    Every pool/promotion/leakage read goes through here so a request scoped to
    trust_domain X structurally cannot return a domain-Y skill — isolation is one
    decision, enforced in the query, not a post-filter that can be forgotten.

    The target must expose ``org_id`` / ``cohort_id`` / ``trust_domain`` columns
    (the ``skills`` table does); a target that doesn't is a programming error.
    """
    entity = stmt.get_final_froms()[0]
    for col_name in ("org_id", "cohort_id", "trust_domain"):
        col = getattr(entity.c, col_name, None)
        if col is None:
            raise ValueError(
                f"scope_query: target has no {col_name} column — it is not "
                "cohort/trust-domain-scoped"
            )
    stmt = stmt.where(entity.c.org_id == scope.org_id)
    stmt = stmt.where(entity.c.cohort_id == scope.cohort_id)
    stmt = stmt.where(entity.c.trust_domain == scope.trust_domain)
    return stmt


def enforce_scope(scope: CohortScope, skill) -> None:
    """Assert a single ``skill`` object is inside ``scope`` or raise.

    The guard for the *direct-access* path (e.g. promote/verify a skill fetched
    by id, where ``scope_query``'s WHERE-clause can't run). Raises
    ``TrustBoundaryViolation`` on any org / cohort / trust_domain mismatch —
    this is the hard denial that makes Section G real rather than a no-op.

    ``skill`` may be a ``Skill`` ORM row or any object carrying ``org_id`` /
    ``cohort_id`` / ``trust_domain`` attributes (e.g. the in-memory store's
    record), so it works on both the Postgres and offline paths.
    """
    if not scope.contains(
        org_id=skill.org_id,
        cohort_id=skill.cohort_id,
        trust_domain=skill.trust_domain,
    ):
        raise TrustBoundaryViolation(
            requested_org=scope.org_id,
            requested_cohort=scope.cohort_id,
            requested_trust_domain=scope.trust_domain,
            skill_org=skill.org_id,
            skill_cohort=skill.cohort_id,
            skill_trust_domain=skill.trust_domain,
        )
