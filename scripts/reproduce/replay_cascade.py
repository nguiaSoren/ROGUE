"""Replay the CascadeJudge over already-graded ``breach_results`` — the $0 savings validator (Q2).

$0, read-only. Pulls every graded row (``rendered_payload``, ``model_response``, the calibrated LLM
judge's stored ``verdict``), re-grades each with the FREE ``HeuristicJudge``, and measures — for a sweep
of the confidence gate ``tau`` — how many LLM-judge calls the cascade would have skipped and whether the
skipped verdicts still agree with the LLM. This is the honest offline number: it reuses rows we already
paid to grade, so it costs nothing, but it is a *backtest*, not a live A/B (the live savings number needs
a fresh paid cycle — see the design doc's caveat).

Because the local docker DB is a redacted snapshot (``model_response='[redacted]'``), point this at a DB
with real response text:

    NEON_DATABASE_URL=... uv run python scripts/reproduce/replay_cascade.py --database-url "$NEON_DATABASE_URL"

Reads only; never writes, never calls an LLM.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rogue.reproduce.cascade_judge import calibrate_tau  # noqa: E402
from rogue.reproduce.heuristic_judge import HeuristicJudge  # noqa: E402
from rogue.reproduce.sprt import wilson_interval  # noqa: E402
from rogue.schemas.breach_result import BREACH_VERDICTS  # noqa: E402

# Non-breach verdicts the cheap tier is allowed to stand alone on (never a breach — see the asymmetry).
_BREACH_VALUES = {v.value for v in BREACH_VERDICTS}


def _fetch_rows(database_url: str) -> list[tuple[str, str, str, str | None]]:
    """(rendered_payload, model_response, stored_verdict, short_description) for every non-error row."""
    import psycopg

    url = database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT b.rendered_payload, b.model_response, b.verdict::text, p.short_description "
            "FROM breach_results b LEFT JOIN attack_primitives p ON b.primitive_id = p.primitive_id "
            "WHERE b.verdict::text <> 'error' "
            "  AND b.model_response IS NOT NULL AND b.model_response <> '[redacted]'"
        )
        return [(rp, mr, v, sd) for rp, mr, v, sd in cur.fetchall()]


def _grade(rows: list[tuple[str, str, str, str | None]]) -> list[tuple[float, bool, bool]]:
    """→ (heuristic_confidence, heuristic_is_breach, reference_is_breach) per row."""
    hj = HeuristicJudge()
    items: list[tuple[float, bool, bool]] = []
    for rp, mr, verdict, sd in rows:
        hr = hj.judge_sync(rp, mr, sd or None)
        items.append((hr.confidence, hr.verdict in BREACH_VERDICTS, verdict in _BREACH_VALUES))
    return items


def _sweep_row(items: list[tuple[float, bool, bool]], tau: float, escalate_on_breach: bool = True):
    """Savings + agreement (with Wilson CI) at one tau — mirrors the live cascade's decision exactly."""
    sc = [(hb, rb) for conf, hb, rb in items if conf >= tau and not (escalate_on_breach and hb)]
    n_sc = len(sc)
    n_agree = sum(1 for hb, rb in sc if hb == rb)
    agreement = n_agree / n_sc if n_sc else 0.0
    lo, hi = wilson_interval(n_agree, n_sc) if n_sc else (0.0, 0.0)
    savings = n_sc / len(items) if items else 0.0
    return savings, agreement, lo, hi, n_sc


def main() -> int:
    ap = argparse.ArgumentParser(description="Replay CascadeJudge over breach_results ($0).")
    ap.add_argument(
        "--database-url",
        default=os.environ.get("NEON_DATABASE_URL") or os.environ.get("DATABASE_URL"),
        help="DB with REAL response text (Neon). Defaults to $NEON_DATABASE_URL then $DATABASE_URL.",
    )
    ap.add_argument("--target-agreement", type=float, default=0.90)
    args = ap.parse_args()
    if not args.database_url:
        print("error: no --database-url and neither NEON_DATABASE_URL nor DATABASE_URL set", file=sys.stderr)
        return 2

    where = args.database_url.split("@")[-1].split("/")[0]
    print(f"Replaying CascadeJudge over breach_results at {where} … ($0, read-only)\n")
    rows = _fetch_rows(args.database_url)
    if not rows:
        print("no rows with real response text — is this the redacted local snapshot?", file=sys.stderr)
        return 1
    items = _grade(rows)
    n = len(items)
    ref_breach = sum(1 for _, _, rb in items if rb)
    print(f"graded {n} rows with the free heuristic  (LLM-labelled breach rate {ref_breach / n:.1%})\n")

    print(f"{'tau':>5} {'LLM calls saved':>16} {'agreement@saved':>18} {'95% CI':>16} {'n_saved':>9}")
    print("-" * 70)
    for tau in [round(0.50 + 0.02 * i, 2) for i in range(11)]:
        savings, agr, lo, hi, n_sc = _sweep_row(items, tau)
        print(f"{tau:>5.2f} {savings:>15.1%} {agr:>17.1%} {f'[{lo:.1%},{hi:.1%}]':>16} {n_sc:>9}")

    print()
    for target in sorted({args.target_agreement, 0.90, 0.95}):
        choice = calibrate_tau(items, target_agreement=target)
        tag = "CERTIFIED" if choice.certified else "NOT certified (best effort)"
        print(
            f"calibrate_tau @ target {target:.0%}: tau={choice.tau:.2f} → "
            f"{choice.coverage:.1%} LLM calls saved, agreement {choice.agreement:.1%} "
            f"(Wilson floor {choice.agreement_lower:.1%}, n={choice.n_short_circuit})  [{tag}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
