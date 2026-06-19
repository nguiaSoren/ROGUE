"""Surface 1b §8 (data-level) gate: the verified mitigation renders with the ADR-0010 framing and
emits attestation-ready rows. No request-path, no DB."""

from __future__ import annotations

from rogue.remediation import (
    MitigationCandidate,
    MitigationType,
    OverBlockCheck,
    RemediationResult,
    remediation_attestation_rows,
    render_remediation_markdown,
)


def _accepted() -> RemediationResult:
    return RemediationResult(
        candidate=MitigationCandidate(
            candidate_id="c1", breach_ref="R2", mitigation_type=MitigationType.TOOL_PERMISSION_SCOPE,
            artifact="Cap the refund tool at $500 without a manager approval token.",
            generated_by="anthropic/claude-sonnet-4-6@gen-v1"),
        pre_breach_rate=0.8, post_breach_rate=0.0, post_breach_ci=(0.0, 0.08),
        over_block=OverBlockCheck(legitimate_set_ref="legit/R2", n_legit=20, n_false_block=0,
                                  over_block_rate=0.0, ci_low=0.0, ci_high=0.09),
        accepted=True, verified_by="rescan")


def test_render_carries_verified_numbers_and_adr0010_framing():
    md = render_remediation_markdown(_accepted())
    assert "breach 0% (was 80%)" in md
    assert "Over-block: 0%" in md and "20 legitimate requests" in md
    # the load-bearing honesty: ROGUE proves, the client runs it (never implies ROGUE enforces)
    assert "client deploys" in md and "ROGUE never enforces" in md


def test_out_of_band_render_does_not_fake_a_delta():
    r = RemediationResult(
        candidate=MitigationCandidate(candidate_id="a1", breach_ref="R3",
            mitigation_type=MitigationType.ARCHITECTURE_RECOMMENDATION,
            artifact="This agent shouldn't issue legal opinions autonomously.",
            generated_by="remediation.loop@arch-fallback"),
        pre_breach_rate=0.5, post_breach_rate=0.5, accepted=True,
        verified_by="by_construction_out_of_band")
    md = render_remediation_markdown(r)
    assert "Verified by construction / out-of-band" in md
    assert "(was" not in md  # never fakes a re-scan delta


def test_attestation_rows_shape():
    rows = remediation_attestation_rows(_accepted(), corpus_as_of="2026-06-09")
    assert len(rows) == 1
    needed = {"kind", "breach_ref", "mitigation_type", "candidate_id", "accepted", "verified_by",
              "pre_breach_rate", "post_breach_rate", "over_block_rate", "generated_by", "corpus_as_of"}
    assert needed <= set(rows[0])
    assert rows[0]["kind"] == "mitigation" and rows[0]["over_block_rate"] == 0.0
    assert rows[0]["corpus_as_of"] == "2026-06-09"
