"""Surface 2 independence lint — the ENFORCEMENT TEETH of ADR-0011.

This is the mechanism that makes the independence invariant (ADR-0011, unified
spec §5, build 07 §1) *demonstrably enforced* rather than merely asserted. The
headline number Surface 2 produces — a human false-approve rate with a bootstrap
CI — is only worth signing if the "correct disposition" for every case is
provably independent of (a) the regulation text, (b) the reviewers' own votes,
and (c) the verifier model's own opinion. A corpus whose label secretly traces
to a forbidden source is a signed attestation of a number that was never
established — worse than no product (ADR-0011 Consequences).

So this module FAILS LOUDLY. It runs in CI (``.github/workflows/ci.yml``) and
fails the build on any violation; no corpus ships without passing it, and no
false-approve number ships scored against a corpus that hasn't. The four named
rules below are the probe a sharp reviewer pulls first; each is enforced here.

CLI exit-gate (CI runs this)::

    uv run python -m rogue.oversight.independence_lint

Clean corpus → prints a pass line + ``corpus_stats`` and exits 0; any violation
→ prints each violation and exits 1.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

from rogue.oversight.case_corpus import (
    _LABEL_PROVENANCES,
    GatedCase,
    corpus_stats,
    load_corpus,
)

__all__ = [
    "LintViolation",
    "lint_corpus",
    "assert_corpus_independent",
    "REGULATION_PATTERNS",
    "LABEL_BALANCE_MIN",
    "LABEL_BALANCE_MAX",
    "CASE_CLASS_FLOOR",
]


# --- Rule names (stable identifiers; cited in CI output + tests). --------------
RULE_REGULATION_DERIVED = "regulation-derived-label"
RULE_VERIFIER_PROVENANCE = "verifier-provenance"
RULE_BALANCE = "balance"
RULE_GROUNDING = "grounding-present"


# --- Thresholds (module constants — single place to tune the invariant). -------
# Rule 1: a designed_rationale that quotes/paraphrases regulation text. The label
# must read "this is a BEC pattern", never "violates §X". Each pattern is one
# way a statute / article / policy ID leaks into the rationale.
REGULATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("CFR citation", re.compile(r"\b\d+\s*CFR\b")),
    ("U.S.C citation", re.compile(r"U\.S\.C")),
    ("section sign (§)", re.compile(r"§")),
    ("violation language", re.compile(r"\bviolat(es|ion)\b", re.IGNORECASE)),
    ("Article N", re.compile(r"\bArticle\s+\d+", re.IGNORECASE)),
    ("Section N", re.compile(r"\bSection\s+\d+", re.IGNORECASE)),
    ("policy #N", re.compile(r"policy\s*#?\d+", re.IGNORECASE)),
)

# Rule 3: APPROVE/DENY split tolerance — each label must hold a [40%, 60%] share
# of the corpus (a skewed/all-DENY corpus manufactures a flattering
# false-approve rate). And each case_class must clear a 15% floor so no class is
# vestigial.
LABEL_BALANCE_MIN: float = 0.40
LABEL_BALANCE_MAX: float = 0.60
CASE_CLASS_FLOOR: float = 0.15


@dataclass(frozen=True)
class LintViolation:
    """One independence-lint failure: which case, which rule, why."""

    case_id: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.case_id}: {self.detail}"


def _check_regulation_derived(case: GatedCase) -> list[LintViolation]:
    """Rule 1 — flag a rationale that quotes/paraphrases regulation text."""
    violations: list[LintViolation] = []
    for label, pattern in REGULATION_PATTERNS:
        match = pattern.search(case.designed_rationale)
        if match is not None:
            violations.append(
                LintViolation(
                    case_id=case.case_id,
                    rule=RULE_REGULATION_DERIVED,
                    detail=(
                        f"designed_rationale matches regulation pattern "
                        f"{label!r} ({match.group(0)!r}); the label must state the "
                        f"pattern ('this is a BEC pattern'), not cite a regulation"
                    ),
                )
            )
    return violations


def _check_verifier_provenance(case: GatedCase) -> list[LintViolation]:
    """Rule 2 — belt-and-suspenders: provenance must be in the allowed set.

    ``verifier`` is the circularity trap (spec §2 source #4) and is not even an
    allowed enum value; this asserts the loaded value is one of the allowed
    provenances so any drift (incl. a hand-edited fixture) is caught here too.
    """
    if case.label_provenance not in _LABEL_PROVENANCES:
        return [
            LintViolation(
                case_id=case.case_id,
                rule=RULE_VERIFIER_PROVENANCE,
                detail=(
                    f"label_provenance {case.label_provenance!r} is not in the "
                    f"allowed set {list(_LABEL_PROVENANCES)} (a verifier-derived "
                    f"label would be circular)"
                ),
            )
        ]
    return []


def _check_grounding(case: GatedCase) -> list[LintViolation]:
    """Rule 4 — every case needs ≥1 source_ref or it can't be independence-checked."""
    if not case.source_refs:
        return [
            LintViolation(
                case_id=case.case_id,
                rule=RULE_GROUNDING,
                detail="source_refs is empty; a case with no source cannot be "
                "independence-checked",
            )
        ]
    return []


def _check_balance(cases: list[GatedCase]) -> list[LintViolation]:
    """Rule 3 — corpus-level: APPROVE/DENY split + per-case-class floor.

    Corpus-level violations carry ``case_id="<corpus>"`` since they describe the
    whole set, not one case.
    """
    violations: list[LintViolation] = []
    total = len(cases)
    if total == 0:
        return [
            LintViolation(
                case_id="<corpus>",
                rule=RULE_BALANCE,
                detail="empty corpus; cannot establish a balanced answer key",
            )
        ]

    label_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    for case in cases:
        label_counts[case.designed_label] = label_counts.get(case.designed_label, 0) + 1
        class_counts[case.case_class] = class_counts.get(case.case_class, 0) + 1

    # Both labels must be present and each within [MIN, MAX] of the total.
    for label in ("APPROVE", "DENY"):
        share = label_counts.get(label, 0) / total
        if not (LABEL_BALANCE_MIN <= share <= LABEL_BALANCE_MAX):
            violations.append(
                LintViolation(
                    case_id="<corpus>",
                    rule=RULE_BALANCE,
                    detail=(
                        f"{label} share {share:.1%} "
                        f"({label_counts.get(label, 0)}/{total}) is outside the "
                        f"allowed [{LABEL_BALANCE_MIN:.0%}, {LABEL_BALANCE_MAX:.0%}] "
                        f"band; a skewed corpus manufactures a flattering "
                        f"false-approve rate"
                    ),
                )
            )

    # Each present case_class must clear the floor.
    for case_class, count in sorted(class_counts.items()):
        share = count / total
        if share < CASE_CLASS_FLOOR:
            violations.append(
                LintViolation(
                    case_id="<corpus>",
                    rule=RULE_BALANCE,
                    detail=(
                        f"case_class {case_class!r} share {share:.1%} "
                        f"({count}/{total}) is below the {CASE_CLASS_FLOOR:.0%} "
                        f"floor; the corpus is not adequately stratified"
                    ),
                )
            )
    return violations


def lint_corpus(cases: list[GatedCase]) -> list[LintViolation]:
    """Run every independence rule over a corpus; return ALL violations.

    Empty list == clean. Does NOT stop at the first violation — the CI gate and
    tests want the complete picture (every leaky case + every imbalance).
    """
    violations: list[LintViolation] = []
    for case in cases:
        violations.extend(_check_regulation_derived(case))
        violations.extend(_check_verifier_provenance(case))
        violations.extend(_check_grounding(case))
    violations.extend(_check_balance(cases))
    return violations


def assert_corpus_independent(cases: list[GatedCase]) -> None:
    """Raise with every violation if the corpus is not provably independent.

    The hard gate used by the measurement harness (build 07 §3) and CI: if any
    rule fires, raise ``AssertionError`` listing all of them.
    """
    violations = lint_corpus(cases)
    if violations:
        lines = "\n".join(f"  - {v}" for v in violations)
        raise AssertionError(
            f"independence lint FAILED ({len(violations)} violation(s)); "
            f"the corpus is NOT a provably-independent answer key (ADR-0011):\n"
            f"{lines}"
        )


def _main() -> int:
    """CI exit-gate entry point. 0 = clean, 1 = violations (build fails)."""
    cases = load_corpus()
    violations = lint_corpus(cases)
    if violations:
        print(
            f"independence_lint: FAIL — {len(violations)} violation(s) "
            f"on {len(cases)} case(s) (ADR-0011):",
            file=sys.stderr,
        )
        for v in violations:
            print(f"  - {v}", file=sys.stderr)
        return 1
    print(
        f"independence_lint: PASS — {len(cases)} case(s) carry a "
        f"provably-independent answer key (ADR-0011)."
    )
    print(f"corpus_stats: {corpus_stats(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
