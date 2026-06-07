"""Emit: translate a finished scan into a structured attestation ``payload``.

The shared seam (build 03 §C) between a completed scan and the attestation chain.
``payload_for_scan(report, scan_record)`` builds the **decision-rationale**
structure (v2 §2.5 #3) — not a flat timestamp, but a per-finding *what / what the
judge scored / why* record — plus the non-negotiable **framing** line and
``corpus_as_of``.

What it consumes is the persisted hosted-scan report dict (``ScanReport.to_dict()``,
already saved by ``worker.save_report``): a top-level ``findings`` list of
*aggregated* per-family rows. The hosted path persists this report (not raw
``breach_results`` rows — those are the research corpus), so the attestation
reconstructs from the same stored report the worker had, deterministically.

**Redaction is critical.** An append-only entry can never be un-written, so every
free-text field that could carry a leaked secret is scrubbed via the SAME
``report_service._redact`` the customer renderers use, before it enters the
immutable record.

Surface-specific entry shapes (``payload_for_decision`` / ``payload_for_promotion``)
are added by those surfaces' own slices on the same chain; this file ships the
harm/scan path + the shared seam.

Spec: ``docs/v2/build/03_attestation.md`` §C; ADR-0011 (``ground_truth_ref``).
"""

from __future__ import annotations

from datetime import datetime, timezone

from rogue.platform.report_service import _redact

__all__ = ["payload_for_scan", "framing_line", "canonical_as_of"]


def canonical_as_of(corpus_as_of: datetime) -> str:
    """Serialize ``corpus_as_of`` to a single canonical UTC isoformat.

    The chain hash depends on byte-identical re-serialization, but storage layers
    differ on timezone fidelity (Postgres preserves tz; SQLite returns naive). We
    pin one form — UTC, tz-aware isoformat — treating a naive datetime as already
    UTC, so the payload (and thus the entry_hash) is the SAME whether built at
    append time from a tz-aware value or recomputed at replay from a round-tripped
    one. Do not "improve" this — it's part of the hash recipe.
    """
    dt = corpus_as_of
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


def framing_line(corpus_as_of: datetime) -> str:
    """The non-negotiable scope line carried on every entry (v2 §2.5).

    Threat-informed assurance, not a safety guarantee — the line between a
    defensible product and a liability magnet.
    """
    return (
        "threat-informed assurance, tested against the open-web corpus as of "
        f"{canonical_as_of(corpus_as_of)}; not a safety guarantee"
    )


def _finding_record(finding: dict, *, scan_id: str, index: int) -> dict:
    """Build the decision-rationale record for one aggregated finding.

    The hosted report aggregates per family/technique (not per trial), so each
    record carries the finding's binary disposition + the empirical rate + the
    consummation event (the technique that achieved the goal) + a ``snapshot_ref``
    pointer that resolves back to the source. Free-text excerpts are redacted.
    ``ground_truth_ref`` is None for harm Phase-0 (no independent per-rule label
    yet, ADR-0011) — the field is present so surfaces don't fork the shape.
    """
    n_breach = int(finding.get("n_breach") or 0)
    n_trials = int(finding.get("n_trials") or 0)
    success_rate = float(finding.get("success_rate") or 0.0)
    breached = n_breach > 0
    family = str(finding.get("family") or "")
    technique = str(finding.get("technique") or family or "")

    return {
        "rule": family,  # harm path: the attack family is the "rule" dimension
        "family": family,
        "breach_type": "breach" if breached else "clean",
        "n_breach": n_breach,
        "n_trials": n_trials,
        "success_rate": round(success_rate, 6),
        # CI slot (v2 §3): populated in Phase 1 by a shared bootstrap helper; None now.
        "ci": None,
        "verdict": "breach" if breached else "clean",
        # The judge's rationale for this finding. The aggregated SDK report carries
        # the human "what this means" explanation, not the per-trial judge rationale
        # (that lives on breach_results rows). Surface it redacted; None if absent.
        "judge_rationale": _redact(finding.get("explanation")),
        # The event that DEFINED the breach (v2 §2.2): the technique that achieved
        # the attacker's goal. Empty for a clean finding.
        "consummation_event": technique if breached else "",
        # Pointer, not a blob: a stable handle identifying this finding's source.
        # Phase-0 hosted scans reconstruct from the persisted report by scan_id; the
        # synthetic per-finding handle mirrors the instrument-spine projection seam.
        "snapshot_ref": f"{scan_id}::{technique}::{index}",
        "ground_truth_ref": None,
    }


def _coerce_scan_id(scan_record) -> str:
    """Read ``scan_id`` off a ScanRecord, a dict, or fall back to the report target."""
    if scan_record is None:
        return ""
    if isinstance(scan_record, dict):
        return str(scan_record.get("scan_id") or "")
    return str(getattr(scan_record, "scan_id", "") or "")


def payload_for_scan(report: dict, scan_record, *, corpus_as_of: datetime) -> dict:
    """Build the attestation ``payload`` for a COMPLETED ``scan`` entry.

    ``report`` is the persisted ``ScanReport.to_dict()`` (+ platform ``score`` /
    ``risk_level`` when present); ``scan_record`` is the ``ScanRecord`` (or a dict)
    the entry attests; ``corpus_as_of`` is the "as of date D" the assurance is
    anchored to (the same value passed to ``service.append`` — one source).

    The payload is the structured decision-rationale (v2 §2.5 #3): the headline
    (target / counts / score / risk), a per-finding rationale list, the framing
    line, and ``corpus_as_of``. Deterministic and self-contained: given the same
    stored report + ``corpus_as_of`` it returns a byte-identical dict, so it
    round-trips through ``canonical_payload`` stably and ``replay`` recomputes the
    exact ``entry_hash``.

    Every free-text excerpt is redacted (``report_service._redact``) — an
    append-only entry must never carry a secret.
    """
    scan_id = _coerce_scan_id(scan_record)
    findings = report.get("findings") or []
    finding_records = [
        _finding_record(f, scan_id=scan_id, index=i) for i, f in enumerate(findings)
    ]

    return {
        "entry_type": "scan",
        "scan_id": scan_id,
        "target": _redact(report.get("target")) or "",
        "n_tests": int(report.get("n_tests") or 0),
        "n_breaches": int(report.get("n_breaches") or 0),
        "breach_rate": round(float(report.get("breach_rate") or 0.0), 6),
        # Platform headline (present when the report came through report_service);
        # the bare SDK to_dict() omits them, so default cleanly.
        "score": report.get("score"),
        "risk_level": report.get("risk_level"),
        "top_attack": _redact(report.get("top_attack")),
        "findings": finding_records,
        "corpus_as_of": canonical_as_of(corpus_as_of),
        "framing": framing_line(corpus_as_of),
    }
