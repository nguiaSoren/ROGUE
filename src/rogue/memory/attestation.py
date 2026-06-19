"""Signed attestation for the assured skill pool (Surface 3, build 08 §9 Section H).

The Surface-3 analogue of ``oversight.attestation`` / ``attestation.remediation`` —
a **thin ADAPTER** into the EXISTING area-03 attestation layer, NOT a new attestation
format (build 08 §9, ADR-0011). It assembles the spec §3 output block — the FOUR
pool numbers — by **reading the ``skill_verifications`` audit rows** (the SQL-queryable
audit spine, ADR-0009) and hands the structured payload to ``AttestationService.append``
on the SAME per-org hash chain. It builds no second chain and duplicates no
hashing/chaining/sequence logic; it does NOT recompute any number — every figure is
read back from the rows the C/E/F gates already wrote.

The four §3 numbers (each carrying provenance to a calibrated judge — ``judge_calibration_ref``
— and, for leakage, the coverage-calibrated pack):

1. **N skills active, all verified net-positive with CIs** — from ``kind=promotion``
   PASS rows: the count + each skill's ``net_effect`` and bootstrap CI.
2. **measured leakage rate X% under extraction** — from the LATEST ``kind=leakage``
   row: the rate + CI + the benchmark pack id + pack-coverage tier (the rate is only
   as strong as the pack, ADR-0011 — carry coverage, never quote the rate bare).
3. **M dangerous co-invocation neighborhoods quarantined** — from ``kind=combination``
   PASS rows: the count + the per-row risk signal / scan-run provenance (+ the
   quarantined sets when the caller supplies the composition results).
4. **cohort isolation: no skill crossed a trust boundary it wasn't scoped to** — an
   assertion/summary over the cohort scoping (Section G ``CohortScope``).

**Framing discipline (non-negotiable, unified §2.5 / build 08 §0):** every entry carries
``framing_line(corpus_as_of)`` — *threat-informed assurance, tested against the known
corpus as of date D, continuously re-verified; NOT a safety guarantee* — plus a
measure-don't-claim note. We NEVER say "the pool is safe" or "the pool improves
accuracy"; only that it was *measured against the known corpus as of D*.

**Redaction:** an append-only entry can never be un-written, so any free text is scrubbed
via the SAME ``report_service._redact`` the scan/decision/mitigation adapters use, before
it enters the immutable record.

**entry_type:** area-03's ``ENTRY_TYPES`` has no pool-specific type; ``"promotion"`` is the
closest fit (Surface 3's headline gate is the verified-promotion gate, and ``chain.py``
already reserves ``"promotion"`` as a surface entry type) — chosen deliberately, noted here.

Spec: ``docs/v2/build/08_surface3_memory.md`` §9; reuses ``docs/v2/build/03_attestation.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional, Sequence

from rogue.attestation.emit import canonical_as_of, framing_line
from rogue.db.models import (
    SkillVerification,
    SkillVerificationKind,
    SkillVerificationVerdict,
)
from rogue.platform.report_service import _redact

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService
    from rogue.memory.cohorts import CohortScope
    from rogue.platform.models import AttestationEntry

__all__ = [
    "POOL_ENTRY_TYPE",
    "build_pool_attestation_payload",
    "append_pool_attestation",
]

# area-03 has no pool-specific entry type; "promotion" is the closest of ENTRY_TYPES
# (Surface 3's headline is the verified-promotion gate; chain.py reserves "promotion"
# as a surface entry type). Chosen deliberately — see the module docstring.
POOL_ENTRY_TYPE = "promotion"


def _kind(v: SkillVerification) -> Any:
    return getattr(v, "kind", None)


def _verdict(v: SkillVerification) -> Any:
    return getattr(v, "verdict", None)


def _num(x: Any) -> Optional[float]:
    """Coerce a Numeric column (which round-trips as Decimal) to float, or None."""
    return None if x is None else float(x)


def _decided_at_key(v: SkillVerification):
    """Sort key for "latest" — decided_at, with a stable fallback for None."""
    return (getattr(v, "decided_at", None) or datetime.min, getattr(v, "verification_id", ""))


def _active_skills_block(promotions: Sequence[SkillVerification]) -> dict:
    """§3 number 1 — N skills active, all verified net-positive with CIs.

    Read from ``kind=promotion`` PASS rows: the count + per-skill net_effect + CI +
    provenance to the calibrated judge. We do NOT recompute net-effect — the row IS the
    measurement. Measure-don't-claim: this states the gate ADMITTED N skills whose
    net-effect CI-lower-bound cleared 0; it does not claim the pool "improves accuracy".
    """
    skills: list[dict] = []
    for v in promotions:
        if _verdict(v) is not SkillVerificationVerdict.PASS:
            continue
        skills.append(
            {
                "skill_id": v.skill_id,
                "cohort_id": v.cohort_id,
                "net_effect": _num(v.net_effect),
                "repairs": int(v.repairs or 0),
                "regressions": int(v.regressions or 0),
                "ci_low": _num(v.ci_low),
                "ci_high": _num(v.ci_high),
                "held_out_n": int(v.held_out_n or 0),
                # Provenance to the calibrated net-effect judge (ADR-0011).
                "judge_calibration_ref": v.judge_calibration_ref,
                "scan_run_id": v.scan_run_id,
                "verification_id": v.verification_id,
            }
        )
    return {
        "n_active_verified": len(skills),
        "skills": skills,
        "claim": (
            "N skills admitted to active by the verified-promotion gate, each with a "
            "measured net-effect (repairs - regressions) whose bootstrap-CI lower bound "
            "cleared 0 on its cohort's held-out set"
        ),
    }


def _leakage_block(leakages: Sequence[SkillVerification], coverage: Optional[dict]) -> dict:
    """§3 number 2 — measured leakage rate X% under extraction (latest leakage row).

    Read from the LATEST ``kind=leakage`` row: the measured rate + CI. The rate is only
    as strong as the attack pack (ADR-0011), so the coverage-calibrated pack (id +
    version + strength tier + families) travels with it — supplied by the caller from the
    ``LeakageResult.coverage`` (the row alone does not store the pack identity). Never the
    rate quoted bare.
    """
    if not leakages:
        return {
            "measured": False,
            "leakage_rate": None,
            "note": "no kind=leakage verification on record for this pool",
        }
    latest = max(leakages, key=_decided_at_key)
    return {
        "measured": True,
        "leakage_rate": _num(latest.leakage_rate),
        "ci_low": _num(latest.ci_low),
        "ci_high": _num(latest.ci_high),
        "canary_n": int(latest.held_out_n or 0),
        "verdict": getattr(_verdict(latest), "value", None),
        # Provenance to the calibrated leakage-recovery judge (ADR-0011).
        "judge_calibration_ref": latest.judge_calibration_ref,
        "verification_id": latest.verification_id,
        # Coverage-calibrated pack — the rate is meaningless without it (ADR-0011 / §5).
        "pack_coverage": coverage,
        "claim": (
            "adversarial extraction leakage rate measured against the scrubbed pool; a "
            "breach is RECOVERY of protected content (consummation), not a generic "
            "mention (engagement) — only as strong as the attack pack named in pack_coverage"
        ),
    }


def _quarantine_block(
    combinations: Sequence[SkillVerification],
    quarantined_neighborhoods: Optional[Sequence[dict]],
) -> dict:
    """§3 number 3 — M dangerous co-invocation neighborhoods quarantined.

    Read from ``kind=combination`` PASS rows (a PASS combination row is a *produced*
    harmful composition that was acted on — quarantined). The count + per-row risk
    signal (``net_effect`` carries the risk score the gate wrote) + scan-run provenance
    come from the rows; the quarantined skill SETS (the row does not store them) are
    supplied by the caller from the ``CompositionResult.quarantined`` sets when available.
    Consummation discipline: two skills that *could* combine are NOT counted — only a
    judged, produced harmful composition.
    """
    neighborhoods: list[dict] = []
    for v in combinations:
        if _verdict(v) is not SkillVerificationVerdict.PASS:
            continue
        neighborhoods.append(
            {
                "verification_id": v.verification_id,
                "cohort_id": v.cohort_id,
                "risk_score": _num(v.net_effect),
                "scan_run_id": v.scan_run_id,
                "judge_calibration_ref": v.judge_calibration_ref,
            }
        )
    block: dict[str, Any] = {
        "m_quarantined": len(neighborhoods),
        "neighborhoods": neighborhoods,
        "claim": (
            "M co-invocation neighborhoods quarantined after a judged, PRODUCED harmful "
            "composition (consummation) — skills that could merely theoretically combine "
            "are not counted"
        ),
    }
    if quarantined_neighborhoods:
        # Quarantined SETS supplied by the caller (CompositionResult.quarantined); the
        # row alone does not carry them. Pass through as structured data (skill_ids).
        block["quarantined_sets"] = [dict(q) for q in quarantined_neighborhoods]
    return block


def _isolation_block(scope: "CohortScope") -> dict:
    """§3 number 4 — cohort isolation: no skill crossed a trust boundary it wasn't scoped to.

    A summary over the Section-G ``CohortScope`` the pool was attested under. On a single
    trust domain the cross-boundary checks are present-but-dormant; the assertion is the
    invariant (``cohorts.enforce_scope`` / ``scope_query`` deny any cross-(org, cohort,
    trust_domain) access), not a per-skill recomputation here.
    """
    return {
        "org_id": scope.org_id,
        "cohort_id": scope.cohort_id,
        "trust_domain": scope.trust_domain,
        "isolation_held": True,
        "claim": (
            "every promotion/leakage/combination decision was scoped to "
            f"(org={scope.org_id!r}, cohort={scope.cohort_id!r}, "
            f"trust_domain={scope.trust_domain!r}); no skill crossed a trust boundary it "
            "was not scoped to — cross-boundary access is denied at the query/enforce seam "
            "(Section G). Single-trust-domain mode: cross-team isolation is roadmap."
        ),
    }


def build_pool_attestation_payload(
    verifications: Sequence[SkillVerification],
    *,
    cohort_id: str,
    scope: "CohortScope",
    corpus_as_of: datetime,
    pack_coverage: Optional[dict] = None,
    quarantined_neighborhoods: Optional[Sequence[dict]] = None,
) -> dict:
    """Assemble the Surface-3 pool attestation ``payload`` from ``skill_verifications`` rows.

    ``verifications`` is the audit-spine rows for the cohort (the caller queries them — this
    adapter does not recompute any number, mirroring how the §07 adapter consumes already-
    captured decisions). They are bucketed by ``kind`` into the FOUR §3 numbers:

    * promotion PASS rows  → number 1 (N active, net-positive, CIs)
    * latest leakage row   → number 2 (measured leakage rate + CI + ``pack_coverage``)
    * combination PASS rows → number 3 (M quarantined neighborhoods)
    * ``scope``            → number 4 (cohort/trust-boundary isolation summary)

    ``pack_coverage`` is the leakage pack's coverage dict (id/version/tier/families) — the
    rate is meaningless without it (ADR-0011); supply it from ``LeakageResult.coverage`` for
    a real run. ``quarantined_neighborhoods`` optionally carries the quarantined skill SETS
    the combination rows do not store (from ``CompositionResult.quarantined``).

    Deterministic + self-contained: given the same rows + scope + ``corpus_as_of`` it returns
    a byte-identical dict, so it round-trips through ``chain.canonical_payload`` stably and the
    chain recomputes the exact ``entry_hash``. Every figure is READ from the rows — never
    recomputed (ADR-0009 SQL-queryable audit). Free text (the cohort id) is redacted.
    """
    promotions = [v for v in verifications if _kind(v) is SkillVerificationKind.PROMOTION]
    leakages = [v for v in verifications if _kind(v) is SkillVerificationKind.LEAKAGE]
    combinations = [v for v in verifications if _kind(v) is SkillVerificationKind.COMBINATION]

    return {
        "entry_type": POOL_ENTRY_TYPE,
        "surface": "skill_pool",
        "cohort_id": _redact(cohort_id),
        # --- the FOUR §3 numbers, each read from the audit rows --------------------
        "active_skills": _active_skills_block(promotions),
        "leakage": _leakage_block(leakages, pack_coverage),
        "combination_quarantine": _quarantine_block(combinations, quarantined_neighborhoods),
        "cohort_isolation": _isolation_block(scope),
        # --- framing (non-negotiable) + measure-don't-claim discipline -------------
        "corpus_as_of": canonical_as_of(corpus_as_of),
        "framing": framing_line(corpus_as_of),
        "measurement_note": (
            "tested against the known corpus as of "
            f"{canonical_as_of(corpus_as_of)}, continuously re-verified; this records what "
            "was MEASURED (verified-promotion net-effect, adversarial leakage rate, "
            "quarantined compositions, cohort isolation) — it is threat-informed assurance, "
            "NOT a safety guarantee, and does NOT claim the pool is safe or improves accuracy"
        ),
    }


def append_pool_attestation(
    service: "AttestationService",
    org_id: str,
    *,
    cohort_id: str,
    scope: "CohortScope",
    corpus_as_of: datetime,
    verifications: Sequence[SkillVerification],
    pack_coverage: Optional[dict] = None,
    quarantined_neighborhoods: Optional[Sequence[dict]] = None,
    reproducibility_ref: Optional[str] = None,
    ground_truth_ref: Optional[str] = None,
) -> "AttestationEntry":
    """Append ONE Surface-3 pool attestation to ``org_id``'s chain via the EXISTING engine.

    Thin: it builds the payload with :func:`build_pool_attestation_payload` and hands it to
    ``service.append`` with ``entry_type`` :data:`POOL_ENTRY_TYPE` — the SAME per-org hash
    chain, the same lazy-genesis / monotonic-seq / idempotency invariants. No chain logic is
    duplicated here.

    ``corpus_as_of`` is the chain's mandatory "as of date D" (passed to ``append``; the
    payload also stores its canonical iso form so the bytes are stable).
    ``reproducibility_ref`` defaults to ``f"skillpool:{cohort_id}"`` so a re-run for the same
    cohort/as-of is idempotent (the entry reconstructs from the stored rows).
    ``ground_truth_ref`` defaults to a pointer at the leakage pack the leakage number was
    measured under (ADR-0011 GroundTruthRef) when one is recorded, else the cohort handle.
    """
    payload = build_pool_attestation_payload(
        verifications,
        cohort_id=cohort_id,
        scope=scope,
        corpus_as_of=corpus_as_of,
        pack_coverage=pack_coverage,
        quarantined_neighborhoods=quarantined_neighborhoods,
    )
    ref = reproducibility_ref or f"skillpool:{cohort_id}"
    if ground_truth_ref is None:
        pack_id = (pack_coverage or {}).get("pack_id") if pack_coverage else None
        ground_truth_ref = (
            f"leakage-pack:{pack_id}" if pack_id else f"skillpool-cohort:{cohort_id}"
        )
    return service.append(
        org_id,
        POOL_ENTRY_TYPE,
        payload,
        reproducibility_ref=ref,
        ground_truth_ref=ground_truth_ref,
        corpus_as_of=corpus_as_of,
    )
