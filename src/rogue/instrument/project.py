"""Project an existing harm ``ScanReport`` into instrument-spine types.

This is the **seam every surface reuses** (build/01_foundation.md §0.6): it turns
the *existing* harm-scan output — a ``rogue.report.ScanReport.to_dict()`` dict —
into spine ``Verdict`` + ``Capture`` pairs **without touching** ``report.py`` or
the frozen v1 SDK contract (``sdk/``). The harm scan output flows into the new
spine through this adapter and nowhere else.

What it consumes: the dict shape emitted by ``ScanReport.to_dict()`` — a
top-level ``findings`` list where each finding is an *aggregated* per-family row
(``family``, ``technique``, ``vector``, ``severity``, ``success_rate``,
``n_trials``, ``n_breach``, optional ``example_*``). Because the customer report
aggregates per family/technique (not per trial), this projects **one
``Verdict`` + paired ``Capture`` per finding**: the finding's binary disposition
(breached ⇒ ``breach``, else ``clean``) and the empirical success rate as the
verdict confidence.

Reproducibility pointers: the dedicated content-addressed snapshot store
(``snapshot_ref``, build §0.3) is DEFERRED in Phase 0, and the aggregated report
dict carries no per-trial ``breach_id``. So the Phase-0 pointer is a stable
synthetic handle derived from the target + the finding's technique — enough to
identify *which* finding a capture belongs to. When the snapshot store and a
per-trial projection land, the same field carries the real ``snapshot_ref`` /
``breach_id`` with no shape change to ``Capture``.

Pure new file: imports only ``rogue.instrument.model`` and the stdlib; touches no
shared file and makes no DB or network call.
"""

from __future__ import annotations

from .model import Capture, Target, Verdict


def _pointer_for(target: Target, finding: dict, index: int) -> str:
    """A stable Phase-0 reproducibility handle for a finding's capture.

    Deferred-store placeholder (see module docstring): identifies the finding by
    target + technique + position. Deterministic so the same report projects to
    the same pointers.
    """
    technique = str(finding.get("technique") or finding.get("family") or "finding")
    return f"{target.target_ref}::{technique}::{index}"


def project_scan(report_dict: dict, target: Target) -> list[Verdict]:
    """Project a harm ``ScanReport.to_dict()`` dict into spine ``Verdict``s.

    Returns one ``Verdict`` per finding, in report order. The paired ``Capture``s
    (one per verdict, positionally aligned) are available via
    :func:`project_scan_captures`; :func:`project_scan_pairs` returns both zipped
    together — most callers want ``project_scan_pairs``.
    """
    return [v for v, _ in project_scan_pairs(report_dict, target)]


def project_scan_captures(report_dict: dict, target: Target) -> list[Capture]:
    """The ``Capture`` projected for each finding (positionally aligned with
    :func:`project_scan`)."""
    return [c for _, c in project_scan_pairs(report_dict, target)]


def project_scan_pairs(
    report_dict: dict, target: Target
) -> list[tuple[Verdict, Capture]]:
    """Project a harm report dict into ``(Verdict, Capture)`` pairs — the full seam.

    One pair per finding. The verdict's label is ``breach`` when the finding
    breached at least once (``n_breach > 0``), else ``clean``; its confidence is
    the finding's empirical ``success_rate``. The capture is a pointer (never the
    transcript) and is flagged ``is_negative_exemplar`` for a clean finding so the
    retention discipline (spec §3 / build §0.4) is structural here.
    """
    findings = report_dict.get("findings") or []
    pairs: list[tuple[Verdict, Capture]] = []
    for index, finding in enumerate(findings):
        n_breach = int(finding.get("n_breach") or 0)
        breached = n_breach > 0
        # Empirical success rate as the {breach|clean} confidence; clamp defensively.
        success_rate = float(finding.get("success_rate") or 0.0)
        confidence = min(1.0, max(0.0, success_rate))

        # consummation_event: for the harm case the "event that defined the breach"
        # is the technique that achieved the attacker's goal. Empty for a clean finding.
        technique = str(finding.get("technique") or finding.get("family") or "")
        consummation = technique if breached else ""

        verdict = Verdict(
            label="breach" if breached else "clean",
            consummation_event=consummation,
            class_confidence=confidence,
            ci=None,  # Phase-1 bootstrap-CI population; field exists, unset now
        )

        pointer = _pointer_for(target, finding, index)
        capture = Capture(
            reproducibility_pointer=pointer,
            is_negative_exemplar=not breached,
            latency_ms=None,
            tokens_in=None,
            tokens_out=None,
        )
        pairs.append((verdict, capture))
    return pairs
