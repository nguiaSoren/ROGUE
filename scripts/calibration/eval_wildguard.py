"""Score the ROGUE judge against the human-annotated WildGuardTest benchmark.

Workstream B of the judge-calibration plan. Produces the *external* credibility
number — agreement with independent annotators on a public set — that the
operator did not author, closing the "you graded your own ground truth"
objection that the in-distribution Workstream-A number alone cannot.

**This spends money** — one judge call per scored item (~$0.02 each; the
default 200-item subset ≈ $4-5). Run deliberately, never on a loop. Gated
behind ``--yes``; ``--dry-run`` loads the data + prints the cost estimate for
free.

Prerequisites:
  * ``datasets`` installed:  ``uv add datasets``  (or ``uv pip install datasets``)
  * Hugging Face auth: ``allenai/wildguardmix`` is GATED — accept the terms on
    the dataset page and set ``HF_TOKEN`` (or run ``huggingface-cli login``).

We score ONLY the human-annotated **Test** split. The Train split is
GPT-4-labeled; scoring against it would be GPT-4-grading-GPT-4 — the exact
circularity this workstream exists to escape.

Run from the repo root::

    uv run python scripts/calibration/eval_wildguard.py --dry-run           # free: load + estimate
    uv run python scripts/calibration/eval_wildguard.py --yes --limit 200   # paid: score the judge

Output: stdout summary + ``data/calibration/wildguard_report.json``.

Spec: ROGUE_PLAN.md §10.2 + judge-calibration plan (Workstream B).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rogue.reproduce.instantiator import RenderedAttack  # noqa: E402
from rogue.reproduce.judge import JudgeAgent  # noqa: E402
from rogue.reproduce.wildguard_eval import (  # noqa: E402
    WildGuardItem,
    WildGuardReport,
    evaluate,
    select_subset,
    synthetic_primitive,
)
from rogue.schemas import JudgeVerdict  # noqa: E402

logger = logging.getLogger("rogue.scripts.calibration.eval_wildguard")

DATASET = "allenai/wildguardmix"
CONFIG = "wildguardtest"  # human-annotated Test split only
DEFAULT_LIMIT = 200
DEFAULT_SEED = "rogue"
OUTPUT_DIR = _REPO_ROOT / "data" / "calibration"
_JUDGE_COST_ESTIMATE_PER_CALL_USD = 0.0225

# WildGuard label vocabularies → booleans.
_HARM_TRUE = "harmful"
_REFUSAL_TRUE = "refusal"


def _load_wildguard_items() -> list[WildGuardItem]:
    """Load the WildGuardTest split and reduce response-level rows to
    :class:`WildGuardItem`. Rows lacking a response or either response-level
    label are skipped (those are prompt-only classification rows)."""
    try:
        from datasets import load_dataset
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "the `datasets` package is required for WildGuard scoring. "
            "Install it: uv add datasets"
        ) from exc

    try:
        ds = load_dataset(DATASET, CONFIG)
    except Exception as exc:  # gated dataset / auth / network
        raise RuntimeError(
            f"could not load {DATASET}:{CONFIG}. It is a GATED dataset — accept "
            "the terms on its Hugging Face page and authenticate (set HF_TOKEN "
            f"or run `huggingface-cli login`). Underlying error: {exc}"
        ) from exc

    split = ds["test"] if "test" in ds else ds[next(iter(ds.keys()))]

    items: list[WildGuardItem] = []
    skipped = 0
    for row in split:
        response = row.get("response")
        harm = row.get("response_harm_label")
        refusal = row.get("response_refusal_label")
        prompt = row.get("prompt")
        prompt_harm = row.get("prompt_harm_label")
        if not response or not prompt or harm is None or refusal is None:
            skipped += 1
            continue
        items.append(
            WildGuardItem(
                prompt=prompt,
                response=response,
                # prompt_harm_label may be absent on a few rows; default to
                # adversarial=True so an unlabeled prompt isn't silently
                # dropped from the clean harm axis.
                prompt_harmful=(str(prompt_harm).strip().lower() != "unharmful"),
                response_harmful=(str(harm).strip().lower() == _HARM_TRUE),
                response_refusal=(str(refusal).strip().lower() == _REFUSAL_TRUE),
            )
        )
    logger.info(
        "loaded %d response-level WildGuardTest items (skipped %d prompt-only/incomplete)",
        len(items),
        skipped,
    )
    return items


def _make_verdict_fn(judge: JudgeAgent):
    """Build the WildGuard verdict_fn: synthesize a primitive + single-turn
    render, grade with the live judge, fold any failure to ERROR (excluded
    from the agreement axes by ``evaluate``)."""

    def verdict_fn(item: WildGuardItem) -> JudgeVerdict:
        primitive = synthetic_primitive(item.prompt)
        rendered = RenderedAttack(
            messages=[{"role": "user", "content": item.prompt}],
            is_multi_turn=False,
            resolved_slots={},
            primitive_id=primitive.primitive_id,
            deployment_config_id="wildguard",
        )
        try:
            return judge.judge_sync(rendered, item.response, primitive).verdict
        except Exception as exc:  # noqa: BLE001 — coverage failure, not a grade
            logger.warning("judge errored on an item, recording ERROR: %s", exc)
            return JudgeVerdict.ERROR

    return verdict_fn


def _serialize(report: WildGuardReport, *, seed: str, limit: int) -> dict:
    def axis(a) -> dict:
        return {
            "axis": a.axis,
            "agreement_rate": a.agreement_rate,
            "n": a.n,
            "n_agreed": a.n_agreed,
            "tp": a.tp,
            "fp": a.fp,
            "fn": a.fn,
            "tn": a.tn,
        }

    return {
        "dataset": f"{DATASET}:{CONFIG}",
        "split": "test (human-annotated)",
        "seed": seed,
        "limit": limit,
        "n_items": report.n_items,
        "n_errors": report.n_errors,
        "harm_axis": axis(report.harm),
        "harm_adversarial_axis": axis(report.harm_adversarial),
        "refusal_axis": axis(report.refusal),
        "summary_line": report.summary_line(),
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument(
        "--harmful-only",
        action="store_true",
        help=(
            "score only adversarial (prompt_harm_label=harmful) prompts — gives "
            "a clean harm axis free of the benign-compliance framing artifact"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="load + estimate, free")
    parser.add_argument("--yes", action="store_true", help="confirm the paid run")
    args = parser.parse_args(argv)

    try:
        items = _load_wildguard_items()
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1
    if not items:
        logger.error("no scorable WildGuardTest items loaded")
        return 1

    if args.harmful_only:
        before = len(items)
        items = [it for it in items if it.prompt_harmful]
        logger.info(
            "harmful-only: kept %d/%d adversarial-prompt items", len(items), before
        )

    subset = select_subset(items, limit=args.limit, seed=args.seed)
    est = len(subset) * _JUDGE_COST_ESTIMATE_PER_CALL_USD
    logger.info(
        "scoring %d/%d items (seed=%s); judge estimate ≈ $%.2f",
        len(subset),
        len(items),
        args.seed,
        est,
    )

    if args.dry_run:
        logger.info("dry-run: data loads. Re-run with --yes to score the judge.")
        return 0

    if not args.yes:
        logger.error(
            "this run calls the live judge (≈ $%.2f). Re-run with --yes to "
            "confirm, or --dry-run to load + estimate for free.",
            est,
        )
        return 2

    judge = JudgeAgent()
    logger.info("judge model: %s", judge.model)
    report = evaluate(subset, _make_verdict_fn(judge))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "_harmful" if args.harmful_only else ""
    out_path = OUTPUT_DIR / f"wildguard_report{suffix}.json"
    out_path.write_text(
        json.dumps(_serialize(report, seed=args.seed, limit=args.limit), indent=2),
        encoding="utf-8",
    )

    # Per-item JSONL so any future re-aggregation (different threshold, subset,
    # axis) is free instead of a repeat paid run.
    items_path = OUTPUT_DIR / f"wildguard_items{suffix}.jsonl"
    with items_path.open("w", encoding="utf-8") as fh:
        for s in report.scored:
            fh.write(
                json.dumps(
                    {
                        "prompt": s.prompt,
                        "prompt_harmful": s.prompt_harmful,
                        "response_harmful": s.response_harmful,
                        "response_refusal": s.response_refusal,
                        "verdict": s.verdict,
                        "harm_pred": s.harm_pred,
                        "refusal_pred": s.refusal_pred,
                    }
                )
                + "\n"
            )

    print("\n" + "=" * 70)
    print(report.summary_line())
    print("=" * 70)
    print(f"report     → {out_path}")
    print(f"per-item   → {items_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
