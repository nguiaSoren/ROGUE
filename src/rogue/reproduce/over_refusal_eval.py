"""Over-refusal / False-Refusal-Rate (FRR) evaluation — the "safeguard board".

Why this exists (the helpfulness-cost companion to the robustness board)
-----------------------------------------------------------------------
The committed robustness leaderboard ranks models by how often they *break* under
attack (breach rate). A model that refuses everything scores perfectly there while
being useless — so a breach board alone rewards over-caution. This module measures
the other side of the same trade-off: the **False Refusal Rate (FRR)** — the fraction
of *benign, should-answer* look-alike prompts a model wrongly declines. Paired with
the breach board it is a first-of-its-kind, comparable safeguard metric (nobody
publishes breach-rate + over-refusal-rate side by side), and it is the "safeguard
board" CLAUDE.md's LinkedIn angles already name.

FRR definition (locked)
-----------------------
For a panel of benign prompts a *good* model should ANSWER:

    FRR = (# benign prompts the model OVER-BLOCKED) / (# benign prompts scored)

An OVER-BLOCK is a refusal/decline that gives no substantive help (the same axis
``remediation.over_block_judge`` grades). The denominator excludes errored calls
(a transport error is a coverage failure, not a refusal — counting it would inflate
FRR). Lower is better; a model with a *low* breach rate AND a *low* FRR is the
genuinely well-aligned one.

Reused machinery (this module writes no new judge, no new CI)
-------------------------------------------------------------
* the over-block *judging* is ``remediation.over_block_judge`` — the calibrated
  ``judge_over_block`` on a LIVE run, its ``heuristic_over_block`` sibling for the
  $0/offline path — injected as ``detector_fn`` (never constructed here);
* the point-estimate CI is ``sprt.wilson_interval`` (the same interval the breach
  board reports); the resample CI is ``diff.bootstrap.bootstrap_ci`` (the same one
  ``retest``'s over-block rate uses).

This module is PURE — no ``datasets``, no LLM, no network. The benign-set load and
the panel firing live in ``scripts/sweep/run_over_refusal_sweep.py`` (gated/paid);
the benign prompts themselves come from ``reproduce.benign_datasets``. ``score_model``
is therefore unit-testable with fixed ``(prompt, response)`` pairs + a stub detector.

Spec: audit-4 GAP 1 (standing over-refusal / FRR leaderboard facet).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from rogue.diff.bootstrap import bootstrap_ci
from rogue.reproduce.sprt import wilson_interval

__all__ = [
    "BenignItem",
    "ModelFrr",
    "OverRefusalReport",
    "ScoredBenignItem",
    "SetFrr",
    "score_model",
    "to_board",
]


# A detector answers: did the model OVER-BLOCK this (request, response)? True = refused a
# should-answer request. ``over_block_judge.judge_over_block`` (live) and ``heuristic_over_block``
# (offline) both satisfy this — injected, never constructed here.
OverBlockDetector = Callable[[str, str], bool]


@dataclass(frozen=True)
class BenignItem:
    """One benign, should-answer look-alike prompt (an XSTest / JBB-benign row).

    ``category`` is the benchmark's own subtype (e.g. XSTest ``homonyms`` /
    ``safe_contexts``) kept for a per-category breakdown; ``source`` names the
    benchmark so the board's provenance can never blur which set a number came from.
    """

    prompt: str
    source: str
    category: str = ""


@dataclass(frozen=True)
class ScoredBenignItem:
    """One benign prompt after firing + over-block grading.

    ``refused`` is the detector's call (True = over-blocked). ``error`` marks a
    coverage failure (no response); such rows are excluded from FRR, never scored
    as a refusal. Kept per-item so a later re-aggregation (a different detector, a
    per-category cut) is free instead of a repeat paid run.
    """

    prompt: str
    source: str
    category: str
    response: str
    refused: bool | None
    error: bool = False


@dataclass(frozen=True)
class SetFrr:
    """FRR restricted to one benign set (e.g. xstest) — the per-denominator cut."""

    source: str
    n: int
    n_refused: int

    @property
    def frr(self) -> float | None:
        return (self.n_refused / self.n) if self.n else None


@dataclass(frozen=True)
class ModelFrr:
    """One model's over-refusal result across the benign panel.

    ``n_scored`` is the FRR denominator (fired minus errored); ``frr`` = ``n_refused /
    n_scored``. ``wilson`` is the Wilson score interval (the breach board's CI); ``boot``
    is the percentile-bootstrap interval (retest's over-block CI). ``by_set`` splits the
    rate per benign benchmark so a model that only over-refuses XSTest homonyms is visible.
    """

    model: str
    n_fired: int
    n_scored: int
    n_errors: int
    n_refused: int
    wilson: tuple[float, float]
    boot: tuple[float, float]
    by_set: dict[str, SetFrr] = field(default_factory=dict)
    scored: tuple[ScoredBenignItem, ...] = ()

    @property
    def frr(self) -> float | None:
        return (self.n_refused / self.n_scored) if self.n_scored else None

    def summary_line(self) -> str:
        frr = self.frr
        frr_str = f"{frr:.1%}" if frr is not None else "n/a"
        lo, hi = self.wilson
        return (
            f"{self.model}: FRR={frr_str} [{lo:.1%}, {hi:.1%}] "
            f"({self.n_refused}/{self.n_scored} refused, {self.n_errors} errors)"
        )


@dataclass(frozen=True)
class OverRefusalReport:
    """The whole panel's FRR board — one :class:`ModelFrr` per model, ranked most-helpful first."""

    models: tuple[ModelFrr, ...]
    benign_sets: tuple[str, ...]

    def ranked(self) -> list[ModelFrr]:
        """Lowest FRR first (most helpful / least over-cautious). Models with no scored
        item (all errored) sort last — an unmeasurable FRR is not a good one."""
        return sorted(
            self.models,
            key=lambda m: (m.frr if m.frr is not None else 2.0, m.model),
        )

    def summary_line(self) -> str:
        return "over-refusal board | " + " | ".join(m.summary_line() for m in self.ranked())


def score_model(
    model: str,
    graded: list[tuple[BenignItem, str | None]],
    detector_fn: OverBlockDetector,
) -> ModelFrr:
    """Score one model's benign responses into a :class:`ModelFrr`.

    ``graded`` is ``[(item, response_text_or_None), …]`` — the runner fires the benign
    panel at the model and pairs each prompt with its response (``None`` = an errored /
    empty call). For each non-errored row the injected ``detector_fn(prompt, response)``
    decides over-block; the FRR is over scored (non-errored) rows only.

    No model is constructed here — ``detector_fn`` is the injected over-block judge
    (``over_block_judge.judge_over_block`` live, ``heuristic_over_block`` offline).
    """
    scored: list[ScoredBenignItem] = []
    n_errors = 0
    flags: list[bool] = []  # per-scored-row over-block booleans → bootstrap CI
    by_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # source -> [n_scored, n_refused]

    for item, response in graded:
        if response is None or not str(response).strip():
            n_errors += 1
            scored.append(
                ScoredBenignItem(
                    prompt=item.prompt,
                    source=item.source,
                    category=item.category,
                    response="",
                    refused=None,
                    error=True,
                )
            )
            continue
        refused = bool(detector_fn(item.prompt, response))
        flags.append(refused)
        counts = by_counts[item.source]
        counts[0] += 1
        counts[1] += int(refused)
        scored.append(
            ScoredBenignItem(
                prompt=item.prompt,
                source=item.source,
                category=item.category,
                response=response[:2500],
                refused=refused,
            )
        )

    n_scored = len(flags)
    n_refused = sum(flags)
    return ModelFrr(
        model=model,
        n_fired=len(graded),
        n_scored=n_scored,
        n_errors=n_errors,
        n_refused=n_refused,
        wilson=wilson_interval(n_refused, n_scored),
        boot=bootstrap_ci(flags),
        by_set={
            src: SetFrr(source=src, n=c[0], n_refused=c[1]) for src, c in sorted(by_counts.items())
        },
        scored=tuple(scored),
    )


def _first_refusal_sample(m: ModelFrr) -> dict | None:
    """A short, on-card example: the first benign prompt this model over-blocked (or, if it
    over-blocked none, the first it answered) — the concrete "it refused *this*?" receipt."""
    refused = next((s for s in m.scored if s.refused is True), None)
    pick = refused or next((s for s in m.scored if s.refused is False), None)
    if pick is None:
        return None
    return {
        "prompt": pick.prompt[:400],
        "source": pick.source,
        "refused": pick.refused,
        "response_excerpt": pick.response[:400],
    }


def to_board(
    report: OverRefusalReport,
    *,
    panel: str,
    detector: str,
    measured_at: str,
    note: str = "",
) -> dict:
    """Serialize a measured report into the safeguard ``board.json`` contract.

    Mirrors ``data/robustness/leaderboard_advbench.json`` in shape (a ``board`` map of
    model -> stats) but keyed to the FRR metric, and carries the ``status: "measured"``
    the frontend reads to switch out of the pending/empty state. ``round`` keeps the
    JSON stable across reruns. No numbers are invented — every field traces to ``report``.
    """
    board: dict[str, dict] = {}
    for m in report.ranked():
        lo, hi = m.wilson
        blo, bhi = m.boot
        board[m.model] = {
            "n": m.n_scored,
            "n_fired": m.n_fired,
            "n_errors": m.n_errors,
            "n_refused": m.n_refused,
            "frr": round(m.frr, 4) if m.frr is not None else None,
            "wilson_ci": [round(lo, 4), round(hi, 4)],
            "bootstrap_ci": [round(blo, 4), round(bhi, 4)],
            "by_set": {
                src: {
                    "n": s.n,
                    "n_refused": s.n_refused,
                    "frr": round(s.frr, 4) if s.frr is not None else None,
                }
                for src, s in m.by_set.items()
            },
            "sample": _first_refusal_sample(m),
        }
    return {
        "facet": "safeguard",
        "metric": "false_refusal_rate",
        "status": "measured",
        "measured_at": measured_at,
        "panel": panel,
        "detector": detector,
        "benign_sets": list(report.benign_sets),
        "note": note,
        "board": board,
    }


def pending_board(
    *,
    benign_sets: tuple[str, ...],
    note: str = (
        "Measurement pending — no approved paid run has populated this board yet. "
        "Run scripts/sweep/run_over_refusal_sweep.py --go to measure."
    ),
) -> dict:
    """The honest empty state (marketing-honesty filter): the schema the frontend renders
    before any paid run, carrying ``status: "pending"`` and an EMPTY ``board`` — never a
    fabricated number. Same top-level shape as :func:`to_board` so the frontend reads one
    contract for both states."""
    return {
        "facet": "safeguard",
        "metric": "false_refusal_rate",
        "status": "pending",
        "measured_at": None,
        "panel": None,
        "detector": None,
        "benign_sets": list(benign_sets),
        "note": note,
        "board": {},
    }
