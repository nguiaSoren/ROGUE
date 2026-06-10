"""Surface 2 scorer — hand-computed fixture + the load-bearing denominator semantics.

The false-approve rate's DENOMINATOR is the DENY-truth decisions (not all
decisions); a flattering rate is the failure mode the independence invariant exists
to stop. This suite pins the four confusion cells, both rates, and that the CIs are
present, bracket the rate, and are reproducible across reruns (locked seed).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rogue.oversight.case_corpus import GatedCase, GatedDecision
from rogue.oversight.scorer import score


def _case(case_id: str, designed_label: str) -> GatedCase:
    return GatedCase(
        case_id=case_id,
        case_class="large_wire",
        facts={"amount": "USD 1,000,000"},
        designed_label=designed_label,
        designed_rationale="this is the BEC pattern",
        label_provenance="synthetic_designed",
        source_refs=["https://example.com/x"],
    )


def _dec(case_id: str, decision: str) -> GatedDecision:
    return GatedDecision(
        case_id=case_id,
        reviewer="r",
        decision=decision,
        decided_at=datetime.now(timezone.utc),
    )


def _hand_fixture():
    """A 10-case fixture with KNOWN cells.

    5 DENY-truth cases, 5 APPROVE-truth cases.
      DENY-truth decisions:    d0..d4 — d0,d1 wrongly APPROVE → 2 false-approve;
                               d2,d3,d4 correctly DENY → 3 true-deny.
      APPROVE-truth decisions: a0..a4 — a0 wrongly DENY → 1 false-deny;
                               a1..a4 correctly APPROVE → 4 true-approve.

    Hand totals:
      n_decisions     = 10
      n_deny_truth    = 5,  false_approve = 2 → false_approve_rate = 2/5 = 0.40
      n_approve_truth = 5,  false_deny    = 1 → false_deny_rate    = 1/5 = 0.20
      confusion: true_approve=4, false_approve=2, true_deny=3, false_deny=1
    """
    cases = [_case(f"d{i}", "DENY") for i in range(5)] + [
        _case(f"a{i}", "APPROVE") for i in range(5)
    ]
    decisions = [
        _dec("d0", "APPROVE"),  # false-approve
        _dec("d1", "APPROVE"),  # false-approve
        _dec("d2", "DENY"),     # true-deny
        _dec("d3", "DENY"),     # true-deny
        _dec("d4", "DENY"),     # true-deny
        _dec("a0", "DENY"),     # false-deny
        _dec("a1", "APPROVE"),  # true-approve
        _dec("a2", "APPROVE"),  # true-approve
        _dec("a3", "APPROVE"),  # true-approve
        _dec("a4", "APPROVE"),  # true-approve
    ]
    return cases, decisions


def test_hand_computed_rates_and_cells():
    cases, decisions = _hand_fixture()
    report = score(decisions, cases)

    assert report.n_decisions == 10

    assert report.n_deny_truth == 5
    assert report.n_false_approve == 2
    assert report.false_approve_rate == pytest.approx(0.40)

    assert report.n_approve_truth == 5
    assert report.n_false_deny == 1
    assert report.false_deny_rate == pytest.approx(0.20)

    assert report.confusion == {
        "true_approve": 4,
        "false_approve": 2,
        "true_deny": 3,
        "false_deny": 1,
    }


def test_false_approve_denominator_is_deny_truth_not_all_decisions():
    """The denominator MUST be DENY-truth decisions, never all decisions.

    Here: 2 false-approves out of 5 DENY-truth = 0.40. Over all 10 decisions it
    would be a flattering 0.20. The invariant exists to prevent exactly that dilution.
    """
    cases, decisions = _hand_fixture()
    report = score(decisions, cases)
    assert report.false_approve_rate == pytest.approx(2 / report.n_deny_truth)
    assert report.false_approve_rate != pytest.approx(2 / report.n_decisions)
    # And the denominator is exactly the DENY-truth count.
    assert report.n_deny_truth == sum(1 for c in cases if c.designed_label == "DENY")


def test_cis_present_and_bracket_the_rate():
    cases, decisions = _hand_fixture()
    report = score(decisions, cases)
    for rate, ci in (
        (report.false_approve_rate, report.fa_ci),
        (report.false_deny_rate, report.fd_ci),
    ):
        lo, hi = ci
        assert 0.0 <= lo <= hi <= 1.0
        assert lo <= rate <= hi, (rate, ci)


def test_ci_reproducible_across_reruns():
    cases, decisions = _hand_fixture()
    r1 = score(decisions, cases)
    r2 = score(decisions, cases)
    # Locked DEFAULT_SEED → bit-identical CIs on rerun.
    assert r1.fa_ci == r2.fa_ci
    assert r1.fd_ci == r2.fd_ci


def test_unknown_case_id_raises_loudly():
    cases, _ = _hand_fixture()
    bogus = [_dec("does-not-exist", "APPROVE")]
    with pytest.raises(KeyError, match="unknown case_id"):
        score(bogus, cases)


def test_summary_line_shape():
    cases, decisions = _hand_fixture()
    report = score(decisions, cases)
    line = report.summary_line()
    assert "false-approve" in line
    assert "false-deny" in line
    assert "deny-truth" in line
    assert "approve-truth" in line
    # The rendered rate matches the computed one.
    assert "40%" in line  # false-approve 2/5
    assert "20%" in line  # false-deny 1/5


def test_zero_division_safe_when_no_deny_truth():
    # All APPROVE-truth → no DENY-truth decisions; false_approve_rate is 0.0, not NaN.
    cases = [_case(f"a{i}", "APPROVE") for i in range(3)]
    decisions = [_dec(f"a{i}", "APPROVE") for i in range(3)]
    report = score(decisions, cases)
    assert report.n_deny_truth == 0
    assert report.false_approve_rate == 0.0
    assert report.fa_ci == (0.0, 0.0)
