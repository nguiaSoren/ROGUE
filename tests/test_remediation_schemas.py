"""Wave-1 foundation gate for Surface 1b (build-05 §2/§3-schema exit gate).

The remediation wire schemas round-trip, the type vocabulary matches the spec, and the ADR-0010/
0011 honesty defaults hold (no fabricated CI, recommend-now gate not measured-backed by default).
No DB, no network — pure schema.
"""

from __future__ import annotations

from rogue.remediation import (
    CONFIG_APPLICABLE,
    MitigationCandidate,
    MitigationType,
    OverBlockCheck,
    RemediationResult,
)


def _candidate(mtype=MitigationType.SYSTEM_PROMPT_PATCH) -> MitigationCandidate:
    return MitigationCandidate(
        candidate_id="cand-1",
        breach_ref="R2",
        mitigation_type=mtype,
        artifact="Never authorize a refund above the $500 cap without a manager approval token.",
        generated_by="anthropic/claude-sonnet-4-6@gen-v1",
        rationale="closes the over-cap authorization path",
    )


def test_type_vocabulary_matches_spec():
    assert {m.value for m in MitigationType} == {
        "system_prompt_patch", "finetune_preference_data", "tool_permission_scope",
        "retrieval_context_fix", "architecture_recommendation", "guardrail_rule", "human_gate_route",
    }
    # only the config-mutating types are re-scannable (§6); the rest are out-of-band / sandbox-rule
    assert CONFIG_APPLICABLE == {MitigationType.SYSTEM_PROMPT_PATCH, MitigationType.TOOL_PERMISSION_SCOPE}


def test_candidate_round_trips_and_gate_defaults_false():
    c = _candidate()
    assert MitigationCandidate.model_validate_json(c.model_dump_json()) == c
    # ADR-0010 / S2-LINK honesty: the human-gate route is recommend-now, not measured-backed
    assert _candidate(MitigationType.HUMAN_GATE_ROUTE).measured_gate_backed is False


def test_overblock_carries_independent_ref_and_no_fabricated_ci():
    ob = OverBlockCheck(legitimate_set_ref="legit/R2", n_legit=20, n_false_block=0, over_block_rate=0.0)
    assert ob.ci_low is None and ob.ci_high is None  # honest: no CI until measured (ADR-0011)
    assert OverBlockCheck.model_validate_json(ob.model_dump_json()) == ob


def test_result_breach_reduced_and_accept_provenance():
    r = RemediationResult(
        candidate=_candidate(), pre_breach_rate=0.8, post_breach_rate=0.0,
        post_breach_ci=(0.0, 0.08),
        over_block=OverBlockCheck(legitimate_set_ref="legit/R2", n_legit=20, n_false_block=0,
                                  over_block_rate=0.0, ci_low=0.0, ci_high=0.09),
    )
    assert r.breach_reduced is True
    assert r.accepted is False  # the loop sets this; the schema never asserts acceptance itself
    assert r.verified_by == "rescan"
    # an out-of-band type records honestly rather than faking a delta (§6.note)
    r2 = RemediationResult(candidate=_candidate(MitigationType.FINETUNE_PREFERENCE_DATA),
                           pre_breach_rate=0.8, post_breach_rate=0.8,
                           verified_by="by_construction_out_of_band")
    assert r2.breach_reduced is False and r2.verified_by == "by_construction_out_of_band"
