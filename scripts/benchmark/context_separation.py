#!/usr/bin/env python
"""Does strong CONTEXT SEPARATION exist? — the cheap question before any per-model
ladder rewrite (contextual routing).

The early-stop starvation problem (§10.10) is solved and the contextual map already
reads the UNBIASED full breach_results matrix (no short-circuit). What's unresolved
is whether contextual *execution* (per-model ladders) is worth the architecture
change. That's only true if breach rate varies a LOT by target model within a
family/modality/renderer. So: compute breach rate per (cut × target_model), measure
the SPREAD across models for each cut, and look for big gaps.

  big spreads (Typographic: Gemini .80 / GPT .18)  → contextual routing compelling
  flat (.45 / .48 / .43 everywhere)                → the rewrite isn't worth it

Read-only on breach_results; cells with N<MIN_N trials are masked (greyed → "-").

    uv run python scripts/benchmark/context_separation.py
    uv run python scripts/benchmark/context_separation.py --min-n 15
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

BREACH = "('full_breach','partial_breach')"


def _matrix(c, group_col: str, min_n: int):
    """Return {group: {model: (rate, n)}} for a grouping column on attack_primitives."""
    rows = c.execute(text(f"""
        SELECT p.{group_col}::text AS grp, d.target_model AS model,
               count(*) AS n,
               count(*) FILTER (WHERE b.verdict IN {BREACH}) AS br
        FROM breach_results b
        JOIN attack_primitives p ON p.primitive_id = b.primitive_id
        JOIN deployment_configs d ON d.config_id = b.deployment_config_id
        GROUP BY p.{group_col}, d.target_model""")).all()
    out: dict[str, dict[str, tuple[float, int]]] = {}
    models: set[str] = set()
    for r in rows:
        models.add(r.model)
        if r.n >= min_n:
            out.setdefault(r.grp, {})[r.model] = (r.br / r.n, r.n)
    return out, sorted(models)


def _short(model: str) -> str:
    return model.split("/")[-1][:14]


def _print_cut(title: str, mat, models, min_n: int):
    print(f"\n{'='*78}\n{title}  (breach rate; cells N<{min_n} masked '-')\n")
    hdr = "  " + f"{'group':26}" + "".join(f"{_short(m):>15}" for m in models) + f"{'SPREAD':>9}"
    print(hdr)
    ranked = []
    for grp, cells in mat.items():
        vals = [v[0] for v in cells.values()]
        if len(vals) < 2:
            continue
        spread = max(vals) - min(vals)
        ranked.append((spread, grp, cells))
    ranked.sort(reverse=True)
    for spread, grp, cells in ranked:
        line = f"  {grp[:26]:26}"
        for m in models:
            if m in cells:
                rate, n = cells[m]
                line += f"{rate:>13.2f} "
            else:
                line += f"{'-':>14} "
        line += f"{spread:>8.2f}"
        print(line)
    return ranked


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--min-n", type=int, default=20, help="mask cells with fewer than N trials")
    args = ap.parse_args()
    load_dotenv(str(_ROOT / ".env"))
    e = create_engine(os.environ["DATABASE_URL"])

    all_ranked = {}
    with e.connect() as c:
        for title, col in [("FAMILY × target_model", "family"),
                           ("MODALITY (vector) × target_model", "vector")]:
            mat, models = _matrix(c, col, args.min_n)
            all_ranked[title] = _print_cut(title, mat, models, args.min_n)

    # The decision metric is NOT raw spread (that's a model MAIN EFFECT — some models
    # just breach more). Per-model ladders only pay off for the INTERACTION: does the
    # BEST family differ by model (rank crossover)? Measure it as the regret of using
    # ONE global-best family for every model.
    print(f"\n{'='*78}\nVERDICT — is contextual routing worth the per-model-ladder rewrite?\n")
    fam = all_ranked["FAMILY × target_model"]
    # global-best family = highest mean rate across the models that have it
    fam_mean: dict[str, float] = {}
    by_model: dict[str, dict[str, float]] = {}
    for _spread, grp, cells in fam:
        rates = [v[0] for v in cells.values()]
        fam_mean[grp] = sum(rates) / len(rates)
        for m, (rate, _n) in cells.items():
            by_model.setdefault(m, {})[grp] = rate
    gbest = max(fam_mean, key=fam_mean.get)
    crossover = []
    aligned = 0
    for m, fams in by_model.items():
        if len(fams) < 3:
            continue  # too sparse to judge a model's ranking (audio-only tiers)
        top = max(fams, key=fams.get)
        regret = fams[top] - fams.get(gbest, 0.0)
        if top != gbest and regret >= 0.10:
            crossover.append(f"{_short(m)}: prefers {top[:22]} ({fams[top]:.2f}) over "
                             f"global-best {gbest[:16]} ({fams.get(gbest,0):.2f}); regret {regret:.2f}")
        else:
            aligned += 1
    print(f"  global-best family (pooled lead): {gbest}")
    print(f"  models where the global lead is already optimal (regret≈0): {aligned}")
    print(f"  models with a genuine CROSSOVER (a per-model ladder would route differently): {len(crossover)}")
    for c in crossover:
        print(f"    - {c}")
    verdict = ("STRONG interaction → per-model ladders worth evaluating" if len(crossover) >= 3
               else "WEAK interaction → the rewrite is NOT worth it; a GLOBAL ladder ordered by "
                    f"pooled breach rate (lead with {gbest}) is near-optimal for most models. "
                    "Capture the few exceptions (e.g. the modality tier + any crossover model) "
                    "with targeted per-model PRIORS, not an architecture change."
               if len(crossover) >= 1 else
               "NO interaction → keep the single global ladder; routing adds nothing.")
    print(f"\n  → {verdict}")
    print("  (raw spread is large but it's a MODEL main effect — most models share the same "
          "best family, so a global order already captures it.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
