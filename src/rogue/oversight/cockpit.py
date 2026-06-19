"""Surface 2 reviewer decision-support cockpit — the assembler (build 07 §4).

THE HARD RULE (research-backed, build 07 §4 / spec §4): surface evidence to
*CHECK*, NEVER prose to *PERSUADE*. Fluent, persuasive free-text drives human
over-reliance on wrong verdicts — a measured failure mode. The assembler
therefore emits STRUCTURED FACTS ONLY: the case's checkable ``facts`` strip
(verbatim), the verifier's calibrated case-level confidence (area-02), and the
case-class's MEASURED historical false-approve rate (the scorer's history).
There is NO generated free-text recommendation field, by design — and the
``no_persuasive_prose`` guard below makes that discipline enforceable: it scans
every string the strip carries for recommendation verbs and flags any that slip
in.

A ``CockpitStrip`` is a reviewer's pre-decision dashboard reduced to numbers +
verifiable facts. Nothing in it tells the reviewer what to do; everything in it
is something the reviewer can independently confirm.

The frontend strip (a compact factual UI under ``frontend/(app)/``) is
DEFERRED (light-footprint, no dev server, Edit-over-rewrite per CLAUDE.md).
This module is the backend assembler only.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

from rogue.oversight.case_corpus import GatedCase

__all__ = [
    "CockpitStrip",
    "assemble_cockpit",
    "no_persuasive_prose",
    "assert_no_persuasive_prose",
]


# Recommendation-verb heuristic. A clean cockpit strip carries only structured
# facts (short, checkable) + numbers; none of its text should read as a verdict
# or a recommendation. Any string value matching one of these substrings (case-
# insensitive) is flagged as persuasive prose.
_PERSUASIVE_MARKERS: tuple[str, ...] = (
    "you should",
    "we recommend",
    "i recommend",
    "i suggest",
    "we suggest",
    "approve this",
    "deny this",
    "reject this",
    "i advise",
    "you ought to",
    "you must approve",
    "you must deny",
    "recommend approving",
    "recommend denying",
)


@dataclass(frozen=True)
class CockpitStrip:
    """The reviewer decision-support strip — STRUCTURED FACTS ONLY.

    Deliberately has NO recommendation / verdict-as-prose field: surfacing
    persuasive prose drives over-reliance on wrong verdicts (build 07 §4). The
    only free text is ``facts`` — short checkable facts copied verbatim from the
    ``GatedCase``, never a summary that argues a disposition.
    """

    case_id: str
    case_class: str
    # The checkable facts strip (amount, parties, dispute type, what was flagged,
    # verification steps) — verbatim from GatedCase.facts, NOT summarized to prose.
    facts: dict[str, str]
    # The verifier's calibrated case-level confidence for this case (area-02);
    # None if unavailable. The assembler does NOT compute it — it is passed in.
    calibrated_confidence: float | None
    # The MEASURED historical false-approve rate for this case_class from prior
    # runs (the scorer's history); None if no history exists yet.
    class_false_approve_rate: float | None
    # NO recommendation field, NO free-text verdict — by design (build 07 §4).


def assemble_cockpit(
    case: GatedCase,
    *,
    calibrated_confidence: float | None = None,
    class_false_approve_rate: float | None = None,
) -> CockpitStrip:
    """Assemble the decision-support strip for ``case`` — structured facts only.

    Copies the case's structured ``facts`` verbatim (never summarized into prose)
    and attaches the two passed-in numbers: ``calibrated_confidence`` (the
    verifier's calibrated case-level confidence from area-02) and
    ``class_false_approve_rate`` (the measured historical false-approve rate for
    this case-class). The assembler computes neither — they are supplied by
    area-02 and the scorer's history respectively.

    The returned strip carries NO recommendation / verdict-as-prose field. The
    guard ``assert_no_persuasive_prose`` is applied before returning, so a strip
    that somehow carried persuasive text would fail loudly rather than ship.
    """
    strip = CockpitStrip(
        case_id=case.case_id,
        case_class=case.case_class,
        facts=dict(case.facts),  # verbatim copy — do not summarize into prose
        calibrated_confidence=calibrated_confidence,
        class_false_approve_rate=class_false_approve_rate,
    )
    assert_no_persuasive_prose(strip)
    return strip


def no_persuasive_prose(strip: CockpitStrip) -> list[str]:
    """Return violation messages for any persuasive-prose text in ``strip``.

    Empty list = clean (the §4 discipline holds). The guard scans every string
    value the strip carries — every ``facts`` value plus any other str-typed
    field — for recommendation verbs ("you should", "we recommend", "approve
    this", "deny this", "i suggest", ...). A clean strip's only text is the
    short, checkable ``facts`` values; none should read as a verdict.
    """
    violations: list[str] = []

    def _scan(location: str, value: str) -> None:
        low = value.lower()
        for marker in _PERSUASIVE_MARKERS:
            if marker in low:
                violations.append(
                    f"persuasive prose in {location}: contains {marker!r} "
                    f"(surface facts to CHECK, never prose to PERSUADE — "
                    f"build 07 §4): {value!r}"
                )

    # Scan every string-typed field on the dataclass (belt-and-suspenders: also
    # catches a verdict accidentally stuffed into case_id/case_class), plus every
    # facts value.
    for f in fields(strip):
        val = getattr(strip, f.name)
        if isinstance(val, str):
            _scan(f.name, val)
        elif isinstance(val, dict):
            for k, v in val.items():
                if isinstance(v, str):
                    _scan(f"{f.name}[{k!r}]", v)

    return violations


def assert_no_persuasive_prose(strip: CockpitStrip) -> None:
    """Raise ``ValueError`` if ``strip`` carries any persuasive prose.

    The §4 discipline made enforceable: a cockpit strip ships structured facts
    only. Any recommendation-as-prose is a build-stopping defect.
    """
    violations = no_persuasive_prose(strip)
    if violations:
        raise ValueError(
            "CockpitStrip carries persuasive prose (build 07 §4 — surface "
            "evidence to CHECK, never prose to PERSUADE):\n  "
            + "\n  ".join(violations)
        )
