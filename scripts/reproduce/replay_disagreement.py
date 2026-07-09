"""$0 illustrative validator for the Q5 judge-disagreement uncertainty flag.

The live flag (`reproduce/disagreement_judge.py`) re-grades each breach cell with
the **strict bracket** and flags the ones the conservative grader won't confirm.
The real strict-bracket disagreement rate needs paid strict grades (the gated
arm). What we CAN show for **$0**, from data already frozen, is how often
independent safety graders *disagree* on the JBB-300 — a lower-bound proxy for
how many breaches are judge-fragile (i.e. how many cells the flag would surface).

On the frozen JBB-300 judge-comparison set we have four field-standard
classifiers' calls (HarmBench / GPT-4 / LlamaGuard-2 / Llama-3) plus the human
majority. For each item we ask: do the graders unanimously agree? The fraction
that **split** — especially on the human-harmful items — is the natural
"low-confidence" set. This is cross-*judge* disagreement (not strict-bracket), so
it is an honest illustration of the phenomenon, not the live number.

Run (free)::

    uv run python scripts/reproduce/replay_disagreement.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark.datasets import load_jbb_judge_comparison  # noqa: E402
from rogue.reproduce.cascade_judge import _wilson_lower  # noqa: E402 — reuse the Wilson floor
from rogue.reproduce.jbb_eval import BASELINE_CLASSIFIERS  # noqa: E402

logger = logging.getLogger("rogue.scripts.reproduce.replay_disagreement")


def _wilson_ci(k: int, n: int) -> tuple[float, float, float]:
    """(point, lo, hi) Wilson interval — reuse the cascade's lower-bound helper for lo, mirror for hi."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    lo = _wilson_lower(k, n)
    hi = 1.0 - _wilson_lower(n - k, n)  # symmetry: upper = 1 − lower of the complement
    return (p, lo, hi)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    argparse.ArgumentParser(description=__doc__).parse_args(argv)

    try:
        items = load_jbb_judge_comparison()
    except FileNotFoundError as exc:
        logger.error("%s (run: uv run python -m benchmark.datasets --freeze)", exc)
        return 1

    def split(item) -> bool:
        calls = [bool(item.baselines[c]) for c in BASELINE_CLASSIFIERS]
        return any(calls) and not all(calls)  # graders disagree iff not unanimous

    harmful = [it for it in items if it.human_majority]
    clean = [it for it in items if not it.human_majority]
    n_all_split = sum(1 for it in items if split(it))
    n_harm_split = sum(1 for it in harmful if split(it))
    n_clean_split = sum(1 for it in clean if split(it))

    all_ci = _wilson_ci(n_all_split, len(items))
    harm_ci = _wilson_ci(n_harm_split, len(harmful))
    clean_ci = _wilson_ci(n_clean_split, len(clean))

    print("\n" + "=" * 68)
    print("Q5 judge-disagreement — $0 cross-judge split prevalence on JBB-300")
    print("(4 field-standard classifiers: HarmBench / GPT-4 / LlamaGuard-2 / Llama-3)")
    print("=" * 68)
    print(f"  all items      : {n_all_split}/{len(items)} split "
          f"= {all_ci[0]:.1%} [{all_ci[1]:.1%}, {all_ci[2]:.1%}]")
    print(f"  human-HARMFUL   : {n_harm_split}/{len(harmful)} split "
          f"= {harm_ci[0]:.1%} [{harm_ci[1]:.1%}, {harm_ci[2]:.1%}]   <- the low-confidence-breach proxy")
    print(f"  human-clean     : {n_clean_split}/{len(clean)} split "
          f"= {clean_ci[0]:.1%} [{clean_ci[1]:.1%}, {clean_ci[2]:.1%}]")
    print("=" * 68)
    print(
        "Read: on ~{:.0%} of genuinely-harmful items the standard judges split — a floor on how many\n"
        "breaches are judge-fragile. The LIVE per-cell number (ROGUE's own primary-vs-strict bracket)\n"
        "is the gated arm (paid strict grades).".format(harm_ci[0])
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
