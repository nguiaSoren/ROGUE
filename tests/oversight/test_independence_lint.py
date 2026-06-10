"""Surface 2 independence lint — the ADR-0011 canary (build 07 §1).

The whole product rests on this: the headline false-approve number is only worth
signing if the answer key is provably independent of (a) the regulation text,
(b) the reviewers' votes, and (c) the verifier model's opinion. This suite proves
the REAL corpus passes, then SEEDS each forbidden shape and proves the lint catches
it — and that ``lint_corpus`` returns EVERY violation, never stops at the first.
"""

from __future__ import annotations

import pytest

from rogue.oversight.case_corpus import GatedCase, load_corpus
from rogue.oversight.independence_lint import (
    RULE_BALANCE,
    RULE_GROUNDING,
    RULE_REGULATION_DERIVED,
    assert_corpus_independent,
    lint_corpus,
)


def _case(
    case_id: str,
    *,
    case_class: str = "large_wire",
    designed_label: str = "DENY",
    rationale: str = "this is the vendor-email-compromise BEC pattern",
    provenance: str = "synthetic_designed",
    source_refs: list[str] | None = None,
) -> GatedCase:
    return GatedCase(
        case_id=case_id,
        case_class=case_class,
        facts={"amount": "USD 1,000,000"},
        designed_label=designed_label,
        designed_rationale=rationale,
        label_provenance=provenance,
        source_refs=source_refs if source_refs is not None else ["https://example.com/x"],
    )


def _balanced_clean_corpus() -> list[GatedCase]:
    """A small balanced+stratified clean corpus (passes every rule)."""
    cases: list[GatedCase] = []
    classes = ["large_wire", "high_value_refund", "vendor_change"]
    # 12 cases: 6 DENY / 6 APPROVE, 4 per class → all shares == 33% (>= 15% floor),
    # label split 50/50 (within [40,60]).
    for i in range(12):
        cases.append(
            _case(
                f"c-{i:03d}",
                case_class=classes[i % 3],
                designed_label="DENY" if i % 2 == 0 else "APPROVE",
            )
        )
    return cases


# --- the real corpus is clean -------------------------------------------------- #


def test_real_corpus_passes_independence():
    cases = load_corpus()
    # Must not raise.
    assert_corpus_independent(cases)
    assert lint_corpus(cases) == []


def test_synthetic_clean_corpus_passes():
    assert lint_corpus(_balanced_clean_corpus()) == []


# --- (a) regulation-derived label is caught ------------------------------------ #


@pytest.mark.parametrize(
    "rationale",
    [
        "violates 31 CFR §1010 reporting requirements",
        "this transfer violates the bank's policy",
        "prohibited under 18 U.S.C 1956",
        "breaches Article 12 of the directive",
        "fails Section 314 due diligence",
        "contravenes policy #4471",
    ],
)
def test_regulation_derived_label_is_caught(rationale):
    bad = _case("reg-001", rationale=rationale)
    violations = lint_corpus([bad] + _balanced_clean_corpus())
    reg = [v for v in violations if v.rule == RULE_REGULATION_DERIVED]
    assert reg, f"expected a regulation-derived violation for {rationale!r}"
    assert all(v.case_id == "reg-001" for v in reg)


# --- (b) all-DENY corpus is caught (balance) ----------------------------------- #


def test_all_deny_corpus_is_caught():
    cases = [_case(f"d-{i}", designed_label="DENY") for i in range(10)]
    violations = lint_corpus(cases)
    balance = [v for v in violations if v.rule == RULE_BALANCE]
    assert balance, "an all-DENY corpus must trip the balance rule"
    # The APPROVE share (0%) is outside [40%, 60%].
    assert any("APPROVE share" in v.detail for v in balance)


# --- (c) missing case-class / skew past the floor is caught (balance) ---------- #


def test_skewed_case_class_below_floor_is_caught():
    # 19 large_wire + 1 vendor_change → vendor_change share 5% < 15% floor.
    # Keep label balance clean so ONLY the floor trips.
    cases = [
        _case(f"lw-{i}", case_class="large_wire", designed_label="DENY" if i % 2 else "APPROVE")
        for i in range(19)
    ]
    cases.append(_case("vc-0", case_class="vendor_change", designed_label="DENY"))
    violations = lint_corpus(cases)
    floor = [v for v in violations if v.rule == RULE_BALANCE and "floor" in v.detail]
    assert floor, "a case_class below the 15% floor must trip the balance rule"
    assert any("vendor_change" in v.detail for v in floor)


def test_empty_corpus_is_caught():
    violations = lint_corpus([])
    assert any(v.rule == RULE_BALANCE for v in violations)


# --- (d) belt-and-suspenders: a non-allowed provenance is rejected at the model - #


def test_non_allowed_provenance_rejected_at_gatedcase_layer():
    # The forbidden "verifier" provenance can't even be constructed (Literal +
    # from_dict loud-reject) — so a verifier-derived label is not representable.
    with pytest.raises(Exception):
        GatedCase(
            case_id="v-1",
            case_class="large_wire",
            facts={"amount": "x"},
            designed_label="DENY",
            designed_rationale="ok",
            label_provenance="verifier",  # type: ignore[arg-type]
            source_refs=["https://example.com/x"],
        )
    with pytest.raises(ValueError, match="label_provenance"):
        GatedCase.from_dict(
            {
                "case_id": "v-1",
                "case_class": "large_wire",
                "facts": {"amount": "x"},
                "designed_label": "DENY",
                "designed_rationale": "ok",
                "label_provenance": "verifier",
                "source_refs": ["https://example.com/x"],
            }
        )


# --- lint returns ALL violations, not just the first --------------------------- #


def test_lint_returns_all_violations_not_just_first():
    # Two distinct leaky cases + a corpus imbalance — every one must surface.
    bad1 = _case("bad-1", rationale="violates 31 CFR §1010")  # regulation (2 patterns: CFR + §)
    bad2 = _case("bad-2", rationale="prohibited under 18 U.S.C 1956")  # regulation
    cases = [bad1, bad2] + [_case(f"d-{i}", designed_label="DENY") for i in range(8)]
    # This corpus is all-DENY too → balance also trips.
    violations = lint_corpus(cases)

    rules = {v.rule for v in violations}
    case_ids = {v.case_id for v in violations}
    assert RULE_REGULATION_DERIVED in rules
    assert RULE_BALANCE in rules
    # Both leaky cases are reported (not stopped after the first).
    assert {"bad-1", "bad-2"} <= case_ids
    # bad-1 cites both a CFR number AND a § sign → at least 2 regulation hits on it.
    bad1_reg = [
        v for v in violations
        if v.case_id == "bad-1" and v.rule == RULE_REGULATION_DERIVED
    ]
    assert len(bad1_reg) >= 2


def test_assert_raises_with_all_violations_listed():
    cases = [_case(f"d-{i}", designed_label="DENY") for i in range(6)]
    cases[0] = _case("d-0", designed_label="DENY", rationale="violates §99")
    with pytest.raises(AssertionError) as exc:
        assert_corpus_independent(cases)
    msg = str(exc.value)
    assert "independence lint FAILED" in msg
    assert RULE_REGULATION_DERIVED in msg or "regulation" in msg
    assert RULE_BALANCE in msg or "balance" in msg


def test_grounding_rule_name_exported():
    # Smoke: the grounding rule is wired (empty source_refs is blocked at the model
    # layer, so this confirms the rule constant exists for the lint surface).
    assert RULE_GROUNDING == "grounding-present"
