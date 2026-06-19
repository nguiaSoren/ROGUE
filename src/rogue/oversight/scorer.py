"""Surface 2 scorer — aggregate reviewer decisions into a false-approve /
false-deny rate, each with a bootstrap CI (build 07 §2, ADR-0011).

This is the human analogue of ``reproduce/judge_calibration.py``: where the
judge calibrator scores a model-grader against hand labels, this scores a human
reviewer's dispositions against the *designed-label corpus* — the answer key
that is provably independent of the regulation, the votes, and the verifier
(the independence invariant, ``case_corpus.py`` header). The reviewer's decision
is compared to ``GatedCase.designed_label`` directly; there is no LLM grading
the human's reasoning (build 07 §2 disposition-judge note).

The headline number — the **false-approve rate** — is structurally
``CalibrationReport.false_positive_breach_rate`` conditioned on human-DENY-truth
cases: of the decisions made on cases the key says should be DENIED, how often
did the reviewer wrongly APPROVE? Its mirror, the **false-deny rate**, is over
APPROVE-truth cases. Both carry a percentile-bootstrap CI via
``diff/bootstrap.py`` ``bootstrap_ci`` (REUSED directly, locked ``DEFAULT_SEED``
so the interval is reproducible), and ``format_ci`` renders the brief line.

Cell definitions (must match ``disposition_judge`` — build 07 §2 EXIT GATE):

    FALSE_APPROVE = decision == APPROVE and designed_label == DENY
    FALSE_DENY    = decision == DENY    and designed_label == APPROVE
    TRUE_APPROVE  = decision == APPROVE and designed_label == APPROVE
    TRUE_DENY     = decision == DENY    and designed_label == DENY

Engagement ≠ breach: deliberation notes / latency are NOT scored here — only
``decision`` vs ``designed_label`` determines the cell (spec §1).
"""

from __future__ import annotations

from dataclasses import dataclass

from rogue.diff.bootstrap import DEFAULT_SEED, bootstrap_ci, format_ci
from rogue.oversight.case_corpus import GatedCase, GatedDecision

__all__ = ["OversightReport", "score"]


@dataclass(frozen=True)
class OversightReport:
    """Outcome of one :func:`score` run — the human-gate headline numbers.

    ``false_approve_rate`` is the per-case wrong-approval rate over the
    DENY-truth decisions (its denominator is ``n_deny_truth``, NOT all
    decisions); ``false_deny_rate`` is the wrong-denial rate over the
    APPROVE-truth decisions. ``fa_ci`` / ``fd_ci`` are the percentile-bootstrap
    95% CIs of those rates (locked seed → reproducible). ``confusion`` carries
    the four cell counts.
    """

    n_decisions: int

    n_deny_truth: int
    n_false_approve: int
    false_approve_rate: float
    fa_ci: tuple[float, float]

    n_approve_truth: int
    n_false_deny: int
    false_deny_rate: float
    fd_ci: tuple[float, float]

    confusion: dict  # {true_approve, false_approve, true_deny, false_deny}

    def summary_line(self) -> str:
        """One-line brief: false-approve + false-deny rates with CIs + n's.

        Example: ``"false-approve 33% [3%, 67%] (n=3 deny-truth) | false-deny
        33% [3%, 67%] (n=3 approve-truth)"``. Uses ``format_ci`` for each rate.
        """
        fa = format_ci(self.false_approve_rate, *self.fa_ci)
        fd = format_ci(self.false_deny_rate, *self.fd_ci)
        return (
            f"false-approve {fa} (n={self.n_deny_truth} deny-truth) | "
            f"false-deny {fd} (n={self.n_approve_truth} approve-truth)"
        )


def score(decisions: list[GatedDecision], cases: list[GatedCase]) -> OversightReport:
    """Aggregate reviewer ``decisions`` against the corpus answer key.

    Each :class:`GatedDecision` is joined to its :class:`GatedCase` by
    ``case_id``. A decision whose ``case_id`` is not in ``cases`` is a corpus
    integrity error — we raise ``KeyError`` LOUDLY rather than silently dropping
    it (a dropped decision would quietly shrink the denominator and flatter the
    rate; ADR-0011 loud-rejection discipline, mirroring ``case_corpus``).

    The false-approve rate is computed over the **DENY-truth decisions only**
    (the denominator is the count of decisions on cases the key labels DENY),
    not over all decisions — this is ``false_positive_breach_rate`` conditioned
    on human-DENY-truth. The per-case 0/1 wrong-approval vector over those
    decisions feeds :func:`bootstrap_ci` (locked :data:`DEFAULT_SEED`) for the
    CI. The false-deny rate mirrors this over APPROVE-truth decisions.
    """
    by_id: dict[str, GatedCase] = {c.case_id: c for c in cases}

    # Per-case 0/1 vectors, conditioned on the designed label (the answer key).
    fa_vector: list[int] = []  # over DENY-truth decisions: 1 == wrongly APPROVED
    fd_vector: list[int] = []  # over APPROVE-truth decisions: 1 == wrongly DENIED

    true_approve = false_approve = true_deny = false_deny = 0

    for d in decisions:
        case = by_id.get(d.case_id)
        if case is None:
            raise KeyError(
                f"decision references unknown case_id {d.case_id!r} "
                f"(not in the supplied corpus of {len(cases)} cases)"
            )

        if case.designed_label == "DENY":
            wrong_approval = 1 if d.decision == "APPROVE" else 0
            fa_vector.append(wrong_approval)
            if wrong_approval:
                false_approve += 1
            else:
                true_deny += 1
        else:  # designed_label == "APPROVE"
            wrong_denial = 1 if d.decision == "DENY" else 0
            fd_vector.append(wrong_denial)
            if wrong_denial:
                false_deny += 1
            else:
                true_approve += 1

    n_deny_truth = len(fa_vector)
    n_approve_truth = len(fd_vector)

    false_approve_rate = false_approve / n_deny_truth if n_deny_truth else 0.0
    false_deny_rate = false_deny / n_approve_truth if n_approve_truth else 0.0

    fa_ci = bootstrap_ci(fa_vector, seed=DEFAULT_SEED)
    fd_ci = bootstrap_ci(fd_vector, seed=DEFAULT_SEED)

    return OversightReport(
        n_decisions=len(decisions),
        n_deny_truth=n_deny_truth,
        n_false_approve=false_approve,
        false_approve_rate=false_approve_rate,
        fa_ci=fa_ci,
        n_approve_truth=n_approve_truth,
        n_false_deny=false_deny,
        false_deny_rate=false_deny_rate,
        fd_ci=fd_ci,
        confusion={
            "true_approve": true_approve,
            "false_approve": false_approve,
            "true_deny": true_deny,
            "false_deny": false_deny,
        },
    )
