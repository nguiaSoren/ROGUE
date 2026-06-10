"""Trust-boundary isolation (Section G) — the hard cross-domain denial.

Adversarial: a team-b request must NEVER see/promote a team-a skill, and a direct
cross-domain access must raise — not silently filter to empty.
"""

from __future__ import annotations

import pytest

from rogue.db.models import SkillStatus
from rogue.memory.cohorts import (
    CohortScope,
    TrustBoundaryViolation,
    enforce_scope,
    resolve_scope,
)
from rogue.memory.pool import InMemorySkillStore, SkillPool
from rogue.platform.tenancy import Principal


def _two_domain_pool(embed_fn):
    store = InMemorySkillStore()
    pool = SkillPool(store=store, embed_fn=embed_fn)
    a = pool.ingest_candidate(
        "team-a private playbook for incident triage",
        org_id="org-1", cohort_id="team-a", trust_domain="domain-a", source_kind="distilled",
    )
    a.status = SkillStatus.ACTIVE
    b = pool.ingest_candidate(
        "team-b private playbook for deploy rollback",
        org_id="org-1", cohort_id="team-b", trust_domain="domain-b", source_kind="distilled",
    )
    b.status = SkillStatus.ACTIVE
    return pool, store, a, b


def test_team_b_retrieve_never_returns_team_a_skill(embed_fn):
    pool, _store, a, _b = _two_domain_pool(embed_fn)
    # Query team-b for the very text of the team-a skill — must still not cross over.
    got = pool.retrieve(
        "team-b", "incident triage playbook", k=10, org_id="org-1", trust_domain="domain-b"
    )
    ids = {s.skill_id for s in got}
    assert a.skill_id not in ids
    assert all(s.cohort_id == "team-b" and s.trust_domain == "domain-b" for s in got)


def test_direct_cross_domain_access_raises(embed_fn):
    _pool, _store, a, _b = _two_domain_pool(embed_fn)
    # A scope for team-b directly enforced against a team-a skill must DENY, not filter.
    scope_b = resolve_scope(org_id="org-1", cohort_id="team-b", trust_domain="domain-b")
    with pytest.raises(TrustBoundaryViolation):
        enforce_scope(scope_b, a)


def test_cross_org_access_raises(embed_fn):
    _pool, _store, a, _b = _two_domain_pool(embed_fn)
    scope_other_org = resolve_scope(org_id="org-2", cohort_id="team-a", trust_domain="domain-a")
    with pytest.raises(TrustBoundaryViolation):
        enforce_scope(scope_other_org, a)


def test_single_domain_is_in_scope(embed_fn):
    _pool, _store, a, _b = _two_domain_pool(embed_fn)
    # The matching scope must NOT raise — single-domain is the tautology case.
    scope_a = resolve_scope(org_id="org-1", cohort_id="team-a", trust_domain="domain-a")
    enforce_scope(scope_a, a)  # no exception
    assert scope_a.contains(org_id="org-1", cohort_id="team-a", trust_domain="domain-a")


def test_scope_contains_requires_all_three_to_match():
    scope = CohortScope(org_id="o", cohort_id="c", trust_domain="d")
    assert scope.contains(org_id="o", cohort_id="c", trust_domain="d")
    assert not scope.contains(org_id="o", cohort_id="c", trust_domain="OTHER")
    assert not scope.contains(org_id="o", cohort_id="OTHER", trust_domain="d")
    assert not scope.contains(org_id="OTHER", cohort_id="c", trust_domain="d")


def test_resolve_scope_principal_org_mismatch_raises():
    principal = Principal(org_id="org-1", role="owner", key_id="k1")
    # Passing a conflicting explicit org_id alongside the principal is a violation.
    with pytest.raises(TrustBoundaryViolation):
        resolve_scope(
            org_id="org-2", cohort_id="c", trust_domain="d", principal=principal
        )


def test_resolve_scope_requires_org_or_principal():
    with pytest.raises(ValueError):
        resolve_scope(cohort_id="c", trust_domain="d")
