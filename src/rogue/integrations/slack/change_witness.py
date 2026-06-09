"""ChangeWitness — the signed-attestation READER for the Slack cycle (build-06 §5).

The thin read side of the attestation seam. The worker already auto-signs an
*enriched* ``scan`` entry per Slack cycle (its payload carries the frozen
``surface1_context`` block + the ``rule_breach_report``), and area-05's
:func:`rogue.attestation.remediation.append_mitigation` signs each verified fix
onto the SAME per-org hash chain. This module just READS those signed entries back
into the small, render-ready :class:`ChangeWitnessSummary` the §6/§8 surface (and
the demo) needs — and composes the cycle's accepted mitigations onto the chain.

It implements NO hashing/signing/chaining of its own: it consumes
``AttestationService`` (area-03) for reads, REUSES ``emit.framing_line`` for the
non-negotiable scope line, REUSES ``append_mitigation`` for the mitigation writes,
and optionally REUSES ``replay`` for the byte-reproducibility check. Side-effect-free
import (plain reads on call; no DB/engine built at import).

Spec: ``docs/v2/build/06_*`` §5; reuses ``docs/v2/build/03_attestation.md`` chain
+ ``docs/v2/build/05_*`` §8.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from rogue.attestation import emit
from rogue.attestation.remediation import append_mitigation
from rogue.attestation.replay import replay

if TYPE_CHECKING:
    from rogue.attestation.service import AttestationService
    from rogue.platform.models import AttestationEntry
    from rogue.schemas.remediation import RemediationResult

__all__ = [
    "ChangeWitnessSummary",
    "latest_agent_scan_entry",
    "latest_change_witness",
    "append_cycle_mitigations",
]


@dataclass(frozen=True)
class ChangeWitnessSummary:
    """The render-ready projection of one Slack cycle's signed ``scan`` entry.

    What the §6/§8 surface + the demo show: who was tested, the signed-entry
    coordinates (so the audit trail is checkable), the breaching rules with their
    "holds N/M" + CI, the verified mitigations folded onto the same chain, the
    independent-label pointer, and — when a ``report_loader`` was supplied — whether
    the entry replays byte-for-byte. ``framing`` is the non-negotiable scope line
    (threat-informed assurance, NOT a safety guarantee); it is never re-phrased here.
    """

    agent_name: str
    org_id: str
    scan_id: str
    entry_id: str
    entry_hash: str
    corpus_as_of: str
    framing: str
    breaching_rules: list[dict]
    verified_mitigations: list[dict]
    ground_truth_ref: str | None
    replay_ok: bool | None = None


def _payload(entry) -> dict:
    """Read the ``payload`` dict off an ORM entry or a dict (dual-shape tolerance)."""
    if isinstance(entry, dict):
        return entry.get("payload") or {}
    return getattr(entry, "payload", None) or {}


def _attr(entry, name):
    """Read ``name`` off an ORM entry or a dict."""
    if isinstance(entry, dict):
        return entry.get(name)
    return getattr(entry, name, None)


def _agent_name_of(entry) -> str | None:
    """The ``surface1_context.agent.agent_name`` carried on a Slack ``scan`` entry, if any."""
    ctx = _payload(entry).get("surface1_context") or {}
    agent = ctx.get("agent") or {}
    return agent.get("agent_name")


def _breaching_rules(payload: dict) -> list[dict]:
    """Render the breaching per-rule verdicts (``n_breaches > 0``) as small dicts.

    Pulls from the carried ``rule_breach_report.rule_verdicts`` (the frozen area-04
    shape). ``holds`` is the clean-trial fraction ``"{n_trials - n_breaches}/{n_trials}"``;
    ``ci`` is the trial-outcome bootstrap CI ``[ci_low, ci_high]`` (None when absent).
    """
    report = payload.get("rule_breach_report") or {}
    verdicts = report.get("rule_verdicts") or []
    rules: list[dict] = []
    for v in verdicts:
        n_breaches = int(v.get("n_breaches") or 0)
        if n_breaches <= 0:
            continue
        n_trials = int(v.get("n_trials") or 0)
        ci_low = v.get("ci_low")
        ci_high = v.get("ci_high")
        ci = [ci_low, ci_high] if (ci_low is not None or ci_high is not None) else None
        rules.append(
            {
                "rule_id": v.get("rule_id") or "?",
                "breach_type": v.get("breach_type") or "?",
                "family": v.get("attack_family") or "—",
                "holds": f"{n_trials - n_breaches}/{n_trials}",
                "ci": ci,
            }
        )
    return rules


def _mitigation_links_scan(mit_payload: dict, scan_id: str) -> bool:
    """True iff a ``mitigation`` entry's payload points at ``scan_id``.

    Area-05's record carries pointer handles of the form ``{scan_id}::...`` —
    ``snapshot_ref`` (``{scan_id}::{candidate_id}::{index}``) and ``artifact_ref``
    (``{scan_id}::{breach_ref}::{candidate_id}``). Match on the scan_id prefix of
    either; guard against a degenerate empty scan_id matching everything.
    """
    if not scan_id:
        return False
    prefix = f"{scan_id}::"
    for key in ("snapshot_ref", "artifact_ref"):
        ref = mit_payload.get(key)
        if isinstance(ref, str) and ref.startswith(prefix):
            return True
    return False


def _verified_mitigations(service: "AttestationService", org_id: str, scan_id: str) -> list[dict]:
    """Render this cycle's mitigation entries (those whose payload links to ``scan_id``).

    Surfaces the verified disposition + the post-breach rate + a redacted excerpt of
    the fix's rationale (the artifact TEXT is never stored on-chain — the record keeps
    a ``artifact_ref`` pointer, so the excerpt is the rationale, which area-05 already
    redacted before signing).
    """
    entries = service.list_entries(org_id, entry_type="mitigation", limit=500)
    out: list[dict] = []
    for e in entries:
        mp = _payload(e)
        if not _mitigation_links_scan(mp, scan_id):
            continue
        out.append(
            {
                "mitigation_type": mp.get("mitigation_type"),
                "accepted": bool(mp.get("accepted")),
                "artifact_excerpt": mp.get("rationale"),
                "post_breach_rate": mp.get("post_breach_rate"),
            }
        )
    return out


def latest_agent_scan_entry(
    org_id: str,
    agent_name: str,
    *,
    attestation_service: "AttestationService",
):
    """The agent's most-recent signed ``scan`` entry (max ``seq``), or ``None``.

    Lists the org's ``scan`` entries, keeps those whose embedded
    ``surface1_context.agent.agent_name`` matches ``agent_name``, and returns the
    highest-``seq`` one (``list_entries`` is seq-ascending). ``None`` when the agent
    has no signed scan entry. The single shared "find the latest scan" path —
    :func:`latest_change_witness` (§5) and Tripwire's ``predict_breach`` (§6) both
    route through here so they can never diverge on what "latest scan" means.
    """
    scans = attestation_service.list_entries(org_id, entry_type="scan", limit=500)
    matching = [e for e in scans if _agent_name_of(e) == agent_name]
    if not matching:
        return None
    # list_entries is seq-ascending; the latest cycle is the highest seq.
    return max(matching, key=lambda e: _attr(e, "seq"))


def latest_change_witness(
    org_id: str,
    agent_name: str,
    *,
    attestation_service: "AttestationService",
    report_loader: Callable[[str], dict | None] | None = None,
) -> ChangeWitnessSummary | None:
    """Read the LATEST signed Slack ``scan`` entry for one agent into a summary.

    1. Take the agent's highest-``seq`` signed ``scan`` entry via
       :func:`latest_agent_scan_entry`. None → return None.
    2. Render the breaching per-rule verdicts (``n_breaches > 0``) with holds N/M + CI.
    3. Find + render this cycle's mitigation entries (payload links to the same scan_id).
    4. ``framing`` = the entry's own stored ``payload["framing"]`` when present, else
       :func:`emit.framing_line` over its ``corpus_as_of`` — never re-phrased.
    5. When ``report_loader`` is given, run :func:`replay` and set ``replay_ok`` to its
       ``reproducible`` flag (None on any error / when no loader).
    """
    entry = latest_agent_scan_entry(
        org_id, agent_name, attestation_service=attestation_service
    )
    if entry is None:
        return None

    payload = _payload(entry)
    scan_id = str(payload.get("scan_id") or _attr(entry, "reproducibility_ref") or "")

    corpus_as_of = payload.get("corpus_as_of")
    if not corpus_as_of:
        stored = _attr(entry, "corpus_as_of")
        corpus_as_of = emit.canonical_as_of(stored) if stored is not None else ""

    framing = payload.get("framing")
    if not framing:
        stored = _attr(entry, "corpus_as_of")
        # Never phrase the scope as a guarantee — reuse the canonical line.
        framing = emit.framing_line(stored) if stored is not None else ""

    replay_ok: bool | None = None
    if report_loader is not None:
        try:
            replay_ok = replay(entry, report_loader=report_loader).reproducible
        except Exception:
            replay_ok = None

    return ChangeWitnessSummary(
        agent_name=agent_name,
        org_id=org_id,
        scan_id=scan_id,
        entry_id=str(_attr(entry, "entry_id") or ""),
        entry_hash=str(_attr(entry, "entry_hash") or ""),
        corpus_as_of=str(corpus_as_of),
        framing=framing,
        breaching_rules=_breaching_rules(payload),
        verified_mitigations=_verified_mitigations(attestation_service, org_id, scan_id),
        ground_truth_ref=payload.get("ground_truth_ref"),
        replay_ok=replay_ok,
    )


def append_cycle_mitigations(
    attestation_service: "AttestationService",
    org_id: str,
    scan_id: str,
    results: list["RemediationResult"],
    *,
    corpus_as_of,
) -> list["AttestationEntry"]:
    """Fold this cycle's ACCEPTED mitigations onto the org's chain, return the entries.

    The "include mitigation entries" wiring: for each ``accepted`` result it calls
    area-05's :func:`append_mitigation` (which REUSES the same hash chain — no chain
    logic here), keyed by its position ``index=i`` for a stable ``snapshot_ref``.
    Non-accepted results are skipped (the chain attests verified fixes, not rejections).

    Posture: NOT best-effort — an append error PROPAGATES so the caller decides how to
    react (a failed sign is a real chain fault, not a cosmetic one; swallowing it would
    silently drop an attestation). The caller can wrap this if it wants soft-fail.
    """
    appended: list["AttestationEntry"] = []
    for i, result in enumerate(results):
        if not result.accepted:
            continue
        entry = append_mitigation(
            attestation_service,
            org_id,
            result,
            scan_id=scan_id,
            index=i,
            corpus_as_of=corpus_as_of,
        )
        appended.append(entry)
    return appended
