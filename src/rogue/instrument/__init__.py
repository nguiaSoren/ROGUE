"""Public surface for the ROGUE v2 instrument spine.

ROGUE v2 = "measured assurance"; the instrument is the loop
*fire → capture → judge → signed record*. This package is the **shared
vocabulary** the three surfaces import instead of forking — one import root:

    from rogue.instrument import Target, Probe, Capture, Verdict, GroundTruthRef

The spine **wraps/points at** the frozen Day-0 harvest/reproduce wire format in
``rogue.schemas`` (e.g. ``JudgeVerdict``/``BREACH_VERDICTS``) and **never
duplicates its enums** (build/01_foundation.md §0.2). ``project_scan`` is the seam
that turns an existing harm ``ScanReport.to_dict()`` into spine types without
touching ``report.py`` or the SDK.

Spec: ``docs/v2/ROGUE_unified_spec.md`` §3; ADR-0011 (independence invariant).
"""

from .model import (
    FORBIDDEN_GROUND_TRUTH_TOKENS,
    AttestationEntry,
    Capture,
    GroundTruthRef,
    Mitigation,
    Probe,
    Target,
    Verdict,
)
from .project import (
    project_scan,
    project_scan_captures,
    project_scan_pairs,
)

__all__ = [
    # spine types (spec §3)
    "Target",
    "Probe",
    "Capture",
    "Verdict",
    "GroundTruthRef",
    "Mitigation",
    "AttestationEntry",
    # independence-invariant guard (ADR-0011)
    "FORBIDDEN_GROUND_TRUTH_TOKENS",
    # report → spine projection seam (build §0.6)
    "project_scan",
    "project_scan_captures",
    "project_scan_pairs",
]
