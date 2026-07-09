"""$0 offline validator for the Q5 judge artifact-robustness probe.

Runs the probe (`rogue.reproduce.calibration.artifact_robustness`) over the
frozen JBB-300 judge-comparison slice (`benchmark/frozen/jbb_judge_comparison.jsonl`,
Eiras' exact dataset) using ROGUE's **network-free** :class:`HeuristicJudge` as the
grader — so it produces a REAL ΔFNR/ΔFPR number for the free structural tier for
**$0**, and exercises the whole machinery (perturbations, 2×2, CIs, induced-FN)
end-to-end without a single API call.

What this does and does NOT measure. The heuristic is a *structural* judge (it
counts code fences / numbered steps / quantities), so it is robust-by-construction
to the tone artifacts (apology/benign block) that fool a *semantic* LLM judge —
which is itself an honest, publishable contrast. The headline number the
judge-reliability work wants — the ΔFNR of ROGUE's **black-box Claude** judge, the
one the board actually rides on — needs the paid arm:

    uv run python scripts/calibration/eval_jbb_judge.py --yes --artifact-robustness

Run (free)::

    uv run python scripts/calibration/replay_artifact_robustness.py
    uv run python scripts/calibration/replay_artifact_robustness.py --limit 100
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.datasets import load_jbb_judge_comparison  # noqa: E402
from rogue.reproduce.calibration.artifact_robustness import (  # noqa: E402
    DEFAULT_PERTURBATIONS,
    LabeledResponse,
    probe_artifact_robustness,
)
from rogue.reproduce.heuristic_judge import HeuristicJudge  # noqa: E402
from rogue.schemas.breach_result import BREACH_VERDICTS  # noqa: E402

logger = logging.getLogger("rogue.scripts.calibration.replay_artifact_robustness")
OUTPUT_DIR = _REPO_ROOT / "data" / "calibration"


def _heuristic_grade_fn():
    """grade_fn for the probe backed by the keyless HeuristicJudge (network-free, $0)."""
    hj = HeuristicJudge()

    def grade(case: LabeledResponse, response_text: str) -> bool:
        # The heuristic grades (attack_prompt, response[, goal]); perturbations edit the response.
        return hj.judge_sync(case.prompt, response_text, case.goal).verdict in BREACH_VERDICTS

    return grade


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="0 = all 300; else first N items")
    parser.add_argument("--out", default=str(OUTPUT_DIR / "artifact_robustness_heuristic.json"))
    args = parser.parse_args(argv)

    try:
        items = load_jbb_judge_comparison()
    except FileNotFoundError as exc:
        logger.error("%s (run: uv run python -m benchmark.datasets --freeze)", exc)
        return 1
    if args.limit > 0:
        items = items[: args.limit]

    cases = [
        LabeledResponse(
            key=str(it.index), goal=it.goal, prompt=it.prompt,
            response=it.response, human_is_harmful=bool(it.human_majority),
        )
        for it in items
    ]
    report = probe_artifact_robustness(
        cases, _heuristic_grade_fn(),
        judge_label="heuristic_judge",
        perturbations=DEFAULT_PERTURBATIONS,  # all 4 — it's free
    )

    print("\n" + "=" * 68)
    print("Q5 artifact-robustness — $0 replay over JBB-300 with the HeuristicJudge")
    print("=" * 68)
    print(report.summary_line())
    for p in report.perturbations.values():
        print("  " + p.summary_line())
    print("=" * 68)
    print(
        "NOTE: the heuristic is a STRUCTURAL grader (robust-by-construction to tone\n"
        "artifacts). The black-box Claude ΔFNR — the headline judge-reliability number — is the paid\n"
        "arm: eval_jbb_judge.py --yes --artifact-robustness."
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    print(f"\nreport → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
