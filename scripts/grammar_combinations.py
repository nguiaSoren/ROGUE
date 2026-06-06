"""Pairwise grammar-node interaction report (Engineer 5 — combination analysis).

OBSERVATIONAL, $0, READ-ONLY. Builds the per-primitive dataset from the live DB, labels
each primitive with structural ``GrammarNode``s, then computes pairwise interactions on
the per-(primitive × target) unit and writes:

    data/grammar_analysis/combinations.json   — full machine-readable result
    data/grammar_analysis/combinations.md      — top synergistic pairs + caveats

NO writes to the DB. NO API calls. NO scipy. Gated behind ``--go`` so it never runs by
accident (it only SELECTs, but we keep the discipline of the costly-script convention).

Run:
    uv run python scripts/grammar_combinations.py --go
    uv run python scripts/grammar_combinations.py --go --min-cell-n 5 \\
        --database-url postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from pathlib import Path

# Repo root on sys.path so `import rogue.*` works under `uv run python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from rogue.grammar.combinations import (  # noqa: E402
    pairwise_interactions,
    suppressed_pair_count,
)
from rogue.grammar.dataset import build_grammar_analysis_dataset  # noqa: E402
from rogue.grammar.labeler import label_records  # noqa: E402

logger = logging.getLogger("grammar_combinations")

DEFAULT_DATABASE_URL = "postgresql+psycopg://rogue:rogue_dev_password@localhost:5432/rogue"
OUT_DIR = Path("data/grammar_analysis")
JSON_PATH = OUT_DIR / "combinations.json"
MD_PATH = OUT_DIR / "combinations.md"


def _fmt_node(n) -> str:
    return n.value if hasattr(n, "value") else str(n)


def _interaction_to_jsonable(inter) -> dict:
    d = asdict(inter)
    d["node_a"] = _fmt_node(inter.node_a)
    d["node_b"] = _fmt_node(inter.node_b)
    d["both_ci"] = list(inter.both_ci)
    return d


def _write_json(interactions, suppressed, min_cell_n, n_obs, n_records):
    payload = {
        "unit": "per-(primitive × target)",
        "baseline_model": (
            "odds-scale (multiplicative-on-odds / logistic) no-interaction null; "
            "expected_p_both from OR_both == OR_a * OR_b"
        ),
        "min_cell_n": min_cell_n,
        "n_records_with_breach_data": n_records,
        "n_observations": n_obs,
        "n_pairs_reported": len(interactions),
        "n_pairs_suppressed_small_n": suppressed,
        "p_values_corrected": False,
        "p_value_note": (
            "Fisher-exact p of the both-vs-neither table; UNCORRECTED (pre-FDR). "
            "Engineer 6's validation layer applies multiple-comparison correction."
        ),
        "judge_caveat": (
            "breach_matrix is graded by the OLD v1/v2 judge (over-reports vs judge v3). "
            "Absolute breach rates are v1/v2-baseline."
        ),
        "interactions": [_interaction_to_jsonable(i) for i in interactions],
    }
    JSON_PATH.write_text(json.dumps(payload, indent=2))


def _write_md(interactions, suppressed, min_cell_n, n_obs, n_records, top_k=25):
    synergistic = [i for i in interactions if i.synergy]
    lines: list[str] = []
    lines.append("# Grammar-node pairwise interactions\n")
    lines.append(
        "Observational, $0, read-only. Analysis unit = **per-(primitive × target)** "
        "(NOT per-primitive — the per-primitive ANY-breach base rate is ~0.79, a ceiling "
        "that washes out contrast).\n"
    )
    lines.append("## Method\n")
    lines.append(
        "- **No-interaction baseline:** odds-scale (multiplicative-on-odds / logistic) "
        "null. `expected_p_both` is derived from `OR_both == OR_a * OR_b`, then converted "
        "back to a probability. `interaction_delta = p_both - expected_p_both` "
        "(**> 0 = synergy**: the combination breaches more than the no-interaction model "
        "predicts).\n"
    )
    lines.append(
        "- **OR / Fisher p:** both-vs-neither 2×2. `synergy = interaction_delta > 0 AND "
        "Fisher p < 0.05`.\n"
    )
    lines.append(
        f"- **Small-n suppression:** any pair with a cell < `min_cell_n={min_cell_n}` is "
        f"DROPPED. **{suppressed} pair(s) suppressed** for small-n (not silently — counted "
        "here).\n"
    )
    lines.append(
        "- **⚠ p-values are UNCORRECTED (pre-FDR).** Engineer 6's validation layer applies "
        "the multiple-comparison correction; treat `synergy` here as a screening flag.\n"
    )
    lines.append(
        "- **⚠ judge caveat:** breach_matrix is v1/v2-judge-graded (over-reports vs v3).\n"
    )
    lines.append(
        "- **Reading `delta` vs `OR`:** `delta > 0` means the combination breaches MORE "
        "than the multiplicative-odds null predicts. A row can have `delta > 0` AND "
        "`OR_both < 1` — that is positive *interaction* against a backdrop where the two "
        "single-node main effects are NEGATIVE (the combination recovers toward baseline). "
        "It is genuine synergy *relative to the null*, not 'this pair breaches a lot'. "
        "Read `delta` for interaction, `OR_both`/`p_both` for the raw both-cell level.\n"
    )
    lines.append(
        f"\n**Dataset:** {n_records} records with breach data → {n_obs} "
        f"(primitive × target) observations. **{len(interactions)} pair(s) tested**, "
        f"**{len(synergistic)} flagged synergistic** (pre-FDR).\n"
    )

    def _table(title, rows):
        out = [f"\n## {title}\n"]
        if not rows:
            out.append("_None._\n")
            return out
        out.append(
            "| pair | n_both | p_both | expected | delta | OR | Fisher p |\n"
            "|---|---:|---:|---:|---:|---:|---:|\n"
        )
        for i in rows:
            pair = f"`{_fmt_node(i.node_a)}` + `{_fmt_node(i.node_b)}`"
            out.append(
                f"| {pair} | {i.n_both} | {i.p_both:.3f} | {i.expected_p_both:.3f} | "
                f"{i.interaction_delta:+.3f} | {i.odds_ratio_both:.2f} | "
                f"{i.p_value:.4f} |\n"
            )
        return out

    lines += _table(
        f"Top synergistic pairs (synergy=True, by delta desc, max {top_k})",
        synergistic[:top_k],
    )
    lines += _table(
        f"Top interactions overall (by delta desc, max {top_k})",
        interactions[:top_k],
    )

    MD_PATH.write_text("".join(lines))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--go",
        action="store_true",
        help="Required. Confirms the read-only DB pass should run.",
    )
    ap.add_argument("--database-url", default=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL))
    ap.add_argument("--min-cell-n", type=int, default=5)
    ap.add_argument(
        "--breach-threshold",
        type=float,
        default=0.0,
        help="any_breach_rate > threshold counts a target as breached (default 0.0).",
    )
    args = ap.parse_args()

    if not args.go:
        logger.info(
            "Refusing to run without --go. This is read-only ($0) but gated by convention.\n"
            "    uv run python scripts/grammar_combinations.py --go"
        )
        return 2

    logger.info("Building grammar-analysis dataset (SELECT-only)...")
    engine = create_engine(args.database_url)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        records = build_grammar_analysis_dataset(
            session, breach_threshold=args.breach_threshold
        )

    with_data = [r for r in records if r.has_breach_data]
    n_obs = sum(len(r.targets) for r in with_data)
    logger.info(
        "  %d records (%d with breach data) → %d (primitive × target) observations.",
        len(records),
        len(with_data),
        n_obs,
    )

    labels = label_records(records)
    interactions = pairwise_interactions(records, labels, min_cell_n=args.min_cell_n)
    suppressed = suppressed_pair_count(records, labels, min_cell_n=args.min_cell_n)

    n_syn = sum(1 for i in interactions if i.synergy)
    logger.info(
        "  %d pairs tested, %d flagged synergistic (pre-FDR), %d suppressed (small-n).",
        len(interactions),
        n_syn,
        suppressed,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(interactions, suppressed, args.min_cell_n, n_obs, len(with_data))
    _write_md(interactions, suppressed, args.min_cell_n, n_obs, len(with_data))
    logger.info("Wrote %s and %s", JSON_PATH, MD_PATH)
    logger.info(
        "NOTE: p-values are UNCORRECTED (pre-FDR) — Engineer 6 corrects. "
        "breach_matrix is v1/v2-judge-graded."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
