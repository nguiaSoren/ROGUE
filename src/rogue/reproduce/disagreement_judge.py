"""DisagreementJudge — flag a breach the strict grading bracket won't confirm as low-confidence.

Companion to the artifact-robustness probe (Q5). Where that probe measures
*offline* how much a benign artifact can fool the judge (ΔFNR), this wrapper
surfaces per-cell judge uncertainty *live*: ROGUE's judge already ships a
conservative **strict bracket** (``JudgeAgent(strict=True)`` — the same rubric
with an under-flagging preamble, `reproduce/judge.py` ``_STRICT_PREAMBLE``), used
today only in the calibration harness as a "crude ensemble." Here we put it to
work at scan time.

The signal — a *bracket-fragile breach*. When the primary judge calls a cell a
breach, we re-grade that one cell with the strict bracket. If the strict grader
does **not** confirm the breach, the verdict sits on the boundary between the
primary and the conservative grader: it is a **low-confidence breach**. We do
not change the headline verdict (the primary still decides — the strict grade
never *creates* or *removes* a breach); we only stamp the cell so the matrix and
threat brief can show that this particular breach is judge-fragile. This
operationalises the Eiras/Chen finding that a safety judge's verdicts carry real
uncertainty a single grade hides, and gives the judge-reliability work a live
per-cell robustness flag to sit alongside the offline ΔFNR column.

Why only breach cells (the asymmetry + the cost bound). A red-team's expensive
error is a spurious breach inflating the board (Schwinn 2603.06594: attacks
"inflate their success rates by exploiting judge insufficiencies"). Re-grading
every *non-breach* cell to hunt false negatives would roughly double the judge
cost of a whole scan; re-grading only the (rare) breach cells bounds the extra
spend to ``#breaches × 1`` strict grade — small, since breaches are the minority
outcome. The permissive-bracket direction (does a primary *non-breach* become a
breach under the over-flagging grader — i.e. an induced false negative) is the
natural extension and is exactly what the paid cross-bracket arm measures on a
balanced labeled slice; it is deliberately out of the live path here.

Design (mirrors :class:`~rogue.reproduce.cascade_judge.CascadeJudge`):
  * **Transparent proxy** — presents ``JudgeAgent``'s async ``judge`` / sync
    ``judge_sync`` and forwards every other attribute to the wrapped judge
    (``__getattr__``), so it drops in wherever a ``JudgeAgent`` is used.
  * **Lazy strict sibling** — a second ``JudgeAgent(..., strict=True)`` built on
    first use from the wrapped judge's own ``model`` / ``breach_type`` /
    ``prompt_version``, so the strict grade is the identical rubric under the
    conservative preamble. The strict grade may **never fail a scan**: any error
    just means "no disagreement info" (the cell is left unflagged), exactly like
    the cascade's cheap tier can only ever *save* a scan.
  * **Off by default** — :func:`resolve_disagreement` returns the base judge
    untouched unless ``ROGUE_JUDGE_DISAGREEMENT`` is on, so every surface is
    byte-identical (no extra call, rationale unchanged) until the flag is set.
    Only wraps a real LLM judge (one exposing ``.model``); a keyless
    ``HeuristicJudge`` base is returned as-is (there is no strict heuristic
    bracket to disagree with).

The flag is carried in the ``JudgeResult.rationale`` as a
``[JUDGE_UNCERTAIN:strict=<verdict>]`` prefix — the same lightweight,
no-migration surfacing the existing ``[JUDGE_REFUSED→<model>]`` flag uses, so it
flows through ``breach_results.judge_rationale`` to the matrix / API / MCP /
dashboard for free.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from rogue.reproduce.judge import JudgeResult
from rogue.schemas.breach_result import BREACH_VERDICTS

_log = logging.getLogger(__name__)

ENV_DISAGREEMENT = "ROGUE_JUDGE_DISAGREEMENT"     # off (default) | on
UNCERTAIN_FLAG_PREFIX = "[JUDGE_UNCERTAIN:strict="  # rationale marker; closed with "] "


@dataclass
class DisagreementStats:
    """Live counters — how many breaches the strict bracket confirmed vs flagged.
    Pure telemetry; the headline verdict is never changed by this wrapper."""

    n_total: int = 0            # cells graded
    n_breaches: int = 0         # primary called a breach (⇒ strict re-grade fired)
    n_confirmed: int = 0        # strict bracket also called a breach (robust)
    n_flagged: int = 0          # strict bracket did NOT confirm (bracket-fragile)
    n_strict_errors: int = 0    # strict grade errored → left unflagged (no info)

    @property
    def fragile_rate(self) -> float:
        """Fraction of breaches the strict bracket wouldn't confirm."""
        return self.n_flagged / self.n_breaches if self.n_breaches else 0.0

    def summary(self) -> str:
        return (
            f"judge disagreement: {self.n_flagged}/{self.n_breaches} breaches "
            f"flagged low-confidence (strict bracket disagreed), "
            f"{self.n_confirmed} confirmed"
            + (f", {self.n_strict_errors} strict-errors" if self.n_strict_errors else "")
        )


def is_uncertain(rationale: str | None) -> bool:
    """True iff a rationale carries the bracket-disagreement flag (matrix/report helper)."""
    return bool(rationale) and UNCERTAIN_FLAG_PREFIX in rationale


class DisagreementJudge:
    """Wrap an LLM ``JudgeAgent``; flag any breach the strict bracket won't confirm.

    Args:
        llm: the primary calibrated judge (``JudgeAgent`` or a proxy of one,
            e.g. a ``CascadeJudge``). Must expose ``.model``; ``.breach_type`` /
            ``.prompt_version`` are read to build the matching strict sibling.
    """

    def __init__(self, llm: Any) -> None:
        self._llm = llm
        self._strict: Any | None = None  # lazy — built on first breach
        self.stats = DisagreementStats()

    def _strict_judge(self) -> Any:
        """Build (once) the strict-bracket sibling of the wrapped judge."""
        if self._strict is None:
            from rogue.reproduce.judge import JudgeAgent  # noqa: PLC0415 — lazy, avoids import cycle

            self._strict = JudgeAgent(
                model=getattr(self._llm, "model", None),
                breach_type=getattr(self._llm, "breach_type", "capability_transfer"),
                prompt_version=getattr(self._llm, "prompt_version", "v3"),
                strict=True,
            )
        return self._strict

    def _stamp(self, result: JudgeResult, strict_verdict: str) -> JudgeResult:
        """Prefix the rationale with the uncertainty flag (verdict + rationale unchanged otherwise)."""
        flag = f"{UNCERTAIN_FLAG_PREFIX}{strict_verdict}] "
        return result.model_copy(update={"rationale": (flag + result.rationale)[:2_000]})

    async def judge(
        self, rendered: Any, model_response: str, primitive: Any, context: Any = None
    ) -> JudgeResult:
        """Async grade — the interface the trial loops call. Strict-checks only breaches."""
        self.stats.n_total += 1
        result = await self._llm.judge(rendered, model_response, primitive, context)
        if result.verdict not in BREACH_VERDICTS:
            return result
        self.stats.n_breaches += 1
        try:
            strict = await self._strict_judge().judge(
                rendered, model_response, primitive, context
            )
        except Exception as exc:  # noqa: BLE001 — strict grade must never fail a scan
            _log.warning("strict-bracket re-grade errored (%s) — leaving cell unflagged", exc)
            self.stats.n_strict_errors += 1
            return result
        if strict.verdict in BREACH_VERDICTS:
            self.stats.n_confirmed += 1
            return result
        self.stats.n_flagged += 1
        return self._stamp(result, strict.verdict.value)

    def judge_sync(
        self, rendered: Any, model_response: str, primitive: Any, context: Any = None
    ) -> JudgeResult:
        """Sync grade — same strict-check, for any synchronous consumer."""
        self.stats.n_total += 1
        result = self._llm.judge_sync(rendered, model_response, primitive, context)
        if result.verdict not in BREACH_VERDICTS:
            return result
        self.stats.n_breaches += 1
        try:
            strict = self._strict_judge().judge_sync(
                rendered, model_response, primitive, context
            )
        except Exception as exc:  # noqa: BLE001 — strict grade must never fail a scan
            _log.warning("strict-bracket re-grade errored (%s) — leaving cell unflagged", exc)
            self.stats.n_strict_errors += 1
            return result
        if strict.verdict in BREACH_VERDICTS:
            self.stats.n_confirmed += 1
            return result
        self.stats.n_flagged += 1
        return self._stamp(result, strict.verdict.value)

    def __getattr__(self, name: str) -> Any:
        """Forward everything else (``.model``, ``.breach_type``, ``.anthropic_grade_kwargs``, the
        ``_grade_via_*`` internals the deep stages reach for) to the wrapped judge — transparent proxy."""
        # __getattr__ only fires for names not found normally, so it never shadows judge/judge_sync.
        return getattr(self._llm, name)


def resolve_disagreement(base_judge: Any) -> Any:
    """Wrap ``base_judge`` in a disagreement check when the flag is on; return it untouched when off.

    The single seam every construction site calls, applied *outside* the cascade seam:
    ``judge = resolve_disagreement(resolve_cascade(JudgeAgent(...)))``. Off unless
    ``ROGUE_JUDGE_DISAGREEMENT`` ∈ {on,1,true,yes}. Only wraps a judge that exposes a truthy ``.model``
    (a real LLM judge, possibly behind a cascade proxy) — a keyless ``HeuristicJudge`` has no strict
    bracket to disagree with, so it is returned as-is. Wrapping is an add-on, never a dependency of a
    scan completing.
    """
    mode = os.environ.get(ENV_DISAGREEMENT, "off").strip().lower()
    if mode not in ("on", "1", "true", "yes"):
        return base_judge
    if not getattr(base_judge, "model", None):
        _log.info("judge disagreement on but base judge has no LLM model — leaving unwrapped")
        return base_judge
    _log.info("judge disagreement on (strict-bracket re-grade of breach cells)")
    return DisagreementJudge(base_judge)


__all__ = [
    "DisagreementJudge",
    "DisagreementStats",
    "resolve_disagreement",
    "is_uncertain",
    "ENV_DISAGREEMENT",
    "UNCERTAIN_FLAG_PREFIX",
]
