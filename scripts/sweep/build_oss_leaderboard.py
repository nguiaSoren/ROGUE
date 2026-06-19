"""Compute the OSS-model leaderboard stats from the persisted `fl-*` breach_results (the Featherless
single-shot aggressive-pack sweep) and emit:
  * `src/rogue/data/oss_leaderboard_stats.json` — stats per model (for the per-model cards), and
  * the `frontend/src/lib/leaderboard-data.ts` OSS entries (printed, to paste into the OSS section).

Methodology = single-shot aggressive pack, n_trials=3 — DISTINCT from the existing 8 models'
deep-pipeline numbers (don't merge them on one ranking). The headline `mean_breach_rate` is the
PRIMITIVE-level any-breach rate (a primitive counts as breached if ANY of its trials breached), which
is exactly the `N/17 = X%` the scan reports, so the board matches the sweep output.

Run:  uv run python scripts/sweep/build_oss_leaderboard.py
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

import psycopg
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")
_URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
_OUT = _ROOT / "src" / "rogue" / "data" / "oss_leaderboard_stats.json"
_MEASURED = "2026-06-20"
_BREACH = ("partial_breach", "full_breach")


def main() -> None:
    with psycopg.connect(_URL, connect_timeout=20) as conn:
        configs = conn.execute(
            "select config_id, target_model from deployment_configs where config_id like 'fl-%'"
        ).fetchall()
        models = []
        for config_id, target_model in configs:
            rows = conn.execute(
                "select br.primitive_id, ap.family, br.verdict "
                "from breach_results br join attack_primitives ap on ap.primitive_id = br.primitive_id "
                "where br.deployment_config_id = %s",
                (config_id,),
            ).fetchall()
            if not rows:
                continue
            n_trials = len(rows)
            # primitive-level any-breach (matches the scan's "N/17 breached") + per-family
            prim_breached: dict[str, bool] = defaultdict(bool)
            prim_family: dict[str, str] = {}
            for pid, fam, verdict in rows:
                prim_family[pid] = fam
                if verdict in _BREACH:
                    prim_breached[pid] = True
            prims = list(prim_family)
            n_prim = len(prims)
            breached_prims = sum(1 for p in prims if prim_breached[p])
            fam_tot: dict[str, int] = defaultdict(int)
            fam_br: dict[str, int] = defaultdict(int)
            for p in prims:
                fam_tot[prim_family[p]] += 1
                if prim_breached[p]:
                    fam_br[prim_family[p]] += 1
            fam_rate = {f: fam_br[f] / fam_tot[f] for f in fam_tot}
            worst_family = max(fam_rate, key=lambda f: (fam_rate[f], fam_br[f]))
            models.append(
                {
                    "config_id": config_id,
                    "target_model": target_model,
                    "model_label": target_model.split("/")[-1],
                    "mean_breach_rate": round(breached_prims / n_prim, 4),
                    "worst_family": worst_family,
                    "worst_breach_rate": round(fam_rate[worst_family], 4),
                    "n_trials": n_trials,
                    "n_families": len(fam_tot),
                    "n_primitives": n_prim,
                    "breached_primitives": breached_prims,
                }
            )

    models.sort(key=lambda m: m["mean_breach_rate"])
    _OUT.write_text(
        json.dumps(
            {
                "methodology": "single-shot aggressive pack (n_trials=3); primitive-level any-breach",
                "measured": _MEASURED,
                "n_models": len(models),
                "models": models,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {_OUT} ({len(models)} models)\n")
    print("=== leaderboard-data.ts OSS entries (paste into the OSS section) ===")
    for m in models:
        print(
            f'  {{ model_label: "{m["model_label"]}", target_model: "{m["target_model"]}", '
            f'mean_breach_rate: {m["mean_breach_rate"]}, worst_family: "{m["worst_family"]}", '
            f'worst_breach_rate: {m["worst_breach_rate"]}, n_trials: {m["n_trials"]}, '
            f'n_families: {m["n_families"]} }},'
        )


if __name__ == "__main__":
    main()
