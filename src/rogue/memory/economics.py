"""Verification compute economics — THE #1 feasibility risk (Surface 3, Section D).

These three filters are **survival requirements, not optimizations** (build 08 §5).
Naively verifying every candidate skill against every cohort distribution is a
combinatorial rollout bill (N candidates × M cohorts paid LLM rollouts) that makes
the whole surface economically non-viable. Built *with* the promotion gate
(``rogue.memory.promotion``), not after.

The three mitigations, cheapest-first (each prunes before the next):

1. **Cheap applicability pre-filter** (:func:`is_applicable`) — before any rollout,
   check the candidate's ``applicability_condition`` (the SoK ``C`` precondition)
   against the cohort's task profile. Pure dict comparison, no model. Skips a
   candidate that structurally cannot apply to a cohort. (Bias guard, build 08 §5
   risk: a too-aggressive filter silently skips a real regression — so the default
   on a *missing/empty* condition is **applicable**, never skip; a skill only opts
   *out* of a cohort by an explicit, unmet condition.)
2. **Cohort scoping** (REUSE ``cohorts.scope_query`` semantics via
   :func:`in_cohort_scope`) — verify net-effect *per cohort* and promote only where
   proven. A skill net-positive for cohort A may regress cohort B; scoping
   structurally solves it and prunes cross-cohort rollouts that would never be
   promoted anyway.
3. **Lazy gating** (:func:`should_verify`) — a per-skill retrieval-pressure counter;
   only skills retrieved often enough (≥ ``threshold``) trigger an expensive
   rollout. The long tail nobody retrieves costs ~nothing.

:func:`plan_verifications` applies all three → the pruned ``(skill, cohort)``
rollout set, and reports the reduction vs the naive N×M baseline
(:class:`VerificationPlan` — **the number IS the feasibility proof**, build 08 §5
EXIT GATE D).

**Ranking signals discipline (re-asserted here):** popularity is NOT a safety
signal and is NOT the lazy-gate signal either. *Retrieval pressure* gates *whether
we pay to verify* (an economics decision); it never feeds *ranking / admission* —
admission is the measured net-effect CI from the promotion gate. The two must not
be conflated: a frequently-retrieved skill still has to clear the net-effect gate,
and being popular never substitutes for being measured net-positive.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rogue.db.models import Skill

__all__ = [
    "DEFAULT_RETRIEVAL_THRESHOLD",
    "is_applicable",
    "in_cohort_scope",
    "should_verify",
    "VerificationPlan",
    "plan_verifications",
]

# A skill must be retrieved at least this many times before it earns an (expensive)
# rollout verification. Tunable per deployment; the long tail below it costs nothing.
DEFAULT_RETRIEVAL_THRESHOLD = 5

# Lazy gating gates COST, never RANKING. Retrieval pressure decides whether to pay
# for a rollout; it is NOT a safety/admission signal (popularity ≠ safety — build
# 08 §4 / SkillProbe). Admission is the measured net-effect CI, full stop.
assert DEFAULT_RETRIEVAL_THRESHOLD >= 1


# ----------------------------------------------------------------------------------
# Filter 1 — cheap applicability pre-filter (no model)
# ----------------------------------------------------------------------------------


def is_applicable(skill: Skill, cohort_profile: Mapping[str, Any]) -> bool:
    """True iff the candidate's ``applicability_condition`` (``C``) holds for a cohort.

    Cheap (pure dict comparison, NO model rollout). The condition is the SoK ``C``
    precondition stored on ``Skill.applicability_condition``; the ``cohort_profile``
    is that cohort's task profile (e.g. ``{"language": "python", "domain": "web",
    "frameworks": ["fastapi"]}``).

    Matching rules (conservative — bias toward *applicable* so the filter never
    silently skips a real regression, build 08 §5 risk):

    - **Empty / missing condition → applicable.** A skill with no declared
      precondition applies everywhere; it does not opt out of any cohort.
    - For each ``key: expected`` in the condition, the cohort profile must satisfy
      it; a key absent from the profile means the requirement is **unknown**, and
      unknown is treated as *applicable* (don't skip on missing profile data).
    - ``expected`` is a scalar → the profile value must equal it (or, if the profile
      value is a list, contain it).
    - ``expected`` is a list/tuple/set → it is a set of acceptable values; the
      profile value (scalar or list) must intersect it.

    Only an explicit, *present-and-unmet* requirement makes a skill inapplicable —
    that is the single case where we safely skip a rollout.
    """
    condition = skill.applicability_condition or {}
    if not condition:
        return True

    for key, expected in condition.items():
        if key not in cohort_profile:
            # Requirement we can't evaluate → don't skip (bias to applicable).
            continue
        actual = cohort_profile[key]
        if not _matches(expected, actual):
            return False
    return True


def _matches(expected: Any, actual: Any) -> bool:
    """Whether a single applicability requirement ``expected`` is met by ``actual``."""
    actual_set = set(actual) if isinstance(actual, (list, tuple, set)) else {actual}
    if isinstance(expected, (list, tuple, set)):
        return bool(set(expected) & actual_set)
    return expected in actual_set


# ----------------------------------------------------------------------------------
# Filter 2 — cohort scoping (REUSE cohorts scope semantics)
# ----------------------------------------------------------------------------------


def in_cohort_scope(skill: Skill, cohort_id: str, trust_domain: str | None = None) -> bool:
    """True iff ``skill`` belongs to ``cohort_id`` (and ``trust_domain`` if given).

    The Python-side mirror of ``cohorts.scope_query``'s WHERE clause: a skill is only
    verified/promoted *within its own cohort* (and trust_domain), never against every
    cohort's distribution. This is the structural fix for "net-positive for A,
    regresses B" — and it prunes every cross-cohort ``(skill, cohort)`` pair that
    could never be promoted anyway. (Full DB reads still go through
    ``cohorts.scope_query`` — this is the in-memory planning predicate.)
    """
    if skill.cohort_id != cohort_id:
        return False
    if trust_domain is not None and skill.trust_domain != trust_domain:
        return False
    return True


# ----------------------------------------------------------------------------------
# Filter 3 — lazy gating (retrieval-pressure counter)
# ----------------------------------------------------------------------------------


def should_verify(
    skill: Skill,
    retrieval_count: int,
    *,
    threshold: int = DEFAULT_RETRIEVAL_THRESHOLD,
) -> bool:
    """True iff ``skill`` has enough retrieval pressure to earn an expensive rollout.

    Lazy gating: only skills retrieved ``>= threshold`` times trigger a (paid)
    verification. The long tail nobody retrieves never pays for a rollout. This
    gates COST only — it is **not** a safety/ranking signal (a frequently-retrieved
    skill still has to clear the measured net-effect gate; popularity never admits a
    skill — build 08 §4).
    """
    return retrieval_count >= threshold


# ----------------------------------------------------------------------------------
# The planner — applies all three; quantifies the N×M reduction (EXIT GATE D)
# ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class VerificationPlan:
    """The pruned rollout set + the feasibility-proof numbers (build 08 §5 EXIT GATE D).

    ``pairs`` is the ``(skill, cohort_id)`` set that survived all three filters and
    will actually trigger a (paid) rollout. ``naive`` is the N×M baseline (every
    candidate × every cohort). ``reduction_factor`` is ``naive / planned`` (how many
    times fewer rollouts) — the number that proves the surface is economically
    viable. The per-filter ``*_pruned`` counts show where the matrix collapsed.
    """

    pairs: tuple[tuple[Skill, str], ...]
    naive: int
    planned: int
    pruned_inapplicable: int
    pruned_out_of_scope: int
    pruned_low_pressure: int

    @property
    def reduction_factor(self) -> float:
        """``naive / planned`` — how many times fewer rollouts than the N×M baseline."""
        return float(self.naive) / float(self.planned) if self.planned else float("inf")

    def summary(self) -> str:
        """One-line human summary for logs / EXIT GATE D."""
        rf = "inf" if self.planned == 0 else f"{self.reduction_factor:.1f}x"
        return (
            f"verification plan: {self.planned}/{self.naive} rollouts "
            f"({rf} reduction) — pruned: "
            f"{self.pruned_inapplicable} inapplicable, "
            f"{self.pruned_out_of_scope} out-of-scope, "
            f"{self.pruned_low_pressure} low-pressure"
        )


def plan_verifications(
    candidates: Sequence[Skill],
    cohorts: Sequence[str],
    retrieval_counts: Mapping[str, int],
    cohort_profiles: Mapping[str, Mapping[str, Any]],
    *,
    threshold: int = DEFAULT_RETRIEVAL_THRESHOLD,
) -> VerificationPlan:
    """Apply all three §D filters → the pruned ``(skill, cohort)`` rollout set.

    For every candidate × every cohort (the naive N×M baseline), keep the pair iff:

    1. **cohort scope** — the skill belongs to that cohort (:func:`in_cohort_scope`);
    2. **applicability** — its ``C`` precondition holds for the cohort's task profile
       (:func:`is_applicable`);
    3. **lazy gate** — the skill's retrieval pressure ≥ ``threshold``
       (:func:`should_verify`).

    Filters are applied scope → applicability → lazy-gate; each pair is attributed to
    the *first* filter that prunes it (so the per-filter counts partition the pruned
    set and ``planned + sum(pruned) == naive``).

    Args:
        candidates: the candidate skills (the "N").
        cohorts: the cohort ids to consider (the "M").
        retrieval_counts: ``skill_id -> retrieval count`` for the lazy gate (a skill
            absent from the map is treated as 0 retrievals → never verified).
        cohort_profiles: ``cohort_id -> task profile`` for the applicability filter
            (a cohort absent from the map → empty profile → applicability defaults to
            *applicable*, per :func:`is_applicable`'s bias-to-applicable rule).
        threshold: lazy-gate retrieval threshold.

    Returns:
        a :class:`VerificationPlan` carrying the surviving pairs + the N×M reduction.
    """
    naive = len(candidates) * len(cohorts)
    pairs: list[tuple[Skill, str]] = []
    pruned_inapplicable = 0
    pruned_out_of_scope = 0
    pruned_low_pressure = 0

    for skill in candidates:
        rc = retrieval_counts.get(skill.skill_id, 0)
        for cohort_id in cohorts:
            # 1. cohort scope (cheapest, prunes the most off-cohort pairs)
            if not in_cohort_scope(skill, cohort_id):
                pruned_out_of_scope += 1
                continue
            # 2. applicability pre-filter (cheap dict check, no model)
            if not is_applicable(skill, cohort_profiles.get(cohort_id, {})):
                pruned_inapplicable += 1
                continue
            # 3. lazy gate (retrieval pressure)
            if not should_verify(skill, rc, threshold=threshold):
                pruned_low_pressure += 1
                continue
            pairs.append((skill, cohort_id))

    return VerificationPlan(
        pairs=tuple(pairs),
        naive=naive,
        planned=len(pairs),
        pruned_inapplicable=pruned_inapplicable,
        pruned_out_of_scope=pruned_out_of_scope,
        pruned_low_pressure=pruned_low_pressure,
    )
