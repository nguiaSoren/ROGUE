#!/usr/bin/env python3
"""$0 offline validation of the noise-corrected calibration overlay (Feng/Lee).

De-bias ROGUE's judge-labelled breach rate against the judge's own error profile,
using ONLY data already paid for — no LLM, no network, no paid run:

  * D_M (small human-labelled calibration set) → TPR̂/FPR̂:
    ``data/calibration/frozen_cited/jbb_judge_items.jsonl`` (300 JBB items, each
    with ``human_majority`` ground truth and ``rogue_breach`` the judge's call).
  * D_J (large judge-labelled run) → raw rate R̂_J and n_J:
    the ``breach_results`` table (every stored trial's judge verdict), read-only
    over the local snapshot or $DATABASE_URL.

Then it applies :func:`rogue.reproduce.calibration.noise_corrected.noise_corrected_rate`
and prints the de-biased rate + CI (Lee) and the certification verdict (Feng).

Honesty caveat (printed in the output): D_M here is the JBB adversarial-harmful
calibration set, while D_J is ROGUE's own reproduction population. The TPR̂/FPR̂
transfer across those populations is the *representativeness assumption* Feng's
framework rests on; a production headline wants a calibration set drawn from the
same population as the judge run (one judge-only paid pass per judge). This
replay demonstrates the pipeline + the magnitude of the correction, not a shipped
per-judge certification.

Run:
    uv run python scripts/calibration/replay_noise_corrected.py
    uv run python scripts/calibration/replay_noise_corrected.py --alpha 0.20 --zeta 0.05
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from rogue.reproduce.calibration.noise_corrected import (  # noqa: E402
    DEFAULT_ALPHA,
    DEFAULT_ZETA,
    noise_corrected_rate,
)

_CAL = _REPO_ROOT / "data" / "calibration"
_DM_PATH = _CAL / "frozen_cited" / "jbb_judge_items.jsonl"
_OUT_PATH = _CAL / "noise_corrected_harm_replay.json"

# breach polarity: positive = breach.
_BREACH_VERDICTS = {"partial_breach", "full_breach"}
_ERROR_VERDICTS = {"error"}


def _judge_breach(row: dict) -> bool:
    """Judge's breach call in the released calibration rows (tolerant field name)."""
    for k in ("rogue_breach", "judge_breach", "breach"):
        if k in row:
            return bool(row[k])
    raise KeyError("no judge-breach field in calibration row")


def _load_dm_2x2(path: Path) -> tuple[int, int, int, int]:
    """(tp, fp, fn, tn) on the breach axis from the human-labelled calibration set."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    tp = fp = fn = tn = 0
    for r in rows:
        human = bool(r["human_majority"])
        judge = _judge_breach(r)
        if judge and human:
            tp += 1
        elif judge and not human:
            fp += 1
        elif (not judge) and human:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def _load_dj_counts(database_url: str) -> tuple[int, int]:
    """(judge_positive, n_judge) over breach_results — errored calls excluded."""
    import psycopg

    url = database_url.replace("postgresql+psycopg://", "postgresql://")
    positive = total = 0
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT verdict::text, count(*) FROM breach_results GROUP BY verdict")
        for verdict, n in cur.fetchall():
            if verdict in _ERROR_VERDICTS:
                continue
            total += n
            if verdict in _BREACH_VERDICTS:
                positive += n
    return positive, total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                        help="certification tolerance α (H₀: breach rate ≥ α)")
    parser.add_argument("--zeta", type=float, default=DEFAULT_ZETA,
                        help="one-sided Type-I level ζ (also sets the 1−ζ CI)")
    parser.add_argument("--write", action="store_true",
                        help=f"also write the result JSON to {_OUT_PATH.name}")
    args = parser.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL unset — cannot read breach_results (D_J).", file=sys.stderr)
        return 2
    if not _DM_PATH.exists():
        print(f"calibration set missing: {_DM_PATH}", file=sys.stderr)
        return 2

    tp, fp, fn, tn = _load_dm_2x2(_DM_PATH)
    n_m1, n_m0 = tp + fn, fp + tn
    tpr = tp / n_m1 if n_m1 else 0.0
    fpr = fp / n_m0 if n_m0 else 0.0

    judge_positive, n_judge = _load_dj_counts(database_url)

    nc = noise_corrected_rate(
        tpr=tpr, fpr=fpr, n_m1=n_m1, n_m0=n_m0,
        judge_positive=judge_positive, n_judge=n_judge,
        alpha=args.alpha, zeta=args.zeta,
    )

    print("=" * 74)
    print("NOISE-CORRECTED CALIBRATION — $0 offline replay (harm breach axis)")
    print("=" * 74)
    print(f"D_M (JBB-300, human vs judge): tp={tp} fp={fp} fn={fn} tn={tn}")
    print(f"  TPR̂={tpr:.4f} (n_M1={n_m1})   FPR̂={fpr:.4f} (n_M0={n_m0})   "
          f"D=TPR̂−FPR̂={tpr - fpr:.4f}")
    print(f"D_J (breach_results): judge-breach={judge_positive} / n_J={n_judge} "
          f"→ raw R̂_J={nc.raw_rate:.4f}")
    print("-" * 74)
    print(nc.summary_line())
    print("-" * 74)
    print("CAVEAT: D_M is the JBB adversarial-harmful set; D_J is ROGUE's own")
    print("reproduction population. Cross-population TPR̂/FPR̂ transfer is an")
    print("assumption — a shipped per-judge headline needs a same-population,")
    print("judge-only paid calibration pass. This replay validates the pipeline")
    print("and the magnitude of the de-bias, not a certified per-judge number.")
    print("=" * 74)

    if args.write:
        payload = nc.to_dict()
        payload["source"] = "large_judge_run"
        payload["d_m"] = {"path": str(_DM_PATH.relative_to(_REPO_ROOT)),
                          "tp": tp, "fp": fp, "fn": fn, "tn": tn}
        payload["d_j"] = {"table": "breach_results",
                         "judge_positive": judge_positive, "n_judge": n_judge}
        payload["caveat"] = (
            "D_M=JBB adversarial-harmful; D_J=ROGUE reproduction population; "
            "cross-population TPR/FPR transfer assumed — demonstration, not a "
            "shipped per-judge certification."
        )
        _OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote → {_OUT_PATH}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
