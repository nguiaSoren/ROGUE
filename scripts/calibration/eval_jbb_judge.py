"""Score the ROGUE judge against JBB judge_comparison's human majority — and rank
it against HarmBench / GPT-4 / LlamaGuard-2 / Llama-3 on the same 300 items.

Workstream C of the judge-calibration plan. Produces the "judge vs humans vs
LlamaGuard vs HarmBench" comparison: a credibility number on a public,
human-labeled set, alongside the field-standard classifiers the operator did not
author. No generation, no target-model calls, no corpus change — the responses
and competing labels are frozen in ``benchmark/frozen/jbb_judge_comparison.jsonl``.

**This spends money** — one judge call per scored item (~$0.0225 each; the full
300-item set ≈ $6.75). Gated behind ``--yes``; ``--dry-run`` loads + prints the
free baseline agreements and the cost estimate.

Run from the repo root::

    uv run python scripts/calibration/eval_jbb_judge.py --dry-run            # free: baselines + estimate
    uv run python scripts/calibration/eval_jbb_judge.py --yes                # paid: score the judge (300)
    uv run python scripts/calibration/eval_jbb_judge.py --yes --limit 60     # paid: cheap stratified subset

Output: stdout ranked table + ``data/calibration/jbb_judge_report.json`` + per-item
JSONL (so re-aggregation is free, never a repeat paid run).

Prereq: one-time freeze — ``uv run python -m benchmark.datasets --freeze``.
Spec: ROGUE_PLAN.md §10.2 + judge-calibration plan (Workstream C).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.datasets import JudgeComparisonItem, load_jbb_judge_comparison  # noqa: E402
from rogue.reproduce.calibration.artifact_robustness import (  # noqa: E402
    DETERMINISTIC_PERTURBATIONS,
    LabeledResponse,
    probe_artifact_robustness,
)
from rogue.reproduce.instantiator import RenderedAttack  # noqa: E402
from rogue.reproduce.jbb_eval import BASELINE_CLASSIFIERS, JBBReport, evaluate, jbb_primitive  # noqa: E402
from rogue.reproduce.judge import JudgeAgent  # noqa: E402
from rogue.schemas import JudgeVerdict  # noqa: E402
from rogue.schemas.breach_result import BREACH_VERDICTS  # noqa: E402

# Q5 artifact-robustness: env alias for the --artifact-robustness flag (so the knob is documented in
# .env.example next to the other ROGUE_* levers). Either the flag or the env truthy value enables it.
ENV_ARTIFACT_ROBUSTNESS = "ROGUE_JUDGE_ARTIFACT_ROBUSTNESS"

logger = logging.getLogger("rogue.scripts.calibration.eval_jbb_judge")

OUTPUT_DIR = _REPO_ROOT / "data" / "calibration"
_JUDGE_COST_ESTIMATE_PER_CALL_USD = 0.0225


def _stratified_subset(
    items: list[JudgeComparisonItem], limit: int, seed: str = "rogue"
) -> list[JudgeComparisonItem]:
    """Up to ``limit`` items, balanced across the human_majority truth cells so
    the axis keeps both jailbroken and non-jailbroken support. Deterministic
    (md5 ordering within each cell), no RNG."""
    if limit <= 0 or limit >= len(items):
        return list(items)
    pos = sorted(
        (i for i in items if i.human_majority),
        key=lambda i: hashlib.md5(f"{seed}:{i.index}".encode()).hexdigest(),
    )
    neg = sorted(
        (i for i in items if not i.human_majority),
        key=lambda i: hashlib.md5(f"{seed}:{i.index}".encode()).hexdigest(),
    )
    out: list[JudgeComparisonItem] = []
    pc = nc = 0
    while len(out) < limit and (pc < len(pos) or nc < len(neg)):
        if pc < len(pos):
            out.append(pos[pc])
            pc += 1
        if len(out) < limit and nc < len(neg):
            out.append(neg[nc])
            nc += 1
    return out


def _make_verdict_fn(judge: JudgeAgent):
    def verdict_fn(item: JudgeComparisonItem) -> JudgeVerdict:
        primitive = jbb_primitive(item.goal)
        rendered = RenderedAttack(
            messages=[{"role": "user", "content": item.prompt}],
            is_multi_turn=False,
            resolved_slots={},
            primitive_id=primitive.primitive_id,
            deployment_config_id="jbb_judge_comparison",
        )
        try:
            return judge.judge_sync(rendered, item.response, primitive).verdict
        except Exception as exc:  # noqa: BLE001 — coverage failure, not a grade
            logger.warning("judge errored on item %s, recording ERROR: %s", item.index, exc)
            return JudgeVerdict.ERROR

    return verdict_fn


def _make_grade_fn(judge: JudgeAgent):
    """Grade a (possibly perturbed) response text with the real judge → is-breach.

    The artifact-robustness probe's ``grade_fn``: it perturbs ``item.response`` and
    asks whether the judge still calls it a breach. Same render/primitive as the
    baseline verdict fn, but the response text is the probe's (perturbed) one."""

    def grade(case: LabeledResponse, response_text: str) -> bool:
        primitive = jbb_primitive(case.goal)
        rendered = RenderedAttack(
            messages=[{"role": "user", "content": case.prompt}],
            is_multi_turn=False,
            resolved_slots={},
            primitive_id=primitive.primitive_id,
            deployment_config_id="jbb_judge_comparison",
        )
        try:
            return judge.judge_sync(rendered, response_text, primitive).verdict in BREACH_VERDICTS
        except Exception as exc:  # noqa: BLE001 — a coverage miss is an honest non-breach, not a crash
            logger.warning("artifact-robustness grade errored on item %s: %s", case.key, exc)
            return False

    return grade


def _run_artifact_robustness(
    subset: list[JudgeComparisonItem], report: JBBReport, judge: JudgeAgent
) -> dict:
    """Q5: re-grade the slice under the deterministic artifact perturbations and
    report the judge's ΔFNR/ΔFPR. Reuses the already-paid baseline grade from
    ``report.scored`` (aligned to ``subset`` order), so only the perturbed grades
    cost. See :mod:`rogue.reproduce.calibration.artifact_robustness`."""
    cases = [
        LabeledResponse(
            key=str(it.index), goal=it.goal, prompt=it.prompt,
            response=it.response, human_is_harmful=bool(it.human_majority),
        )
        for it in subset
    ]
    # Baseline breach bits already graded by evaluate() (None/ERROR → non-breach).
    baseline_pred = [bool(s.rogue_breach) for s in report.scored]
    ar = probe_artifact_robustness(
        cases, _make_grade_fn(judge),
        judge_label=f"rogue_judge:{judge.model}",
        perturbations=DETERMINISTIC_PERTURBATIONS,
        baseline_pred=baseline_pred,
    )
    print("\n" + "=" * 60)
    print("Q5 artifact-robustness (ΔFNR under benign judge-hacks):")
    print("  " + ar.summary_line())
    for p in ar.perturbations.values():
        print("  " + p.summary_line())
    print("=" * 60)
    return ar.to_dict()


def _baselines_only_report(items: list[JudgeComparisonItem]) -> JBBReport:
    """Free report: score the four stored classifiers (no judge calls)."""
    return evaluate(items, lambda _it: JudgeVerdict.ERROR)


def _serialize(report: JBBReport, *, seed: str, limit: int) -> dict:
    def axis(a) -> dict:
        return {
            "agreement_rate": a.agreement_rate,
            "n": a.n,
            "n_agreed": a.n_agreed,
            "tp": a.tp,
            "fp": a.fp,
            "fn": a.fn,
            "tn": a.tn,
        }

    return {
        "dataset": "JailbreakBench/JBB-Behaviors:judge_comparison/test",
        "axis": "breach (jailbroken) vs human_majority",
        "seed": seed,
        "limit": limit,
        "n_items": report.n_items,
        "n_judge_errors": report.n_errors,
        "n_human_positive": report.n_human_positive,
        "predictors": {name: axis(agg) for name, agg in report.predictors.items()},
        "ranked": report.ranked(),
        "summary_line": report.summary_line(),
    }


def _print_ranked(report: JBBReport) -> None:
    print("\n" + "=" * 60)
    print("breach-axis agreement vs human majority (ranked):")
    for name, rate in report.ranked():
        agg = report.predictors[name]
        tag = "  <- ROGUE" if name == "rogue_judge" else ""
        print(f"  {name:14} {rate:6.1%}  ({agg.n_agreed}/{agg.n}){tag}")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="0 = all 300; else stratified subset")
    parser.add_argument("--seed", default="rogue")
    parser.add_argument("--prompt-version", default="v3", help="judge rubric version to score (e.g. v1, v3)")
    parser.add_argument("--dry-run", action="store_true", help="baselines + estimate, free")
    parser.add_argument("--yes", action="store_true", help="confirm the paid judge run")
    parser.add_argument(
        "--artifact-robustness", action="store_true",
        help="Q5: also re-grade under the 3 deterministic artifact perturbations and report ΔFNR/ΔFPR "
        "(adds ~3 judge calls/item; env ROGUE_JUDGE_ARTIFACT_ROBUSTNESS also enables it)",
    )
    args = parser.parse_args(argv)

    artifact_robustness = args.artifact_robustness or os.environ.get(
        ENV_ARTIFACT_ROBUSTNESS, ""
    ).strip().lower() in ("1", "true", "yes", "on")

    try:
        items = load_jbb_judge_comparison()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1
    subset = _stratified_subset(items, args.limit, args.seed)
    # +3 deterministic perturbation grades/item when the artifact-robustness probe is on.
    _ar_extra = len(DETERMINISTIC_PERTURBATIONS) if artifact_robustness else 0
    est = len(subset) * (1 + _ar_extra) * _JUDGE_COST_ESTIMATE_PER_CALL_USD

    if args.dry_run or not args.yes:
        base = _baselines_only_report(subset)
        print(f"\nloaded {len(subset)}/{len(items)} items (human+={base.n_human_positive})")
        print("baseline classifiers (free, stored labels) — the bar ROGUE must clear:")
        for name in BASELINE_CLASSIFIERS:
            agg = base.predictors[name]
            print(f"  {name:14} {agg.agreement_rate:6.1%}  ({agg.n_agreed}/{agg.n})")
        if artifact_robustness:
            print(
                f"\nscoring the ROGUE judge + artifact-robustness over {len(subset)} items "
                f"(1 baseline + {_ar_extra} perturbations each) ≈ ${est:.2f}"
            )
        else:
            print(f"\nscoring the ROGUE judge over {len(subset)} items ≈ ${est:.2f}")
        if args.dry_run:
            print("dry-run: re-run with --yes to score the judge.")
            return 0
        logger.error("this calls the live judge (≈ $%.2f). Re-run with --yes to confirm.", est)
        return 2

    judge = JudgeAgent(prompt_version=args.prompt_version)
    logger.info(
        "judge model: %s | rubric: %s | scoring %d items (≈ $%.2f)",
        judge.model, args.prompt_version, len(subset), est,
    )
    report = evaluate(subset, _make_verdict_fn(judge))

    # Q5 artifact-robustness — additive: only runs when enabled, reuses the baseline grade above.
    artifact_robustness_block = None
    if artifact_robustness:
        artifact_robustness_block = _run_artifact_robustness(subset, report, judge)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"jbb_judge_report_{args.prompt_version}.json"
    _payload = _serialize(report, seed=args.seed, limit=args.limit)
    _payload["judge_model"] = judge.model
    _payload["resolved_model"] = judge._last_resolved_model
    if artifact_robustness_block is not None:
        _payload["artifact_robustness"] = artifact_robustness_block
    out_path.write_text(
        json.dumps(_payload, indent=2),
        encoding="utf-8",
    )
    items_path = OUTPUT_DIR / "jbb_judge_items.jsonl"
    with items_path.open("w", encoding="utf-8") as fh:
        for s in report.scored:
            fh.write(
                json.dumps(
                    {
                        "index": s.index,
                        "human_majority": s.human_majority,
                        "verdict": s.verdict,
                        "rogue_breach": s.rogue_breach,
                        "baselines": s.baselines,
                    }
                )
                + "\n"
            )

    _print_ranked(report)
    print(f"report   → {out_path}")
    print(f"per-item → {items_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
