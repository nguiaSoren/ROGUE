"""Second-judge robustness check (P2): score the SAME v3 consummation-gate rubric
on a DIFFERENT-FAMILY judge model over the JBB judge_comparison 300 (external
human-majority labels the operator did not author). The v3 rubric was calibrated
with anthropic/claude-sonnet-4-6; if the *rubric* is the contribution (not the
specific judge model), a comparable judge from another family should land in a
similar agreement band on this externally-labeled set.

Sequential (the OpenAI/OpenRouter judge paths are not Anthropic-batchable) with
provider-automatic prompt caching — the rubric prefix is identical across all
300 calls, so OpenAI caches it. Writes a DISTINCT report
(``jbb_judge_report_v3_<model>.json``) so the primary sonnet result
(``jbb_judge_report_v3.json``) is preserved. Errors on individual cells are
recorded as ERROR, never a crash.

    uv run python scripts/calibration/eval_jbb_judge_2nd.py --dry-run
    uv run python scripts/calibration/eval_jbb_judge_2nd.py --model openai/gpt-5.4 --limit 6 --yes   # cheap sanity
    uv run python scripts/calibration/eval_jbb_judge_2nd.py --model openai/gpt-5.4 --yes             # full 300
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from rogue.reproduce.jbb_eval import BASELINE_CLASSIFIERS, evaluate  # noqa: E402
from rogue.reproduce.judge import JudgeAgent  # noqa: E402
from benchmark.datasets import load_jbb_judge_comparison  # noqa: E402

# Reuse the primary script's stratified-subset + verdict_fn + serializer + printer.
_spec = importlib.util.spec_from_file_location("ej", _REPO / "scripts/calibration/eval_jbb_judge.py")
_ej = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ej)

logger = logging.getLogger("rogue.scripts.calibration.eval_jbb_judge_2nd")
OUT = _REPO / "data" / "calibration"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="openai/gpt-5.4",
                    help="second judge model (different family from sonnet-4.6)")
    ap.add_argument("--prompt-version", default="v3")
    ap.add_argument("--strict", action="store_true",
                    help="prepend the conservative over-flag-suppression bracket "
                         "(P2 calibration-anchor refine arm: tests whether the "
                         "method's own over-flag lever lifts an open judge's precision)")
    ap.add_argument("--limit", type=int, default=0, help="0 = all 300; else stratified subset")
    ap.add_argument("--seed", default="rogue")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="confirm the paid run")
    args = ap.parse_args(argv)

    items = load_jbb_judge_comparison()
    subset = _ej._stratified_subset(items, args.limit, args.seed)
    tag = args.model.split("/")[-1].replace(".", "-") + ("_strict" if args.strict else "")

    base = _ej._baselines_only_report(subset)
    print(f"\nloaded {len(subset)}/{len(items)} items (human+={base.n_human_positive})")
    print("baselines (free) + the primary result we are stress-testing:")
    for name in BASELINE_CLASSIFIERS:
        agg = base.predictors[name]
        print(f"  {name:18} {agg.agreement_rate:6.1%}")
    print("  rogue_judge(sonnet-4.6) 91.0%  <- v3 rubric, the band a 2nd-family judge should land near")

    if args.dry_run or not args.yes:
        print(f"\nwould grade {len(subset)} items SEQUENTIALLY with judge={args.model} "
              f"(rubric {args.prompt_version}), provider-cached. Re-run with --yes to fire the paid run.")
        return 0

    judge = JudgeAgent(prompt_version=args.prompt_version, model=args.model, strict=args.strict)
    logger.info("grading %d items | judge=%s | rubric=%s | strict=%s | sequential + provider cache",
                len(subset), judge.model, args.prompt_version, args.strict)
    report = evaluate(subset, _ej._make_verdict_fn(judge))

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"jbb_judge_report_{args.prompt_version}_{tag}.json"
    payload = _ej._serialize(report, seed=args.seed, limit=args.limit)
    payload["judge_model"] = judge.model
    payload["resolved_model"] = judge._last_resolved_model
    payload["resolved_provider"] = judge._last_resolved_provider
    payload["provider_pin"] = {
        "JUDGE_OPENROUTER_PROVIDER": (
            os.environ.get("JUDGE_OPENROUTER_PROVIDER")
            or os.environ.get("ROGUE_OPENROUTER_PROVIDER", "")
        ),
        "JUDGE_OPENROUTER_QUANT": (
            os.environ.get("JUDGE_OPENROUTER_QUANT")
            or os.environ.get("ROGUE_OPENROUTER_QUANT", "")
        ),
    }
    payload["strict"] = args.strict
    payload["note"] = ("second-judge robustness check (different family, sequential, provider-cached); "
                       "primary judge anthropic/claude-sonnet-4-6 result is jbb_judge_report_v3.json"
                       + ("; STRICT over-flag-suppression bracket (P2 calibration-anchor refine arm)"
                          if args.strict else ""))
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Per-item verdicts so a downstream intersection-of-parsed-cases delta can be
    # computed without re-running (ERROR cells differ run-to-run; comparing two
    # arms on their common non-ERROR indices removes the denominator artifact).
    items_path = OUT / f"jbb_judge_items_{tag}.jsonl"
    with items_path.open("w", encoding="utf-8") as fh:
        for s in report.scored:
            fh.write(json.dumps({
                "index": s.index,
                "human_majority": s.human_majority,
                "verdict": s.verdict,
                "rogue_breach": s.rogue_breach,
            }) + "\n")
    print(f"per-item → {items_path}")

    print("\n" + "=" * 64)
    print(f"SECOND-JUDGE robustness  judge={judge.model}  rubric={args.prompt_version}  "
          f"(errors={report.n_errors})")
    _ej._print_ranked(report)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
