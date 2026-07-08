"""Q16 offline validation — encoding-operator fidelity over the real corpus ($0).

The build side of Q16 is deterministic, so it validates offline with no paid
panel call. This runner measures the one property that decides whether a new
operator is *usable* in the live search: **non-neutering fidelity** — does the
variant it produces still express the parent's goal, so the goal-preservation
gate (``rogue.reproduce.search.goal_preservation``) keeps it rather than
silently dropping it?  An operator that the gate can't decode back never fires,
so this number is a hard gate on the wiring, replayed over payloads ROGUE has
already harvested.

It does NOT measure bypass-rate lift against a model — that needs the paid
reproduce panel (~$35, or free on the next scheduled run once
``ROGUE_OBF_EXTENDED`` is on). This is the honest $0 number and its ceiling.

Corpus: ``data/research/promptrend_corpus.jsonl`` (real harvested jailbreak
prompts, ``cleaned_prompt`` field). Reuses ``wilson_ci`` for the interval — no
new deps.

    uv run python scripts/research/q16_encoding_offline_validation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rogue.grammar.stats import wilson_ci  # noqa: E402
from rogue.obfuscation.operators import EXTENDED_OBFUSCATION_OPERATORS, apply_operator  # noqa: E402
from rogue.reproduce.search.goal_preservation import check_goal_preserved  # noqa: E402

_CORPUS = Path(__file__).resolve().parents[2] / "data/research/promptrend_corpus.jsonl"


def _load_payloads(limit: int | None = None) -> list[str]:
    out: list[str] = []
    with _CORPUS.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            p = (rec.get("cleaned_prompt") or "").strip()
            if len(p) >= 12:  # skip trivially short rows
                out.append(p)
            if limit and len(out) >= limit:
                break
    return out


def main(argv: list[str] | None = None) -> int:
    payloads = _load_payloads()
    if not payloads:
        print(f"no payloads loaded from {_CORPUS}", file=sys.stderr)
        return 2

    n = len(payloads)
    print(f"Q16 offline fidelity — non-neutering rate over N={n} real harvested payloads")
    print("(goal-preservation gate accepts the variant → it will fire in live search)")
    print(f"{'operator':<28} {'kept/N':>10} {'rate':>7}  95% Wilson CI")
    print("-" * 64)

    for op in EXTENDED_OBFUSCATION_OPERATORS:
        kept = 0
        changed = 0
        for p in payloads:
            variant = apply_operator(op.name, p)
            if variant != p:
                changed += 1
            if check_goal_preserved(p, variant, p).preserved:
                kept += 1
        lo, hi = wilson_ci(kept, n)
        print(f"{op.name:<28} {kept:>6}/{n:<3} {kept / n:>6.1%}  [{lo:.1%}, {hi:.1%}]  (surface-changed {changed}/{n})")

    print("-" * 64)
    print("CAVEAT: fidelity == non-neutering (the operator fires), NOT bypass efficacy.")
    print("Live headline (bypass-rate delta vs the panel) needs one paid reproduce")
    print("cycle (~$35) or a flag-on scheduled run; this is the $0 offline ceiling.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
