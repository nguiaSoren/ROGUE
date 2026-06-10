"""SkillPool ingest / dedup-cluster / scoped-retrieve / fixture-load (Section B)."""

from __future__ import annotations

from rogue.db.models import Skill, SkillSourceKind, SkillStatus
from rogue.memory.pool import (
    DEFAULT_FIXTURE_PATH,
    InMemorySkillStore,
    SkillPool,
)

_ORG = "org-a"
_COHORT = "team-a"
_TD = "domain-a"


def _pool(embed_fn) -> tuple[SkillPool, InMemorySkillStore]:
    store = InMemorySkillStore()
    return SkillPool(store=store, embed_fn=embed_fn), store


def test_ingest_creates_a_candidate_row(embed_fn):
    pool, store = _pool(embed_fn)
    skill = pool.ingest_candidate(
        "write idempotent migrations for postgres",
        org_id=_ORG,
        cohort_id=_COHORT,
        trust_domain=_TD,
        source_kind="correction",
    )
    assert isinstance(skill, Skill)
    assert skill.status is SkillStatus.CANDIDATE
    assert skill.source_kind is SkillSourceKind.CORRECTION
    assert skill.org_id == _ORG and skill.cohort_id == _COHORT and skill.trust_domain == _TD
    assert skill.embedding is not None
    assert len(store.skills) == 1


def test_near_duplicate_clusters_no_second_active_row(embed_fn):
    """An ingest near an ACTIVE skill clusters onto it — no second active row."""
    pool, store = _pool(embed_fn)
    md = "validate user input before the database write to avoid injection"
    # Seed an ACTIVE skill (the gate flips to active; here we plant one directly).
    active = pool.ingest_candidate(
        md, org_id=_ORG, cohort_id=_COHORT, trust_domain=_TD, source_kind="distilled"
    )
    active.status = SkillStatus.ACTIVE

    # Ingest the identical text again → must cluster onto the existing active skill.
    clustered = pool.ingest_candidate(
        md, org_id=_ORG, cohort_id=_COHORT, trust_domain=_TD, source_kind="distilled"
    )
    assert clustered.skill_id == active.skill_id
    active_rows = [s for s in store.skills if s.status is SkillStatus.ACTIVE]
    assert len(active_rows) == 1, "near-duplicate must not create a 2nd active row"
    assert len(store.skills) == 1


def test_candidate_does_not_dedup_against_candidate(embed_fn):
    """Dedup only fires against ACTIVE skills — two candidates of same text coexist."""
    pool, store = _pool(embed_fn)
    md = "always pin dependency versions in the lockfile"
    a = pool.ingest_candidate(md, org_id=_ORG, cohort_id=_COHORT, trust_domain=_TD, source_kind="correction")
    b = pool.ingest_candidate(md, org_id=_ORG, cohort_id=_COHORT, trust_domain=_TD, source_kind="correction")
    assert a.skill_id != b.skill_id
    assert len([s for s in store.skills if s.status is SkillStatus.CANDIDATE]) == 2


def test_retrieve_returns_active_and_in_cohort_only(embed_fn):
    pool, store = _pool(embed_fn)
    # An ACTIVE in-cohort skill (should be returned).
    a = pool.ingest_candidate(
        "rotate api keys on a schedule", org_id=_ORG, cohort_id=_COHORT, trust_domain=_TD, source_kind="correction"
    )
    a.status = SkillStatus.ACTIVE
    # A CANDIDATE in-cohort skill (active-only → excluded).
    pool.ingest_candidate(
        "use a connection pool for the database", org_id=_ORG, cohort_id=_COHORT, trust_domain=_TD, source_kind="correction"
    )
    # An ACTIVE but OUT-OF-COHORT skill (scope → excluded).
    other = pool.ingest_candidate(
        "rotate api keys on a schedule too", org_id=_ORG, cohort_id="team-b", trust_domain="domain-b", source_kind="correction"
    )
    other.status = SkillStatus.ACTIVE

    got = pool.retrieve(_COHORT, "key rotation", k=10, org_id=_ORG, trust_domain=_TD)
    ids = {s.skill_id for s in got}
    assert a.skill_id in ids
    assert other.skill_id not in ids
    assert all(s.status is SkillStatus.ACTIVE for s in got)
    assert all(s.cohort_id == _COHORT and s.trust_domain == _TD for s in got)


def test_retrieve_respects_k(embed_fn):
    pool, _ = _pool(embed_fn)
    for i in range(5):
        s = pool.ingest_candidate(
            f"distinct skill body number {i} alpha beta gamma",
            org_id=_ORG, cohort_id=_COHORT, trust_domain=_TD, source_kind="trajectory",
        )
        s.status = SkillStatus.ACTIVE
    got = pool.retrieve(_COHORT, "skill body", k=3, org_id=_ORG, trust_domain=_TD)
    assert len(got) == 3


def test_load_fixture_loads_all_55(embed_fn):
    pool, store = _pool(embed_fn)
    loaded = pool.load_fixture(org_id=_ORG, cohort_id=_COHORT, trust_domain=_TD)
    assert len(loaded) == 55
    # Every fixture skill is a candidate scoped to the requested cohort/domain.
    assert all(s.status is SkillStatus.CANDIDATE for s in store.skills)
    assert all(s.cohort_id == _COHORT and s.trust_domain == _TD for s in store.skills)
    # Default fixture path points at the 55-skill pool fixture.
    assert DEFAULT_FIXTURE_PATH.name == "skill_pool.json"
