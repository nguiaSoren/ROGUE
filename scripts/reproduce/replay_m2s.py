"""$0 offline validation for Q14 M2S consolidation — a READ-ONLY corpus census.

M2S's value proposition is *cheaper multi-turn coverage*: a multi-turn primitive fired via
``run_conversation`` spends K sequential victim calls (one per turn); its M2S-consolidated form fires
ONE. That cost reduction is deterministic and measurable offline from the corpus turn counts — no
target/judge call, no spend. What this script does NOT measure is the ASR retained/lifted by
consolidation; that requires firing both forms on a real panel and is the gated paid A/B (~$5–15).

Reads ``attack_primitives`` (structural ``multi_turn_sequence`` field — NOT the redacted
``payload_slots``) and, when present, joins ``breach_results`` to size the *fired* multi-turn surface.
Pure SELECTs; writes nothing. Run against Neon (the live corpus) — the local docker snapshot stores
sequences as scalars, so its multi-turn count is 0.

    uv run python scripts/reproduce/replay_m2s.py            # uses DATABASE_URL
    uv run python scripts/reproduce/replay_m2s.py --dsn ...  # explicit DSN
"""

from __future__ import annotations

import argparse
import os
import statistics

from sqlalchemy import create_engine, text


def _dsn(explicit: str | None) -> str:
    dsn = explicit or os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
    if not dsn:
        raise SystemExit("no DSN: pass --dsn or set DATABASE_URL")
    return dsn


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M2S corpus census ($0, read-only)")
    ap.add_argument("--dsn", default=None)
    ap.add_argument("--method", default="pythonize", choices=("hyphenize", "numberize", "pythonize"))
    args = ap.parse_args(argv)

    engine = create_engine(_dsn(args.dsn))
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM attack_primitives")).scalar_one()
        # per-primitive turn counts for the multi-turn (≥2) slice. json_typeof guards the redacted
        # snapshot's scalar values; works for both json and jsonb columns.
        # CASE guarantees short-circuit — json_array_length is only evaluated on array-typed values
        # (some rows store the field as a JSON scalar/string, which would otherwise raise).
        _len = (
            "CASE WHEN json_typeof(multi_turn_sequence::json) = 'array' "
            "THEN json_array_length(multi_turn_sequence::json) ELSE 0 END"
        )
        rows = conn.execute(
            text(
                f"SELECT primitive_id, {_len} AS n FROM attack_primitives "
                f"WHERE multi_turn_sequence IS NOT NULL AND {_len} >= 2"
            )
        ).all()
        turn_counts = [int(r.n) for r in rows]

        # breach_results referencing a multi-turn primitive = the actually-fired multi-turn surface.
        fired = None
        try:
            _len_ap = (
                "CASE WHEN json_typeof(ap.multi_turn_sequence::json) = 'array' "
                "THEN json_array_length(ap.multi_turn_sequence::json) ELSE 0 END"
            )
            fired = conn.execute(
                text(
                    "SELECT COUNT(*) FROM breach_results br "
                    "JOIN attack_primitives ap ON ap.primitive_id = br.primitive_id "
                    f"WHERE ap.multi_turn_sequence IS NOT NULL AND {_len_ap} >= 2"
                )
            ).scalar_one()
        except Exception as e:  # noqa: BLE001 — census must not fail on a missing table
            print(f"(breach_results join skipped: {e})")

    n_mt = len(turn_counts)
    print(f"corpus: {total} primitives, {n_mt} multi-turn (≥2 turns) = {100 * n_mt / total:.1f}%")
    if n_mt:
        total_turns = sum(turn_counts)
        print(f"turns on the multi-turn slice: total={total_turns}, "
              f"mean={statistics.mean(turn_counts):.2f}, median={statistics.median(turn_counts)}, "
              f"max={max(turn_counts)}")
        # M2S consolidates each multi-turn primitive to 1 victim call. Per-trial victim-call reduction:
        print(f"victim-call reduction on the multi-turn slice (per trial): "
              f"{total_turns} → {n_mt} calls "
              f"({100 * (total_turns - n_mt) / total_turns:.1f}% fewer)")
    if fired is not None:
        print(f"breach_results rows on multi-turn primitives (fired surface): {fired}")
    print(f"\nNOTE: ASR retained/lifted by the {args.method} consolidation is NOT measured here — "
          "that is the gated paid A/B (fire scripted vs consolidated on a live panel).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
