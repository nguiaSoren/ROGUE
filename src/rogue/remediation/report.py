"""Surface 1b §8 (data level) — render the verified mitigation + emit attestation-ready rows.

NET-NEW and no request-path: this turns a :class:`RemediationResult` into (a) customer-facing
markdown carrying the VERIFIED re-test evidence + the ADR-0010 "client deploys; ROGUE re-verifies"
framing, and (b) attestation rows (mirroring the area-03 finding-record shape) for the hash-chain
to consume. It deliberately does NOT modify the existing ``report.py::remediation_for`` or the
platform report/DB layers — that supersede is the remaining §8 modify-existing step, done against
the platform layer separately (see the build doc + the orchestrator's handoff note).
"""

from __future__ import annotations

from rogue.schemas.remediation import RemediationResult


def render_remediation_markdown(result: RemediationResult) -> str:
    """The customer-facing mitigation block: the verified numbers + the honest framing (ADR-0010)."""
    c = result.candidate
    lines = [f"### Mitigation for {c.breach_ref} — {c.mitigation_type.value}"]
    if result.verified_by == "rescan":
        pre, post = f"{result.pre_breach_rate * 100:.0f}%", f"{result.post_breach_rate * 100:.0f}%"
        lines.append(f"**Verified:** re-tested vs the same attack family — breach {post} (was {pre}).")
        if result.over_block is not None:
            ob = result.over_block
            lines.append(
                f"Over-block: {ob.over_block_rate * 100:.0f}% on {ob.n_legit} legitimate requests "
                "(the agent kept answering what it should).")
    else:
        lines.append("**Verified by construction / out-of-band** — the fix lives outside the "
                     "prompt/scope; no re-scan breach-rate delta is claimed.")
    lines.append(f"Artifact: {c.artifact}")
    lines.append("_The client deploys this into their own runtime; ROGUE never enforces it, and "
                 "re-verifies it continuously as new variants are harvested (ADR-0010)._")
    if not result.accepted:
        lines.append("_(Not accepted — recorded for the iteration trail.)_")
    return "\n\n".join(lines)


def remediation_attestation_rows(
    result: RemediationResult, *, corpus_as_of: str | None = None
) -> list[dict]:
    """Emit attestation-ready rows for the mitigation (area-03 consumes them into the hash-chain).

    This layer EMITS rows; it never builds the chain (mirrors governance.attestation_rows). Keeps
    the two provenances honest: the trial-outcome re-test rates vs the calibration of the judge that
    produced them (the latter travels with the breach record, not duplicated here).
    """
    c = result.candidate
    return [{
        "kind": "mitigation",
        "breach_ref": c.breach_ref,
        "mitigation_type": c.mitigation_type.value,
        "candidate_id": c.candidate_id,
        "accepted": result.accepted,
        "verified_by": result.verified_by,
        "pre_breach_rate": result.pre_breach_rate,
        "post_breach_rate": result.post_breach_rate,
        "over_block_rate": (result.over_block.over_block_rate if result.over_block else None),
        "generated_by": c.generated_by,
        "corpus_as_of": corpus_as_of,
    }]
