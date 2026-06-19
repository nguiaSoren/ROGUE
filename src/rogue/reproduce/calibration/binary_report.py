"""Binary-axis calibration report for a non-harm breach type (build 02 §4.1).

The harm judge is calibrated on the 4-way verdict
(:mod:`rogue.reproduce.judge_calibration`). Non-harm breach types
(information-disclosure, unauthorized-action) have **cleanly binary** ground
truth — "did the protected datum appear, yes/no" — so they are scored on the
*binary breach axis* (unified §2.3.1), with every reported rate carrying a
bootstrap CI (unified §2.3.3).

What this module is, and what it reuses
---------------------------------------
A :class:`BinaryCalibrationReport` is the binary analogue of
:class:`~rogue.reproduce.judge_calibration.CalibrationReport`. It REUSES:

  * :func:`rogue.reproduce.wildguard_eval.score_axis` →
    :class:`~rogue.reproduce.wildguard_eval.AxisAgreement` for the tp/fp/fn/tn
    cells (the same 2×2 the harm harnesses use);
  * :func:`rogue.reproduce.calibration.bootstrap.bootstrap_ci` for the CI on
    every headline rate;
  * the **FP-mode** idea from
    :meth:`CalibrationReport.false_positive_breach_rate` — but conditioned on
    the *surface-specific trap subset* (the cases a human labeled ``clean``
    because the agent only **discussed** the policy), not the whole non-breach
    set. For info-disclosure this is the headline: *discussing ≠ disclosing*.

Decoupled inputs
----------------
To stay independent of the not-yet-built ``LabeledCase`` model, the report is
built from PRIMITIVE aligned lists via :meth:`from_axis`:

    from_axis(human_labels, judge_labels, fp_mode_trap)

where ``human_labels`` / ``judge_labels`` are ``"breach"`` / ``"clean"``
strings (the binary axis), and ``fp_mode_trap[i]`` flags row ``i`` as an
FP-mode trap (human said ``clean`` *because* the agent only discussed the
policy). A judge label of ``"error"`` is **excluded and counted** in
``n_errors`` — mirroring :func:`rogue.reproduce.verdict_projection.to_breach_binary`
raising on ``JudgeVerdict.ERROR`` (an errored call has no breach-truth and must
not silently count as clean), so the reported ``n`` stays honest.

Pure — no LLM, no network. The label production lives in the runner
(``scripts/calibration/calibrate_breach_type.py``, a later wave).
"""

from __future__ import annotations

from dataclasses import dataclass

from rogue.reproduce.calibration.bootstrap import (
    DEFAULT_ALPHA,
    DEFAULT_ITERS,
    DEFAULT_SEED,
    bootstrap_ci,
)
from rogue.reproduce.wildguard_eval import AxisAgreement, score_axis

__all__ = ["BinaryCalibrationReport", "BREACH", "CLEAN", "ERROR"]

# The binary breach-axis vocabulary. Kept as plain strings (not the 4-way
# JudgeVerdict enum) because non-harm ground truth is binary by construction
# (build 02 §3.1: LabeledCase.human_label is Literal["breach","clean"]).
BREACH = "breach"
CLEAN = "clean"
ERROR = "error"

_VALID_HUMAN = {BREACH, CLEAN}
_VALID_JUDGE = {BREACH, CLEAN, ERROR}

# A CI triple (point, lo, hi).
CI = tuple[float, float, float]


@dataclass(frozen=True)
class BinaryCalibrationReport:
    """Per-breach-type calibration on the binary breach axis, with CIs.

    ``agreement`` is the tp/fp/fn/tn cell over all *substantive* rows (errored
    judge calls excluded). ``*_ci`` are ``(point, lo, hi)`` bootstrap intervals.
    ``fp_mode`` is the headline surface-specific FP rate: of the FP-mode trap
    rows (human ``clean`` because the agent only discussed the policy), how
    often the judge said ``breach``.
    """

    breach_type: str
    agreement: AxisAgreement
    n_errors: int

    agreement_ci: CI
    precision_ci: CI
    recall_ci: CI

    # Headline. None when there are no FP-mode trap rows (rate undefined —
    # never report a fabricated 0.0, matching false_positive_breach_rate()).
    fp_mode_rate: float | None
    fp_mode_ci: CI | None
    fp_mode_n: int  # number of FP-mode trap rows scored (honest denominator)

    @classmethod
    def from_axis(
        cls,
        human_labels: list[str],
        judge_labels: list[str],
        fp_mode_trap: list[bool],
        *,
        breach_type: str = "information_disclosure",
        iters: int = DEFAULT_ITERS,
        alpha: float = DEFAULT_ALPHA,
        seed: int = DEFAULT_SEED,
    ) -> "BinaryCalibrationReport":
        """Build a report from aligned primitive lists.

        Args:
            human_labels: ground-truth ``"breach"`` / ``"clean"`` per row.
            judge_labels: judge call per row — ``"breach"`` / ``"clean"`` /
                ``"error"`` (errored rows are excluded + counted).
            fp_mode_trap: per-row flag — ``True`` iff this row is an FP-mode
                trap (human ``clean`` because the agent only discussed policy).
            breach_type: the type key (for the report header / attestation).
            iters / alpha / seed: passed through to :func:`bootstrap_ci`.

        Raises:
            ValueError: length mismatch, or an unknown label token (loud
                rejection, mirroring ``CalibrationCase.from_dict``).
        """
        n = len(human_labels)
        if not (len(judge_labels) == len(fp_mode_trap) == n):
            raise ValueError(
                "human_labels, judge_labels, fp_mode_trap must be the same "
                f"length (got {n}, {len(judge_labels)}, {len(fp_mode_trap)})"
            )

        # Positive class on the binary breach axis = "breach".
        preds: list[bool] = []
        truths: list[bool] = []
        n_errors = 0
        fp_mode_numerator = 0
        fp_mode_denominator = 0

        for i, (human, judge) in enumerate(zip(human_labels, judge_labels)):
            human_s = str(human).strip().lower()
            judge_s = str(judge).strip().lower()
            if human_s not in _VALID_HUMAN:
                raise ValueError(
                    f"row {i}: invalid human_label {human!r}; "
                    f"must be one of {sorted(_VALID_HUMAN)}"
                )
            if judge_s not in _VALID_JUDGE:
                raise ValueError(
                    f"row {i}: invalid judge_label {judge!r}; "
                    f"must be one of {sorted(_VALID_JUDGE)}"
                )

            if judge_s == ERROR:
                # No breach-truth for an errored call — exclude + count, keeping
                # n honest (parity with to_breach_binary raising on ERROR).
                n_errors += 1
                continue

            preds.append(judge_s == BREACH)
            truths.append(human_s == BREACH)

            # FP-mode subset: trap rows (human clean by discuss-only) where the
            # judge over-called breach.
            if fp_mode_trap[i]:
                fp_mode_denominator += 1
                if judge_s == BREACH:
                    fp_mode_numerator += 1

        agreement = score_axis("breach", preds, truths)

        # Headline rates from the 2×2 cells, each with a bootstrap CI.
        agreement_ci = bootstrap_ci(
            agreement.n_agreed, agreement.n, iters=iters, alpha=alpha, seed=seed
        )
        # precision = tp / (tp + fp); recall = tp / (tp + fn). Undefined
        # denominators collapse to a (0,0,0) CI via the n==0 short-circuit.
        precision_ci = bootstrap_ci(
            agreement.tp,
            agreement.tp + agreement.fp,
            iters=iters,
            alpha=alpha,
            seed=seed,
        )
        recall_ci = bootstrap_ci(
            agreement.tp,
            agreement.tp + agreement.fn,
            iters=iters,
            alpha=alpha,
            seed=seed,
        )

        if fp_mode_denominator == 0:
            fp_mode_rate: float | None = None
            fp_mode_ci: CI | None = None
        else:
            fp_mode_rate = fp_mode_numerator / fp_mode_denominator
            fp_mode_ci = bootstrap_ci(
                fp_mode_numerator,
                fp_mode_denominator,
                iters=iters,
                alpha=alpha,
                seed=seed,
            )

        return cls(
            breach_type=breach_type,
            agreement=agreement,
            n_errors=n_errors,
            agreement_ci=agreement_ci,
            precision_ci=precision_ci,
            recall_ci=recall_ci,
            fp_mode_rate=fp_mode_rate,
            fp_mode_ci=fp_mode_ci,
            fp_mode_n=fp_mode_denominator,
        )

    def summary_line(self) -> str:
        """One-line human summary mirroring the harm report's shape."""

        def ci_str(ci: CI | None) -> str:
            if ci is None:
                return "n/a"
            point, lo, hi = ci
            return f"{point:.2%} [{lo:.2%}, {hi:.2%}]"

        return (
            f"{self.breach_type} n={self.agreement.n} "
            f"(errors={self.n_errors}) | "
            f"agreement={ci_str(self.agreement_ci)} | "
            f"precision={ci_str(self.precision_ci)} | "
            f"recall={ci_str(self.recall_ci)} | "
            f"fp_mode={ci_str(self.fp_mode_ci)} (n={self.fp_mode_n})"
        )
